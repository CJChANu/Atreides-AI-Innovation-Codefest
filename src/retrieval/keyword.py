"""Keyword retrieval over the FTS5 index.

This channel exists because the archive's vocabulary is invented. "Vharencrag
Fortress", "Thrice-Bound Edge" and "323 AS" are exactly the tokens a general
embedding model represents poorly and exactly the tokens the questions hinge on.
BM25 gets them right by construction.

The raw BM25 score is combined with the document's source reliability, so an
official codex row outranks a ballad stanza that matches equally well — without
the ballad being hidden, because it may be the thing that reveals a conflict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.common.provenance import reliability_of
from src.storage.db import ArchiveStore

# FTS5 treats these as operators; a question containing them must not become a
# malformed query. We tokenise the user's text ourselves and quote each term.
_TOKEN = re.compile(r"[\w'-]+", re.UNICODE)


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    content: str
    page_start: int | None
    section_path: str
    source_class: str
    relative_path: str
    title: str
    bm25: float
    score: float

    def citation(self) -> str:
        where = f"p.{self.page_start}" if self.page_start else (self.section_path or "—")
        return f"{self.title} ({self.source_class}, {where})"


def to_fts_query(text: str, *, mode: str = "or") -> str:
    """Turn free text into a safe FTS5 MATCH expression.

    Every term is double-quoted, which both escapes FTS5 operators and keeps
    hyphenated archive names (``Thrice-Bound``) together as a phrase.
    """
    terms = [t for t in _TOKEN.findall(text) if len(t) > 1]
    if not terms:
        return ""
    joiner = " AND " if mode == "and" else " OR "
    return joiner.join(f'"{t}"' for t in terms)


class KeywordIndex:
    def __init__(self, store: ArchiveStore) -> None:
        self.store = store

    def search(self, query: str, *, limit: int = 20, mode: str = "or") -> list[Hit]:
        match = to_fts_query(query, mode=mode)
        if not match:
            return []
        rows = self.store.connection.execute(
            """
            SELECT c.chunk_id, c.document_id, c.content, c.page_start, c.section_path,
                   c.source_class, d.relative_path, d.title,
                   bm25(chunks_fts) AS raw
            FROM chunks_fts
            JOIN chunks    c ON c.chunk_id = chunks_fts.chunk_id
            JOIN documents d ON d.document_id = c.document_id
            WHERE chunks_fts MATCH ?
            ORDER BY raw
            LIMIT ?
            """,
            (match, limit * 3),
        ).fetchall()
        if not rows:
            return []

        # bm25() returns a *negative* relevance in SQLite (lower is better).
        # Normalise to 0..1 so the score is comparable with the other channels.
        raws = [r["raw"] for r in rows]
        best, worst = min(raws), max(raws)
        span = (worst - best) or 1.0

        hits = []
        for row in rows:
            normalised = (worst - row["raw"]) / span
            quality = reliability_of(row["source_class"])
            hits.append(
                Hit(
                    chunk_id=row["chunk_id"],
                    document_id=row["document_id"],
                    content=row["content"],
                    page_start=row["page_start"],
                    section_path=row["section_path"],
                    source_class=row["source_class"],
                    relative_path=row["relative_path"],
                    title=row["title"],
                    bm25=normalised,
                    score=0.8 * normalised + 0.2 * quality,
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]
