"""Fact lookup and traversal.

The fact store is not just a table of answers — it is a *graph*. A fact's value
often names another subject that has facts of its own, and following that link is
exactly what a multi-hop question requires:

    Gravemaw Wyrm --lair--> Marrowwell Abbey --ruled_by--> The Bleeding Crown

This module provides the two primitives the investigation loop needs: look up
what is recorded about a subject, and resolve a value back into a subject so the
next hop can be taken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.graph.entities import normalise
from src.storage.db import ArchiveStore

# Infobox values often list several entities; each is a separate hop candidate.
_VALUE_SPLIT = re.compile(r"\s*;\s*")
# "The Winter Reckoning in 228 AS" -> the entity is the part before the qualifier.
_QUALIFIER = re.compile(r"\s+in\s+\d{1,4}\s*AS\b.*$", re.IGNORECASE)


@dataclass
class FactRow:
    """One recorded assertion, with everything needed to cite and weigh it."""

    subject_id: str
    subject_name: str
    attribute: str
    value_text: str
    value_key: str
    value_number: float | None
    chunk_id: str
    document_id: str
    page: int | None
    source_class: str
    reliability: float

    def citation(self, title: str = "") -> str:
        where = f"p.{self.page}" if self.page else "infobox"
        return f"{title or self.document_id} ({self.source_class}, {where})"


@dataclass
class AttributeView:
    """Every recorded value for one subject+attribute, grouped by agreement.

    Grouping happens on ``value_key`` (case- and punctuation-folded), so
    presentation differences never look like disagreement. More than one group
    *is* the conflict.
    """

    subject_id: str
    subject_name: str
    attribute: str
    groups: dict[str, list[FactRow]] = field(default_factory=dict)

    @property
    def is_conflicting(self) -> bool:
        return len(self.groups) > 1

    def best(self) -> tuple[str, list[FactRow]]:
        """The value group with the most reliable supporting source.

        Ties are broken by how many independent documents assert the value, then
        by group size — corroboration is worth something, but it never outweighs
        a materially more authoritative source.
        """
        def rank(item: tuple[str, list[FactRow]]) -> tuple:
            rows = item[1]
            return (max(r.reliability for r in rows),
                    len({r.document_id for r in rows}),
                    len(rows))

        return max(self.groups.items(), key=rank)

    def ordered_groups(self) -> list[tuple[str, list[FactRow]]]:
        return sorted(self.groups.items(),
                      key=lambda kv: max(r.reliability for r in kv[1]), reverse=True)


class FactQuery:
    def __init__(self, store: ArchiveStore) -> None:
        self.store = store
        self._titles: dict[str, str] = {
            row["document_id"]: row["title"]
            for row in store.connection.execute("SELECT document_id, title FROM documents")
        }
        self._subjects: set[str] = {
            row["subject_id"]
            for row in store.connection.execute("SELECT DISTINCT subject_id FROM facts")
        }

    def title_of(self, document_id: str) -> str:
        return self._titles.get(document_id, document_id)

    def knows(self, subject_id: str) -> bool:
        return subject_id in self._subjects

    # -- lookup -------------------------------------------------------------

    def attributes_of(self, subject_id: str) -> list[str]:
        rows = self.store.connection.execute(
            "SELECT DISTINCT attribute FROM facts WHERE subject_id = ? ORDER BY attribute",
            (subject_id,),
        ).fetchall()
        return [r["attribute"] for r in rows]

    def lookup(self, subject_id: str, attribute: str) -> AttributeView | None:
        """All recorded values for one subject+attribute, grouped by agreement."""
        rows = self.store.connection.execute(
            "SELECT * FROM facts WHERE subject_id = ? AND attribute = ?",
            (subject_id, attribute),
        ).fetchall()
        if not rows:
            return None

        view = AttributeView(subject_id, rows[0]["subject_name"], attribute)
        for row in rows:
            view.groups.setdefault(row["value_key"], []).append(_to_fact(row))
        return view

    def search_subject(self, name: str) -> str | None:
        """Resolve a display name to a subject that has facts recorded."""
        candidate = normalise(name)
        return candidate if candidate in self._subjects else None

    # -- traversal ----------------------------------------------------------

    def resolve_hop_targets(self, value_text: str) -> list[tuple[str, str]]:
        """Split a fact value into ``(subject_id, display name)`` hop candidates.

        A value such as "The Winter Reckoning; The Leaden Accord" is two
        candidates; "Crookvale in 297 AS" is one, with the date qualifier removed.
        Only names the fact store actually knows about are returned, so a hop can
        never be taken into a subject we have no evidence for.
        """
        candidates: list[tuple[str, str]] = []
        for part in _VALUE_SPLIT.split(value_text):
            cleaned = _QUALIFIER.sub("", part).strip(" .,;")
            if not cleaned:
                continue
            subject_id = normalise(cleaned)
            if subject_id in self._subjects:
                candidates.append((subject_id, cleaned))
        return candidates

    def subjects_with_value(self, attribute: str, value_name: str) -> list[FactRow]:
        """Inverse lookup: who has `attribute` pointing at `value_name`?

        This is what turns a one-directional record into a traversable edge —
        "which faction has X as a member" is the same stored row as "X is a member
        of which faction", read from the other end.
        """
        key = re.sub(r"[^a-z0-9]+", " ", value_name.lower()).strip()
        rows = self.store.connection.execute(
            "SELECT * FROM facts WHERE attribute = ? AND (value_key = ? OR value_key LIKE ?)",
            (attribute, key, f"%{key}%"),
        ).fetchall()
        return [_to_fact(r) for r in rows]


def _to_fact(row) -> FactRow:
    return FactRow(
        subject_id=row["subject_id"], subject_name=row["subject_name"],
        attribute=row["attribute"], value_text=row["value_text"],
        value_key=row["value_key"], value_number=row["value_number"],
        chunk_id=row["chunk_id"], document_id=row["document_id"], page=row["page"],
        source_class=row["source_class"], reliability=row["reliability"],
    )
