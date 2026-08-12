# AI-Powered Sports Engagement Content Agent

Generates **Instagram-ready interactive sports content** in five formats — MCQ, True/False,
This-or-That poll, Fill-in-the-Blank and Guess-the-Number — grounded in **live web search**
(for recent, fast-changing facts) and a **ChromaDB knowledge base** (for stable, historical
records).

Every generated item carries the source that supported it, is validated against a
format-specific schema before it is returned, and is fingerprinted so the same question
never comes back in a later session.

---

## Quick start

```bash
# 1. Install
python -m pip install -r requirements.txt

# 2. Configure
cp .env.example .env          # Windows: copy .env.example .env
#   then edit .env and set GROQ_API_KEY=gsk_...

# 3. Run
python run.py
```

Open **http://127.0.0.1:8000**.

On first launch the app seeds ChromaDB with 104 curated documents across 10 sports and
downloads the embedding model (~80 MB, once). Subsequent starts are instant.

```bash
python -m pytest tests -q     # 39 tests, no API key or network needed
```

---

## What it does

Pick a sport, a difficulty and one or more content types, and the agent returns a batch
of 4–5 items. Any single item can be regenerated without touching the rest of the batch,
or the whole batch can be regenerated at once.

| Content type | Output | Instagram surface | Fact-checked |
|---|---|---|---|
| Multiple Choice Question | Question, 4 options, correct answer, explanation | Story — Quiz sticker | ✅ |
| True / False | Statement, correct answer, explanation | Story — Poll sticker | ✅ |
| This-or-That Poll | Prompt, 2 options, **no correct answer** | Story — Poll sticker · Feed caption | ❌ opinion by design |
| Fill in the Blank | Sentence with one blank, 4 options, answer, explanation | Story — Quiz sticker · Reel caption | ✅ |
| Guess the Number | Question, target number, tolerance ±, accepted range, explanation | Story — Question sticker / Emoji slider | ✅ |

Each item also ships a ready-to-paste `instagram` block: the sticker type, the question,
the options in order, the index of the correct one, and a formatted feed caption. Where the
text would exceed Instagram's sticker character limits (92 for a quiz question, 25 per
option, 80 for a poll prompt), the dashboard shows a truncation warning so the creator can
regenerate rather than discover it in the app.

---

## Architecture

```
                        ┌────────────────────────────────────────────┐
  POST /api/generate    │              SportsContentAgent            │
  ─────────────────────▶│                                            │
                        │  1. RESEARCH  (once per batch, concurrent) │
                        │     ├── web_search ──▶ recent facts   W1…Wn│
                        │     └── ChromaDB   ──▶ stable facts   K1…Kn│
                        │                                            │
                        │  2. GENERATE  (once per item, concurrent)  │
                        │     type-specific template                 │
                        │     + constrained JSON decoding            │
                        │                                            │
                        │  3. VALIDATE  (per-type Pydantic contract) │
                        │     failure ──▶ feed the error back, retry │
                        │                                            │
                        │  4. DE-DUPLICATE                           │
                        │     vs. SQLite history (cross-session)     │
                        │     vs. the rest of this batch             │
                        └────────────────────────────────────────────┘
```

| Module | Responsibility |
|---|---|
| `app/agent.py` | Orchestration: research → generate → validate → dedupe, plus regeneration |
| `app/prompt_templates.py` | **Five separate prompt templates**, one per content type |
| `app/schemas.py` | JSON Schemas for constrained decoding + Pydantic contracts for validation |
| `app/web_search.py` | Live research via Groq's `groq/compound-mini` agentic model (built-in web search) |
| `app/vector_store.py` | ChromaDB retrieval for stable/historical facts |
| `app/knowledge_seed.py` | 104 curated seed documents across 10 sports |
| `app/history.py` | Cross-session freshness store (SQLite + Jaccard similarity) |
| `app/main.py` | FastAPI JSON API and static dashboard |
| `app/static/` | Dashboard (vanilla HTML/CSS/JS — no build step) |

### The type-specific architecture

The assignment calls for "a type-specific generation template for each content type rather
than one generic prompt". That is load-bearing here, not cosmetic: the five formats have
genuinely different failure modes, and a single prompt cannot address them.

| Type | What its template does that no other template does |
|---|---|
| **MCQ** | Requires distractors of the *same category* as the answer (four names, or four years — never mixed), and forbids the correct option from being the longest or most detailed, which is the classic way an MCQ leaks its answer. |
| **True / False** | Requires a *statement*, not a question, and instructs that false statements be built by altering one specific detail of a real fact — a false statement made of invented material is not a fun guess. Also bans hedging words, which otherwise telegraph the answer. |
| **This-or-That Poll** | Inverts the core instruction of every other template: there must be **no** correct answer, and no option that is obviously better. It is also the only template not bound to the retrieved evidence, because it makes no factual claim. |
| **Fill in the Blank** | Requires the blank on the *interesting* word, not a filler word, and requires all four options to fit grammatically — otherwise grammar gives the answer away without any sports knowledge. |
| **Guess the Number** | Requires the question to state its exact scope (which tournament, which format) so only one number is correct, and calibrates tolerance to magnitude: single digits → ±1, hundreds → ±10–25, thousands → ±50–200. |

Difficulty is injected as a separate calibration block (Easy = casual fan, Medium = regular
follower, Hard = die-hard), and is **omitted entirely for polls**, which have no answer to
be easy or hard about.

### Grounding and source citation

Retrieved evidence is labelled before it enters the prompt — web-search facts as `W1…Wn`,
knowledge-base documents as `K1…Kn`. The output schema requires the model to return an
`evidence_used` list, so each item names the specific lines it relied on. The agent maps
those ids back to concrete sources, and the dashboard shows per-item badges — `web search`,
`vector DB` or both — with clickable URLs.

If the model cites nothing resolvable, the item falls back to the batch's retrieved set
rather than being shown as unsourced. Polls are labelled `opinion — not fact-checked`,
which is a statement of design intent, not a failure.

Web search is a separate API call from generation, on a separate model. That is deliberate:
research runs on `groq/compound-mini`, an agentic model with built-in, automatic web search
and no tool schema to declare — Groq doesn't document structured-output support on that
model family, so it stays a free-text call. Generation runs on `openai/gpt-oss-20b`, which
supports Groq's strict JSON Schema mode. It also means a batch pays for research once and
reuses it across all 4–5 items — and per-item regeneration reuses it again, so replacing one
card costs one model call, not a fresh research cycle.

### Validation: two independent layers

1. **Constrained decoding.** Each type's JSON Schema goes to the API via
   `response_format={"type": "json_schema", "json_schema": {"strict": true, ...}}`, so the
   model can only emit structurally valid JSON.
2. **Independent Pydantic validation.** Every item is then re-validated in the app.

The second layer is not redundant. Constrained decoding guarantees *shape*, not *semantics* —
it cannot enforce that an MCQ's `correct_answer` letter matches its `correct_option_text`,
that a fill-in-the-blank's answer actually appears among its options, or that a poll's
options are distinct. Those are exactly the checks layer 2 performs:

- MCQ — exactly 4 distinct non-empty options, exactly one correct answer, letter/text agreement
- Poll — exactly 2 distinct options, `correct_answer` structurally pinned to `None`
- Fill-in-the-Blank — exactly one `___`, exactly 4 options, answer present among them
- Guess-the-Number — numeric target, strictly positive tolerance, range recomputed from target ± tolerance
- All — option prefixes (`A)`, `1.`) stripped, answer casing normalised

A validation failure is **not** surfaced as an error. The failure message is fed back into
the prompt as a retry note and the item is regenerated, so the caller only ever sees items
that passed.

### Freshness across sessions

Prompting alone cannot deliver "avoid repeating the same question across sessions" — the
model has no memory of yesterday. So every accepted item is fingerprinted into SQLite and
the store is used twice:

- **Before** generation, the last 40 subjects for that sport are injected as an explicit
  avoid-list.
- **After** generation, the candidate is compared against history by Jaccard token overlap
  (stopword-filtered). Above the threshold (default 0.55) it is regenerated with a tighter
  avoid-list quoting the specific collision.

Because items in a batch generate concurrently, they can also collide with *each other* —
history cannot catch that, since nothing is written until the batch completes. A second pass
compares the batch against itself and sequentially regenerates any collision.

Both freshness checks are **soft**: they trigger regeneration while retries remain, but on
the final attempt the item is accepted anyway. A slightly repetitive item is better than a
short batch.

Diversity is also pushed from the front: ChromaDB queries rotate through eight query angles,
retrieved documents are shuffled so the model doesn't anchor on the top-ranked one every
time, and each item in a batch gets a different angle hint.

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/` | Dashboard |
| `GET` | `/api/health` | Model, credentials, KB and history stats |
| `GET` | `/api/meta` | Sports, difficulties, content types for the UI |
| `POST` | `/api/generate` | Generate a batch |
| `POST` | `/api/regenerate-item` | Replace one item, keep the rest — refetches live research by default (`refresh_research: false` to reuse the batch's) |
| `POST` | `/api/regenerate-batch` | Replace every item |
| `POST` | `/api/search` | Ad hoc live web search — standalone, uncached, always a fresh request |
| `GET` | `/api/history` | Inspect the freshness store |
| `DELETE`| `/api/history` | Clear it (optionally per sport) |

Interactive docs at `/docs`.

```bash
curl -X POST http://127.0.0.1:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"sport":"Cricket","difficulty":"Medium",
       "types":["mcq","true_false","poll","fill_blank","guess_number"],
       "count":5,"mixed":true}'
```

`/api/search` is the standalone research entry point — it isn't part of the quiz
pipeline and nothing about it is cached. Every call is its own live request to
`groq/compound-mini`, so the same query asked twice can come back with different
results as the web changes:

```bash
curl -X POST http://127.0.0.1:8000/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"Who won the most recent Formula 1 race?"}'
```

<details>
<summary>Sample item</summary>

```json
{
  "id": "9f2c1a4b7e03",
  "type": "guess_number",
  "type_label": "Guess the Number",
  "sport": "Cricket",
  "difficulty": "Medium",
  "payload": {
    "question": "How many runs did Virat Kohli score in the 2023 ODI World Cup?",
    "target_number": 765,
    "tolerance": 25,
    "unit": "runs",
    "acceptable_range": [740, 790],
    "explanation": "Kohli's 765 runs is the most by any batter in a single World Cup."
  },
  "sources": [
    { "kind": "web_search", "title": "ICC tournament records",
      "reference": "https://…", "snippet": "Kohli finished the 2023 World Cup with 765 runs." }
  ],
  "grounding": "Web search",
  "grounding_kinds": ["web_search"],
  "fact_checked": true,
  "recommended_surface": "Story — Question sticker or Emoji slider",
  "instagram": {
    "sticker": "Question / Emoji slider",
    "question": "How many runs did Virat Kohli score in the 2023 ODI World Cup?",
    "answer": "765 runs",
    "accepted": "740 – 790 runs",
    "caption": "How many runs …\n\nAnswer 👉 765 runs (±25 counts!)\n…"
  },
  "format_warnings": [],
  "attempts": 1
}
```
</details>

---

## Configuration

All optional except the API key. See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** From [console.groq.com/keys](https://console.groq.com/keys). |
| `SPORTS_AGENT_MODEL` | `openai/gpt-oss-20b` | Structured-JSON generation model. Must support Groq strict structured outputs — currently `openai/gpt-oss-20b` / `openai/gpt-oss-120b`. |
| `SPORTS_AGENT_RESEARCH_MODEL` | `groq/compound-mini` | Agentic model with built-in, automatic web search (no tool schema needed). `groq/compound` supports multiple searches per request but needs a higher-tier token budget. |
| `SPORTS_AGENT_TEMPERATURE` | `0.6` | Sampling temperature (0–2) |
| `SPORTS_AGENT_REASONING_EFFORT` | `low` | `openai/gpt-oss-*` models spend completion tokens on hidden reasoning before the final JSON — `low` leaves headroom for the actual answer |
| `SPORTS_AGENT_MAX_CONCURRENCY` | `2` | Max simultaneous generation calls per batch — lower Groq tiers enforce a small per-minute token budget shared across concurrent requests |
| `CHROMA_DIR` | `app/data/chroma` | ChromaDB persistence directory |
| `HISTORY_DB` | `app/data/history.sqlite3` | Freshness store |
| `DEDUPE_THRESHOLD` | `0.55` | Similarity above which two items are duplicates |
| `ENABLE_WEB_SEARCH` | `1` | Set `0` to run on the knowledge base alone |

### Extending the knowledge base

Add tuples to `SEED_DOCUMENTS` in `app/knowledge_seed.py` (and the sport to `SPORTS`), then
delete `app/data/chroma/` to force a re-seed. At runtime, `KnowledgeBase.add_document()`
upserts without a restart. Sports outside the seed list still work — the KB falls back to an
unfiltered search and web search covers the rest.

---

## Deployment

`render.yaml` at the repo root is a [Render](https://render.com) Blueprint — it defines the
build/start commands and every env var from the table above, so standing up a live instance
is mostly clicking through Render's dashboard rather than configuring anything by hand:

1. Push this repo to GitHub (already done if you're reading this from there).
2. On Render: **New +** → **Blueprint** → connect the repo. It reads `render.yaml` automatically.
3. Render will prompt for `GROQ_API_KEY` specifically (it's marked `sync: false` in the
   blueprint so it's never read from the repo) — paste your key there.
4. Deploy. First boot re-seeds ChromaDB same as a fresh local run.

Two things worth knowing about the free tier specifically:
- **Storage is ephemeral.** `app/data/` resets on every deploy and on the periodic restarts
  Render does for free services. That's fine here by design — Chroma re-seeds itself and the
  freshness history is meant to be disposable — but don't expect history to persist across
  restarts the way it does on a long-running local instance.
- **Free services spin down when idle** and cold-start on the next request, so the first load
  after a quiet period can take 30–60 seconds before the page appears.

---

## Testing

50 tests, no API key and no network. A stub client stands in for the model, so the real
orchestration is exercised exactly as it runs in production.

```bash
python -m pytest tests -q
```

- `tests/test_validation.py` — the per-type contracts, Instagram packaging, similarity scoring,
  the defensive strip of any evidence-id that leaks into visible text
- `tests/test_pipeline.py` — batch generation, mixed batches, per-item and full-batch
  regeneration, source citation, retry-on-invalid-payload, freshness, and a check that all
  five content types really do use five distinct system prompts
- `tests/test_web_search.py` — response parsing against Groq's real `executed_tools` shape,
  and detecting a "declined to search" reply so it isn't mistaken for research

Several bugs were found and fixed against the live API, not just the stub — worth listing
because they're the kind stubs alone don't catch:

- A SQLite connection leak (`with sqlite3.connect(...)` manages the transaction but never
  closes the handle) — caught by the offline suite.
- A required-but-never-supplied `acceptable_range` field that made every Guess-the-Number
  item fail validation — caught by the offline suite.
- **Token budget mismatch.** The generation call carried over a budget sized for a
  large-context model; on Groq's lower tiers, that alone exceeded the account's per-minute
  token limit once a batch's items generated concurrently.
- **Reasoning models need reasoning room.** `openai/gpt-oss-20b` spends completion tokens on
  hidden chain-of-thought before the final JSON — an undersized token cap let it exhaust the
  budget mid-thought, which Groq's strict-mode validator then rejects outright rather than
  truncating gracefully. Fixed with `reasoning_effort: "low"` plus a right-sized cap.
- **Nested response shape.** Groq's `search_results` field is a container object wrapping the
  actual results list, not the list itself — the first version silently discarded every
  citation URL in favor of one generic fallback per tool call.
- **A refusal disguised as an answer.** The research model occasionally answered from its own
  training data with a "my knowledge only goes to X" disclaimer instead of actually
  searching. That text is non-empty, so it slipped past the "no results" check and got handed
  to generation as if it were real evidence. Now detected and discarded explicitly.

None of these would have surfaced from the stub alone — they're artifacts of a specific
provider's real response shapes and rate limits, which is the case for running against the
live API at least once before calling a migration done.

---

## Design notes and limitations

- **Batch context is in-memory.** Regeneration needs its batch's research context, which
  lives in a process-local dict. A server restart invalidates open batches (the API returns
  a clear message). Redis or a database would fix this for a multi-worker deployment.
- **Freshness is per sport, not per user.** The SQLite store is global. Multi-tenant use
  would want a creator/account column on `generated_items`.
- **Fact-checking is grounding, not verification.** Items are constrained to retrieved
  evidence and cite it, which removes the main hallucination path — but the agent does not
  independently re-verify a claim against a second source. A verification pass over the
  final items would be the next accuracy improvement.
- **Web search reliability depends on the Groq account tier.** `groq/compound-mini` was
  chosen specifically because full `groq/compound` 413'd on the tier this was built against —
  a higher tier may handle `groq/compound` fine and get multi-search research instead of
  single-search. When live search genuinely returns nothing (rate-limited, or the model
  declines to search), the batch falls back to knowledge-base-only grounding and says so in
  `warnings` — by design, not silently.
