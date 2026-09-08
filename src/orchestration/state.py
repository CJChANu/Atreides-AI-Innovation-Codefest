"""Typed state for the investigation.

Everything the loop learns lives here, and everything here is serialisable. The
trace a user sees and the trace we debug from are the same object — there is no
separate "explanation" that could drift from what actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.graph.fact_query import FactRow


class Intent(str, Enum):
    """What kind of work the question requires, not what it is about."""

    ATTRIBUTE_LOOKUP = "attribute_lookup"        # "what is X's threat rating"
    CONFLICT_RESOLUTION = "conflict_resolution"  # "in which year was X *actually* forged"
    RELATION_HOP = "relation_hop"                # "who rules the lair of X"
    INVERSE_HOP = "inverse_hop"                  # "which faction has X as a member"
    CALCULATION = "calculation"                  # "what percentage of X's a is Y's b"
    MULTI_FACT = "multi_fact"                    # "where and when was X forged, and where is it housed"
    OPEN_QUESTION = "open_question"              # anything else; falls back to text search


class StopReason(str, Enum):
    ALL_SUPPORTED = "all required sub-questions are supported"
    NO_NEW_EVIDENCE = "no new evidence for two consecutive iterations"
    INSUFFICIENT_EVIDENCE = "the archive holds no evidence for the remaining sub-questions"
    ITERATION_BUDGET = "iteration budget exhausted"
    QUERY_BUDGET = "query budget exhausted"
    TIME_BUDGET = "time budget exhausted"
    NO_ENTITY = "no known entity could be identified in the question"


class ClaimType(str, Enum):
    DIRECT = "direct"            # explicitly stated in a source
    INFERRED = "inferred"        # derived from a documented chain of stated facts
    CONFLICTING = "conflicting"  # sources disagree
    UNSUPPORTED = "unsupported"  # proposed but not grounded; excluded from the answer


@dataclass
class SubQuestion:
    """A unit of the investigation with an explicit completion condition.

    Without the completion condition the loop cannot tell "answered" from
    "attempted", and would stop as soon as it found *something*.
    """

    key: str
    text: str
    completion: str
    satisfied: bool = False
    # Tried and found nothing. Distinct from `satisfied`: it stops the loop
    # re-issuing a query that already failed, without ever letting an empty
    # result masquerade as an answer.
    attempted: bool = False
    evidence: list[FactRow] = field(default_factory=list)
    note: str = ""

    def satisfy(self, evidence: list[FactRow], note: str = "") -> None:
        self.evidence = evidence
        self.satisfied = True
        self.attempted = True
        self.note = note

    def fail(self, note: str = "") -> None:
        """Record that this sub-question was investigated and not answered."""
        self.attempted = True
        self.satisfied = False
        self.note = note


@dataclass
class Iteration:
    """One pass of the loop, recorded for the audit trail."""

    number: int
    sub_question: str
    action: str
    query: str
    retrieval_modes: list[str] = field(default_factory=list)
    retrieved_chunks: list[str] = field(default_factory=list)
    new_entities: list[str] = field(default_factory=list)
    new_claims: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    next_action: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.number,
            "sub_question": self.sub_question,
            "action": self.action,
            "query": self.query,
            "retrieval_modes": self.retrieval_modes,
            "retrieved_chunks": self.retrieved_chunks[:10],
            "new_entities": self.new_entities,
            "new_claims": self.new_claims,
            "unresolved": self.unresolved,
            "next_action": self.next_action,
            "reason": self.reason,
        }


@dataclass
class Claim:
    """An assertion the answer may make, with its grounding."""

    text: str
    claim_type: ClaimType
    confidence: float
    evidence: list[FactRow] = field(default_factory=list)
    alternatives: list[tuple[str, list[FactRow]]] = field(default_factory=list)
    # Which sub-question produced this claim, so the renderer can pick the
    # answer-bearing one without relying on list positions lining up.
    step_key: str = ""

    def to_dict(self, title_of) -> dict[str, Any]:
        return {
            "text": self.text,
            "claim_type": self.claim_type.value,
            "confidence": round(self.confidence, 3),
            "evidence": [
                {"document_id": e.document_id, "document": title_of(e.document_id),
                 "page": e.page, "chunk_id": e.chunk_id, "source_class": e.source_class}
                for e in self.evidence
            ],
        }


@dataclass
class Operand:
    """One (subject, attribute) pair the question requires a value for.

    Every question that asks for more than one thing — a calculation over two
    quantities, a comparison of two creatures, a four-part question about one
    relic — becomes a list of these. Keeping them as first-class objects, rather
    than reusing the single `attribute` slot, is what lets the loop notice that
    it has one value and not the other instead of quietly answering with the
    half it found.

    `must_be_numeric` separates the two uses: arithmetic needs a number and must
    reject "None recorded", while a comparison is perfectly well served by a
    place name.
    """

    subject_id: str
    subject_name: str
    attribute: str
    must_be_numeric: bool = False
    # Filled in once the fact store yields a value for this pair.
    value: float | None = None
    value_text: str = ""
    evidence: list[FactRow] = field(default_factory=list)
    note: str = ""

    @property
    def grounded(self) -> bool:
        """True when this requirement has been met by real evidence.

        Arithmetic needs a number and nothing else will do; a comparison or a
        multi-part lookup is satisfied by whatever the archive recorded, which
        is usually a place or a name.
        """
        return self.value is not None if self.must_be_numeric else bool(self.value_text)

    def describe(self) -> str:
        return f"{self.subject_name}'s {self.attribute.replace('_', ' ')}"


@dataclass
class Calculation:
    """What arithmetic the question asks for, and over which operands.

    `kind` names the formula; `numerator` and `denominator` index into the
    question's operand list for the two-operand forms, while `total` and
    `average` simply use every operand.
    """

    kind: str                       # percentage | ratio | difference | total | average
    numerator: int = 0
    denominator: int = 1

    @property
    def is_pairwise(self) -> bool:
        return self.kind in {"percentage", "ratio", "difference"}

    def formula(self, operands: list[Operand]) -> str:
        """The arithmetic written out, for the trace."""
        names = [operand.describe() for operand in operands]
        if self.kind == "percentage":
            return f"({names[self.numerator]} ÷ {names[self.denominator]}) × 100"
        if self.kind == "ratio":
            return f"{names[self.numerator]} ÷ {names[self.denominator]}"
        if self.kind == "difference":
            return f"{names[self.numerator]} − {names[self.denominator]}"
        if self.kind == "average":
            return f"mean of {', '.join(names)}"
        return " + ".join(names)

    def apply(self, values: list[float]) -> float | None:
        try:
            if self.kind == "percentage":
                return values[self.numerator] / values[self.denominator] * 100.0
            if self.kind == "ratio":
                return values[self.numerator] / values[self.denominator]
            if self.kind == "difference":
                return values[self.numerator] - values[self.denominator]
            if self.kind == "average":
                return sum(values) / len(values)
            return sum(values)
        except (IndexError, ZeroDivisionError):
            return None


@dataclass
class Question:
    """The structured form of the user's question."""

    text: str
    intent: Intent
    entities: list[tuple[str, str]] = field(default_factory=list)  # (subject_id, name)
    attribute: str | None = None
    bridge_attribute: str | None = None   # the first hop of a two-hop question
    answer_type: str = "value"
    expects_conflict: bool = False
    filter_terms: list[str] = field(default_factory=list)
    # Set only for Intent.CALCULATION.
    operands: list[Operand] = field(default_factory=list)
    calculation: Calculation | None = None

    @property
    def primary(self) -> tuple[str, str] | None:
        return self.entities[0] if self.entities else None

    @property
    def ungrounded_operands(self) -> list[Operand]:
        return [operand for operand in self.operands if not operand.grounded]


@dataclass
class Investigation:
    """The complete record of one question being answered."""

    question: Question
    sub_questions: list[SubQuestion] = field(default_factory=list)
    iterations: list[Iteration] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    evidence_chain: list[str] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    # Set by whichever step actually produced the answer. A forward lookup answers
    # with the fact's value; a reverse lookup answers with its subject. Recording
    # it explicitly beats re-deriving it from the rendered evidence chain.
    answer_value: str = ""
    # For a calculation: the formula, the operands it consumed, and the result.
    # Recorded rather than re-derived so the arithmetic in the answer and the
    # arithmetic in the trace cannot disagree.
    computation: dict[str, Any] = field(default_factory=dict)
    # Which mode actually ran, and what the LLM contributed. Both surface in the
    # trace so a viewer can tell an LLM-assisted run from a deterministic one.
    ai_mode: str = "deterministic"
    assist_notes: list[str] = field(default_factory=list)
    stop_reason: StopReason = StopReason.ITERATION_BUDGET
    queries_issued: int = 0
    graph_expansions: int = 0
    elapsed_seconds: float = 0.0

    @property
    def unresolved(self) -> list[SubQuestion]:
        return [s for s in self.sub_questions if not s.satisfied]

    @property
    def actionable(self) -> list[SubQuestion]:
        """Sub-questions still worth spending a query on."""
        return [s for s in self.sub_questions if not s.satisfied and not s.attempted]

    def to_dict(self, title_of) -> dict[str, Any]:
        return {
            "question": self.question.text,
            "answer": self.answer_value,
            "intent": self.question.intent.value,
            "entities": [name for _, name in self.question.entities],
            "sub_questions": [
                {"text": s.text, "completion": s.completion,
                 "satisfied": s.satisfied, "attempted": s.attempted, "note": s.note}
                for s in self.sub_questions
            ],
            "claims": [c.to_dict(title_of) for c in self.claims],
            "evidence_chain": self.evidence_chain,
            "conflicts": self.conflicts,
            "calculation": self.computation,
            "investigation": {
                "iterations": len(self.iterations),
                "queries": self.queries_issued,
                "graph_expansions": self.graph_expansions,
                "elapsed_seconds": round(self.elapsed_seconds, 3),
                "stop_reason": self.stop_reason.value,
                "ai_mode": self.ai_mode,
                "assist_notes": self.assist_notes,
            },
            "trace": [i.to_dict() for i in self.iterations],
        }
