"""Dates, and what follows from them.

A stored value is not an answer to a question about *time*. "The Aegis is housed
in Gloamreach" and "Gloamreach was devastated in 227 AS" are both recorded facts,
and putting them side by side does not say whether the Aegis was there when it
happened. Answering that needs one more step: read the years, order them, and say
what the ordering rules out.

That step is arithmetic over evidence, not retrieval, which is why it lives here
rather than in the fact store. Everything in this module is a pure function over
values already extracted and cited elsewhere — it invents no facts, and every
conclusion it produces names the two dates it rests on.

The archive dates everything as "<year> AS", and states events as a place with a
year attached ("Gloamreach in 227 AS; Cindermere Hold in 228 AS"), so both are
parseable exactly rather than approximately.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_YEAR = re.compile(r"(\d{1,4})\s*AS\b", re.IGNORECASE)
# "Gloamreach in 227 AS" / "Devastated Gloamreach in 320 AS" / "Wields X since 314 AS"
_PLACE_YEAR = re.compile(
    r"(?P<place>[^;,]*?)\s+(?:in|since|at|during)\s+(?P<year>\d{1,4})\s*AS\b",
    re.IGNORECASE,
)
_LEADING_VERB = re.compile(
    r"^\s*(?:devastated|waged(?:\s+at)?|fought(?:\s+at)?|wields?|held|besieged|"
    r"destroyed|razed|sacked|founded|forged)\s+", re.IGNORECASE
)

# Attributes that say when a thing came into existence. An event before this year
# is an event the thing could not have been present for — that is the whole basis
# of an anachronism check, so the set is deliberately small and literal.
ORIGIN_ATTRIBUTES: frozenset[str] = frozenset({
    "forging_date", "founded", "born", "began",
})

# Attributes whose values are dated events at named places.
EVENT_ATTRIBUTES: frozenset[str] = frozenset({
    "devastated", "devastated_sites", "major_devastation", "related_region_and_year",
    "waged_at", "waged", "recorded_deployment", "belligerent_in", "began", "ended",
})

# Attributes that record where a thing *is*, not where it has always been. The
# distinction is the substance of the answer: custody now is not presence then.
CUSTODY_ATTRIBUTES: frozenset[str] = frozenset({
    "housed_in", "current_housing", "place_of_housing", "seat", "lair", "serves_at",
})


def parse_year(text: str) -> int | None:
    """First in-world year in the text, as an integer. '354 AS' -> 354."""
    match = _YEAR.search(text or "")
    return int(match.group(1)) if match else None


def all_years(text: str) -> list[int]:
    return [int(value) for value in _YEAR.findall(text or "")]


@dataclass(frozen=True)
class DatedPlace:
    """A place with a year attached, as the archive writes them together."""

    place: str
    year: int


def split_dated_places(value_text: str) -> list[DatedPlace]:
    """Parse "Greyfell Citadel in 337 AS; Palewell Abbey in 338 AS".

    Multi-valued event rows are the archive's normal shape, and taking only the
    first would silently drop the devastation a question happens to be about.
    """
    found: list[DatedPlace] = []
    for part in re.split(r"\s*;\s*", value_text or ""):
        match = _PLACE_YEAR.search(part)
        if not match:
            continue
        place = _LEADING_VERB.sub("", match.group("place")).strip(" .,:")
        if place:
            found.append(DatedPlace(place=place, year=int(match.group("year"))))
    return found


def mentions_place(value_text: str, place: str) -> bool:
    def fold(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", text.lower())

    return fold(place).strip() in fold(value_text)


@dataclass
class Anachronism:
    """The finding that a thing could not have been present at an event."""

    subject: str
    subject_year: int
    subject_attribute: str
    event: str
    event_place: str
    event_year: int

    @property
    def gap(self) -> int:
        return self.subject_year - self.event_year

    @property
    def impossible(self) -> bool:
        """True when the subject did not yet exist when the event happened."""
        return self.subject_year > self.event_year

    def explain(self) -> str:
        origin = self.subject_attribute.replace("_", " ")
        if self.impossible:
            return (f"{self.subject} has a recorded {origin} of {self.subject_year} AS, "
                    f"which is {self.gap} years *after* {self.event_place} was "
                    f"affected in {self.event_year} AS ({self.event}). It did not yet "
                    f"exist when that happened.")
        return (f"{self.subject} has a recorded {origin} of {self.subject_year} AS, "
                f"{abs(self.gap)} years before {self.event_place} was affected in "
                f"{self.event_year} AS ({self.event}), so the dates do not rule out "
                f"its presence.")


def check_anachronism(subject: str, subject_attribute: str, subject_year: int,
                      event: str, event_place: str, event_year: int) -> Anachronism:
    return Anachronism(subject=subject, subject_year=subject_year,
                       subject_attribute=subject_attribute, event=event,
                       event_place=event_place, event_year=event_year)


@dataclass(frozen=True)
class Span:
    """A dated interval, e.g. a war from its start year to its end year."""

    label: str
    start: int
    end: int | None = None

    @property
    def duration(self) -> int | None:
        return None if self.end is None else self.end - self.start

    def describe(self) -> str:
        if self.end is None:
            return f"{self.label}: began {self.start} AS (no end recorded)"
        return (f"{self.label}: {self.start} AS to {self.end} AS "
                f"({self.duration} years)")


def order_by_year(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Dated items, earliest first. The basis of every ordering question."""
    return sorted(items, key=lambda item: item[1])


def describe_ordering(items: list[tuple[str, int]]) -> str:
    """'A (225 AS), then B (227 AS), then C (320 AS)'."""
    ordered = order_by_year(items)
    if not ordered:
        return ""
    parts = [f"{label} ({year} AS)" for label, year in ordered]
    return parts[0] if len(parts) == 1 else ", then ".join(parts)


def years_between(first: int, second: int) -> int:
    """Absolute gap in years. Direction is stated separately, in words."""
    return abs(second - first)


def overlaps(first: Span, second: Span) -> bool | None:
    """Whether two spans overlap, or None when a needed end date is missing.

    Returning None rather than False matters: "we cannot tell" and "they do not
    overlap" are different answers, and only one of them is a finding.
    """
    if first.end is None or second.end is None:
        return None
    return first.start <= second.end and second.start <= first.end


@dataclass
class TemporalVerdict:
    """The reasoned answer to a presence-at-an-event question."""

    findings: list[Anachronism] = field(default_factory=list)
    custody_note: str = ""

    @property
    def all_impossible(self) -> bool:
        return bool(self.findings) and all(f.impossible for f in self.findings)

    @property
    def any_impossible(self) -> bool:
        return any(f.impossible for f in self.findings)

    def summarise(self) -> str:
        if not self.findings:
            return ""
        parts = [finding.explain() for finding in self.findings]
        if self.all_impossible:
            lead = ("The conclusion does not follow, because the dates rule it out. "
                    if len(self.findings) == 1 else
                    "The conclusion does not follow for any of the recorded events. ")
        elif self.any_impossible:
            lead = "The dates rule this out for some of the recorded events, but not all. "
        else:
            lead = "The dates do not rule this out. "
        tail = f" {self.custody_note}" if self.custody_note else ""
        return lead + " ".join(parts) + tail
