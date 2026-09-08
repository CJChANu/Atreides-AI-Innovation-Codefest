# Data model

One SQLite file (`data/archive.sqlite3`). Every table below exists to support one
guarantee: **a claim must be able to name the page it came from.**

## `documents` — one row per physical file

| Column | Notes |
|---|---|
| `document_id` | `sha256(normalised path + size + hash prefix)`, truncated. Deterministic across runs. |
| `relative_path` | Path within the corpus. The corpus is never modified. |
| `source_format` | `pdf` · `pdf_scan` · `docx` · `markdown` · `text` · `image` |
| `source_class` | Reliability tier (`codex` … `ballad`), classified structurally from the path |
| `reliability` | 0–1, from the source class. Feeds ranking and confidence. |
| `file_hash` | Full SHA-256. Drives idempotent re-ingestion. |
| `page_count` | Real page count for PDFs; `NULL` for formats without pages |
| `superseded_by` | Set when this file is a format twin of a preferred document |

A changed file yields a **new** `document_id`, which is what makes re-ingestion
idempotent for unchanged files and versioned for changed ones.

## `chunks` — the citation unit

Every retrievable, quotable unit. `page_start`/`page_end` and `section_path` are
**inherited from the blocks a parser produced**, never computed by the chunker.
`ocr_confidence` is the *minimum* across the chunk's blocks — a chunk is only as
trustworthy as its worst-read source.

`chunk_id` encodes its own provenance: `doc-9ac5693e67d3160f-p0011-s00-c018`
reads as document, page 11, section 0, chunk 18.

## `chunks_fts` — BM25 keyword index

A contentless FTS5 virtual table (`content=''`): the text is stored once in
`chunks`, and the index holds only postings, joined back on `chunk_id`.
Tokeniser: `unicode61 remove_diacritics 2`.

User text never reaches FTS5 raw. `to_fts_query()` tokenises and double-quotes
every term, which both escapes FTS5 operators (`NEAR`, `*`, parentheses) and keeps
hyphenated archive names such as `Thrice-Bound` together as a phrase.

## `tables_extracted` and `figures`

Tables keep both a cell matrix (`columns_json` / `rows_json`) and a flat retrieval
text, so they can be searched *and* rendered. Figures keep the asset path, caption,
nearby text and OCR text. Images embedded in PDFs are written to `data/assets/`
named by `figure_id`; standalone plates are referenced in place, because the
corpus is read-only.

## `entities`, `entity_aliases`, `edges`, `entity_mentions`

`entity_id` is a normalised name (`house_morvain`), so that `[[Weeping Lurker]]`,
`Weeping Lurker (creature)` and a bare heading all collapse to one node — without
which multi-hop expansion would silently split in two.

Every edge stores `chunk_id`, `document_id`, `page`, `method` and `confidence`.
`method` records *how* the edge was derived, so a deterministic `infobox` edge is
never confused with a probabilistic `llm` one:

| method | confidence | source |
|---|---|---|
| `infobox` | 0.9 | a typed key/value row (`Seat`, `Forged at`, `Ruling power`) |
| `wikilink` | 0.6 | a `[[link]]` inside an article — related, but untyped |
| `llm` | varies | Phase 3, prose-only sources |

An edge that cannot name the chunk it came from is not allowed into the graph.

## `facts` — subject / attribute / value with provenance

Lifted from key/value tables (wiki infoboxes, codex classification grids) and from
figure-plate OCR.

| Column | Purpose |
|---|---|
| `attribute` | Canonicalised, so `Forged`, `Forging date` and `Forged in` all become `forging_date` and are comparable across sources |
| `value_text` | The value as written, for display |
| `value_key` | Case- and punctuation-folded, **for conflict grouping only** — so `Contested` and `contested` are not a disagreement |
| `value_number` | Populated when the value is essentially a number; `391 AS` → `391.0` |
| `chunk_id`, `page` | Provenance |
| `source_class`, `reliability` | Lets a codex value and a ballad value be reported side by side |

Contradiction detection is then a query, not a judgement:

```sql
SELECT subject_id, attribute
FROM facts
GROUP BY subject_id, attribute
HAVING COUNT(DISTINCT value_key) > 1;
```

Currently 34 conflicts across 164 subjects. Two of them are the answers to the 1C
sample questions.

## `ingestion_warnings`

Kept rather than printed and forgotten. OCR gaps and failed table extractions are
exactly the limitations the system must be able to report to a user instead of
answering "no evidence found".
