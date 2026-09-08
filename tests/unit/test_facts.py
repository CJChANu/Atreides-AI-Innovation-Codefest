"""Fact normalisation decides what counts as a contradiction."""

from src.graph.facts import clean_value, normalise_attribute, numeric_value, value_key
from src.graph.plate_facts import extract_plate_facts, is_chart_plate, subject_from_caption


def test_attribute_variants_collapse_so_sources_are_comparable():
    assert normalise_attribute("Forged") == normalise_attribute("Forging date") == "forging_date"
    assert normalise_attribute("Present housing") == normalise_attribute("Housed in") == "housed_in"


def test_structural_labels_are_dropped():
    assert normalise_attribute("Name") is None
    assert normalise_attribute("Value") is None


def test_unmapped_labels_are_kept_rather_than_lost():
    assert normalise_attribute("Reed-Wind Omen") == "reed_wind_omen"


def test_wikilinks_are_stripped_from_values():
    assert clean_value("[[Ironfell Citadel]]") == "Ironfell Citadel"
    assert clean_value("**391 AS**") == "391 AS"


def test_in_world_years_are_comparable_numbers():
    assert numeric_value("391 AS") == 391.0
    assert numeric_value("3,107") == 3107.0
    # A number embedded in prose is not a numeric value.
    assert numeric_value("Crookgate Keep, third hall") is None


def test_case_differences_are_not_conflicts():
    assert value_key("Contested") == value_key("contested")


def test_plate_labels_yield_their_number():
    facts = extract_plate_facts("Creature plate: Weeping Lurker",
                                "Weeping Lurker THREAT RATING 3 of 10")
    assert facts == [("threat_rating", "3", 3.0)]


def test_chart_plates_assert_nothing():
    """Axis ticks are not values; we would rather answer 'unknown' than wrongly."""
    text = ("The Thrice-Bound Edge - Attunement Cost 20 Novice tolerance "
            "Adept tolerance Master tolerance Measured in vitae-grains.")
    assert is_chart_plate(text)
    assert extract_plate_facts("Artifact plate: The Thrice-Bound Edge", text) == []


def test_subject_is_read_from_the_caption():
    assert subject_from_caption("Creature plate: Weeping Lurker") == "Weeping Lurker"
