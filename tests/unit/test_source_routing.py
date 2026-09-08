"""Which source can answer which attribute.

The reported failure: asked where a relic is housed, the system searched the
relic's *illustration*, found a painting with no legible text, and reported the
answer unavailable — while the housing location sat in the wiki infobox. Nearly
every entity has a plate of some kind, so "a plate exists for this entity" is
never a reason to consult it. What matters is whether a plate could carry the
attribute being asked for.
"""

from src.graph.plate_facts import FIGURE_ATTRIBUTES, is_figure_attribute
from src.graph.facts import normalise_attribute


def test_measured_quantities_route_to_plates():
    for attribute in ("threat_rating", "attunement_cost", "garrison_strength",
                      "recorded_casualties"):
        assert is_figure_attribute(attribute)


def test_text_attributes_never_route_to_plates():
    """These live in codex tables and infoboxes; no plate states them."""
    for attribute in ("housed_in", "forging_site", "forging_date", "artifact_class",
                      "ruled_by", "lair", "member_of"):
        assert not is_figure_attribute(attribute)


def test_a_missing_attribute_routes_nowhere():
    assert not is_figure_attribute(None)
    assert not is_figure_attribute("")


def test_the_figure_set_is_only_measurements():
    """A guard on scope: plates in this archive carry numbers, nothing else."""
    assert FIGURE_ATTRIBUTES == {
        "threat_rating", "attunement_cost", "garrison_strength",
        "recorded_casualties", "shards_of_will",
    }


# -- the alias gaps that sent questions to the wrong source ------------------

def test_every_housing_spelling_collapses_to_one_attribute():
    """Six spellings across the wiki and two codexes; one of them held the Aegis."""
    for label in ("Housed in", "Place of housing", "Current housing", "Housing",
                  "Current repository", "Present housing"):
        assert normalise_attribute(label) == "housed_in", label


def test_every_forging_year_spelling_collapses():
    for label in ("Forged", "Forging date", "Forging", "Forged year"):
        assert normalise_attribute(label) == "forging_date", label


def test_casualty_spellings_collapse():
    for label in ("Recorded casualties", "Casualties", "Casualty figure"):
        assert normalise_attribute(label) == "recorded_casualties", label


def test_forging_place_and_year_stay_distinct():
    """Collapsing these two would answer 'where' with a year."""
    assert normalise_attribute("Place of forging") == "forging_site"
    assert normalise_attribute("Forged year") == "forging_date"
