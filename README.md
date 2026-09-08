# Ashen Era Intelligent Document Assistant

**SLIIT Codefest 2026 — AI Competition, powered by IFS**
Sub-track **1C — Searching the Way a Human Does** (primary), extended with
**1B — Connecting Facts Across Thousands of Pages**.

An archive investigator for the Ashen Era Archive: 339 files and ~1,330 pages of
novels, wiki articles, codex data books, in-world ephemera, simulated scans and
figure plates. It does not treat a question as one similarity search. It plans an
investigation, searches iteratively, expands connected entities across documents,
verifies evidence, and answers with page-level citations, confidence, conflicts,
and a visible trace of why it stopped.

> **Status — Phases 1–3 are complete and running.** Ingestion, the three indexes,
> the bounded investigation loop, claim verification and grounded answer
> generation all work end-to-end on the real archive, with no API key required.
> Vector retrieval and the web UI are the remaining phases; see
> [docs/roadmap.md](docs/roadmap.md) for exactly what is and is not built.

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
| Vector index | planned | Phase 2 |
| Web UI | planned | Phase 4 |

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
python scripts/build_indexes.py            # graph + facts, ~1 s
```

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
python scripts/run_eval.py
```

| configuration | answered | cited | partial |
|---|---:|---:|---:|
| keyword only (1 lookup) | 20 | 20 | — |
| loop, 1 iteration | 0 | 0 | 20 |
| loop, 2 iterations | 11 | 10 | 20 |
| **full loop** | **11** | **10** | **6** |

A keyword lookup "answers" all twenty questions because it always returns *a
passage* — which is exactly why answered-count alone is a misleading metric. The
loop's later iterations do not find more answers; they find the **conflicts** and
resolve them, which is what takes 14 answers from unverified to supported.

## Test

```bash
pytest
```

85 tests. The unit tests pin the rules that citations depend on (ID stability,
provenance inheritance, table integrity, conflict normalisation, confidence
bounds); the integration tests run the real pipeline and the real loop over a
miniature corpus, and assert that every claim names a chunk that exists, that the
loop respects its budget, and that an unanswerable question is never reported as
supported.

---

## Repository layout

```
src/
  common/        config, canonical data model, deterministic IDs, reliability policy
  ingestion/     discovery, per-format parsers, OCR adapter, chunker, pipeline
  storage/       SQLite schema and store (metadata + FTS5 + graph + facts)
  retrieval/     keyword/BM25 search  (vector + fusion: Phase 2)
  graph/         entity normalisation, graph builder, traversal, fact extraction
  orchestration/ query understanding, decomposition, the bounded loop
  verification/  claim classification, confidence, contradiction handling
  generation/    grounded answer and trace rendering
  api/           FastAPI surface  (Phase 4)
scripts/         ingest_archive.py, build_indexes.py, ask.py, search.py, run_eval.py
tests/           unit + integration
docs/            architecture, decisions, data model, limitations, roadmap, diagrams
ai_usage/        AI usage disclosure and exported chat logs
```

## Documentation

- [docs/architecture.md](docs/architecture.md) — components and data flow
- [docs/investigation-protocol.md](docs/investigation-protocol.md) — how the 1C loop searches and stops
- [docs/data-model.md](docs/data-model.md) — every table and what it guarantees
- [docs/decisions.md](docs/decisions.md) — the choices we made and what we rejected
- [docs/limitations.md](docs/limitations.md) — what does not work, and what we tried that failed
- [docs/roadmap.md](docs/roadmap.md) — build order and current status
- [ai_usage/ai-usage-disclosure.md](ai_usage/ai-usage-disclosure.md) — how AI tools were used

## Security

No API key is ever committed. Keys are read from the environment or a git-ignored
`.env`; `configuration-example/.env.example` contains placeholders only.
