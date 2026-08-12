"""The agent: retrieve → generate → validate → de-duplicate.

One request produces a batch. The pipeline is:

    1. RESEARCH (once per batch)
       web_search  -> recent, fast-changing facts
       ChromaDB    -> stable, historical facts
       Both are labelled (W1..Wn / K1..Kn) so items can cite them individually.

    2. GENERATE (once per item, concurrently)
       A type-specific prompt template + constrained JSON decoding.
       Polls skip factual grounding by design — they are opinion content.

    3. VALIDATE (once per item)
       Independent Pydantic pass enforcing the per-type invariants. A failure
       is fed back into the prompt and the item is regenerated.

    4. DE-DUPLICATE (once per item, then once per batch)
       Against persistent cross-session history, and against the rest of this
       batch. Collisions are regenerated with a tightened avoid-list.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from datetime import datetime, timezone

import groq
from groq import AsyncGroq
from pydantic import ValidationError

from .config import settings
from .history import HistoryStore, get_history, similarity, tokenize
from .prompt_templates import ITEM_ANGLES, build_generation_prompt
from .schemas import (
    EVIDENCE_KEY,
    JSON_SCHEMAS,
    OPINION_TYPES,
    PAYLOAD_MODELS,
    RECOMMENDED_SURFACE,
    Batch,
    ContentItem,
    ContentType,
    Difficulty,
    Source,
    SourceKind,
    build_instagram_block,
    subject_of,
)
from .vector_store import KnowledgeBase, get_knowledge_base
from .web_search import WebResearcher

log = logging.getLogger(__name__)

MIN_BATCH_SIZE = 4
MAX_BATCH_SIZE = 5


class AgentError(RuntimeError):
    """Raised when an item could not be produced after all retries."""


class ResearchContext:
    """Everything retrieved for one batch, reused across its items.

    Also survives the batch so per-item regeneration doesn't have to pay for a
    fresh web search — the evidence is still valid, only the item changes.
    """

    def __init__(
        self,
        sport: str,
        web_brief: str,
        web_sources: list[Source],
        kb_sources: list[Source],
    ) -> None:
        self.sport = sport
        self.web_brief = web_brief
        self.web_sources = web_sources
        self.kb_sources = kb_sources

        # Map the citation ids used in the prompt back to concrete sources.
        self.evidence: dict[str, Source] = {}
        for i, line in enumerate(_bullets(web_brief), start=1):
            match = web_sources[(i - 1) % len(web_sources)] if web_sources else None
            self.evidence[f"W{i}"] = Source(
                kind=SourceKind.WEB_SEARCH,
                title=match.title if match else "Live web search",
                reference=match.reference if match else "",
                snippet=line,
            )
        for i, src in enumerate(kb_sources, start=1):
            self.evidence[f"K{i}"] = src

    @property
    def kb_lines(self) -> list[str]:
        return [s.snippet for s in self.kb_sources]

    def resolve(self, ids: list[str]) -> list[Source]:
        out, seen = [], set()
        for raw in ids or []:
            key = str(raw).strip().upper().replace(".", "").replace(" ", "")
            src = self.evidence.get(key)
            if src and key not in seen:
                seen.add(key)
                out.append(src)
        return out


def _bullets(brief: str) -> list[str]:
    return [ln.strip().lstrip("-•*").strip() for ln in brief.splitlines() if ln.strip()]


class SportsContentAgent:
    def __init__(
        self,
        client: AsyncGroq | None = None,
        kb: KnowledgeBase | None = None,
        history: HistoryStore | None = None,
    ) -> None:
        if client is None:
            if not settings.configured:
                raise AgentError(
                    "No Groq credentials found. Copy .env.example to .env and set "
                    "GROQ_API_KEY, then restart the server."
                )
            client = AsyncGroq(api_key=settings.api_key)
        self._client = client
        self._kb = kb or get_knowledge_base()
        self._history = history or get_history()
        self._researcher = WebResearcher(self._client)
        self._gen_semaphore = asyncio.Semaphore(settings.max_concurrent_generation)
        # batch_id -> (ResearchContext, Batch); holds the batch's own evidence
        # for lookups/history and for the opt-out case where a caller passes
        # refresh_research=False on a regeneration.
        self._batches: dict[str, tuple[ResearchContext, Batch]] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def generate_batch(
        self,
        sport: str,
        difficulty: Difficulty,
        types: list[ContentType],
        count: int = 5,
        mixed: bool = False,
    ) -> Batch:
        count = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, count))
        if not types:
            raise AgentError("Select at least one content type.")

        plan = self._plan_types(types, count, mixed)
        ctx = await self._research(sport)
        warnings: list[str] = []
        if not ctx.kb_sources:
            warnings.append(f"No knowledge-base documents matched '{sport}'.")

        items = await self._generate_items(ctx, plan, difficulty)
        items = await self._resolve_intra_batch_duplicates(ctx, items, difficulty)

        if len(items) < len(plan):
            warnings.append(
                f"Only {len(items)} of {len(plan)} requested items generated — "
                "the rest failed after retries (see server logs; often a "
                "provider rate limit)."
            )

        for item in items:
            self._history.record(
                item.id,
                sport,
                item.type.value,
                item.difficulty.value if item.difficulty else None,
                subject_of(item.type, item.payload),
            )

        batch = Batch(
            id=uuid.uuid4().hex[:12],
            sport=sport,
            difficulty=difficulty,
            requested_types=types,
            mixed=mixed,
            items=items,
            research_summary=ctx.web_brief,
            web_sources=ctx.web_sources,
            kb_sources=ctx.kb_sources,
            warnings=warnings,
            created_at=_now(),
        )
        self._batches[batch.id] = (ctx, batch)
        return batch

    async def regenerate_item(
        self, batch_id: str, item_id: str, refresh_research: bool = True
    ) -> tuple[ContentItem, Batch]:
        entry = self._batches.get(batch_id)
        if entry is None:
            raise AgentError("That batch is no longer in memory — generate a new batch.")
        ctx, batch = entry

        index = next((i for i, it in enumerate(batch.items) if it.id == item_id), None)
        if index is None:
            raise AgentError("Item not found in this batch.")

        old = batch.items[index]
        if refresh_research:
            ctx = await self._research(batch.sport)

        # Forget the old item so it stops blocking its own topic space, but
        # explicitly avoid it so the replacement is genuinely different.
        self._history.forget(old.id)
        sibling_subjects = [
            subject_of(it.type, it.payload) for it in batch.items if it.id != old.id
        ]
        extra_avoid = [subject_of(old.type, old.payload), *sibling_subjects]

        fresh = await self._generate_one(
            ctx=ctx,
            ctype=old.type,
            difficulty=batch.difficulty,
            angle=random.choice(ITEM_ANGLES),
            extra_avoid=extra_avoid,
        )
        batch.items[index] = fresh
        self._history.record(
            fresh.id,
            batch.sport,
            fresh.type.value,
            fresh.difficulty.value if fresh.difficulty else None,
            subject_of(fresh.type, fresh.payload),
        )
        self._batches[batch_id] = (ctx, batch)
        return fresh, batch

    async def search_web(self, query: str) -> tuple[str, list[Source]]:
        """Ad hoc live web search, independent of the batch pipeline.

        Every call is a fresh live request — nothing here is cached or
        reused, so asking the same query again later can return different
        results as the web changes.
        """
        return await self._researcher.search(query)

    async def regenerate_batch(self, batch_id: str) -> Batch:
        entry = self._batches.get(batch_id)
        if entry is None:
            raise AgentError("That batch is no longer in memory — generate a new batch.")
        _, batch = entry
        for item in batch.items:
            self._history.forget(item.id)
        self._batches.pop(batch_id, None)
        return await self.generate_batch(
            sport=batch.sport,
            difficulty=batch.difficulty,
            types=batch.requested_types,
            count=len(batch.items),
            mixed=batch.mixed,
        )

    # ------------------------------------------------------------------ #
    # Pipeline stages
    # ------------------------------------------------------------------ #

    @staticmethod
    def _plan_types(types: list[ContentType], count: int, mixed: bool) -> list[ContentType]:
        """Decide the type of each slot in the batch."""
        if not mixed or len(types) == 1:
            return [types[0]] * count
        # Round-robin so every requested type appears before any repeats.
        plan = [types[i % len(types)] for i in range(count)]
        random.shuffle(plan)
        return plan

    async def _research(self, sport: str) -> ResearchContext:
        """Run web search and vector retrieval concurrently."""
        web_task = asyncio.create_task(self._researcher.research(sport))
        kb_sources = await asyncio.to_thread(self._kb.retrieve, sport, 10)
        web_brief, web_sources = await web_task
        return ResearchContext(sport, web_brief, web_sources, kb_sources)

    async def _generate_items(
        self, ctx: ResearchContext, plan: list[ContentType], difficulty: Difficulty
    ) -> list[ContentItem]:
        angles = random.sample(ITEM_ANGLES, k=min(len(plan), len(ITEM_ANGLES)))
        while len(angles) < len(plan):
            angles.append(random.choice(ITEM_ANGLES))

        results = await asyncio.gather(
            *(
                self._generate_one(ctx, ctype, difficulty, angle)
                for ctype, angle in zip(plan, angles)
            ),
            return_exceptions=True,
        )

        items: list[ContentItem] = []
        for res in results:
            if isinstance(res, BaseException):
                log.error("Item generation failed: %s", res)
                continue
            items.append(res)

        if not items:
            raise AgentError(
                "Every item failed to generate. Check the server logs and your API key."
            )
        return items

    async def _resolve_intra_batch_duplicates(
        self, ctx: ResearchContext, items: list[ContentItem], difficulty: Difficulty
    ) -> list[ContentItem]:
        """Items generate in parallel, so they can collide with each other.

        Persistent history can't catch that (nothing is written until the batch
        completes), so this second pass compares the batch against itself and
        sequentially regenerates any collision.
        """
        accepted: list[ContentItem] = []
        accepted_tokens: list[set[str]] = []

        for item in items:
            subject = subject_of(item.type, item.payload)
            toks = tokenize(subject)
            clash = any(similarity(toks, t) >= settings.dedupe_threshold for t in accepted_tokens)
            if not clash:
                accepted.append(item)
                accepted_tokens.append(toks)
                continue

            log.info("Intra-batch duplicate detected, regenerating: %s", subject[:80])
            try:
                replacement = await self._generate_one(
                    ctx=ctx,
                    ctype=item.type,
                    difficulty=difficulty,
                    angle=random.choice(ITEM_ANGLES),
                    extra_avoid=[subject_of(a.type, a.payload) for a in accepted],
                )
                replacement.attempts += item.attempts
                accepted.append(replacement)
                accepted_tokens.append(tokenize(subject_of(replacement.type, replacement.payload)))
            except Exception:
                log.exception("Duplicate replacement failed; keeping the original item")
                accepted.append(item)
                accepted_tokens.append(toks)

        return accepted

    # ------------------------------------------------------------------ #
    # Single-item generation
    # ------------------------------------------------------------------ #

    async def _generate_one(
        self,
        ctx: ResearchContext,
        ctype: ContentType,
        difficulty: Difficulty,
        angle: str,
        extra_avoid: list[str] | None = None,
    ) -> ContentItem:
        extra_avoid = extra_avoid or []
        avoid = [*extra_avoid, *self._history.avoid_list(ctx.sport)]
        retry_note = ""
        last_error: Exception | None = None
        attempts = 0

        for attempt in range(settings.max_dedupe_retries + 1):
            attempts = attempt + 1
            system, user = build_generation_prompt(
                ctype=ctype,
                sport=ctx.sport,
                difficulty=difficulty.value,
                web_brief=ctx.web_brief,
                kb_lines=ctx.kb_lines,
                avoid=avoid,
                angle_hint=angle,
                retry_note=retry_note,
            )

            try:
                raw = await self._call_model(system, user, ctype, JSON_SCHEMAS[ctype])
            except Exception as exc:  # network / API failure — retry once, then give up
                last_error = exc
                retry_note = ""
                log.warning("Model call failed (attempt %d) for %s: %s", attempts, ctype, exc)
                continue

            evidence_ids = raw.pop(EVIDENCE_KEY, [])

            # --- Schema validation -------------------------------------- #
            try:
                payload = PAYLOAD_MODELS[ctype](**raw).model_dump()
            except ValidationError as exc:
                last_error = exc
                retry_note = (
                    "Your previous attempt failed schema validation with: "
                    f"{_short_validation_error(exc)}. Fix exactly that and try again."
                )
                log.info("Schema validation failed for %s: %s", ctype, retry_note)
                continue

            # --- Freshness ---------------------------------------------- #
            # Both freshness checks are *soft*: they trigger a regeneration
            # while retries remain, but on the final attempt the item is
            # accepted anyway. A slightly repetitive item beats a short batch.
            is_last_attempt = attempt >= settings.max_dedupe_retries
            subject = subject_of(ctype, payload)

            if _clashes(subject, extra_avoid) and not is_last_attempt:
                retry_note = (
                    "Your previous attempt repeated a subject already used in this batch. "
                    "Choose a completely different fact, person or moment."
                )
                last_error = AgentError("intra-batch duplicate")
                log.info("Intra-batch duplicate — regenerating %s", ctype.value)
                continue

            duplicate, matched, score = self._history.is_duplicate(ctx.sport, subject)
            if duplicate and not is_last_attempt:
                retry_note = (
                    f"Your previous attempt was {score:.0%} similar to an item already "
                    f'published for this sport ("{matched}"). Pick a different subject '
                    "entirely — not a rewording."
                )
                last_error = AgentError("history duplicate")
                log.info("History duplicate (%.2f) — regenerating %s", score, ctype.value)
                continue

            return self._assemble(ctx, ctype, difficulty, payload, evidence_ids, attempts)

        raise AgentError(f"Could not generate a valid {ctype.value} item: {last_error}")

    async def _call_model(self, system: str, user: str, ctype: ContentType, schema: dict) -> dict:
        # A single item's JSON payload is a few hundred tokens at most — a
        # generous cap here, not a request for the model to write an essay.
        # Groq's free/on-demand tier enforces a *per-minute* token budget
        # shared across concurrent requests, so an oversized cap here was
        # enough on its own to blow the limit when a batch's items generate
        # in parallel.
        max_attempts = 4
        last_exc: Exception | None = None

        for attempt in range(max_attempts):
            try:
                async with self._gen_semaphore:
                    response = await self._client.chat.completions.create(
                        model=settings.model,
                        temperature=settings.temperature,
                        max_completion_tokens=2048,
                        reasoning_effort=settings.reasoning_effort,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        response_format={
                            "type": "json_schema",
                            "json_schema": {"name": ctype.value, "strict": True, "schema": schema},
                        },
                    )
                break
            except groq.RateLimitError as exc:
                # Transient token/request-per-minute pressure — back off and
                # retry the *same* call rather than burning a dedupe-retry
                # attempt (those rebuild the prompt; this doesn't need that).
                last_exc = exc
                if attempt == max_attempts - 1:
                    raise AgentError(f"Groq rate limit: {exc}") from exc
                delay = min(2**attempt, 8) + random.random()
                log.info("Rate limited by Groq (attempt %d/%d) — retrying in %.1fs",
                          attempt + 1, max_attempts, delay)
                await asyncio.sleep(delay)
            except groq.APIError as exc:
                raise AgentError(f"Groq API error: {exc}") from exc
        else:  # pragma: no cover - loop always breaks or raises above
            raise AgentError(f"Groq rate limit: {last_exc}")

        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise AgentError("The model declined this request.")
        if choice.finish_reason == "length":
            raise AgentError("Response hit the token cap before completing.")

        text = choice.message.content
        if not text:
            raise AgentError("Model returned no content.")
        return json.loads(text)

    def _assemble(
        self,
        ctx: ResearchContext,
        ctype: ContentType,
        difficulty: Difficulty,
        payload: dict,
        evidence_ids: list[str],
        attempts: int,
    ) -> ContentItem:
        is_opinion = ctype in OPINION_TYPES

        if is_opinion:
            sources = [
                Source(
                    kind=SourceKind.OPINION,
                    title="Opinion-based — not fact-checked",
                    reference="",
                    snippet=(
                        "This-or-That polls have no correct answer by design, so no "
                        "factual grounding is asserted."
                    ),
                )
            ]
            grounding = "Opinion — not fact-checked"
            kinds = [SourceKind.OPINION]
        else:
            sources = ctx.resolve(evidence_ids)
            if not sources:
                # The model cited nothing resolvable; fall back to the batch's
                # retrieved set so the item is never shown as unsourced.
                sources = (ctx.web_sources[:1] or []) + (ctx.kb_sources[:1] or [])
            kinds = sorted({s.kind for s in sources}, key=lambda k: k.value)
            labels = {
                SourceKind.WEB_SEARCH: "Web search",
                SourceKind.VECTOR_DB: "Knowledge base",
            }
            grounding = " + ".join(labels.get(k, k.value) for k in kinds) or "Ungrounded"

        payload_for_ig = dict(payload)
        instagram, warnings = build_instagram_block(ctype, payload_for_ig)

        return ContentItem(
            id=uuid.uuid4().hex[:12],
            type=ctype,
            type_label=_label(ctype),
            sport=ctx.sport,
            difficulty=None if is_opinion else difficulty,
            payload=payload,
            sources=sources,
            grounding=grounding,
            grounding_kinds=kinds,
            fact_checked=not is_opinion,
            recommended_surface=RECOMMENDED_SURFACE[ctype],
            instagram=instagram,
            format_warnings=warnings,
            created_at=_now(),
            attempts=attempts,
        )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _label(ctype: ContentType) -> str:
    from .schemas import CONTENT_TYPE_LABELS

    return CONTENT_TYPE_LABELS[ctype]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clashes(subject: str, others: list[str]) -> bool:
    toks = tokenize(subject)
    return any(similarity(toks, tokenize(o)) >= settings.dedupe_threshold for o in others)


def _short_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err.get("loc", ())) or "payload"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


_agent: SportsContentAgent | None = None


def get_agent() -> SportsContentAgent:
    global _agent
    if _agent is None:
        _agent = SportsContentAgent()
    return _agent
