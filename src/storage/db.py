"""SQLite storage layer.

Everything derived from the archive is written here; the corpus itself is never
modified. The layer exposes plain methods rather than an ORM so that the SQL —
especially the FTS5 query — stays readable and reviewable.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from src.common.models import Chunk, Document, Figure, Table

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SECTION_SEPARATOR = " > "


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ArchiveStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ArchiveStore:
        return self

    def __exit__(self, *exc) -> None:
        self.connection.commit()
        self.close()

    def reset(self) -> None:
        """Drop all derived data. The corpus is untouched; only our index dies."""
        for table in ("chunks_fts", "ingestion_warnings", "figures",
                      "tables_extracted", "chunks", "documents"):
            self.connection.execute(f"DELETE FROM {table}")
        self.connection.commit()

    # -- writes -------------------------------------------------------------

    def document_is_current(self, document_id: str, file_hash: str) -> bool:
        """True when this exact file version is already ingested (idempotency check)."""
        row = self.connection.execute(
            "SELECT file_hash FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()
        return row is not None and row["file_hash"] == file_hash

    def delete_document(self, document_id: str) -> None:
        self.connection.execute(
            "DELETE FROM chunks_fts WHERE chunk_id IN "
            "(SELECT chunk_id FROM chunks WHERE document_id = ?)",
            (document_id,),
        )
        self.connection.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))

    def upsert_document(self, document: Document) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO documents
               (document_id, relative_path, title, source_format, source_class,
                reliability, file_hash, file_size, page_count, version,
                ingested_at, superseded_by, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (document.document_id, document.relative_path, document.title,
             document.source_format, document.source_class, document.reliability,
             document.file_hash, document.file_size, document.page_count,
             document.version, document.ingested_at or _now(),
             document.superseded_by, document.notes),
        )

    def add_chunks(self, chunks: list[Chunk]) -> None:
        self.connection.executemany(
            """INSERT OR REPLACE INTO chunks
               (chunk_id, document_id, document_version, source_format, source_class,
                content, content_type, page_start, page_end, section_path,
                char_start, char_end, table_ids, figure_ids, ocr_confidence)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(c.chunk_id, c.document_id, c.document_version, c.source_format,
              c.source_class, c.content, c.content_type, c.page_start, c.page_end,
              SECTION_SEPARATOR.join(c.section_path), c.char_start, c.char_end,
              ",".join(c.table_ids), ",".join(c.figure_ids), c.ocr_confidence)
             for c in chunks],
        )
        self.connection.executemany(
            "INSERT INTO chunks_fts (content, chunk_id) VALUES (?, ?)",
            [(c.content, c.chunk_id) for c in chunks],
        )

    def add_tables(self, tables: list[Table]) -> None:
        self.connection.executemany(
            """INSERT OR REPLACE INTO tables_extracted
               (table_id, document_id, page, section_path, caption, columns_json, rows_json)
               VALUES (?,?,?,?,?,?,?)""",
            [(t.table_id, t.document_id, t.page, SECTION_SEPARATOR.join(t.section_path),
              t.caption, json.dumps(t.columns), json.dumps(t.rows)) for t in tables],
        )

    def add_figures(self, figures: list[Figure]) -> None:
        self.connection.executemany(
            """INSERT OR REPLACE INTO figures
               (figure_id, document_id, page, caption, asset_path, nearby_text,
                ocr_text, width, height)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [(f.figure_id, f.document_id, f.page, f.caption, f.asset_path,
              f.nearby_text, f.ocr_text, f.width, f.height) for f in figures],
        )

    def add_warnings(self, document_id: str, messages: list[str]) -> None:
        if not messages:
            return
        stamp = _now()
        self.connection.executemany(
            "INSERT INTO ingestion_warnings (document_id, message, created_at) VALUES (?,?,?)",
            [(document_id, m, stamp) for m in messages],
        )

    def commit(self) -> None:
        self.connection.commit()

    # -- reads --------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        counts = {}
        for name, sql in (
            ("documents", "SELECT COUNT(*) FROM documents"),
            ("documents_indexed", "SELECT COUNT(*) FROM documents WHERE superseded_by IS NULL"),
            ("chunks", "SELECT COUNT(*) FROM chunks"),
            ("tables", "SELECT COUNT(*) FROM tables_extracted"),
            ("figures", "SELECT COUNT(*) FROM figures"),
            ("warnings", "SELECT COUNT(*) FROM ingestion_warnings"),
            ("pages", "SELECT COALESCE(SUM(page_count),0) FROM documents WHERE superseded_by IS NULL"),
        ):
            counts[name] = self.connection.execute(sql).fetchone()[0]
        return counts

    def get_document(self, document_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM documents WHERE document_id = ?", (document_id,)
        ).fetchone()

    def get_chunk(self, chunk_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()
