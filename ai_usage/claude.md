# CLAUDE.md — repository instructions for AI coding assistants

Read this before changing anything in this repository.

## What this is

An archive investigator for the Ashen Era Archive (SLIIT Codefest 2026, sub-track
1C primary / 1B secondary). See `README.md` for status and `docs/roadmap.md` for
what is built versus planned.

## Ground rules

- **Never modify the corpus.** `AEA_CORPUS_ROOT` is read-only. Everything derived
  goes to `data/`.
- **Never break provenance.** Parsers set page/section/line range; the chunker
  inherits and must not compute them. A fact or edge without a `chunk_id` is a bug.
- **Never commit a key.** Configuration comes from the environment via
  `src/common/config.py`. `.env` is git-ignored; only
  `configuration-example/.env.example` is committed, with placeholders.
- **Never hard-code a sample question.** Judging uses an unpublished set.
- **Degrade honestly.** A missing capability (OCR absent, plate unreadable) is
  reported, never silently treated as "no evidence".

## Layout

```
src/common/        config · models · ids · reliability policy
src/ingestion/     discovery · parsers/ · ocr · chunker · pipeline
src/storage/       schema.sql · db.py
src/retrieval/     keyword.py   (vector + fusion: Phase 2)
src/graph/         entities · builder · query · facts · plate_facts
src/orchestration/ Phase 3 · src/verification/ + src/generation/ Phase 4
scripts/           ingest_archive · build_indexes · build_graph · search
```

## Commands

```bash
pip install -r requirements-dev.txt
python scripts/ingest_archive.py --reset   # full ingest (~3 min with OCR)
python scripts/ingest_archive.py --only wiki --limit 20   # fast iteration
python scripts/build_indexes.py            # graph + facts (~1 s)
python scripts/search.py "query here"
pytest
```

## Conventions

- Python 3.11+, `from __future__ import annotations`, full type hints.
- Comments explain **why**. Do not add comments that restate the code.
- Add a schema table by appending to `src/storage/schema.sql`; it is applied with
  `CREATE ... IF NOT EXISTS` on every open, so it stays additive and re-runnable.
- Any behavioural rule worth stating in `docs/decisions.md` gets a test.

## Before claiming something about the archive

Check it. Run a query, count the rows, open the source file. Several design
decisions here exist because an assumption turned out to be false — see
`docs/limitations.md`, "What we tried that did not work".
