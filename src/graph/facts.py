"""Extraction of attribute facts from key/value tables.

Both the wiki infoboxes (``| Seat | [[Ironfell Citadel]] |``) and the codex
classification tables (``Attunement cost | 27``) are two-column key/value grids.
Lifting them into one normalised ``facts`` table buys three things at once:

* **Precise answers.** "What attunement cost is listed for X" becomes a lookup,
  not a hope that the right sentence made it into the context window.
* **Free contradiction detection.** Two rows with the same subject and attribute
  but different values *are* the conflict — no model judgement required. This is
  what the archive's contested founding dates and forging years look like.
* **Reliability-aware resolution.** Every fact keeps the source class it came
  from, so a codex value and a ballad value can be compared and reported rather
  than one silently winning.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.common.provenance import reliability_of
from src.graph.entities import display_name, normalise
from src.graph.plate_facts import extract_plate_facts, subject_from_caption
from src.ingestion.parsers.markdown_parser import WIKILINK
from src.storage.db import ArchiveStore

# Attribute labels normalise to snake_case; these variants collapse to one name so
# a wiki infobox and a codex table are directly comparable.
ATTRIBUTE_ALIASES = {
    "forged": "forging_date", "forging date": "forging_date", "forged in": "forging_date",
    "forged at": "forging_site", "forging site": "forging_site", "place of forging": "forging_site",
    "founded": "founded", "founding date": "founded", "founding year": "founded",
    "attunement cost": "attunement_cost",
    "threat rating": "threat_rating",
    "garrison strength": "garrison_strength", "garrison": "garrison_strength",
    "current repository": "housed_in", "present housing": "housed_in", "housed in": "housed_in",
    "artifact class": "artifact_class",
    "ruling power": "ruled_by", "ruled by": "ruled_by",
    "region": "region", "lair": "lair", "habit": "habit", "status": "status",
    "seat": "seat", "seated at": "seat",
    "type": "entity_type", "organization type": "entity_type",
    "doctrine": "doctrine",
    "recorded deployment": "recorded_deployment",
    "belligerent in": "belligerent_in",
    "known members": "known_members",
    "victor": "victor", "outcome": "outcome",
}

# Rows whose label is one of these carry no fact — they restate the subject or
# label the grid itself.
SKIP_LABELS = {"name", "subject", "field", "value", "classification", "record",
               "columns", "recorded description"}

_ROW = re.compile(r"^\s*(?P<label>[^|]{1,60}?)\s*\|\s*(?P<value>.+?)\s*$")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_YEAR = re.compile(r"\b(\d{1,4})\s*AS\b", re.IGNORECASE)


@dataclass
class FactReport:
    facts: int = 0
    subjects: int = 0
    conflicts: int = 0

    def summary(self) -> str:
        return (f"facts     {self.facts}\nsubjects  {self.subjects}\n"
                f"conflicts {self.conflicts} (same subject+attribute, differing values)")


def normalise_attribute(label: str) -> str | None:
    cleaned = label.strip().strip("|*").strip().lower()
    if not cleaned or cleaned in SKIP_LABELS:
        return None
    if cleaned in ATTRIBUTE_ALIASES:
        return ATTRIBUTE_ALIASES[cleaned]
    # Unmapped labels are still kept: an unknown attribute is better than a lost
    # fact, and the snake_case form is stable enough to compare across sources.
    return re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_") or None


def clean_value(raw: str) -> str:
    """Strip wiki-link and markdown decoration, keeping the readable value."""
    value = WIKILINK.sub(lambda m: m.group(1), raw)
    value = value.replace("**", "").replace("|", " ").strip(" .;")
    return re.sub(r"\s+", " ", value).strip()


def value_key(value: str) -> str:
    """Comparison key for conflict detection.

    Case and trailing punctuation are presentation, not disagreement: a codex
    saying "Contested" and a wiki saying "contested" agree. Only differences that
    survive this normalisation are reported as conflicts.
    """
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def numeric_value(value: str) -> float | None:
    """Return a comparable number for a value, preferring an ``NNN AS`` year."""
    year = _YEAR.search(value)
    if year:
        return float(year.group(1))
    # Only treat the value as numeric when it is *essentially* a number, so
    # "Crookgate Keep, 3rd hall" does not become 3.
    match = _NUMBER.fullmatch(value.replace(",", "").strip())
    return float(match.group().replace(",", "")) if match else None


class FactExtractor:
    def __init__(self, store: ArchiveStore) -> None:
        self.store = store

    def build(self) -> FactReport:
        connection = self.store.connection
        connection.execute("DELETE FROM facts")

        rows = connection.execute(
            """SELECT c.chunk_id, c.document_id, c.content, c.page_start,
                      c.section_path, c.source_class, d.title
               FROM chunks c JOIN documents d ON d.document_id = c.document_id
               WHERE c.content_type = 'table' AND d.superseded_by IS NULL"""
        ).fetchall()

        payload: list[tuple] = []
        for row in rows:
            subject_raw = self._subject_of(row)
            if not subject_raw:
                continue
            subject_id = normalise(subject_raw)
            if not subject_id:
                continue
            reliability = reliability_of(row["source_class"])

            for line in row["content"].splitlines():
                match = _ROW.match(line)
                if not match:
                    continue
                attribute = normalise_attribute(match.group("label"))
                if attribute is None:
                    continue
                value = clean_value(match.group("value"))
                if not value or len(value) > 200:
                    continue
                payload.append((subject_id, display_name(subject_raw), attribute, value,
                                value_key(value), numeric_value(value), row["chunk_id"],
                                row["document_id"], row["page_start"], row["source_class"],
                                reliability))

        payload += self._plate_facts()

        connection.executemany(
            """INSERT OR IGNORE INTO facts
               (subject_id, subject_name, attribute, value_text, value_key,
                value_number, chunk_id, document_id, page, source_class, reliability)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )
        connection.commit()

        report = FactReport()
        report.facts = connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
        report.subjects = connection.execute(
            "SELECT COUNT(DISTINCT subject_id) FROM facts").fetchone()[0]
        report.conflicts = connection.execute(
            """SELECT COUNT(*) FROM (
                   SELECT subject_id, attribute FROM facts
                   GROUP BY subject_id, attribute
                   HAVING COUNT(DISTINCT value_key) > 1)"""
        ).fetchone()[0]
        return report

    def _plate_facts(self) -> list[tuple]:
        """Facts printed on figure plates, cited to the figure's own page."""
        rows = self.store.connection.execute(
            """SELECT c.chunk_id, c.document_id, c.content, c.page_start, c.source_class,
                      f.caption, f.ocr_text, f.figure_id
               FROM chunks c
               JOIN documents d ON d.document_id = c.document_id
               LEFT JOIN figures f ON f.figure_id = c.figure_ids
               WHERE c.content_type = 'figure' AND d.superseded_by IS NULL"""
        ).fetchall()

        payload: list[tuple] = []
        for row in rows:
            caption = row["caption"] or row["content"].splitlines()[0]
            subject_raw = subject_from_caption(caption)
            subject_id = normalise(subject_raw)
            if not subject_id:
                continue
            reliability = reliability_of(row["source_class"])
            for attribute, value, number in extract_plate_facts(caption, row["content"]):
                payload.append((subject_id, display_name(subject_raw), attribute, value,
                                value_key(value), number, row["chunk_id"], row["document_id"],
                                row["page_start"], row["source_class"], reliability))
        return payload

    @staticmethod
    def _subject_of(row) -> str:
        """The entity a table describes: its heading, else the document title."""
        section = row["section_path"] or ""
        # For a wiki infobox the path is 'House Morvain > Infobox'; the article
        # title is the subject, not the section that happens to hold the grid.
        head = section.split(" > ")[0] if section else ""
        # Wiki headings are often themselves links ('[[Gloamreach]] (location)').
        head = WIKILINK.sub(lambda m: m.group(1), head).strip("[] ")
        if head and head.lower() not in {"infobox", "classification"}:
            return head
        return row["title"]
