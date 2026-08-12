"""Live web research via Groq's `groq/compound` model.

`groq/compound` is Groq's agentic system model: it decides on its own whether
to run a web search before answering, with no tool schema for us to declare.
The executed searches come back on `message.executed_tools`. This is the
"fresh / fast-changing" half of retrieval: recent match results, records
broken this season, transfers, tournament outcomes.

It runs as its own API call, separate from generation, because Groq does not
document `response_format` (structured JSON) support on compound models — so
research stays a free-text call and generation stays a schema-constrained one.

Deliberately kept SIMPLE, not "deep": one narrow, single-purpose search per
call (a handful of facts on one angle) rather than an open-ended "research
everything about this sport" request. A broad ask makes the compound system
reach for more elaborate multi-step reasoning internally, which is both
slower and far more likely to spill onto a separate, tightly-limited model
this account barely has quota for (see `_create_with_retry`'s docstring).
A small, specific query stays cheap and mostly avoids that.

`WebResearcher` exposes two entry points, both uncached — every call is a
fresh live request:
  - `research(sport)`  — the batch pipeline's per-sport brief. Each call picks
    a different random angle (latest result, a broken record, a transfer,
    ...), so calling it again for the same sport — e.g. on a "refresh
    research" regeneration — sends a genuinely different query instead of
    repeating the last one.
  - `search(query)`    — an ad hoc, standalone query with no reuse at all;
    each call is independent and can return different results than the last.

Output is a short factual brief/answer plus the list of pages the model
actually consulted, which is what gets attached as `web_search` sources.
"""

from __future__ import annotations

import asyncio
import logging
import random

import groq
from groq import AsyncGroq

from .config import settings
from .schemas import Source, SourceKind

log = logging.getLogger(__name__)

RESEARCH_SYSTEM = """You are a web-search assistant for a sports content team.

Run ONE simple, direct web search and report back only what it actually found — \
a short list of plain factual sentences, not an essay. Never answer from memory, \
and never mention a training data cutoff; you have a live search tool for that \
reason. If the search turns up little, say so plainly instead of guessing."""

# A single broad "research everything recent" prompt made the compound system
# reach for more elaborate internal reasoning. Picking one narrow angle per
# call keeps each request small — and rotating it means calling research()
# again for the same sport (e.g. a "refresh research" regeneration) asks a
# genuinely different question instead of repeating the last one verbatim.
RESEARCH_QUERY_ANGLES = (
    "the most recent match or tournament result",
    "a record or milestone broken in the last year",
    "the latest transfer, retirement or roster change",
    "the current rankings or standings",
    "a standout recent performance by a top athlete",
)

RESEARCH_USER = """Search query: latest {angle} in {sport}.

Report back 4-8 short factual bullet points from what the search actually found, \
each with a specific number, name or date."""

GENERIC_SEARCH_SYSTEM = """You are a web-search assistant.

Run ONE simple, direct web search for the user's query and report back only what \
it actually found — a few plain factual sentences, not an essay. Never answer from \
memory, and never mention a training data cutoff; you have a live search tool for \
that reason. If the search turns up little, say so plainly instead of guessing."""

GENERIC_SEARCH_USER = """Search query: {query}"""


async def _create_with_retry(client: AsyncGroq, *, label: str, **kwargs):
    """Call chat.completions.create with a short retry for transient failures.

    `groq/compound(-mini)` sometimes delegates its reasoning step to a
    different underlying model server-side (observed: `openai/gpt-oss-120b`)
    that can be separately rate-limited from the model we actually asked
    for — Groq surfaces that as a 429 (occasionally a 413) on *our* request,
    even though `compound-mini` itself has plenty of headroom. The Groq SDK's
    own built-in retry only fires on 429/5xx, not 413, and neither is
    retried at all without this: one hit and the caller gave up permanently.
    That inner budget's own error message tells us exactly how long it needs
    (a `retry-after` header, typically a few seconds) — honor that when
    present instead of guessing; a fixed short backoff was cutting the retry
    off before the budget had actually recovered.
    """
    max_attempts = 4
    for attempt in range(max_attempts):
        try:
            return await client.chat.completions.create(**kwargs)
        except groq.APIStatusError as exc:
            status = getattr(exc, "status_code", None)
            if status not in (429, 413) or attempt == max_attempts - 1:
                raise
            retry_after = _retry_after_seconds(exc)
            # Cap even a server-suggested wait: if the real cause is a daily
            # quota (minutes/hours away), sitting here that long buys nothing
            # — better to give up quickly and let the caller fall back.
            delay = min(retry_after, 12.0) if retry_after is not None else 1.5 * (attempt + 1)
            delay += random.random()
            log.info(
                "%s hit a transient %s (likely internal model contention) — "
                "retrying in %.1fs (attempt %d/%d)",
                label, status, delay, attempt + 1, max_attempts,
            )
            await asyncio.sleep(delay)


def _retry_after_seconds(exc: groq.APIStatusError) -> float | None:
    """Read the server's own suggested wait, if it gave one."""
    response = getattr(exc, "response", None)
    if response is None:
        return None
    ms_header = response.headers.get("retry-after-ms")
    if ms_header is not None:
        try:
            return max(0.0, float(ms_header) / 1000)
        except ValueError:
            pass
    header = response.headers.get("retry-after")
    if header is None:
        return None
    try:
        return max(0.0, float(header))
    except ValueError:
        return None


class WebResearcher:
    def __init__(self, client: AsyncGroq) -> None:
        self._client = client

    async def research(self, sport: str) -> tuple[str, list[Source]]:
        """Return (factual brief, sources consulted). Never raises."""
        if not settings.enable_web_search:
            return "", []

        angle = random.choice(RESEARCH_QUERY_ANGLES)

        try:
            response = await _create_with_retry(
                self._client,
                label=f"Research for {sport!r} ({angle})",
                model=settings.research_model,
                temperature=settings.temperature,
                max_completion_tokens=600,
                messages=[
                    {"role": "system", "content": RESEARCH_SYSTEM},
                    {"role": "user", "content": RESEARCH_USER.format(sport=sport, angle=angle)},
                ],
            )
        except groq.APIError:
            log.exception("Web research failed for %s; falling back to vector DB only", sport)
            return "", []
        except Exception:
            log.exception("Unexpected web research failure for %s", sport)
            return "", []

        message = response.choices[0].message
        brief = (message.content or "").strip()
        sources = _extract_sources(message)

        if _is_refusal_not_research(brief):
            # The compound model sometimes answers from its own stale training
            # data ("I can't provide recent facts, my data only goes to ...")
            # instead of actually searching — despite the system prompt. That
            # text is non-empty but is not evidence; treating it as a research
            # brief would hand the generation step a fact-free "citation" and
            # suppress the "no web results" warning the caller relies on.
            log.info("Research call for %s declined to search; discarding its reply", sport)
            return "", sources

        return brief, sources

    async def search(self, query: str) -> tuple[str, list[Source]]:
        """Answer an arbitrary query with a fresh web search. Never raises.

        Unlike `research()`, this isn't tied to a sport and isn't reused
        across a batch's items — every call is its own live API request, so
        the same query asked twice can come back with different results as
        the web changes. There is no caching layer anywhere in this path.
        """
        if not settings.enable_web_search:
            return "", []

        try:
            response = await _create_with_retry(
                self._client,
                label=f"Search for {query!r}",
                model=settings.research_model,
                temperature=settings.temperature,
                max_completion_tokens=600,
                messages=[
                    {"role": "system", "content": GENERIC_SEARCH_SYSTEM},
                    {"role": "user", "content": GENERIC_SEARCH_USER.format(query=query)},
                ],
            )
        except groq.APIError:
            log.exception("Web search failed for query %r", query)
            return "", []
        except Exception:
            log.exception("Unexpected web search failure for query %r", query)
            return "", []

        message = response.choices[0].message
        answer = (message.content or "").strip()
        sources = _extract_sources(message)

        if _is_refusal_not_research(answer):
            log.info("Search call for %r declined to search; discarding its reply", query)
            return "", sources

        return answer, sources


# --------------------------------------------------------------------------- #
# Response parsing
# --------------------------------------------------------------------------- #

_REFUSAL_PHRASES = (
    "training data",
    "my knowledge cutoff",
    "knowledge cutoff",
    "i don't have access to",
    "i do not have access to",
    "i don't have real-time",
    "i do not have real-time",
    "unable to provide recent",
    "unable to browse",
    "cannot browse",
    "can't browse",
    "as an ai",
    "i'm not able to search",
    "i am not able to search",
)


def _is_refusal_not_research(brief: str) -> bool:
    """True when the model answered from memory instead of actually searching.

    A real brief is a bulleted list of facts (see RESEARCH_USER's requested
    format); a declined-to-search reply is prose containing one of these
    tells. Checking for the tells rather than requiring bullets is more
    robust — a short brief that legitimately found little is still fine.
    """
    lowered = brief.casefold()
    return any(phrase in lowered for phrase in _REFUSAL_PHRASES)


def _extract_sources(message) -> list[Source]:
    """Pull the pages `groq/compound` actually searched.

    The exact shape of `executed_tools` is not published in Groq's docs at the
    time this was written, so every access here is defensive: unknown or
    missing sub-fields simply yield fewer sources rather than raising.
    """
    executed = getattr(message, "executed_tools", None) or []
    out: list[Source] = []

    for tool in executed:
        try:
            results = _tool_search_results(tool)
            if results:
                out.extend(results)
                continue
            # No structured results list on this tool call — fall back to
            # whatever single url/title/output fields it does carry.
            single = _tool_single_result(tool)
            if single:
                out.append(single)
        except Exception:
            log.debug("Skipping an unparseable executed_tools entry", exc_info=True)

    return _dedupe(out)


def _tool_search_results(tool) -> list[Source]:
    # `search_results` is a container object (`.results` is the actual list),
    # not the list itself — Groq's `ExecutedToolSearchResults` shape.
    container = _get(tool, "search_results", "results")
    if container is None:
        return []
    results = container if isinstance(container, list) else _get(container, "results")
    if not isinstance(results, list):
        return []
    out = []
    for r in results:
        title = _get(r, "title", "name") or "Web result"
        url = _get(r, "url", "link") or ""
        snippet = _get(r, "snippet", "content", "description") or ""
        if title or url:
            out.append(Source(kind=SourceKind.WEB_SEARCH, title=title, reference=url, snippet=snippet))
    return out


def _tool_single_result(tool) -> Source | None:
    title = _get(tool, "title", "name", "type") or "Web search"
    url = _get(tool, "url", "link") or ""
    output = _get(tool, "output", "content") or ""
    if not (url or output):
        return None
    return Source(kind=SourceKind.WEB_SEARCH, title=title, reference=url, snippet=str(output)[:300])


def _get(obj, *names):
    """Read the first present attribute or dict key from `obj`."""
    if obj is None:
        return None
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        else:
            val = getattr(obj, name, None)
            if val is not None:
                return val
    return None


def _dedupe(sources: list[Source]) -> list[Source]:
    seen: set[str] = set()
    out: list[Source] = []
    for s in sources:
        key = s.reference or s.title
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out
