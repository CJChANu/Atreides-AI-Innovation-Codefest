"""LLM output may add signal; it may never overrule the archive index."""

from src.orchestration.llm_assist import merge_understanding, verify_extracted_claims
from src.orchestration.state import Intent, Question


class _Analyzer:
    """Stands in for the index: only these names exist in the archive."""

    KNOWN = {"gravemaw wyrm": ("gravemaw_wyrm", "Gravemaw Wyrm"),
             "marrowwell abbey": ("marrowwell_abbey", "Marrowwell Abbey")}

    def match_entities(self, text):
        hit = self.KNOWN.get(text.strip().lower())
        return [hit] if hit else []


def _question(**kwargs):
    kwargs.setdefault("text", "q")
    kwargs.setdefault("intent", Intent.OPEN_QUESTION)
    return Question(**kwargs)


def test_a_hallucinated_entity_is_not_accepted():
    """The decisive guard: a name the archive does not contain never enters state."""
    question = _question()
    merge_understanding(question, {"entities": ["The Fleet of Nowhere"], "relations": []},
                        _Analyzer())
    assert question.entities == []


def test_an_entity_confirmed_in_the_index_is_added():
    question = _question()
    outcome = merge_understanding(question, {"entities": ["Gravemaw Wyrm"], "relations": []},
                                  _Analyzer())
    assert question.entities == [("gravemaw_wyrm", "Gravemaw Wyrm")]
    assert outcome.used


def test_a_rule_matched_attribute_is_not_overruled():
    question = _question(attribute="lair")
    merge_understanding(question, {"entities": [], "relations": ["ruled_by"]}, _Analyzer())
    assert question.attribute == "lair"


def test_the_llm_fills_an_attribute_only_when_rules_found_none():
    question = _question()
    merge_understanding(question, {"entities": [], "relations": ["ruled_by"]}, _Analyzer())
    assert question.attribute == "ruled_by"


def test_a_rule_matched_intent_is_never_downgraded():
    question = _question(intent=Intent.CONFLICT_RESOLUTION, attribute="founded")
    merge_understanding(question, {"entities": [], "relations": [], "intent": "open_question"},
                        _Analyzer())
    assert question.intent is Intent.CONFLICT_RESOLUTION


def test_no_llm_output_changes_nothing():
    question = _question(attribute="lair")
    assert not merge_understanding(question, None, _Analyzer()).used


# -- claim verification ----------------------------------------------------

EVIDENCE = {"chunk-1": "Marrowwell Abbey is ruled by The Bleeding Crown, per the rolls."}


def test_a_claim_citing_an_unknown_evidence_id_is_rejected():
    kept, rejected = verify_extracted_claims(
        [{"subject": "Marrowwell Abbey", "predicate": "ruled_by",
          "value": "The Bleeding Crown", "evidence_id": "chunk-999"}], EVIDENCE)
    assert kept == []
    assert "unknown evidence id" in rejected[0]


def test_a_claim_the_cited_passage_does_not_make_is_rejected():
    """The failure that matters: plausible statement, wrong source."""
    kept, rejected = verify_extracted_claims(
        [{"subject": "Marrowwell Abbey", "predicate": "ruled_by",
          "value": "House Morvain", "evidence_id": "chunk-1"}], EVIDENCE)
    assert kept == []
    assert "does not appear in the cited passage" in rejected[0]


def test_a_supported_claim_is_kept():
    kept, rejected = verify_extracted_claims(
        [{"subject": "Marrowwell Abbey", "predicate": "ruled_by",
          "value": "The Bleeding Crown", "evidence_id": "chunk-1"}], EVIDENCE)
    assert len(kept) == 1 and rejected == []
