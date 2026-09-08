# `data/` — derived artifacts

Everything in this directory is **generated** from the read-only corpus and is
git-ignored. Deleting it costs nothing but a re-ingest.

| Path             | Built by                    | Contents                                        |
|------------------|-----------------------------|-------------------------------------------------|
| `archive.sqlite3`| `scripts/ingest_archive.py` | documents, chunks, FTS5 index, tables, figures   |
|                  | `scripts/build_indexes.py`  | entities, edges, mentions, facts                 |
| `assets/`        | `scripts/ingest_archive.py` | images extracted from PDFs, named by `figure_id` |
| `cache/`         | model adapters              | cached embedding and LLM responses               |

Rebuild from scratch:

```bash
python scripts/ingest_archive.py --reset
python scripts/build_indexes.py
```

The corpus itself is never modified.
