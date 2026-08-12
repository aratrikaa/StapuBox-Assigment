"""Per-type output contracts.

Two representations live here, and they must stay in sync:

1. ``JSON_SCHEMAS`` — the JSON Schema handed to the Groq API via
   ``response_format={"type": "json_schema", ...}`` (strict mode). This
   constrains generation, so the model can only emit structurally valid JSON
   in the first place.
2. The Pydantic models — the *independent* validation pass every item must
   survive before it is returned to the caller. This is what enforces the
   assignment's per-type invariants (MCQ has exactly 4 options and 1 correct
   answer, a poll has exactly 2 options and no correct answer,
   guess-the-number has a numeric target plus an acceptable range, ...).

Belt and braces on purpose: constrained decoding can still produce a
semantically invalid item (e.g. a `correct_answer` letter that doesn't match
the option text), and that is exactly what layer 2 catches.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class ContentType(str, Enum):
    MCQ = "mcq"
    TRUE_FALSE = "true_false"
    POLL = "poll"
    FILL_BLANK = "fill_blank"
    GUESS_NUMBER = "guess_number"


class Difficulty(str, Enum):
    EASY = "Easy"
    MEDIUM = "Medium"
    HARD = "Hard"


CONTENT_TYPE_LABELS: dict[str, str] = {
    ContentType.MCQ: "Multiple Choice Question",
    ContentType.TRUE_FALSE: "True / False",
    ContentType.POLL: "This-or-That Poll",
    ContentType.FILL_BLANK: "Fill in the Blank",
    ContentType.GUESS_NUMBER: "Guess the Number",
}

# Which Instagram surface each format is designed to drop into.
RECOMMENDED_SURFACE: dict[str, str] = {
    ContentType.MCQ: "Story — Quiz sticker",
    ContentType.TRUE_FALSE: "Story — Poll sticker (True / False)",
    ContentType.POLL: "Story — Poll sticker · Feed caption",
    ContentType.FILL_BLANK: "Story — Quiz sticker · Reel caption",
    ContentType.GUESS_NUMBER: "Story — Question sticker or Emoji slider",
}

# These are the only formats that are opinion-based and therefore NOT fact-checked.
OPINION_TYPES = {ContentType.POLL}

# Soft limits from Instagram's native sticker UI. Exceeding them doesn't fail
# validation — it raises a warning the dashboard shows, so a creator knows the
# text will be truncated in the sticker and can regenerate.
IG_QUIZ_QUESTION_CHARS = 92
IG_QUIZ_OPTION_CHARS = 25
IG_POLL_PROMPT_CHARS = 80
IG_POLL_OPTION_CHARS = 25


# --------------------------------------------------------------------------- #
# Sourcing / grounding
# --------------------------------------------------------------------------- #


class SourceKind(str, Enum):
    WEB_SEARCH = "web_search"
    VECTOR_DB = "vector_db"
    OPINION = "opinion"


class Source(BaseModel):
    """Which retrieved evidence supported this item's factual claim."""

    kind: SourceKind
    title: str = ""
    reference: str = ""  # URL for web results, Chroma document id for the vector DB
    snippet: str = ""


# --------------------------------------------------------------------------- #
# Per-type payloads (validation layer)
# --------------------------------------------------------------------------- #

LETTERS = ("A", "B", "C", "D")


def _clean_options(options: list[str]) -> list[str]:
    """Strip any leading "A) " / "1. " labelling the model may have added."""
    return [re.sub(r"^\s*(?:[A-Da-d][.)]|\d[.)])\s*", "", o).strip() for o in options]


# Prompts instruct the model to keep evidence ids (W1, K2, ...) confined to the
# `evidence_used` field, but a small open-weight model can still slip one into
# visible text (observed live: "... 800 Test wickets (K2)."). This is the
# belt half of belt-and-braces: strip a parenthetical citation-id group from
# any free-text field on the way out, regardless of whether the prompt held.
_EVIDENCE_ID_LEAK = re.compile(r"\s*\(\s*[WK]\d{1,3}(?:\s*,\s*[WK]\d{1,3})*\s*\)")


def _strip_evidence_ids(text: str) -> str:
    return _EVIDENCE_ID_LEAK.sub("", text).strip()


class MCQPayload(BaseModel):
    question: str
    options: list[str]
    correct_answer: Literal["A", "B", "C", "D"]
    correct_option_text: str
    explanation: str

    @field_validator("question", "explanation")
    @classmethod
    def _no_leaked_evidence_ids(cls, v: str) -> str:
        return _strip_evidence_ids(v)

    @field_validator("options")
    @classmethod
    def _exactly_four_distinct(cls, v: list[str]) -> list[str]:
        v = _clean_options(v)
        if len(v) != 4:
            raise ValueError(f"MCQ must have exactly 4 options, got {len(v)}")
        if any(not o for o in v):
            raise ValueError("MCQ options must be non-empty")
        if len({o.casefold() for o in v}) != 4:
            raise ValueError("MCQ options must be distinct")
        return v

    @model_validator(mode="after")
    def _one_correct_answer_that_matches(self) -> "MCQPayload":
        idx = LETTERS.index(self.correct_answer)
        expected = self.options[idx]
        if self.correct_option_text.strip().casefold() != expected.casefold():
            # The letter is authoritative; repair the echo rather than reject a
            # otherwise-good item over a cosmetic mismatch.
            self.correct_option_text = expected
        return self


class TrueFalsePayload(BaseModel):
    statement: str
    correct_answer: bool
    explanation: str

    @field_validator("statement", "explanation")
    @classmethod
    def _no_leaked_evidence_ids(cls, v: str) -> str:
        return _strip_evidence_ids(v)


class PollPayload(BaseModel):
    prompt: str
    options: list[str]
    # Structurally pinned to None: a This-or-That poll has no correct answer.
    correct_answer: None = None
    opinion_based: Literal[True] = True

    @field_validator("options")
    @classmethod
    def _exactly_two_distinct(cls, v: list[str]) -> list[str]:
        v = _clean_options(v)
        if len(v) != 2:
            raise ValueError(f"Poll must have exactly 2 options, got {len(v)}")
        if any(not o for o in v):
            raise ValueError("Poll options must be non-empty")
        if v[0].casefold() == v[1].casefold():
            raise ValueError("Poll options must be distinct")
        return v


class FillBlankPayload(BaseModel):
    sentence: str
    options: list[str]
    correct_answer: str
    explanation: str

    @field_validator("explanation")
    @classmethod
    def _no_leaked_evidence_ids(cls, v: str) -> str:
        return _strip_evidence_ids(v)

    @field_validator("sentence")
    @classmethod
    def _has_a_blank(cls, v: str) -> str:
        v = _strip_evidence_ids(v)
        if "___" not in v:
            raise ValueError("Fill-in-the-blank sentence must contain a '___' blank")
        if v.count("___") > 1:
            raise ValueError("Fill-in-the-blank sentence must contain exactly one blank")
        return v

    @field_validator("options")
    @classmethod
    def _exactly_four_distinct(cls, v: list[str]) -> list[str]:
        v = _clean_options(v)
        if len(v) != 4:
            raise ValueError(f"Fill-in-the-blank must have exactly 4 options, got {len(v)}")
        if len({o.casefold() for o in v}) != 4:
            raise ValueError("Fill-in-the-blank options must be distinct")
        return v

    @model_validator(mode="after")
    def _answer_is_one_of_the_options(self) -> "FillBlankPayload":
        answer = self.correct_answer.strip()
        match = next((o for o in self.options if o.casefold() == answer.casefold()), None)
        if match is None:
            raise ValueError("correct_answer must be one of the four options")
        self.correct_answer = match
        return self


class GuessNumberPayload(BaseModel):
    question: str
    target_number: float
    tolerance: float
    unit: str = ""
    # Derived, never supplied by the model — it is recomputed from
    # target ± tolerance below, so the JSON schema deliberately omits it.
    acceptable_range: list[float] = Field(default_factory=list)
    explanation: str

    @field_validator("question", "explanation")
    @classmethod
    def _no_leaked_evidence_ids(cls, v: str) -> str:
        return _strip_evidence_ids(v)

    @field_validator("tolerance")
    @classmethod
    def _positive_tolerance(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Guess-the-Number needs a positive tolerance")
        return v

    @model_validator(mode="after")
    def _range_matches_target_and_tolerance(self) -> "GuessNumberPayload":
        # The range is derived, never trusted: recompute it from target ± tolerance.
        low = self.target_number - self.tolerance
        high = self.target_number + self.tolerance
        self.acceptable_range = [low, high]
        return self


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    ContentType.MCQ: MCQPayload,
    ContentType.TRUE_FALSE: TrueFalsePayload,
    ContentType.POLL: PollPayload,
    ContentType.FILL_BLANK: FillBlankPayload,
    ContentType.GUESS_NUMBER: GuessNumberPayload,
}


# --------------------------------------------------------------------------- #
# The envelope returned to the dashboard
# --------------------------------------------------------------------------- #


class ContentItem(BaseModel):
    id: str
    type: ContentType
    type_label: str
    sport: str
    difficulty: Difficulty | None  # None only for opinion polls
    payload: dict[str, Any]
    sources: list[Source] = Field(default_factory=list)
    grounding: str  # human-readable label, e.g. "Web search + Knowledge base"
    grounding_kinds: list[SourceKind] = Field(default_factory=list)
    fact_checked: bool
    recommended_surface: str
    instagram: dict[str, Any] = Field(default_factory=dict)
    format_warnings: list[str] = Field(default_factory=list)
    created_at: str
    attempts: int = 1


class Batch(BaseModel):
    id: str
    sport: str
    difficulty: Difficulty
    requested_types: list[ContentType]
    mixed: bool
    items: list[ContentItem]
    research_summary: str = ""
    web_sources: list[Source] = Field(default_factory=list)
    kb_sources: list[Source] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str


# --------------------------------------------------------------------------- #
# JSON Schemas for constrained decoding (generation layer)
# --------------------------------------------------------------------------- #


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_STR = {"type": "string"}

# Per-item source attribution. The model reports which evidence lines it leaned
# on (W1/W2/... = web search, K1/K2/... = vector DB); the agent maps those ids
# back to the concrete Source objects shown in the UI. This is what makes
# "which source supported this answer" answerable per item rather than per batch.
_EVIDENCE_USED = {
    "type": "array",
    "items": _STR,
    "description": (
        "Ids of the retrieved evidence lines that support this item, "
        "e.g. ['W3', 'K1']. Use only ids that appear in RETRIEVED EVIDENCE."
    ),
}


JSON_SCHEMAS: dict[str, dict[str, Any]] = {
    ContentType.MCQ: _obj(
        {
            "question": {**_STR, "description": "The quiz question, one sentence."},
            "options": {
                "type": "array",
                "items": _STR,
                "description": "Exactly four distinct answer options, no A)/B) prefixes.",
            },
            "correct_answer": {
                "type": "string",
                "enum": ["A", "B", "C", "D"],
                "description": "Letter of the correct option (A=first, D=fourth).",
            },
            "correct_option_text": {**_STR, "description": "Verbatim text of the correct option."},
            "explanation": {**_STR, "description": "One or two sentences citing the fact."},
            "evidence_used": _EVIDENCE_USED,
        },
        [
            "question",
            "options",
            "correct_answer",
            "correct_option_text",
            "explanation",
            "evidence_used",
        ],
    ),
    ContentType.TRUE_FALSE: _obj(
        {
            "statement": {**_STR, "description": "A single verifiable claim, not a question."},
            "correct_answer": {"type": "boolean", "description": "true if the statement is true."},
            "explanation": {**_STR, "description": "One or two sentences citing the fact."},
            "evidence_used": _EVIDENCE_USED,
        },
        ["statement", "correct_answer", "explanation", "evidence_used"],
    ),
    ContentType.POLL: _obj(
        {
            "prompt": {**_STR, "description": "An opinion-based this-or-that question."},
            "options": {
                "type": "array",
                "items": _STR,
                "description": "Exactly two rival choices. No correct answer exists.",
            },
        },
        ["prompt", "options"],
    ),
    ContentType.FILL_BLANK: _obj(
        {
            "sentence": {
                **_STR,
                "description": "A factual sentence with exactly one blank written as ___.",
            },
            "options": {
                "type": "array",
                "items": _STR,
                "description": "Exactly four distinct candidates for the blank.",
            },
            "correct_answer": {**_STR, "description": "Verbatim copy of the correct option."},
            "explanation": {**_STR, "description": "One or two sentences citing the fact."},
            "evidence_used": _EVIDENCE_USED,
        },
        ["sentence", "options", "correct_answer", "explanation", "evidence_used"],
    ),
    ContentType.GUESS_NUMBER: _obj(
        {
            "question": {**_STR, "description": "A question whose answer is a single number."},
            "target_number": {"type": "number", "description": "The exact correct number."},
            "tolerance": {
                "type": "number",
                "description": "Positive +/- window counted as a correct guess.",
            },
            "unit": {**_STR, "description": "Unit of the number, e.g. 'runs', 'goals', ''."},
            "explanation": {**_STR, "description": "One or two sentences citing the fact."},
            "evidence_used": _EVIDENCE_USED,
        },
        [
            "question",
            "target_number",
            "tolerance",
            "unit",
            "explanation",
            "evidence_used",
        ],
    ),
}


# The key the model reports its per-item citations under. Stripped from the
# payload before Pydantic validation — it is provenance metadata, not content.
EVIDENCE_KEY = "evidence_used"


def subject_of(ctype: ContentType, payload: dict[str, Any]) -> str:
    """The text used for freshness fingerprinting and the avoid-list."""
    if ctype == ContentType.MCQ:
        return f"{payload['question']} {payload['correct_option_text']}"
    if ctype == ContentType.TRUE_FALSE:
        return payload["statement"]
    if ctype == ContentType.POLL:
        return f"{payload['prompt']} {' '.join(payload['options'])}"
    if ctype == ContentType.FILL_BLANK:
        return f"{payload['sentence']} {payload['correct_answer']}"
    return f"{payload['question']} {payload['target_number']}"


# --------------------------------------------------------------------------- #
# Instagram packaging
# --------------------------------------------------------------------------- #


def _warn(field_name: str, text: str, limit: int) -> list[str]:
    if len(text) > limit:
        return [f"{field_name} is {len(text)} chars — Instagram truncates past {limit}."]
    return []


def build_instagram_block(ctype: ContentType, payload: dict[str, Any]) -> tuple[dict, list[str]]:
    """Turn a validated payload into copy-paste-ready sticker/caption fields."""
    warnings: list[str] = []

    if ctype == ContentType.MCQ:
        block = {
            "sticker": "Quiz",
            "question": payload["question"],
            "options": payload["options"],
            "correct_index": LETTERS.index(payload["correct_answer"]),
            "caption": f"{payload['question']}\n\nAnswer 👉 {payload['correct_option_text']}\n"
            f"{payload['explanation']}",
        }
        warnings += _warn("Question", payload["question"], IG_QUIZ_QUESTION_CHARS)
        for opt in payload["options"]:
            warnings += _warn(f"Option '{opt[:18]}…'", opt, IG_QUIZ_OPTION_CHARS)

    elif ctype == ContentType.TRUE_FALSE:
        block = {
            "sticker": "Poll",
            "question": payload["statement"],
            "options": ["True", "False"],
            "correct_index": 0 if payload["correct_answer"] else 1,
            "caption": f"{payload['statement']}\n\nAnswer 👉 "
            f"{'TRUE' if payload['correct_answer'] else 'FALSE'}\n{payload['explanation']}",
        }
        warnings += _warn("Statement", payload["statement"], IG_POLL_PROMPT_CHARS)

    elif ctype == ContentType.POLL:
        block = {
            "sticker": "Poll",
            "question": payload["prompt"],
            "options": payload["options"],
            "correct_index": None,
            "caption": f"{payload['prompt']}\n\n"
            f"{payload['options'][0]} or {payload['options'][1]}? Vote 👆",
        }
        warnings += _warn("Prompt", payload["prompt"], IG_POLL_PROMPT_CHARS)
        for opt in payload["options"]:
            warnings += _warn(f"Option '{opt[:18]}…'", opt, IG_POLL_OPTION_CHARS)

    elif ctype == ContentType.FILL_BLANK:
        block = {
            "sticker": "Quiz",
            "question": payload["sentence"],
            "options": payload["options"],
            "correct_index": payload["options"].index(payload["correct_answer"]),
            "caption": f"{payload['sentence']}\n\nAnswer 👉 {payload['correct_answer']}\n"
            f"{payload['explanation']}",
        }
        warnings += _warn("Sentence", payload["sentence"], IG_QUIZ_QUESTION_CHARS)
        for opt in payload["options"]:
            warnings += _warn(f"Option '{opt[:18]}…'", opt, IG_QUIZ_OPTION_CHARS)

    else:  # GUESS_NUMBER
        low, high = payload["acceptable_range"]
        unit = f" {payload['unit']}".rstrip()
        block = {
            "sticker": "Question / Emoji slider",
            "question": payload["question"],
            "options": [],
            "correct_index": None,
            "answer": f"{_fmt_num(payload['target_number'])}{unit}",
            "accepted": f"{_fmt_num(low)} – {_fmt_num(high)}{unit}",
            "caption": f"{payload['question']}\n\nAnswer 👉 "
            f"{_fmt_num(payload['target_number'])}{unit} "
            f"(±{_fmt_num(payload['tolerance'])} counts!)\n{payload['explanation']}",
        }
        warnings += _warn("Question", payload["question"], IG_QUIZ_QUESTION_CHARS)

    return block, warnings


def _fmt_num(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else f"{n:g}"
