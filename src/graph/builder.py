"""Build the knowledge graph from evidence already in the index.

We start with the relations the corpus states *explicitly*, before reaching for an
LLM:

* **Wiki links.** ``[[Ironfell Citadel]]`` inside a House Morvain article is a
  human-authored, unambiguous assertion that the two are related. Thousands of
  these exist and they cost nothing to extract.
* **Infobox rows.** ``| Seat | [[Ironfell Citadel]] |`` upgrades that generic link
  to a *typed* edge (``seated_at``), which is what multi-hop questions such as
  "whose dominion encompasses the lair of X" actually traverse.

This gives a dense, fully-cited graph with zero hallucination risk. LLM extraction
is layered on later for the prose-only sources, where it has to earn its place
against a baseline that already works.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.graph.entities import display_name, normalise, type_hint
from src.ingestion.parsers.markdown_parser import extract_wikilinks
from src.storage.db import ArchiveStore

# Infobox field label -> edge predicate. Anything not listed still produces a
# generic `related_to` edge, so an unmapped label loses type information but
# never loses the connection.
FIELD_PREDICATES = {
    "seat": "seated_at",
    "seated at": "seated_at",
    "belligerent in": "belligerent_in",
    "known members": "has_member",
    "member of": "member_of",
    "affiliation": "affiliated_with",
    "ruled by": "ruled_by",
    "lair": "lairs_in",
    "housed in": "housed_in",
    "forged at": "forged_at",
    "region": "located_in",
    "location": "located_in",
    "victor": "won_by",
    "outcome": "outcome_of",
    "participants": "participant_in",
    "wielder": "wielded_by",
    "seat of": "seat_of",
}

_TABLE_ROW = re.compile(r"^(?P<field>[^|]+)\|(?P<value>.+)$")
# A plain-text table value is treated as an entity only if it reads like a name:
# capitalised words, no digits. "The Bleeding Crown" qualifies; "2598" does not.
_PLAIN_NAME = re.compile(r"^(?:The\s+)?(?:[A-Z][\w'-]*)(?:\s+(?:of|the|and|[A-Z][\w'-]*))*$")


def _plain_targets(part: str) -> list[str]:
    candidate = part.strip().strip("*").strip()
    return [candidate] if _PLAIN_NAME.match(candidate) else []
# Infobox values often list several targets separated by ';'.
_VALUE_SPLIT = re.compile(r"\s*;\s*")


@dataclass
class GraphReport:
    entities: int = 0
    edges: int = 0
    mentions: int = 0
    typed_edges: int = 0

    def summary(self) -> str:
        return (f"entities {self.entities}\nedges    {self.edges} "
                f"({self.typed_edges} typed from infoboxes)\nmentions {self.mentions}")


class GraphBuilder:
    def __init__(self, store: ArchiveStore) -> None:
        self.store = store

    def build(self) -> GraphReport:
        report = GraphReport()
        connection = self.store.connection
        for table in ("edges", "entity_mentions", "entity_aliases", "entities"):
            connection.execute(f"DELETE FROM {table}")

        rows = connection.execute(
            """SELECT c.chunk_id, c.document_id, c.content, c.content_type,
                      c.page_start, c.section_path, d.title, d.source_class
               FROM chunks c JOIN documents d ON d.document_id = c.document_id
               WHERE d.superseded_by IS NULL"""
        ).fetchall()

        entities: dict[str, dict] = {}
        mentions: set[tuple[str, str]] = set()
        edges: list[tuple] = []

        for row in rows:
            # The article's own title is the subject of everything it says.
            subject_raw = (row["section_path"].split(" > ")[0] if row["section_path"] else "") or row["title"]
            subject_raw = subject_raw.strip("[] ")
            subject = normalise(subject_raw)
            if subject:
                self._remember(entities, subject, display_name(subject_raw), type_hint(subject_raw))

            targets = extract_wikilinks(row["content"])
            for target_raw in targets:
                target = normalise(target_raw)
                if not target:
                    continue
                self._remember(entities, target, display_name(target_raw), type_hint(target_raw))
                mentions.add((target, row["chunk_id"]))
                if subject and target != subject:
                    edges.append((subject, "related_to", target, row["chunk_id"],
                                  row["document_id"], row["page_start"], "wikilink", 0.6))

            if row["content_type"] == "table" and subject:
                for predicate, target, confidence in self._infobox_edges(row["content"]):
                    self._remember(entities, target[0], target[1], "unknown")
                    edges.append((subject, predicate, target[0], row["chunk_id"],
                                  row["document_id"], row["page_start"], "infobox", confidence))
                    report.typed_edges += 1

        connection.executemany(
            "INSERT OR REPLACE INTO entities (entity_id, name, entity_type, mention_count) "
            "VALUES (?,?,?,?)",
            [(eid, e["name"], e["type"], e["count"]) for eid, e in entities.items()],
        )
        connection.executemany(
            "INSERT OR IGNORE INTO entity_mentions (entity_id, chunk_id) VALUES (?,?)",
            sorted(mentions),
        )
        connection.executemany(
            """INSERT OR IGNORE INTO edges
               (subject_id, predicate, object_id, chunk_id, document_id, page, method, confidence)
               VALUES (?,?,?,?,?,?,?,?)""",
            edges,
        )
        connection.commit()

        report.entities = len(entities)
        report.mentions = len(mentions)
        report.edges = connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        return report

    @staticmethod
    def _remember(entities: dict[str, dict], entity_id: str, name: str, hint: str) -> None:
        record = entities.setdefault(entity_id, {"name": name, "type": hint, "count": 0})
        record["count"] += 1
        # A concrete type always beats 'unknown', whichever mention supplied it.
        if record["type"] == "unknown" and hint != "unknown":
            record["type"] = hint

    @staticmethod
    def _infobox_edges(content: str):
        """Yield (predicate, (entity_id, display), confidence) from infobox rows."""
        for line in content.splitlines():
            match = _TABLE_ROW.match(line.strip())
            if not match:
                continue
            field = match.group("field").strip().strip("|").lower()
            predicate = FIELD_PREDICATES.get(field)
            if predicate is None:
                continue
            for part in _VALUE_SPLIT.split(match.group("value")):
                # Wiki infoboxes link their values; codex tables state them as
                # plain text ("Ruling power | The Bleeding Crown"). Both are the
                # same assertion, so fall back to the literal value when there is
                # no link to follow — otherwise the most authoritative source in
                # the archive would contribute no edges at all.
                targets = extract_wikilinks(part) or _plain_targets(part)
                for target_raw in targets:
                    target = normalise(target_raw)
                    if target:
                        # Infobox edges are stated as structured fact, not prose
                        # proximity, so they carry higher confidence than a link.
                        yield predicate, (target, display_name(target_raw)), 0.9
