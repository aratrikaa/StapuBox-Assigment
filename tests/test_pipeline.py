"""End-to-end pipeline tests with a stubbed Groq client.

No API key and no network. A fake client stands in for the model so the real
orchestration — research fan-out, evidence labelling, per-item generation,
schema validation, retry-on-invalid, de-duplication, Instagram packaging and
per-item regeneration — is exercised exactly as it runs in production.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.agent import SportsContentAgent  # noqa: E402
from app.history import HistoryStore  # noqa: E402
from app.schemas import ContentType, Difficulty, Source, SourceKind  # noqa: E402

# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #


def _choice(message: SimpleNamespace, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


WEB_BRIEF = "\n".join(
    [
        "- India beat Australia by 6 wickets in the third ODI at the MCG on 2 August 2025.",
        "- Shubman Gill scored 112 not out off 96 balls in that chase.",
        "- Jasprit Bumrah took 4 wickets for 28 runs in the same match.",
    ]
)


class FakeCompletions:
    """Stands in for `client.chat.completions`. Branches on `response_format`.

    Only generation calls pass `response_format` (structured JSON); the
    `groq/compound` research call is plain free text, mirroring the real
    split in web_search.py / agent.py.
    """

    def __init__(self, owner: "FakeClient") -> None:
        self.owner = owner

    async def create(self, **kwargs):
        self.owner.calls.append(kwargs)

        if "response_format" not in kwargs:  # the research turn
            self.owner.research_calls += 1
            message = SimpleNamespace(
                content=WEB_BRIEF,
                executed_tools=[
                    {
                        "type": "search",
                        "search_results": [
                            {"title": "MCG ODI report", "url": "https://example.com/odi"},
                            {"title": "Gill century", "url": "https://example.com/gill"},
                        ],
                    }
                ],
            )
            return _choice(message)

        # the generation turn — respond in whatever shape the schema asks for
        self.owner.generation_calls += 1
        schema = kwargs["response_format"]["json_schema"]["schema"]
        message = SimpleNamespace(content=json.dumps(self.owner.payload_for(schema)))
        return _choice(message)


class FakeChat:
    def __init__(self, owner: "FakeClient") -> None:
        self.completions = FakeCompletions(owner)


# Distinct subjects so every stubbed item is genuinely about something
# different — otherwise the (correctly working) dedup layer keeps rejecting
# them and the test measures the fixture rather than the pipeline.
SUBJECTS = [
    ("Gill", "century", "Melbourne"),
    ("Bumrah", "spell", "Perth"),
    ("Kohli", "chase", "Adelaide"),
    ("Jadeja", "allround", "Brisbane"),
    ("Rahul", "keeping", "Sydney"),
    ("Siraj", "swing", "Hobart"),
    ("Pant", "counterattack", "Canberra"),
    ("Ashwin", "carrom", "Geelong"),
    ("Iyer", "pull", "Cairns"),
    ("Shami", "yorker", "Darwin"),
    ("Rohit", "opening", "Townsville"),
    ("Kuldeep", "wristspin", "Ballarat"),
]


class FakeClient:
    """Emits schema-correct payloads, with a hook for injecting bad ones."""

    def __init__(self) -> None:
        self.chat = FakeChat(self)
        self.calls: list[dict] = []
        self.research_calls = 0
        self.generation_calls = 0
        self.force_invalid_once = False
        self._n = 0

    def payload_for(self, schema: dict) -> dict:
        self._n += 1
        n = self._n
        who, what, where = SUBJECTS[(n - 1) % len(SUBJECTS)]
        props = set(schema["properties"])

        if "correct_option_text" in props:  # MCQ
            if self.force_invalid_once:
                self.force_invalid_once = False
                return {  # only three options — must fail validation and retry
                    "question": "Who top-scored?",
                    "options": ["Gill", "Rohit", "Kohli"],
                    "correct_answer": "A",
                    "correct_option_text": "Gill",
                    "explanation": "e",
                    "evidence_used": ["W2"],
                }
            return {
                "question": f"Whose {what} decided the {where} fixture?",
                "options": [who, f"{who}son", f"{who}ka", f"{who}nath"],
                "correct_answer": "A",
                "correct_option_text": who,
                "explanation": f"{who} produced the decisive {what} at {where}.",
                "evidence_used": ["W2"],
            }
        if "statement" in props:  # True / False
            return {
                "statement": f"{who} recorded a {what} at {where}.",
                "correct_answer": n % 2 == 0,
                "explanation": f"Confirmed for {where}.",
                "evidence_used": ["W3", "K1"],
            }
        if "prompt" in props:  # Poll
            return {
                "prompt": f"{who} at {where} or {who}son at {where}?",
                "options": [who, f"{who}son"],
            }
        if "sentence" in props:  # Fill in the blank
            return {
                "sentence": f"___ produced the {what} at {where}.",
                "options": [who, f"{who}son", f"{who}ka", f"{who}nath"],
                "correct_answer": who,
                "explanation": f"{who} did it at {where}.",
                "evidence_used": ["K2"],
            }
        # Guess the number
        return {
            "question": f"How many runs did {who} make at {where}?",
            "target_number": 100 + n,
            "tolerance": 10,
            "unit": "runs",
            "explanation": f"{who} scored them at {where}.",
            "evidence_used": ["W1"],
        }


class FakeKB:
    def sports(self):
        return ["Cricket", "Football"]

    def retrieve(self, sport, n_results=8, angle=None):
        return [
            Source(
                kind=SourceKind.VECTOR_DB,
                title=f"{sport} · record",
                reference=f"kb-{i}",
                snippet=f"Stable historical fact {i} about {sport}.",
            )
            for i in range(1, 4)
        ]

    def stats(self):
        return {"documents": 3}


@pytest.fixture()
def agent(tmp_path):
    return SportsContentAgent(
        client=FakeClient(),
        kb=FakeKB(),
        history=HistoryStore(tmp_path / "h.sqlite3"),
    )


def run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Batch generation
# --------------------------------------------------------------------------- #


def test_single_type_batch_of_five(agent):
    batch = run(
        agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=5)
    )
    assert len(batch.items) == 5
    assert all(i.type == ContentType.MCQ for i in batch.items)
    assert all(len(i.payload["options"]) == 4 for i in batch.items)
    # Research runs once per batch, not once per item.
    assert agent._client.research_calls == 1
    assert agent._client.generation_calls >= 5


def test_batch_size_is_clamped_to_four_or_five(agent):
    small = run(agent.generate_batch("Cricket", Difficulty.EASY, [ContentType.POLL], count=1))
    assert len(small.items) == 4
    big = run(agent.generate_batch("Cricket", Difficulty.EASY, [ContentType.POLL], count=99))
    assert len(big.items) == 5


def test_mixed_batch_contains_every_requested_type(agent):
    types = [
        ContentType.MCQ,
        ContentType.TRUE_FALSE,
        ContentType.POLL,
        ContentType.FILL_BLANK,
        ContentType.GUESS_NUMBER,
    ]
    batch = run(agent.generate_batch("Cricket", Difficulty.HARD, types, count=5, mixed=True))
    assert {i.type for i in batch.items} == set(types)


# --------------------------------------------------------------------------- #
# Grounding and citation
# --------------------------------------------------------------------------- #


def test_items_cite_the_evidence_they_used(agent):
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    for item in batch.items:
        assert item.sources, "every factual item must carry at least one source"
        assert item.fact_checked is True
        # The stub cites W2, which is a web-search line.
        assert any(s.kind == SourceKind.WEB_SEARCH for s in item.sources)
        assert "Web search" in item.grounding


def test_true_false_can_cite_both_retrieval_sources(agent):
    batch = run(
        agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.TRUE_FALSE], count=4)
    )
    kinds = {k for i in batch.items for k in i.grounding_kinds}
    assert SourceKind.WEB_SEARCH in kinds and SourceKind.VECTOR_DB in kinds


def test_polls_are_flagged_opinion_and_never_fact_checked(agent):
    batch = run(agent.generate_batch("Cricket", Difficulty.HARD, [ContentType.POLL], count=4))
    for item in batch.items:
        assert item.fact_checked is False
        assert item.difficulty is None  # difficulty does not apply to opinion polls
        assert item.payload["correct_answer"] is None
        assert item.grounding_kinds == [SourceKind.OPINION]
        assert item.instagram["correct_index"] is None


def test_batch_reports_its_retrieved_evidence(agent):
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    assert batch.research_summary.strip()
    assert len(batch.web_sources) == 2
    assert len(batch.kb_sources) == 3


def test_web_search_failure_degrades_to_knowledge_base_only(agent):
    # WebResearcher swallows its own errors; simulate the swallowed result.
    agent._researcher.research = lambda sport: _empty_research()
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    assert len(batch.items) == 4
    assert batch.research_summary == ""
    assert all(
        SourceKind.WEB_SEARCH not in {s.kind for s in item.sources} for item in batch.items
    )


async def _empty_research():
    return "", []


# --------------------------------------------------------------------------- #
# Validation retry
# --------------------------------------------------------------------------- #


def test_an_invalid_payload_is_regenerated_not_returned(agent):
    agent._client.force_invalid_once = True
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    assert len(batch.items) == 4
    assert all(len(i.payload["options"]) == 4 for i in batch.items)
    # One item needed a second attempt; the bad payload never reaches the caller.
    assert any(i.attempts > 1 for i in batch.items)


# --------------------------------------------------------------------------- #
# Freshness
# --------------------------------------------------------------------------- #


def test_accepted_items_are_written_to_history(agent):
    run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    assert agent._history.stats()["total"] == 4
    assert agent._history.avoid_list("Cricket")


def test_history_avoid_list_reaches_the_prompt(agent):
    run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    agent._client.calls.clear()
    run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))

    generation_prompts = [_user_content(c) for c in agent._client.calls if "response_format" in c]
    assert generation_prompts
    assert all("FRESHNESS" in p for p in generation_prompts)
    assert any("ALREADY been used" in p for p in generation_prompts)


# --------------------------------------------------------------------------- #
# Regeneration
# --------------------------------------------------------------------------- #


def test_regenerating_one_item_leaves_the_others_untouched(agent):
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=5))
    target = batch.items[2]
    others_before = [i.id for i in batch.items if i.id != target.id]

    fresh, updated = run(agent.regenerate_item(batch.id, target.id))

    assert fresh.id != target.id
    assert fresh.type == target.type
    assert fresh.payload != target.payload
    assert [i.id for i in updated.items if i.id != fresh.id] == others_before
    assert len(updated.items) == 5
    # The replaced item is gone from history; the replacement is in it.
    subjects = agent._history.avoid_list("Cricket")
    assert fresh.payload["question"] in " ".join(subjects)


def test_regenerating_an_item_refreshes_research_by_default(agent):
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    before = agent._client.research_calls
    run(agent.regenerate_item(batch.id, batch.items[0].id))
    assert agent._client.research_calls == before + 1, "should fetch new data by default"


def test_regenerating_an_item_can_reuse_stale_research(agent):
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    before = agent._client.research_calls
    run(agent.regenerate_item(batch.id, batch.items[0].id, refresh_research=False))
    assert agent._client.research_calls == before, "should not re-run web search"


def test_regenerating_the_whole_batch_replaces_every_item(agent):
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, [ContentType.MCQ], count=4))
    old_ids = {i.id for i in batch.items}
    fresh = run(agent.regenerate_batch(batch.id))
    assert len({i.id for i in fresh.items} & old_ids) == 0
    assert fresh.sport == batch.sport and fresh.difficulty == batch.difficulty


def test_regenerating_an_unknown_batch_is_a_clean_error(agent):
    with pytest.raises(Exception, match="no longer in memory"):
        run(agent.regenerate_item("does-not-exist", "nope"))


# --------------------------------------------------------------------------- #
# Instagram packaging
# --------------------------------------------------------------------------- #


def test_every_item_ships_instagram_ready_text(agent):
    types = [
        ContentType.MCQ,
        ContentType.TRUE_FALSE,
        ContentType.POLL,
        ContentType.FILL_BLANK,
        ContentType.GUESS_NUMBER,
    ]
    batch = run(agent.generate_batch("Cricket", Difficulty.MEDIUM, types, count=5, mixed=True))
    for item in batch.items:
        assert item.instagram["sticker"]
        assert item.instagram["question"]
        assert item.instagram["caption"]
        assert item.recommended_surface


def test_type_specific_prompts_are_actually_different(agent):
    """Each content type must use its own template, not one generic prompt."""
    types = [
        ContentType.MCQ,
        ContentType.TRUE_FALSE,
        ContentType.POLL,
        ContentType.FILL_BLANK,
        ContentType.GUESS_NUMBER,
    ]
    run(agent.generate_batch("Cricket", Difficulty.MEDIUM, types, count=5, mixed=True))
    systems = {_system_content(c) for c in agent._client.calls if "response_format" in c}
    assert len(systems) == 5, "expected one distinct system prompt per content type"


def _system_content(call: dict) -> str:
    return next(m["content"] for m in call["messages"] if m["role"] == "system")


def _user_content(call: dict) -> str:
    return next(m["content"] for m in call["messages"] if m["role"] == "user")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
