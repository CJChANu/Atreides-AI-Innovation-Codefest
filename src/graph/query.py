"""Graph traversal used by the investigation loop to expand beyond text hits.

The graph is an *accelerator*, never the sole source of truth: every neighbour it
returns comes with the chunk that asserted the edge, so an expansion can always be
checked against the document that justified it.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.graph.entities import normalise
from src.storage.db import ArchiveStore


@dataclass
class Neighbour:
    entity_id: str
    name: str
    predicate: str
    direction: str  # 'out' when the seed is the subject, 'in' when the object
    chunk_id: str
    document_id: str
    page: int | None
    method: str
    confidence: float


class GraphQuery:
    def __init__(self, store: ArchiveStore) -> None:
        self.store = store

    def resolve(self, name: str) -> str | None:
        """Map a free-text name onto an entity_id, if the graph knows it."""
        entity_id = normalise(name)
        row = self.store.connection.execute(
            "SELECT entity_id FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        return row["entity_id"] if row else None

    def neighbours(self, entity_id: str, *, predicates: list[str] | None = None,
                   limit: int = 50) -> list[Neighbour]:
        clause, params = "", [entity_id]
        if predicates:
            placeholders = ",".join("?" * len(predicates))
            clause = f" AND e.predicate IN ({placeholders})"
            params += predicates

        outgoing = self.store.connection.execute(
            f"""SELECT e.object_id AS other, n.name, e.predicate, 'out' AS direction,
                       e.chunk_id, e.document_id, e.page, e.method, e.confidence
                FROM edges e LEFT JOIN entities n ON n.entity_id = e.object_id
                WHERE e.subject_id = ?{clause}""",
            params,
        ).fetchall()
        incoming = self.store.connection.execute(
            f"""SELECT e.subject_id AS other, n.name, e.predicate, 'in' AS direction,
                       e.chunk_id, e.document_id, e.page, e.method, e.confidence
                FROM edges e LEFT JOIN entities n ON n.entity_id = e.subject_id
                WHERE e.object_id = ?{clause}""",
            params,
        ).fetchall()

        results = [
            Neighbour(r["other"], r["name"] or r["other"], r["predicate"], r["direction"],
                      r["chunk_id"], r["document_id"], r["page"], r["method"], r["confidence"])
            for r in list(outgoing) + list(incoming)
        ]
        # Typed, high-confidence edges first: they are the ones worth traversing.
        results.sort(key=lambda n: (n.method != "infobox", -n.confidence))
        return results[:limit]
