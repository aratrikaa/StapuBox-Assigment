"""Offline tests for the validation, dedup and packaging layers.

These need no API key — they exercise everything between the model call and
the dashboard, which is where the assignment's hard guarantees live.

Run with:  python -m pytest tests -q     (or)     python tests/test_validation.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from app.history import HistoryStore, similarity, tokenize  # noqa: E402
from app.schemas import (  # noqa: E402
    JSON_SCHEMAS,
    PAYLOAD_MODELS,
    ContentType,
    FillBlankPayload,
    GuessNumberPayload,
    MCQPayload,
    PollPayload,
    TrueFalsePayload,
    build_instagram_block,
    subject_of,
)

# --------------------------------------------------------------------------- #
# MCQ: exactly 4 options, exactly 1 correct answer
# --------------------------------------------------------------------------- #


def test_mcq_accepts_a_well_formed_item():
    m = MCQPayload(
        question="Who scored the highest individual ODI score?",
        options=["Rohit Sharma", "Martin Guptill", "Virender Sehwag", "Chris Gayle"],
        correct_answer="A",
        correct_option_text="Rohit Sharma",
        explanation="Rohit made 264 against Sri Lanka in 2014.",
    )
    assert len(m.options) == 4
    assert m.correct_option_text == "Rohit Sharma"


def test_mcq_rejects_wrong_option_count():
    with pytest.raises(ValidationError, match="exactly 4 options"):
        MCQPayload(
            question="q",
            options=["a", "b", "c"],
            correct_answer="A",
            correct_option_text="a",
            explanation="e",
        )


def test_mcq_rejects_duplicate_options():
    with pytest.raises(ValidationError, match="distinct"):
        MCQPayload(
            question="q",
            options=["a", "a", "b", "c"],
            correct_answer="A",
            correct_option_text="a",
            explanation="e",
        )


def test_mcq_strips_letter_prefixes_and_repairs_answer_echo():
    m = MCQPayload(
        question="q",
        options=["A) Real Madrid", "B) Milan", "C) Bayern", "D) Ajax"],
        correct_answer="C",
        correct_option_text="Bayern Munich",  # mismatched echo
        explanation="e",
    )
    assert m.options[0] == "Real Madrid"
    # The letter is authoritative, so the echo is repaired rather than rejected.
    assert m.correct_option_text == "Bayern"


# --------------------------------------------------------------------------- #
# Poll: exactly 2 options, no correct answer
# --------------------------------------------------------------------------- #


def test_poll_has_two_options_and_no_answer():
    p = PollPayload(prompt="Messi or Ronaldo — greater dribbler?", options=["Messi", "Ronaldo"])
    assert len(p.options) == 2
    assert p.correct_answer is None
    assert p.opinion_based is True


def test_poll_rejects_three_options():
    with pytest.raises(ValidationError, match="exactly 2 options"):
        PollPayload(prompt="q", options=["a", "b", "c"])


def test_poll_rejects_a_supplied_correct_answer():
    with pytest.raises(ValidationError):
        PollPayload(prompt="q", options=["a", "b"], correct_answer="a")


# --------------------------------------------------------------------------- #
# Guess the Number: numeric target + acceptable range
# --------------------------------------------------------------------------- #


def test_guess_number_derives_the_accepted_range_when_absent():
    """The model is never asked for the range — the validator computes it."""
    g = GuessNumberPayload(
        question="How many runs did Virat Kohli score in the 2023 World Cup?",
        target_number=765,
        tolerance=25,
        unit="runs",
        explanation="e",
    )
    assert g.acceptable_range == [740, 790]


def test_guess_number_overwrites_a_supplied_range():
    g = GuessNumberPayload(
        question="q",
        target_number=100,
        tolerance=5,
        unit="",
        acceptable_range=[0, 0],  # deliberately wrong — must be recomputed
        explanation="e",
    )
    assert g.acceptable_range == [95, 105]


def test_guess_number_rejects_zero_tolerance():
    with pytest.raises(ValidationError, match="positive tolerance"):
        GuessNumberPayload(
            question="q", target_number=10, tolerance=0, unit="", explanation="e"
        )


# --------------------------------------------------------------------------- #
# Fill in the blank
# --------------------------------------------------------------------------- #


def test_fill_blank_requires_exactly_one_blank():
    with pytest.raises(ValidationError, match="'___' blank"):
        FillBlankPayload(
            sentence="No blank here", options=["a", "b", "c", "d"], correct_answer="a",
            explanation="e",
        )
    with pytest.raises(ValidationError, match="exactly one blank"):
        FillBlankPayload(
            sentence="___ and ___", options=["a", "b", "c", "d"], correct_answer="a",
            explanation="e",
        )


def test_fill_blank_answer_must_be_one_of_the_options():
    with pytest.raises(ValidationError, match="must be one of the four options"):
        FillBlankPayload(
            sentence="___ won the 1983 World Cup.",
            options=["India", "Australia", "England", "Pakistan"],
            correct_answer="West Indies",
            explanation="e",
        )


def test_fill_blank_normalises_answer_casing():
    f = FillBlankPayload(
        sentence="___ won the 1983 World Cup.",
        options=["India", "Australia", "England", "Pakistan"],
        correct_answer="india",
        explanation="e",
    )
    assert f.correct_answer == "India"


# --------------------------------------------------------------------------- #
# True / False
# --------------------------------------------------------------------------- #


def test_true_false_payload():
    t = TrueFalsePayload(statement="Bradman averaged 99.94.", correct_answer=True, explanation="e")
    assert t.correct_answer is True


# --------------------------------------------------------------------------- #
# Defensive strip: internal evidence-id citations must never reach the reader
# --------------------------------------------------------------------------- #


def test_leaked_evidence_id_is_stripped_from_explanation():
    """Observed live: a small model wrote "(K2)" straight into an explanation."""
    m = MCQPayload(
        question="q",
        options=["a", "b", "c", "d"],
        correct_answer="A",
        correct_option_text="a",
        explanation="Muttiah Muralitharan has 800 Test wickets (K2).",
    )
    assert "K2" not in m.explanation
    assert m.explanation == "Muttiah Muralitharan has 800 Test wickets."


def test_leaked_evidence_id_is_stripped_from_question_and_statement():
    m = MCQPayload(
        question="Who holds the record (W1, K3)?",
        options=["a", "b", "c", "d"],
        correct_answer="A",
        correct_option_text="a",
        explanation="e",
    )
    assert "W1" not in m.question and "K3" not in m.question

    t = TrueFalsePayload(statement="Bradman averaged 99.94 (K1).", correct_answer=True,
                          explanation="e")
    assert "K1" not in t.statement


def test_leaked_evidence_id_stripped_before_blank_check():
    f = FillBlankPayload(
        sentence="___ took four wickets (W2).",
        options=["Bumrah", "Shami", "Siraj", "Kuldeep"],
        correct_answer="Bumrah",
        explanation="e",
    )
    assert "W2" not in f.sentence
    assert f.sentence == "___ took four wickets."


# --------------------------------------------------------------------------- #
# Every type has a schema, a model and Instagram packaging
# --------------------------------------------------------------------------- #


def test_every_content_type_is_fully_wired():
    for ctype in ContentType:
        assert ctype in JSON_SCHEMAS, f"{ctype} has no JSON schema"
        assert ctype in PAYLOAD_MODELS, f"{ctype} has no validation model"
        schema = JSON_SCHEMAS[ctype]
        assert schema["additionalProperties"] is False
        assert schema["required"], f"{ctype} schema has no required fields"


def test_instagram_block_marks_the_correct_option():
    payload = MCQPayload(
        question="Who won the 1983 World Cup?",
        options=["India", "Australia", "England", "Pakistan"],
        correct_answer="A",
        correct_option_text="India",
        explanation="India beat West Indies at Lord's.",
    ).model_dump()
    block, warnings = build_instagram_block(ContentType.MCQ, payload)
    assert block["sticker"] == "Quiz"
    assert block["correct_index"] == 0
    assert warnings == []


def test_instagram_block_warns_on_overlong_text():
    payload = PollPayload(
        prompt="Which of these two extremely long option labels do you personally "
        "prefer when watching a match on a weekend evening?",
        options=["An extremely long option label", "Another extremely long label"],
    ).model_dump()
    _, warnings = build_instagram_block(ContentType.POLL, payload)
    assert warnings, "expected truncation warnings for overlong sticker text"


def test_poll_instagram_block_has_no_correct_index():
    payload = PollPayload(prompt="Messi or Ronaldo?", options=["Messi", "Ronaldo"]).model_dump()
    block, _ = build_instagram_block(ContentType.POLL, payload)
    assert block["correct_index"] is None


# --------------------------------------------------------------------------- #
# Freshness / dedup
# --------------------------------------------------------------------------- #


def test_similarity_detects_a_reworded_question():
    a = tokenize("Who scored 264 in an ODI against Sri Lanka at Eden Gardens?")
    b = tokenize("Which batter made 264 runs versus Sri Lanka at Eden Gardens in an ODI?")
    assert similarity(a, b) > 0.4

    c = tokenize("How many Ballon d'Or awards has Lionel Messi won?")
    assert similarity(a, c) < 0.15


def test_history_store_flags_near_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        store = HistoryStore(Path(tmp) / "h.sqlite3")
        store.record("i1", "Cricket", "mcq", "Medium", "Rohit Sharma scored 264 against Sri Lanka")

        dup, matched, score = store.is_duplicate(
            "Cricket", "Rohit Sharma made 264 runs versus Sri Lanka", threshold=0.4
        )
        assert dup and matched and score > 0.4

        fresh, _, _ = store.is_duplicate("Cricket", "Anil Kumble took ten wickets in Delhi")
        assert not fresh

        # Sports are isolated from one another.
        other, _, _ = store.is_duplicate("Football", "Rohit Sharma scored 264 against Sri Lanka")
        assert not other

        store.forget("i1")
        gone, _, _ = store.is_duplicate("Cricket", "Rohit Sharma scored 264 against Sri Lanka")
        assert not gone


def test_subject_extraction_covers_every_type():
    payloads = {
        ContentType.MCQ: MCQPayload(
            question="q", options=["a", "b", "c", "d"], correct_answer="A",
            correct_option_text="a", explanation="e",
        ),
        ContentType.TRUE_FALSE: TrueFalsePayload(statement="s", correct_answer=True,
                                                 explanation="e"),
        ContentType.POLL: PollPayload(prompt="p", options=["a", "b"]),
        ContentType.FILL_BLANK: FillBlankPayload(
            sentence="___ x", options=["a", "b", "c", "d"], correct_answer="a", explanation="e",
        ),
        ContentType.GUESS_NUMBER: GuessNumberPayload(
            question="q", target_number=5, tolerance=1, unit="", explanation="e",
        ),
    }
    for ctype, payload in payloads.items():
        assert subject_of(ctype, payload.model_dump()).strip()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
