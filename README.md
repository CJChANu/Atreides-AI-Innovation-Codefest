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

> **Status — Phase 1 (foundation) is complete and running.** Ingestion, the
> keyword index, the knowledge graph and the attribute-fact store all work
> end-to-end on the real archive. The iterative investigation loop, vector
> retrieval and the answer generator are the next phases; see
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
| Vector index | planned | Phase 2 |
| Investigation loop | planned | Phase 3 — the 1C core |
| Answer generator + UI | planned | Phase 4 |

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

Then query the retrieval layer directly:

```bash
python scripts/search.py "Gauntlet of Sorrowfell forged"
```

```
 1. Codex Vaeloria Ii Armory Of Relics And Bestiary (codex, p.11)  score=0.763
    Gauntlet of Sorrowfell | Attunement cost | 12 | Forged | 391 AS
    | Forged at | Vharencrag Fortress | Housed in | Greyfell Citadel
```

Useful flags:

```bash
python scripts/ingest_archive.py --only wiki    # one directory
python scripts/ingest_archive.py --limit 20     # smoke test
python scripts/search.py "thorn wraith" --and   # require every term
```

Re-running ingestion is safe: unchanged files are skipped by content hash, so a
second run is a no-op.

## Test

```bash
pytest
```

50 tests. The unit tests pin the rules that citations depend on (ID stability,
provenance inheritance, table integrity, conflict normalisation); the integration
test runs the real pipeline over a miniature corpus and asserts that every fact
can be traced back to a chunk that exists.

---

## Repository layout

```
src/
  common/        config, canonical data model, deterministic IDs, reliability policy
  ingestion/     discovery, per-format parsers, OCR adapter, chunker, pipeline
  storage/       SQLite schema and store (metadata + FTS5 + graph + facts)
  retrieval/     keyword/BM25 search  (vector + fusion: Phase 2)
  graph/         entity normalisation, graph builder, traversal, fact extraction
  orchestration/ bounded investigation state machine  (Phase 3)
  verification/  claim classification, contradiction handling  (Phase 4)
  generation/    grounded answer synthesis  (Phase 4)
  api/           FastAPI surface  (Phase 4)
scripts/         ingest_archive.py, build_indexes.py, build_graph.py, search.py
tests/           unit + integration
docs/            architecture, decisions, data model, limitations, roadmap, diagrams
ai_usage/        AI usage disclosure and exported chat logs
```

## Documentation

- [docs/architecture.md](docs/architecture.md) — components and data flow
- [docs/data-model.md](docs/data-model.md) — every table and what it guarantees
- [docs/decisions.md](docs/decisions.md) — the choices we made and what we rejected
- [docs/limitations.md](docs/limitations.md) — what does not work, and what we tried that failed
- [docs/roadmap.md](docs/roadmap.md) — build order and current status
- [ai_usage/ai-usage-disclosure.md](ai_usage/ai-usage-disclosure.md) — how AI tools were used

## Security

No API key is ever committed. Keys are read from the environment or a git-ignored
`.env`; `configuration-example/.env.example` contains placeholders only.
