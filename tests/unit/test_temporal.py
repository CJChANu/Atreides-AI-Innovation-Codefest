"""Dates, and the conclusions that follow from ordering them.

The reasoning these tests protect is the one no stored value can supply: "the
Aegis is housed in Gloamreach" and "Gloamreach was devastated in 227 AS" are both
recorded, and neither says whether the Aegis was there when it happened. Only
comparing the years does.
"""

import pytest

from src.reasoning.temporal import (
    DatedPlace,
    TemporalVerdict,
    all_years,
    check_anachronism,
    mentions_place,
    parse_year,
    split_dated_places,
)


# -- reading the archive's dates --------------------------------------------

def test_an_in_world_year_is_read_as_a_number():
    assert parse_year("354 AS") == 354
    assert parse_year("Forged in 72 AS at Stormmarch") == 72
    assert parse_year("no year is stated") is None
    assert parse_year("") is None


def test_every_year_in_a_value_is_available():
    assert all_years("Began 225 AS, ended 235 AS") == [225, 235]


def test_a_multi_valued_event_row_keeps_each_place_with_its_own_year():
    """Taking only the first would drop the devastation a question is about."""
    places = split_dated_places(
        "Greyfell Citadel in 337 AS; Palewell Abbey in 338 AS; Cindermere Hold in 338 AS")
    assert places == [
        DatedPlace("Greyfell Citadel", 337),
        DatedPlace("Palewell Abbey", 338),
        DatedPlace("Cindermere Hold", 338),
    ]


def test_a_leading_verb_is_not_part_of_the_place_name():
    assert split_dated_places("Devastated Gloamreach in 320 AS") == [
        DatedPlace("Gloamreach", 320)]
    assert split_dated_places("Waged at Cindermere Hold in 228 AS") == [
        DatedPlace("Cindermere Hold", 228)]


def test_a_value_with_no_year_yields_nothing():
    assert split_dated_places("Gloamreach") == []


def test_place_matching_ignores_punctuation_and_case():
    assert mentions_place("[[Gloamreach]] in 227 AS", "Gloamreach")
    assert not mentions_place("Greyfell Citadel in 233 AS", "Gloamreach")


# -- the conclusion ---------------------------------------------------------

def test_a_thing_created_after_an_event_cannot_have_been_present():
    finding = check_anachronism("The Cinder-Wrought Aegis", "forging_date", 354,
                                "The War of Drowned Light", "Gloamreach", 227)
    assert finding.impossible
    assert finding.gap == 127
    assert "did not yet exist" in finding.explain()


def test_a_thing_created_before_an_event_is_not_ruled_out():
    finding = check_anachronism("The Thrice-Bound Edge", "forging_date", 123,
                                "The Leaden Accord", "Greyfell Citadel", 337)
    assert not finding.impossible
    assert "do not rule out" in finding.explain()


def test_the_same_year_does_not_rule_out_presence():
    """Created in the year of the event: the dates alone settle nothing."""
    finding = check_anachronism("X", "forging_date", 300, "E", "P", 300)
    assert not finding.impossible


def test_a_verdict_over_several_events_reports_them_all():
    """Gloamreach was devastated twice; an answer naming one is half an answer."""
    verdict = TemporalVerdict(findings=[
        check_anachronism("Aegis", "forging_date", 354, "War of Drowned Light",
                          "Gloamreach", 227),
        check_anachronism("Aegis", "forging_date", 354, "Purge of Blackport",
                          "Gloamreach", 320),
    ])
    assert verdict.all_impossible
    summary = verdict.summarise()
    assert "227" in summary and "320" in summary
    assert "does not follow" in summary


def test_a_mixed_verdict_is_not_reported_as_settled():
    verdict = TemporalVerdict(findings=[
        check_anachronism("X", "forging_date", 300, "E1", "P", 227),
        check_anachronism("X", "forging_date", 300, "E2", "P", 320),
    ])
    assert verdict.any_impossible and not verdict.all_impossible
    assert "some of the recorded events, but not all" in verdict.summarise()


def test_custody_is_reported_as_custody_not_presence():
    verdict = TemporalVerdict(
        findings=[check_anachronism("Aegis", "forging_date", 354, "War", "Gloamreach", 227)],
        custody_note="The archive records Aegis as housed in Gloamreach, which "
                     "establishes where it is kept, not where it was.",
    )
    assert "not where it was" in verdict.summarise()


def test_no_findings_produces_no_claim():
    assert TemporalVerdict().summarise() == ""
