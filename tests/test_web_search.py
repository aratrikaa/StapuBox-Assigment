"""Unit tests for the web research layer.

No API key and no network — these target the response-parsing and
refusal-detection logic in web_search.py directly, with hand-built response
shapes matching what the live Groq API actually returned during testing.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.web_search import WebResearcher, _extract_sources, _is_refusal_not_research  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Refusal detection
# --------------------------------------------------------------------------- #


def test_detects_a_training_data_disclaimer_as_non_research():
    brief = (
        "I'm unable to provide recent, verifiable football facts from the past "
        "12 months because my training data only goes up to June 2024."
    )
    assert _is_refusal_not_research(brief)


def test_does_not_flag_a_genuine_short_brief():
    brief = "- On 2 August 2025, India beat Australia by 6 wickets at the MCG."
    assert not _is_refusal_not_research(brief)


def test_does_not_flag_a_legitimate_found_little_reply():
    brief = "My search turned up very little recent news for this sport."
    assert not _is_refusal_not_research(brief)


# --------------------------------------------------------------------------- #
# Response parsing — real shape observed from groq/compound-mini
# --------------------------------------------------------------------------- #


def _real_shaped_message(content: str, with_results: bool = True):
    """Mirrors Groq's actual ExecutedTool / ExecutedToolSearchResults shape,
    where `search_results` is a container object wrapping `.results`, not the
    list itself — the bug this module previously had."""
    if not with_results:
        return SimpleNamespace(content=content, executed_tools=[])

    result = SimpleNamespace(
        title="Cricket Archives",
        url="https://example.com/archive",
        content="Some match summary text.",
        score=0.84,
    )
    search_results = SimpleNamespace(results=[result], images=None)
    tool = SimpleNamespace(
        type="search",
        arguments='{"query": "..."}',
        search_results=search_results,
        code_results=None,
        output="raw text blob",
    )
    return SimpleNamespace(content=content, executed_tools=[tool])


def test_extract_sources_drills_into_nested_results_container():
    message = _real_shaped_message("some brief")
    sources = _extract_sources(message)
    assert len(sources) == 1
    assert sources[0].reference == "https://example.com/archive"
    assert sources[0].title == "Cricket Archives"
    assert sources[0].snippet == "Some match summary text."


def test_extract_sources_handles_no_executed_tools():
    message = _real_shaped_message("some brief", with_results=False)
    assert _extract_sources(message) == []


def test_extract_sources_never_raises_on_a_malformed_tool():
    message = SimpleNamespace(content="x", executed_tools=[{"unexpected": "shape"}, None, 42])
    assert _extract_sources(message) == []


# --------------------------------------------------------------------------- #
# End-to-end: WebResearcher.research() discards a declined-to-search reply
# --------------------------------------------------------------------------- #


class _FakeCompletions:
    def __init__(self, content: str, with_results: bool = False):
        self._content = content
        self._with_results = with_results
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        message = _real_shaped_message(self._content, with_results=self._with_results)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")])


class _FakeClient:
    def __init__(self, content: str, with_results: bool = False):
        self.chat = SimpleNamespace(completions=_FakeCompletions(content, with_results))


def test_research_discards_a_refusal_reply_but_keeps_any_sources():
    client = _FakeClient(
        "I don't have access to real-time information, my training data cutoff is 2024.",
        with_results=True,  # even if a tool nominally ran, the text itself is the tell
    )
    brief, sources = run(WebResearcher(client).research("Cricket"))
    assert brief == ""
    # Sources aren't discarded — only the untrustworthy prose is.
    assert len(sources) == 1


def test_research_keeps_a_genuine_brief():
    client = _FakeClient("- Team X beat Team Y on 2 August 2025.", with_results=True)
    brief, sources = run(WebResearcher(client).research("Cricket"))
    assert "Team X" in brief
    assert len(sources) == 1


# --------------------------------------------------------------------------- #
# End-to-end: WebResearcher.search() — the standalone, uncached query path
# --------------------------------------------------------------------------- #


def test_search_keeps_a_genuine_answer():
    client = _FakeClient("Team X won the latest match, 3-1.", with_results=True)
    answer, sources = run(WebResearcher(client).search("Who won the latest match?"))
    assert "Team X" in answer
    assert len(sources) == 1


def test_search_discards_a_refusal_reply_but_keeps_any_sources():
    client = _FakeClient(
        "I don't have access to real-time information, my training data cutoff is 2024.",
        with_results=True,
    )
    answer, sources = run(WebResearcher(client).search("Who won the latest match?"))
    assert answer == ""
    assert len(sources) == 1


def test_each_search_call_hits_the_client_independently():
    """Two calls to search() are two live requests — nothing is cached
    between them, matching the "fresh every query" contract."""
    client = _FakeClient("Team X won.", with_results=True)
    researcher = WebResearcher(client)
    run(researcher.search("query one"))
    run(researcher.search("query two"))
    assert client.chat.completions.calls == 2


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
