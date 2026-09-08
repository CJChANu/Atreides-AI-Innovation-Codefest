"""Reading a stated value out of a sentence, and knowing when not to.

The fallback exists because the archive states some values only in prose — the
Cinder-Wrought Aegis' forging year appears in one sentence of a contract about a
different relic. The risk it introduces is the opposite of the bug it fixes:
a pattern loose enough to find that sentence is loose enough to invent facts
from unrelated ones. These tests hold both ends.
"""

from src.graph.prose_facts import extract, search_queries


def test_a_stated_year_is_read_from_the_sentence():
    text = ("**The Cinder-Wrought Aegis**, regalia shaped by the Sundering. "
            "Its forged year is **354 AS**.")
    found = extract(text, "The Cinder-Wrought Aegis", "forging_date")
    assert found is not None
    assert found.value_text == "354 AS"


def test_the_sentence_is_kept_so_the_claim_can_be_quoted():
    text = "The Hollow Edge was forged at Vharencrag. It is housed in Crookgate Keep."
    found = extract(text, "The Hollow Edge", "housed_in")
    assert "Crookgate Keep" in found.quote()


def test_a_pronoun_carries_the_subject_only_from_the_previous_sentence():
    """"Its forged year is X" is about whatever was just named, not anything."""
    text = "The Thrice-Bound Lantern is a ward. Its forged year is 72 AS."
    assert extract(text, "The Thrice-Bound Lantern", "forging_date").value_text == "72 AS"


def test_a_pronoun_does_not_reach_across_an_unrelated_sentence():
    text = ("The Thrice-Bound Lantern is a ward. "
            "Marrowwatch is a border hold of the Gloaming Reach. "
            "Its forged year is 72 AS.")
    assert extract(text, "The Thrice-Bound Lantern", "forging_date") is None


def test_a_hedged_sentence_states_nothing():
    """A documented disagreement must not become a false certainty."""
    text = ("The forged year of The Cinder-Wrought Aegis is contested among sources, "
            "and no single account is accepted as definitive.")
    assert extract(text, "The Cinder-Wrought Aegis", "forging_date") is None


def test_a_value_belonging_to_another_subject_is_not_borrowed():
    text = "The Hollow Edge was forged at Vharencrag in 210 AS."
    assert extract(text, "The Cinder-Wrought Aegis", "forging_site") is None


def test_a_bare_number_near_the_subject_is_not_a_fact():
    """Without the archive's phrasing around it, a number means nothing."""
    text = "The Cinder-Wrought Aegis appears in 34 separate ledgers."
    assert extract(text, "The Cinder-Wrought Aegis", "attunement_cost") is None


def test_an_unknown_attribute_yields_nothing():
    text = "The Cinder-Wrought Aegis has a demeanor of austere sovereignty."
    assert extract(text, "The Cinder-Wrought Aegis", "demeanor") is None


def test_queries_use_the_archives_wording_not_ours():
    """Searching our canonical name ranks the pages that do *not* state it."""
    queries = search_queries("The Cinder-Wrought Aegis", "forging_date")
    assert any("forged year" in query for query in queries)
    # The bare subject is kept as a last resort.
    assert "The Cinder-Wrought Aegis" in queries
