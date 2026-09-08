"""Finding the dated events a place was caught up in.

This is the fact store used the way it is meant to be used: as an index that
tells you *where to look*, not as the answer. Nothing here concludes anything.
It answers two navigational questions —

    when did this thing come into existence?
    what dated events name this place?

— and hands back the rows, each of which still carries the chunk it came from so
the passage behind it can be read and quoted.

The second question is the interesting one, because the archive records it from
the other side. Gloamreach's own page does not say it was devastated; the War of
Drowned Light's page says ``Devastated | Gloamreach in 227 AS``. A lookup on
Gloamreach finds nothing and concludes there is nothing. Searching from the event
end finds both devastations — 227 AS and, in a different war, 320 AS — which is
the difference between a partial answer and a complete one.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.graph.fact_query import FactRow, _to_fact
from src.reasoning.temporal import (
    EVENT_ATTRIBUTES,
    ORIGIN_ATTRIBUTES,
    DatedPlace,
    mentions_place,
    parse_year,
    split_dated_places,
)
from src.storage.db import ArchiveStore


@dataclass
class Origin:
    """When a subject came into existence, and the row that says so."""

    attribute: str
    year: int
    row: FactRow


@dataclass
class Event:
    """A dated event naming a place, read from the event's own record."""

    subject_name: str      # "The War of Drowned Light"
    attribute: str         # "devastated"
    place: str             # "Gloamreach"
    year: int
    row: FactRow

    def describe(self) -> str:
        return f"{self.subject_name} — {self.attribute.replace('_', ' ')} {self.place} in {self.year} AS"


class Timeline:
    def __init__(self, store: ArchiveStore) -> None:
        self.store = store

    def origin_of(self, subject_id: str) -> Origin | None:
        """The earliest recorded existence date for a subject."""
        rows = self.store.connection.execute(
            "SELECT * FROM facts WHERE subject_id = ?", (subject_id,)
        ).fetchall()
        best: Origin | None = None
        for row in rows:
            if row["attribute"] not in ORIGIN_ATTRIBUTES:
                continue
            year = parse_year(row["value_text"])
            if year is None:
                continue
            if best is None or year < best.year:
                best = Origin(attribute=row["attribute"], year=year, row=_to_fact(row))
        return best

    def events_at(self, place: str) -> list[Event]:
        """Every dated event whose record names this place.

        Searched from the event side, because that is the side the archive
        records it on.
        """
        pattern = f"%{place}%"
        rows = self.store.connection.execute(
            "SELECT * FROM facts WHERE value_text LIKE ? AND value_text LIKE '%AS%'",
            (pattern,),
        ).fetchall()

        events: list[Event] = []
        seen: set[tuple[str, str, int]] = set()
        for row in rows:
            if row["attribute"] not in EVENT_ATTRIBUTES:
                continue
            for dated in self._dated_places(row["value_text"], place):
                key = (row["subject_name"], row["attribute"], dated.year)
                if key in seen:
                    continue
                seen.add(key)
                events.append(Event(
                    subject_name=row["subject_name"], attribute=row["attribute"],
                    place=dated.place, year=dated.year, row=_to_fact(row),
                ))
        events.sort(key=lambda event: event.year)
        return events

    @staticmethod
    def _dated_places(value_text: str, place: str) -> list[DatedPlace]:
        """The dated entries in this value that are about `place`.

        A row may list several places with different years; only the ones naming
        the place asked about are relevant, and pairing the wrong year with the
        right place is exactly the error this guards against.
        """
        return [dated for dated in split_dated_places(value_text)
                if mentions_place(dated.place, place) or mentions_place(place, dated.place)]
