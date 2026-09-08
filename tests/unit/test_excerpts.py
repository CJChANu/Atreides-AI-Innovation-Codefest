"""Quoting the line a stored value was read from.

A citation is a promise that the value came from somewhere. The quote is what
lets a reader check it without opening the document — which matters most exactly
where extraction is most likely to have gone wrong.
"""

from src.verification.excerpts import find_excerpt

INFOBOX = """[[The War of Drowned Light]] > Infobox

Infobox
Columns: Field | Value
Conflict | [[The War of Drowned Light]]
Began | 225 AS
Ended | 235 AS
Casualties | 64617
Waged at | [[Cindermere Hold]] in 228 AS; [[Greyfell Citadel]] in 233 AS
Devastated | [[Gloamreach]] in 227 AS"""

PROSE = ("The Cinder-Wrought Aegis is regalia shaped by the Sundering. "
         "Its forged year is **354 AS**. It remains under guard.")


def test_a_table_row_is_quoted_rather_than_the_whole_table():
    """The bug this fixes: quoting an entire infobox as evidence for one field."""
    excerpt = find_excerpt(INFOBOX, "Gloamreach in 227 AS")
    assert excerpt == "Devastated — Gloamreach in 227 AS"


def test_the_most_specific_row_wins():
    """'225 AS' appears in one row; the answer must not quote a longer one."""
    assert find_excerpt(INFOBOX, "225 AS") == "Began — 225 AS"


def test_the_column_header_is_never_quoted_as_evidence():
    excerpt = find_excerpt(INFOBOX, "64617")
    assert "Columns" not in excerpt
    assert excerpt == "Casualties — 64617"


def test_wikilinks_and_markup_are_stripped():
    assert "[[" not in find_excerpt(INFOBOX, "Gloamreach in 227 AS")
    assert "**" not in find_excerpt(PROSE, "354 AS")


def test_a_prose_value_is_quoted_as_its_sentence():
    assert find_excerpt(PROSE, "354 AS") == "Its forged year is 354 AS."


def test_a_value_that_is_not_present_yields_nothing():
    assert find_excerpt(INFOBOX, "999 AS") == ""
    assert find_excerpt("", "354 AS") == ""


def test_an_empty_value_is_not_matched_against_everything():
    assert find_excerpt(INFOBOX, "") == ""


def test_a_long_passage_is_shortened():
    long_text = "The relic was moved. " + ("filler words here. " * 60) + "It ended."
    excerpt = find_excerpt(long_text, "moved")
    assert len(excerpt) <= 221
