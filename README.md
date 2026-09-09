# Ashen Era Intelligent Document Assistant

**SLIIT Codefest 2026 — AI Competition, powered by IFS**
Sub-track **1C — Searching the Way a Human Does** (primary), extended with
**1B — Connecting Facts Across Thousands of Pages**.

A **provenance-first multimodal archive investigator** for the Ashen Era Archive:
339 files and ~1,330 pages of novels, wiki articles, codex data books, in-world
ephemera, simulated scans and figure plates.

It is **not a database lookup tool** and **not a web search engine**. It plans an
investigation, searches iteratively, expands connected entities across documents,
reasons over what it finds, and answers with page-level citations, the quoted
source line, confidence, conflicts, and a visible record of why it stopped.

**What is a retrieval aid, and what is evidence.** The fact store, knowledge
graph, keyword index and vector index are *navigation*: they say where to look.
Every row in them carries the chunk it was extracted from, and an answer follows
that pointer back and quotes the original line. The archive's own documents,
tables, figures and scans are the source of truth; the indexes are the map, not
the territory.

> **Status — the full path runs end to end: ingestion → four indexes → hybrid
> retrieval → bounded investigation → reasoning → verification → API and web UI.**
> It works with **no API key at all**: entity matching, routing, retrieval, OCR,
> chart reading, date reasoning and arithmetic are all deterministic, and the
> measured accuracy is the same with the LLM switched off. Adding a key activates
> LLM assistance with no code change; adding `AEA_VISION_MODEL` activates image
> interpretation. See [docs/limitations.md](docs/limitations.md) for what each
> costs and what remains unsolved.

**Measured** — reproduce with the commands in [Test](#test):

| Set | Score | What it measures |
|---|---|---|
| Held-out questions | **30 / 30** | general capability, written after the rules and never tuned against |
| Team question set | **30 / 30** | regression on questions we developed against |
| Supplied dev set (cited) | **15 / 20** | the 5 misses need artwork interpretation |

---

## Why this archive is hard

Three properties of the corpus drove the design, and each is verifiable from the
data rather than assumed:

1. **The vocabulary is invented.** "Vharencrag Fortress", "the Thrice-Bound Edge",
   "391 AS" are exactly the tokens a general embedding model represents poorly and
   exactly the tokens every question names. Lexical search is not a fallback here;
   it is the primary channel.
2. **Sources disagree, on purpose.** The archive README warns that in-world
   authors are unreliable. The codex records the Gauntlet of Sorrowfell as forged
   in **391 AS** (p.11); the wiki records the date as *contested*. Our fact store
   finds **34 such conflicts** deterministically — that disagreement is the answer
   to several sample questions, not noise to be smoothed away.
3. **Some facts exist only as pictures.** The Weeping Lurker's threat rating
   appears in no table and no sentence — only printed on
   `plate_08_creature_weeping_lurker.png`. A text-only pipeline cannot answer that
   question at all. OCR is a correctness requirement, not a flourish.

## What is built today

| Layer | Status | What it does |
|---|---|---|
| Ingestion | working | PDF, scanned PDF, DOCX, Markdown, plain text and images → provenance-carrying chunks |
| Provenance | working | Every chunk carries document, page or section, source format and source class |
| Reliability policy | working | 11 source tiers from codex down to ballad; affects ranking, never deletes a source |
| Keyword index | working | SQLite FTS5 / BM25, fused with source quality |
| Knowledge graph | working | 417 entities, 1,912 provenance-carrying edges (218 typed) |
| Attribute facts | working | 1,499 subject/attribute/value rows with citations; 34 conflicts detected |
| OCR | working | 17 scanned PDFs and the figure plates, with per-chunk confidence |
| Query understanding | working | Intent, entities, attributes and hop direction, matched against the index |
| Investigation loop | working | Bounded state machine; each query derived from the last result |
| Claim verification | working | direct / inferred / conflicting / unsupported, with bounded confidence |
| Answer + trace | working | Answer, evidence chain, citations, conflicts, stop reason |
| Vector index | working | Local LSA embeddings, 2,547 chunks, 256 dims, 2.4 MB, builds in 7 s |
| Hybrid retrieval | working | BM25 + vector + entity overlap + source quality, weights measured not asserted |
| AI gateway | working | One controlled entry point: schemas, retries, backoff, cache, circuit breaker, fallback |
| LLM assistance | working | Optional; adds signal, never overrules the archive index |
| API + web UI | working | FastAPI; answer, citations, evidence chain, graph path, conflicts, trace, stop reason |
| Vision analysis | not built | The main remaining gap — see limitations |

Measured on the full archive:

```
documents            339   (321 indexed, 18 skipped as format twins)
pages              1,330
chunks             2,547
tables               227
figures              187
entities             417
edges              1,912
facts              1,499   (34 conflicting)
```

---

## Setup

**Requirements:** Python 3.11+ and, for OCR, the `tesseract` binary.

```bash
git clone <this repo> && cd Atreides
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
```

Install the OCR engine (optional but recommended — without it the 17 scans and
the figure plates contribute captions only, and ingestion says so):

```bash
brew install tesseract           # macOS
sudo apt-get install tesseract-ocr   # Debian/Ubuntu
```

Point the system at the corpus:

```bash
cp configuration-example/.env.example .env
# edit .env and set AEA_CORPUS_ROOT to your unpacked Ashen_Era_Archive
```

## Run

```bash
python scripts/ingest_archive.py --reset   # ~3 min with OCR, ~45 s without
python scripts/build_indexes.py            # graph + facts + vector index, ~8 s
python run_api.py                          # → http://127.0.0.1:8000
```

The web UI shows the answer, every claim labelled `direct` / `inferred` /
`conflicting` / `unsupported` with per-source reliability, the evidence chain, the
knowledge-graph path, competing sources and how the conflict was resolved, which
sub-questions were satisfied or failed, the full search trace including any
rejected LLM claims, the stop reason, and every fallback event. The banner shows
which subsystems are live.

### Optional: LLM assistance

Everything above runs with no key. To enable the assisted path, put a free
OpenRouter key in `.env`:

```bash
AEA_LLM_API_KEY=sk-or-...
AEA_LLM_MODEL=nvidia/nemotron-3-super-120b-a12b:free
```

> **Free-tier model IDs churn.** `meta-llama/llama-3.3-70b-instruct:free` was free
> when this project started and now returns 404. If you see that, pick a current
> free model from <https://openrouter.ai/models> and set `AEA_LLM_MODEL`.
> An embedding key is also supported, but see
> [docs/limitations.md](docs/limitations.md) — free-tier rate limits make a hosted
> index build impractical, and the build detects this and falls back to LSA.

The system then uses the LLM for question understanding, gap-directed query
suggestion and candidate-claim extraction from narrative prose — under the guards
in [docs/decisions.md](docs/decisions.md) D16. If the key is absent, invalid,
rate-limited or the provider is down, it falls back to the deterministic path and
says so in the trace.

Then ask it a question:

```bash
python scripts/ask.py "In which year was the Gauntlet of Sorrowfell actually forged?"
```

```
ANSWER    391 AS

SUPPORTING CLAIMS
  ◆ Gauntlet of Sorrowfell's forging date is 391 AS.
      conflicting  ·  confidence 0.55
      └─ Codex Vaeloria II: Armory of Relics and Bestiary [codex, p.11]

CONFLICTING SOURCES
  Gauntlet of Sorrowfell · forging_date
    – "391 AS"                       [codex, reliability 1.00]
    – "Contested; no year is stated" [wiki,  reliability 0.70]
    → The codex record is the more authoritative source, so '391 AS' is preferred.

INVESTIGATION TRACE
  [1] fact_scan       'Gauntlet of Sorrowfell'      → 5 attributes recorded
  [2] fact_lookup     'Gauntlet of Sorrowfell forging date' → 391 AS
  [3] conflict_check  → 2 competing values
  [4] resolve_conflict → resolved to '391 AS' from codex

STOPPED BECAUSE
  all required sub-questions are supported
```

A multi-hop question, where each query depends on the previous answer:

```bash
python scripts/ask.py "Whose dominion encompasses the lair of the Gravemaw Wyrm?"
```

```
ANSWER    The Bleeding Crown

EVIDENCE CHAIN
  1. Gravemaw Wyrm    — lair:     Marrowwell Abbey     [codex p.12]
  2. Marrowwell Abbey — ruled by: The Bleeding Crown   [codex p.34]
```

Add `--json` for the machine-readable trace, `--no-trace` for just the answer.
You can also query the retrieval layer directly with `scripts/search.py`.

Useful flags:

```bash
python scripts/ingest_archive.py --only wiki    # one directory
python scripts/ingest_archive.py --limit 20     # smoke test
python scripts/search.py "thorn wraith" --and   # require every term
```

Re-running ingestion is safe: unchanged files are skipped by content hash, so a
second run is a no-op.

### Ablation

```bash
python scripts/run_eval.py            # what each layer adds on the dev questions
python scripts/run_retrieval_eval.py  # what semantic retrieval adds on paraphrases
python scripts/sweep_weights.py       # reproduce the fusion-weight measurement
```

| configuration | cited | conflicts found | multi-hop | partial |
|---|---:|---:|---:|---:|
| keyword only, 1 lookup | 0 | 0 | 0 | 20 |
| keyword + loop | 10 | 2 | 5 | 7 |
| hybrid + loop | 10 | 2 | 5 | 7 |

**Hybrid retrieval changes nothing on these 20 questions, and we report that
rather than hiding it.** The supplied questions reuse the archive's own vocabulary
almost verbatim, so BM25 already wins them. To find out whether embeddings help at
all, we wrote a paraphrase probe worded to avoid archive vocabulary:

| | R@1 | R@3 | R@5 |
|---|---:|---:|---:|
| keyword only | 5/10 | 7/10 | 7/10 |
| plan's proposed 0.35/0.45 | 4/10 | 7/10 | 8/10 |
| **measured 0.50/0.30** | **5/10** | 7/10 | **8/10** |

That measurement changed the shipped weights — see
[docs/decisions.md](docs/decisions.md) D15.

By sub-track:

| Sub-track | Cited answers |
|---|---|
| **1C — Searching the Way a Human Does** (primary) | **2 / 2** |
| **1B — Connecting Facts Across Thousands of Pages** (secondary) | **6 / 7** |
| 1A — Rich Answers (not our track) | 2 / 11 |

The 1A gap is an ingestion limitation, not a reasoning one: those values are
printed on illustrations. Rather than guess, the loop names the exact image file
to open and marks the answer PARTIAL — see
[docs/limitations.md](docs/limitations.md).

## Test

```bash
pytest
```

320 tests, in four groups:

- **unit** — the rules citations depend on: ID stability, provenance inheritance,
  table integrity, conflict normalisation, confidence bounds, schema validation,
  attribute→source routing, operation detection, date reasoning, chart-plate
  geometry, prose extraction, excerpt quoting, completion status, and the guards
  that stop LLM output overruling the index.
- **integration** — the real pipeline, the real loop and the real HTTP API:
  every claim names a chunk that exists, every citation opens, the loop respects
  its budget, an unanswerable question is never reported as supported, and no
  evidence leaks between investigations.
- **failure_modes** — the fallback matrix: retries, rate limits, non-retryable
  4xx, circuit opening and closing, corrupt cache entries, unconfigured gateway,
  and vision degrading to an honest status rather than a guess.
- **evaluation** — the paraphrase probe backing the weight measurement.

### Measuring general capability

The suite above proves the system still does what it did yesterday. It cannot
show whether an *unseen* question will be answered, and the judge's questions are
unseen by definition — so there is a second set, written from the archive after
the rules were implemented and never tuned against:

```bash
python scripts/run_unseen_eval.py --no-llm
```

It scores per reasoning operation rather than in aggregate, because a category at
0/3 means a whole capability is missing and a total would hide it. Current result
is **30/30**, and the same **30/30** with the LLM disabled — the deterministic
path is not a degraded mode.

```bash
python scripts/run_eval.py            # ablation on the supplied dev questions
python scripts/run_retrieval_eval.py  # what semantic retrieval adds
```

---

## Repository layout

```
src/
  common/        config, canonical data model, deterministic IDs, reliability policy
  ingestion/     discovery, per-format parsers, OCR adapter, chunker, pipeline
  storage/       SQLite schema and store (metadata + FTS5 + graph + facts)
  retrieval/     keyword/BM25 search  (vector + fusion: Phase 2)
  graph/         entity normalisation, graph builder, traversal, fact extraction
  ai_gateway/    the ONLY place that calls a provider: schemas, cache, breaker, adapters
  indexes/       persistent vector index
  retrieval/     keyword (BM25/FTS5), hybrid fusion, figure lookup
  orchestration/ query understanding, decomposition, the bounded loop, LLM guards
  verification/  claim classification, confidence, contradiction handling
  generation/    grounded answer and trace rendering
  api/           FastAPI app, response mapping, web UI
scripts/         ingest_archive · build_indexes · ask · search · run_eval
                 run_retrieval_eval · sweep_weights
run_api.py       start the API and UI
tests/           unit + integration
docs/            architecture, decisions, data model, limitations, roadmap, diagrams
ai_usage/        AI usage disclosure and exported chat logs
```

## Documentation

- [docs/architecture.md](docs/architecture.md) — components and data flow
- [docs/investigation-protocol.md](docs/investigation-protocol.md) — how the 1C loop searches and stops
- [docs/api.md](docs/api.md) — endpoints, response shape, boundary security
- [docs/data-model.md](docs/data-model.md) — every table and what it guarantees
- [docs/decisions.md](docs/decisions.md) — the choices we made and what we rejected
- [docs/limitations.md](docs/limitations.md) — what does not work, and what we tried that failed
- [docs/roadmap.md](docs/roadmap.md) — build order and current status
- [ai_usage/ai-usage-disclosure.md](ai_usage/ai-usage-disclosure.md) — how AI tools were used

## Security

- No API key is ever committed. Keys come from the environment or a git-ignored
  `.env`; `configuration-example/.env.example` holds placeholders only, and
  `/api/health` reports *whether* a key is configured, never its value.
- Asset routes take an id and resolve the path from the index, then verify it
  sits inside the corpus or the derived-assets directory — a crafted `../../`
  cannot escape the archive.
- The corpus is opened read-only; no endpoint mutates it.
