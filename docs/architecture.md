# Architecture

## Principle

**Provenance first.** Every answerable unit keeps the location it came from, and a
citation is *generated from recorded metadata* — never produced by a language
model. Everything else in the design follows from that: parsers own page numbers,
the chunker may only inherit them, and a claim that cannot name a chunk is not
allowed into an answer.

The second principle is that **offline indexing is separated from online
investigation**. Ingestion is slow, deterministic and re-runnable; question
answering is fast and stateless over the index. Keeping them apart is what makes
failures isolable — a bad answer is either a retrieval problem or a reasoning
problem, and the trace says which.

## Components

```
Archive files (PDF · scanned PDF · DOCX · Markdown · TXT · images)
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ OFFLINE — ingestion (scripts/ingest_archive.py)               │
│                                                               │
│  discovery ──▶ fingerprint ──▶ resolve format twins           │
│      │                                                        │
│      ▼                                                        │
│  parsers (one per format; each owns its own provenance)       │
│      ├─ text blocks          + page / section / line range    │
│      ├─ tables               + cell matrix and retrieval text │
│      ├─ figures              + asset, caption, nearby text    │
│      └─ OCR                  + per-page confidence            │
│      │                                                        │
│      ▼                                                        │
│  chunker (structure-aware; tables and figures never split)    │
│      │                                                        │
│      ▼                                                        │
│  SQLite store ──▶ FTS5 keyword index                          │
│                                                               │
│ OFFLINE — derived indexes (scripts/build_indexes.py)          │
│  graph builder  ──▶ entities · edges · mentions               │
│  fact extractor ──▶ subject/attribute/value + conflicts       │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│ ONLINE — investigation  (Phase 3, not yet built)              │
│                                                               │
│  query understanding ──▶ entities · intent · answer type      │
│      ▼                                                        │
│  planner ──▶ sub-questions with completion conditions         │
│      ▼                                                        │
│  ┌── bounded loop ──────────────────────────────────────┐     │
│  │  search (keyword + vector + graph)                   │     │
│  │  extract entities / claims                           │     │
│  │  expand graph to connected facts                     │     │
│  │  which sub-questions still lack evidence?            │     │
│  │  plan the next query ─────────────────────┐          │     │
│  └───────────────────────────────────────────┘          │     │
│      ▼                                                        │
│  verification ──▶ direct · inferred · conflicting · unsupported│
│      ▼                                                        │
│  grounded answer + evidence chain + citations + stop reason   │
└───────────────────────────────────────────────────────────────┘
```

## The three retrieval channels

No single channel is sufficient for this archive, and each fails in a way the
others cover.

| Channel | Strength | Failure mode it has | Covered by |
|---|---|---|---|
| **Keyword (BM25/FTS5)** | Invented names, numbers, exact titles, aliases | Misses paraphrase — "who won the war" vs "the victor was" | vector |
| **Vector** *(Phase 2)* | Paraphrase, indirect phrasing | Represents invented proper nouns poorly | keyword |
| **Graph** | Multi-hop connection where no passage holds the whole answer | Only knows relations that were extracted | both, plus text search |

The graph is an **accelerator, not the truth**. Every edge stores the chunk that
asserted it, so an expansion can always be checked against the document that
justified it, and a missing edge degrades to a text search rather than a wrong
answer.

## The fact store

Wiki infoboxes and codex classification tables are both two-column key/value
grids. Lifting them into one normalised `facts` table buys three things at once:

- **Precise answers.** "What attunement cost is listed for X" becomes a lookup,
  not a hope that the right sentence survived into a context window.
- **Deterministic contradiction detection.** Two rows with the same subject and
  attribute but different normalised values *are* the conflict. No model
  judgement, no false positives from capitalisation.
- **Reliability-aware resolution.** Each fact keeps its source class, so a codex
  value and a ballad value can be reported side by side instead of one silently
  winning.

This is why the two 1C sample questions already resolve with citations before any
LLM is involved: *Gloamreach founded 246 AS* (codex, p.23) against a wiki that
calls it contested; *Gauntlet of Sorrowfell forged 391 AS* (codex, p.11) against a
wiki that calls the date contested.

## Data flow guarantees

1. A chunk's page and section are **inherited from its blocks**, never computed.
2. A table or figure is **never split** across chunks.
3. A fact and a graph edge each store the `chunk_id` that justifies them, and that
   chunk is asserted to exist by the integration test.
4. Ingestion is **idempotent**: unchanged files are skipped by content hash.
5. The corpus is **never written to**; all derived data lives under `data/`.
