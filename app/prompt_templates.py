"""Type-specific generation templates.

Each of the five content types gets its own system prompt and its own user
template — deliberately, rather than one generic prompt with a "type" variable.
The formats have genuinely different failure modes:

* an MCQ needs three *plausible* distractors, not three obvious throwaways;
* a True/False needs a mix of true and false statements, or the audience learns
  to always answer "true";
* a This-or-That poll must have NO right answer, which is the exact opposite of
  the instruction every other template carries;
* a Fill-in-the-Blank needs the blank in the interesting position, not the
  trivial one;
* a Guess-the-Number needs a tolerance calibrated to the magnitude of the number.

Writing one prompt per type is what lets each of those be addressed directly.
"""

from __future__ import annotations

from .schemas import ContentType

# --------------------------------------------------------------------------- #
# Shared fragments
# --------------------------------------------------------------------------- #

BASE_ROLE = """You write interactive sports content for an Instagram audience.

You are given retrieved evidence — recent facts pulled from live web search and \
stable records pulled from a curated knowledge base. Your output must be \
grounded in that evidence."""

GROUNDING_RULES = """
GROUNDING (non-negotiable)
- Every factual claim you make must be supported by the RETRIEVED EVIDENCE below.
- Do not use a fact that is not in the evidence, even if you are confident it is \
true. If the evidence is thin, write a narrower question that the evidence fully \
covers rather than reaching beyond it.
- Never invent statistics, dates, scores or names. A wrong number is worse than \
a boring question.
- Set `evidence_used` to the exact id(s) of the evidence lines you relied on. That \
field is the ONLY place evidence ids ever appear. Never write an id like "W2" or \
"K1" inside the question, statement, sentence, options or explanation — those are \
internal labels for this system, not something a reader should ever see."""

STYLE_RULES = """
STYLE
- Write for a phone screen: punchy, specific, readable at a glance.
- No hashtags, no emoji, no "Did you know" preamble, no meta commentary.
- Name the sport's people and teams plainly; assume the reader follows the sport \
but is not a statistician.
- Explanations are one or two sentences and state the supporting fact."""

DIFFICULTY_GUIDE = {
    "Easy": """DIFFICULTY: Easy
Aim at a casual fan who watches the big moments. Use headline names, marquee \
finals, and facts that a follower of the sport would recognise instantly. \
Distractors should be clearly wrong to anyone who follows the sport.""",
    "Medium": """DIFFICULTY: Medium
Aim at a regular follower who watches most weeks. Require real recall — a \
specific number, a secondary name, the year something happened. Distractors \
should be genuinely tempting: right era, right kind of answer, wrong detail.""",
    "Hard": """DIFFICULTY: Hard
Aim at a die-hard who argues about this sport online. Use precise statistics, \
lesser-known record holders, or fine distinctions between similar achievements. \
Distractors should be near-misses that a knowledgeable fan would have to think \
about.""",
}

INSTAGRAM_LIMITS = """
INSTAGRAM FIT
- Question/statement: keep under 90 characters so the Quiz sticker does not \
truncate it.
- Each option: keep under 25 characters. Short surnames and short phrases, not \
full sentences."""


def _freshness_block(avoid: list[str]) -> str:
    if not avoid:
        return (
            "\nFRESHNESS\n- This is a fresh topic space. Pick the angle you find "
            "most interesting in the evidence."
        )
    listed = "\n".join(f"  - {a}" for a in avoid[:25])
    return f"""
FRESHNESS (this is why your output must be new)
The following subjects have ALREADY been used for this sport in previous items. \
Your item must be about a different fact, a different person, a different \
record or a different moment. Rewording one of these is a failure.
{listed}"""


def _evidence_block(web_brief: str, kb_lines: list[str]) -> str:
    parts = ["\nRETRIEVED EVIDENCE"]

    if web_brief.strip():
        parts.append("\n[WEB SEARCH — recent and fast-changing, id prefix W]")
        for i, line in enumerate(_bullets(web_brief), start=1):
            parts.append(f"  W{i}. {line}")
    else:
        parts.append("\n[WEB SEARCH — no live results available for this request]")

    if kb_lines:
        parts.append("\n[KNOWLEDGE BASE — stable historical records, id prefix K]")
        for i, line in enumerate(kb_lines, start=1):
            parts.append(f"  K{i}. {line}")
    else:
        parts.append("\n[KNOWLEDGE BASE — no matching documents]")

    return "\n".join(parts)


def _bullets(brief: str) -> list[str]:
    out = []
    for raw in brief.splitlines():
        line = raw.strip().lstrip("-•*").strip()
        if line:
            out.append(line)
    return out


# --------------------------------------------------------------------------- #
# Per-type system prompts
# --------------------------------------------------------------------------- #

SYSTEM_PROMPTS: dict[str, str] = {
    ContentType.MCQ: f"""{BASE_ROLE}

You write MULTIPLE CHOICE QUESTIONS with exactly four options and exactly one \
correct answer.
{GROUNDING_RULES}

MCQ CRAFT
- Exactly four options. Exactly one is correct; the other three must be \
unambiguously wrong, with no room to argue.
- Distractors must be the same *kind* of thing as the answer — four player \
names, or four years, or four numbers of similar magnitude. Never mix categories.
- Do not make the correct option the longest, the most detailed, or the only \
one phrased differently. Length and specificity must not leak the answer.
- Vary which position holds the answer across items.
- Options carry no "A)" / "1." prefixes — just the text.
{STYLE_RULES}{INSTAGRAM_LIMITS}""",
    ContentType.TRUE_FALSE: f"""{BASE_ROLE}

You write TRUE / FALSE challenges: one crisp statement the audience judges.
{GROUNDING_RULES}

TRUE/FALSE CRAFT
- Write a STATEMENT, never a question. No question mark.
- The statement must be decisively true or decisively false — no "mostly", no \
"about", nothing that depends on interpretation.
- If you write a FALSE statement, build it by altering one specific detail of a \
real fact from the evidence (wrong year, wrong opponent, wrong number). A false \
statement made of invented material is not fun to play.
- Do not signal the answer with hedging words. "X holds the record" and \
"X allegedly holds the record" read very differently.
- Aim for a believable near-miss, not an absurd claim.
{STYLE_RULES}
INSTAGRAM FIT
- Keep the statement under 80 characters — it renders in a Poll sticker with \
True/False as the two options.""",
    ContentType.POLL: f"""{BASE_ROLE}

You write THIS-OR-THAT POLLS: two rival choices, pure opinion, no correct answer.

THIS IS NOT A QUIZ. It is the one format where being unanswerable is the goal.

POLL CRAFT
- There must be NO correct answer, and no answer that is obviously better. If a \
well-informed fan would say one side is simply right, the poll has failed.
- The two options must be genuinely comparable and genuinely divisive — the kind \
of thing that fills a comments section.
- Frame it as a matter of taste, preference or judgement: greatest, most \
entertaining, would you rather, who do you back.
- Do not ask about facts, records or statistics. Do not include an explanation.
- Use the retrieved evidence only for *who and what is currently relevant* — \
current form, recent rivalries, players in the news. You are not making a \
factual claim, so you are not bound to the evidence the way the quiz formats are.
- Both options must be recognisable to the sport's audience.
{STYLE_RULES}
INSTAGRAM FIT
- Prompt under 80 characters, each option under 25 — it renders directly in a \
Poll sticker.""",
    ContentType.FILL_BLANK: f"""{BASE_ROLE}

You write FILL-IN-THE-BLANK prompts: one factual sentence with a single blank, \
plus four candidate answers.
{GROUNDING_RULES}

FILL-IN-THE-BLANK CRAFT
- The sentence contains exactly one blank, written as three underscores: ___
- Put the blank on the interesting word — the name, the number, the venue — not \
on a filler word. "___ scored 264 against Sri Lanka" works; "Rohit Sharma ___ \
264 against Sri Lanka" does not.
- Leave enough context around the blank that the sentence is answerable from \
knowledge, not from grammar.
- Exactly four options, all of which fit the sentence grammatically. If three \
options make the sentence read wrong, the blank has given itself away.
- The correct answer must be reproduced verbatim as one of the four options.
{STYLE_RULES}{INSTAGRAM_LIMITS}""",
    ContentType.GUESS_NUMBER: f"""{BASE_ROLE}

You write GUESS THE NUMBER prompts: a question whose answer is one specific \
number, plus a tolerance band that counts as a correct guess.
{GROUNDING_RULES}

GUESS-THE-NUMBER CRAFT
- The answer must be a single unambiguous number that appears in the evidence. \
Not a range, not an average you computed, not an estimate.
- State the exact scope in the question so there is only one right answer: which \
tournament, which season, which format, which competition.
- Set the tolerance to the magnitude of the number so the game is winnable but \
not trivial. Roughly: single digits -> 1; tens -> 2-5; hundreds -> 10-25; \
thousands -> 50-200. Never zero.
- Fill `unit` with the thing being counted ("runs", "goals", "seconds", \
"titles"). Use an empty string only when the number is genuinely unitless.
- Prefer numbers a fan could reason toward, not arbitrary trivia.
{STYLE_RULES}
INSTAGRAM FIT
- Keep the question under 90 characters — it renders in a Question sticker or \
an Emoji slider.""",
}


# --------------------------------------------------------------------------- #
# Per-type user templates
# --------------------------------------------------------------------------- #

_TYPE_TASK: dict[str, str] = {
    ContentType.MCQ: "Write ONE multiple choice question with four options and one correct answer.",
    ContentType.TRUE_FALSE: "Write ONE true/false statement.",
    ContentType.POLL: "Write ONE this-or-that opinion poll with exactly two options.",
    ContentType.FILL_BLANK: (
        "Write ONE fill-in-the-blank sentence with a single ___ blank and four options."
    ),
    ContentType.GUESS_NUMBER: (
        "Write ONE guess-the-number question with an exact target and a tolerance."
    ),
}


def build_generation_prompt(
    ctype: ContentType,
    sport: str,
    difficulty: str,
    web_brief: str,
    kb_lines: list[str],
    avoid: list[str],
    angle_hint: str = "",
    retry_note: str = "",
) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for one item of one type."""
    system = SYSTEM_PROMPTS[ctype]

    sections = [
        f"Sport: {sport}",
        _TYPE_TASK[ctype],
    ]

    # A poll has no correct answer, so difficulty does not apply to it.
    if ctype != ContentType.POLL:
        sections.append("")
        sections.append(DIFFICULTY_GUIDE.get(difficulty, DIFFICULTY_GUIDE["Medium"]))

    sections.append(_evidence_block(web_brief, kb_lines))
    sections.append(_freshness_block(avoid))

    if angle_hint:
        sections.append(f"\nANGLE FOR THIS ITEM\n- Lean towards: {angle_hint}")

    if retry_note:
        sections.append(f"\nRETRY\n- {retry_note}")

    sections.append("\nReturn only the JSON object described by the output schema.")
    return system, "\n".join(sections)


# Rotated per item inside a batch so five MCQs about the same sport don't all
# land on the same corner of the evidence.
ITEM_ANGLES = [
    "a very recent result, series or tournament outcome",
    "an all-time record or a career milestone",
    "a specific number: a score, a tally, a margin or a time",
    "a memorable single performance",
    "a national team, club or franchise achievement",
    "a rule, format or measurement of the game",
    "a first, a debut or a breakthrough moment",
    "a head-to-head or rivalry between two names in the evidence",
]
