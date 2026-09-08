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
from src.graph.plate_chart import read_chart_plate
from src.graph.plate_facts import extract_plate_facts, is_chart_plate, subject_from_caption
from src.ingestion.parsers.markdown_parser import WIKILINK
from src.storage.db import ArchiveStore

# Attribute labels normalise to snake_case; these variants collapse to one name so
# a wiki infobox and a codex table are directly comparable.
ATTRIBUTE_ALIASES = {
    "forged": "forging_date", "forging date": "forging_date", "forged in": "forging_date",
    "forging": "forging_date", "forged year": "forging_date", "year forged": "forging_date",
    "forged at": "forging_site", "forging site": "forging_site", "place of forging": "forging_site",
    "founded": "founded", "founding date": "founded", "founding year": "founded",
    "attunement cost": "attunement_cost", "cost": "attunement_cost",
    "threat rating": "threat_rating",
    # The codex writes casualty counts three ways; the question vocabulary only
    # ever asks for "recorded casualties", so the rest were unreachable.
    "recorded casualties": "recorded_casualties", "casualties": "recorded_casualties",
    "casualty figure": "recorded_casualties",
    "garrison strength": "garrison_strength", "garrison": "garrison_strength",
    # Housing is stated six ways across the wiki and the two codexes. Every
    # unaliased spelling is a fact the archive holds and we could not find: the
    # Cinder-Wrought Aegis' housing sat under "place of housing" and a question
    # asking where it is housed came back "not established".
    "current repository": "housed_in", "present housing": "housed_in", "housed in": "housed_in",
    "place of housing": "housed_in", "current housing": "housed_in", "housing": "housed_in",
    "repository": "housed_in",
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
    # Membership is stated four different ways across the wiki and the codexes.
    # Collapsing them is what makes a "member of the faction that won X" hop
    # possible without special-casing each source.
    "membership": "member_of", "member of": "member_of",
    "member": "has_member", "known members": "has_member", "members": "has_member",
    "victor of": "victor_of", "won": "victor_of",
    "service": "serves_at", "place of service": "serves_at", "current service": "serves_at",
    # For a relic the archive treats "where it currently is" and "where it is
    # housed" as the same row; it only ever uses this label on artifacts.
    "current location": "housed_in",
    "lair region": "lair", "known lair-region": "lair",
    "primary domain": "primary_domain",
}

# Rows whose label is one of these carry no fact — they restate the subject or
# label the grid itself.
SKIP_LABELS = {"name", "subject", "field", "value", "classification", "record",
               "columns", "recorded description", "entry", "register", "registry field"}

# The flattened retrieval text of a table starts with a "Columns: A | B" line,
# which looks exactly like a data row. Dropping it removes ~110 junk facts.
_COLUMNS_HEADER = re.compile(r"^columns\s*:", re.IGNORECASE)

# Codex timeline grids are keyed by year ("225 AS | The War ... began"). The year
# is the *value*, not the attribute, so we relabel rather than create one
# attribute per year.
_YEAR_LABEL = re.compile(r"^\d{1,4}\s*AS$", re.IGNORECASE)

_ROW = re.compile(r"^\s*(?P<label>[^|]{1,60}?)\s*\|\s*(?P<value>.+?)\s*$")

# Words that name a *field*, never a subject. Used to reject a mis-detected
# heading before it becomes a fact subject.
_LABEL_LIKE = SKIP_LABELS | set(ATTRIBUTE_ALIASES) | {
    "region", "status", "founded", "habit", "lair", "seat", "role", "born",
    "type", "doctrine", "outcome", "victor", "appearance", "demeanor", "danger",
}
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
    cleaned = label.strip().strip("|*").strip()
    if _COLUMNS_HEADER.match(cleaned):
        return None
    if _YEAR_LABEL.match(cleaned):
        return "timeline_event"
    cleaned = cleaned.lower()
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


# Words that decorate a value without changing it. "The Gloaming Reach" and
# "Gloaming Reach" are the same place; "5805" and "5805 troops" are the same
# count. Left in, each pair is reported to the user as a source disagreement,
# which devalues the real conflicts sitting beside them.
_LEADING_ARTICLE = re.compile(r"^(the|a|an)\s+")
_TRAILING_UNITS = re.compile(
    r"\s+(troops|soldiers|men|souls|souls under arms|swords|spears|strong)$")


def value_key(value: str) -> str:
    """Comparison key for conflict detection.

    Case, punctuation, a leading article and a trailing unit noun are all
    presentation rather than disagreement. Only differences that survive this
    normalisation are reported as conflicts — anything looser would start merging
    genuinely different values, which is the more damaging error.
    """
    # Digit-group separators first: without this "3,107" splits into "3 107" and
    # never matches the same count written plainly.
    key = re.sub(r"(?<=\d),(?=\d)", "", value.lower())
    key = re.sub(r"[^a-z0-9]+", " ", key).strip()
    key = _LEADING_ARTICLE.sub("", key)
    for _ in range(2):                      # "5805 souls under arms" → "5805"
        key = _TRAILING_UNITS.sub("", key)
    return key.strip()


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
                      f.caption, f.ocr_text, f.figure_id, f.asset_path
               FROM chunks c
               JOIN documents d ON d.document_id = c.document_id
               LEFT JOIN figures f ON f.figure_id = c.figure_ids
               WHERE c.content_type = 'figure' AND d.superseded_by IS NULL"""
        ).fetchall()

        # A plate's subject comes from its filename, which has lost the archive's
        # punctuation: "plate_13_artifact_the_cinder_wrought_aegis" gives "The
        # Cinder Wrought Aegis". That normalises to the right subject_id, so
        # lookups already work, but the name is what a reader sees in a citation.
        # The entity table holds the archive's own spelling for the same id.
        canonical = {
            row["entity_id"]: row["name"]
            for row in self.store.connection.execute("SELECT entity_id, name FROM entities")
        }

        payload: list[tuple] = []
        for row in rows:
            caption = row["caption"] or row["content"].splitlines()[0]
            subject_raw = subject_from_caption(caption)
            subject_id = normalise(subject_raw)
            if not subject_id:
                continue
            subject_raw = canonical.get(subject_id, subject_raw)
            reliability = reliability_of(row["source_class"])
            found = extract_plate_facts(caption, row["content"])

            # A chart plate prints its value as a bar against labelled reference
            # bars, so the label grammar above yields nothing on it by design.
            # Reading it off the drawing recovers values that exist nowhere else
            # in the archive — the Cinder-Wrought Aegis' attunement cost is only
            # ever drawn. `read_chart_plate` returns None unless the bar and the
            # printed number agree, so this never trades honesty for coverage.
            if not found and row["asset_path"] and is_chart_plate(
                f"{caption} {row['content']}"
            ):
                reading = read_chart_plate(row["asset_path"], caption=caption,
                                           subject=subject_raw)
                if reading is not None:
                    found = [(reading.attribute, reading.value_text,
                              reading.value_number)]

            for attribute, value, number in found:
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
        # A heading that is itself a field label is not a subject. PDF heading
        # detection sometimes picks up a table's column header ("Region",
        # "Status"), and a fact subject named after an attribute later collides
        # with that same word appearing in a question.
        if head and head.lower() in _LABEL_LIKE:
            head = ""
        if head and head.lower() not in {"infobox", "classification"}:
            return head
        return row["title"]
