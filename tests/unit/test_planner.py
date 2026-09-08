"""Decomposition is what stops the loop halting at the first thing it finds."""

from src.orchestration.planner import decompose, next_action
from src.orchestration.state import Intent, Question


def _question(intent, **kwargs):
    return Question(text="q", intent=intent, entities=[("x", "X")], **kwargs)


def test_a_hop_question_requires_both_hops():
    subs = decompose(_question(Intent.RELATION_HOP, bridge_attribute="lair",
                               attribute="ruled_by"))
    keys = [s.key for s in subs]
    assert "bridge" in keys and "target" in keys
    assert keys.index("bridge") < keys.index("target")


def test_a_conflict_question_adds_a_resolution_step():
    subs = decompose(_question(Intent.CONFLICT_RESOLUTION, attribute="founded",
                               expects_conflict=True))
    assert "resolve" in [s.key for s in subs]


def test_a_plain_lookup_does_not_add_a_resolution_step():
    subs = decompose(_question(Intent.ATTRIBUTE_LOOKUP, attribute="founded"))
    assert "resolve" not in [s.key for s in subs]


def test_every_sub_question_states_its_completion_condition():
    for intent in (Intent.RELATION_HOP, Intent.ATTRIBUTE_LOOKUP, Intent.OPEN_QUESTION):
        for sub in decompose(_question(intent, attribute="founded")):
            assert sub.completion, f"{intent} produced a sub-question with no completion"


def test_the_target_query_uses_what_the_bridge_discovered():
    """This dependency is what makes the search iterative rather than a pipeline."""
    question = _question(Intent.RELATION_HOP, bridge_attribute="lair", attribute="ruled_by")
    pending = [s for s in decompose(question) if s.key == "target"]
    _, query, reason = next_action(question, pending, {"bridged_name": "Marrowwell Abbey"})
    assert "Marrowwell Abbey" in query
    assert "Marrowwell Abbey" in reason


def test_no_pending_sub_questions_means_stop():
    assert next_action(_question(Intent.ATTRIBUTE_LOOKUP), [], {})[0] == "stop"
