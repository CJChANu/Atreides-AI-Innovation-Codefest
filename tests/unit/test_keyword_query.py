"""User text must never reach FTS5 as an expression it could misparse."""

from src.retrieval.keyword import to_fts_query


def test_terms_are_quoted():
    assert to_fts_query("Weeping Lurker") == '"Weeping" OR "Lurker"'


def test_fts_operators_in_a_question_cannot_break_the_query():
    # 'NEAR', '*' and parentheses are FTS5 syntax; quoting neutralises them.
    query = to_fts_query("Who is NEAR(the gate) *?")
    assert "(" not in query and "*" not in query
    assert '"NEAR"' in query


def test_and_mode_requires_every_term():
    assert to_fts_query("gauntlet sorrowfell", mode="and") == '"gauntlet" AND "sorrowfell"'


def test_empty_input_yields_no_query_rather_than_a_crash():
    assert to_fts_query("  ?  ") == ""
