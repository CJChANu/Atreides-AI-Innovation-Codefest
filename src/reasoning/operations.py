"""What kind of work a question needs, independent of what it is about.

The planner used to branch on a handful of intents, each recognised by its own
patterns, and anything outside them fell through to full-text search. That works
until a judge asks something in a shape nobody anticipated — which is the normal
case, not the exception.

This module separates *the operation* from *the subject*. "Which of these two is
larger" is one operation whether it is asked about garrisons, casualties or
attunement costs; "how long did it last" is one operation whether the thing is a
war or a reign. A question declares which operations it needs by its wording, and
the planner assembles a plan from the operations it declared.

Two rules keep this honest and keep it general:

* **No operation names an entity.** Every cue here is a question-shape word —
  "how long", "compare", "in order", "which had the most". A rule that mentions a
  specific relic or war is a rule that answers one question and no others.
* **Every operation states what evidence it needs.** That is what lets the loop
  report a specific gap ("no end year recorded for X") instead of a generic
  failure, and what stops an operation being marked done without its inputs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class OperationKind(str, Enum):
    """The families of work the investigator can perform."""

    # Retrieval-shaped
    FACT_LOOKUP = "fact_lookup"
    MULTI_HOP = "multi_hop"
    GRAPH_TRAVERSAL = "graph_traversal"
    ENTITY_TRACE = "entity_trace"
    # Comparison-shaped
    SOURCE_COMPARISON = "source_comparison"
    CONFLICT_DETECTION = "conflict_detection"
    RELIABILITY_RANKING = "reliability_ranking"
    NUMERIC_COMPARISON = "numeric_comparison"
    SORTING = "sorting"
    # Time-shaped
    TIMELINE = "timeline"
    DATE_ORDERING = "date_ordering"
    DATE_DIFFERENCE = "date_difference"
    DURATION = "duration"
    EXISTENCE_CHECK = "existence_check"
    # Arithmetic-shaped
    PERCENTAGE = "percentage"
    RATIO = "ratio"
    TOTAL = "total"
    AVERAGE = "average"
    DIFFERENCE = "difference"
    # Explanation-shaped
    LOCATION_EVENT_LINK = "location_event_link"
    HISTORY_TRACE = "history_trace"
    CAUSE_EFFECT = "cause_effect"
    IMPACT_ANALYSIS = "impact_analysis"


@dataclass(frozen=True)
class OperationSpec:
    """One operation: how a question asks for it, and what it needs to run."""

    kind: OperationKind
    cues: tuple[str, ...]
    needs: tuple[str, ...]
    describes: str
    # Operations that must run first. A duration needs two dates before it can
    # subtract them; a ranking needs competing values before it can rank.
    depends_on: tuple[OperationKind, ...] = ()

    def matches(self, text: str) -> bool:
        return any(re.search(cue, text, re.IGNORECASE) for cue in self.cues)


# The registry. Ordered most-specific first so a question that asks for a
# duration is not merely logged as mentioning dates.
REGISTRY: tuple[OperationSpec, ...] = (
    OperationSpec(
        kind=OperationKind.DURATION,
        cues=(r"\bhow\s+long\b", r"\blast(ed)?\s+(for\s+)?how\b", r"\bduration\s+of\b",
              r"\bfor\s+how\s+many\s+years\b", r"\bhow\s+many\s+years\s+did\b"),
        needs=("start year", "end year"),
        describes="how long something lasted, from its start and end dates",
    ),
    OperationSpec(
        kind=OperationKind.DATE_DIFFERENCE,
        cues=(r"\bhow\s+many\s+years\s+(after|before|between)\b",
              r"\byears?\s+(apart|between)\b", r"\bhow\s+long\s+after\b",
              r"\bhow\s+much\s+(earlier|later)\b"),
        needs=("two dated events",),
        describes="the number of years between two dated events",
    ),
    OperationSpec(
        kind=OperationKind.DATE_ORDERING,
        cues=(r"\bwhich\s+(came|happened|occurred)\s+first\b", r"\bearliest\b",
              r"\b(which|what)\b.{0,40}\bfirst\b", r"\bolder\b", r"\bnewer\b",
              r"\blatest\b", r"\bbefore\s+or\s+after\b", r"\bin\s+(chronological\s+)?order\b",
              r"\bwhich\s+of\s+these\s+.{0,30}\bfirst\b"),
        needs=("a date for each item",),
        describes="the order two or more dated things occurred in",
    ),
    OperationSpec(
        kind=OperationKind.TIMELINE,
        cues=(r"\btimeline\b", r"\bchronolog", r"\bsequence\s+of\s+events\b",
              r"\bwhat\s+happened\s+(to|at)\b.{0,40}\bover\b", r"\bhistory\s+of\b"),
        needs=("every dated event naming the subject",),
        describes="the dated events involving a subject, in order",
    ),
    OperationSpec(
        kind=OperationKind.EXISTENCE_CHECK,
        cues=(r"\bcould\s+.{0,40}\bhave\s+(been|existed)\b", r"\bwas\s+.{0,40}\bpresent\b",
              r"\bexisted?\s+(at|during|when|before|after)\b",
              r"\balready\s+(exist|been\s+forged|been\s+built)\b"),
        needs=("subject origin date", "event date"),
        describes="whether something existed at the time of an event",
        depends_on=(OperationKind.DATE_ORDERING,),
    ),
    OperationSpec(
        kind=OperationKind.PERCENTAGE,
        cues=(r"\bpercent(age)?\b", r"\bproportion\s+of\b", r"\bshare\s+of\b"),
        needs=("numerator", "denominator"),
        describes="one quantity expressed as a percentage of another",
    ),
    OperationSpec(
        kind=OperationKind.RATIO,
        cues=(r"\bratio\b", r"\bhow\s+many\s+times\b", r"\btimes\s+(larger|greater|smaller)\b"),
        needs=("two quantities",),
        describes="one quantity divided by another",
    ),
    OperationSpec(
        kind=OperationKind.DIFFERENCE,
        cues=(r"\bdifference\s+between\b", r"\bhow\s+many\s+(more|fewer|less)\b",
              r"\bhow\s+much\s+(more|less|larger|smaller)\b"),
        needs=("two quantities",),
        describes="the gap between two quantities",
    ),
    OperationSpec(
        kind=OperationKind.TOTAL,
        cues=(r"\bcombined\b", r"\btotal\b", r"\bsum\s+of\b", r"\btogether\b", r"\ball\s+together\b"),
        needs=("every quantity named",),
        describes="the sum of several quantities",
    ),
    OperationSpec(
        kind=OperationKind.AVERAGE,
        cues=(r"\baverage\b", r"\bmean\s+of\b", r"\btypical\b"),
        needs=("every quantity named",),
        describes="the mean of several quantities",
    ),
    OperationSpec(
        kind=OperationKind.SORTING,
        cues=(r"\b(most|least|highest|lowest|largest|smallest|greatest|worst|best|"
              r"fewest|strongest|weakest|longest|shortest|biggest)\b",
              r"\brank(ed)?\b", r"\bin\s+order\s+of\b", r"\btop\s+\d+\b",
              r"\bwhich\s+\w+\s+has\s+the\b"),
        needs=("a value for each candidate",),
        describes="ordering candidates by a value, or picking the extreme",
    ),
    OperationSpec(
        kind=OperationKind.NUMERIC_COMPARISON,
        cues=(r"\b(larger|smaller|bigger|greater|higher|lower|stronger|weaker)\s+than\b",
              r"\bcompare\b", r"\bwhich\s+has\s+(more|fewer|the\s+larger)\b"),
        needs=("a value for each side",),
        describes="which of two quantities is greater",
    ),
    OperationSpec(
        kind=OperationKind.CONFLICT_DETECTION,
        cues=(r"\bdo\s+(the\s+)?sources\s+(disagree|differ|conflict)\b",
              r"\bcontested\b", r"\bdisputed\b", r"\bactually\b", r"\btruly\b",
              r"\breally\b", r"\bdefinitive\b"),
        needs=("two or more values for one attribute",),
        describes="whether sources record different values for the same thing",
    ),
    OperationSpec(
        kind=OperationKind.RELIABILITY_RANKING,
        cues=(r"\bmost\s+(authoritative|reliable|trustworthy)\b",
              r"\bwhich\s+source\s+should\b", r"\bwhich\s+account\s+is\b"),
        needs=("competing values with source classes",),
        describes="which source to prefer when they disagree",
        depends_on=(OperationKind.CONFLICT_DETECTION,),
    ),
    OperationSpec(
        kind=OperationKind.SOURCE_COMPARISON,
        cues=(r"\bwhat\s+do\s+(the\s+)?sources\s+say\b", r"\baccording\s+to\s+(both|each)\b",
              r"\bhow\s+do\s+.{0,30}\bdiffer\b"),
        needs=("the same attribute from more than one source",),
        describes="what each source says about the same thing",
    ),
    OperationSpec(
        kind=OperationKind.CAUSE_EFFECT,
        cues=(r"\bwhy\s+(did|was|were|does)\b", r"\bwhat\s+caused\b", r"\bbecause\s+of\b",
              r"\bled\s+to\b", r"\bresulted?\s+(in|from)\b", r"\breason\s+(for|why)\b"),
        needs=("the event and what the archive records about its cause",),
        describes="what the archive gives as a cause",
    ),
    OperationSpec(
        kind=OperationKind.IMPACT_ANALYSIS,
        cues=(r"\bwhat\s+(was\s+the\s+)?(impact|effect|consequence)\b",
              r"\bhow\s+did\s+.{0,40}\baffect\b", r"\bwhat\s+happened\s+to\b.{0,40}\bafter\b"),
        needs=("the event and the records naming what it affected",),
        describes="what an event is recorded as having affected",
    ),
    OperationSpec(
        kind=OperationKind.HISTORY_TRACE,
        cues=(r"\bhistory\s+of\b", r"\btrace\s+the\b", r"\bwhat\s+became\s+of\b",
              r"\bcustod(y|ians)\b", r"\bchanged\s+hands\b", r"\bpassed\s+(to|from)\b"),
        needs=("every dated record naming the subject",),
        describes="what the archive records about a subject over time",
    ),
    OperationSpec(
        kind=OperationKind.LOCATION_EVENT_LINK,
        cues=(r"\bwhat\s+happened\s+(at|in)\b", r"\bevents?\s+at\b",
              r"\bwhich\s+(wars?|conflicts?|battles?)\s+.{0,30}\b(reached|affected|touched)\b"),
        needs=("dated events naming the place",),
        describes="which events the archive attaches to a place",
    ),
    OperationSpec(
        kind=OperationKind.MULTI_HOP,
        cues=(r"\bof\s+the\s+\w+\s+of\b", r"\bwhose\s+\w+\b.{0,40}\bof\b",
              r"\bthe\s+\w+\s+that\s+\w+\b.{0,30}\bof\b"),
        needs=("a bridge value, then the target attribute on it"),
        describes="a value reached by following one relation into another",
    ),
    OperationSpec(
        kind=OperationKind.ENTITY_TRACE,
        cues=(r"\bwho\s+(wielded|held|commanded|ruled)\b", r"\bsince\s+when\b",
              r"\bwho\s+(has|had)\s+\w+\s+it\b"),
        needs=("records naming the subject and a holder",),
        describes="who has been associated with something, and when",
    ),
)


@dataclass
class DetectedOperation:
    """An operation this question requires, and why we think so."""

    kind: OperationKind
    spec: OperationSpec
    trigger: str

    def to_dict(self) -> dict:
        return {
            "operation": self.kind.value,
            "why": f"the question says {self.trigger!r}",
            "needs": list(self.spec.needs),
            "describes": self.spec.describes,
        }


@dataclass
class OperationPlan:
    """Everything a question asks the investigator to do."""

    operations: list[DetectedOperation] = field(default_factory=list)

    @property
    def kinds(self) -> set[OperationKind]:
        return {operation.kind for operation in self.operations}

    def requires(self, kind: OperationKind) -> bool:
        return kind in self.kinds

    @property
    def is_arithmetic(self) -> bool:
        return bool(self.kinds & {OperationKind.PERCENTAGE, OperationKind.RATIO,
                                  OperationKind.DIFFERENCE, OperationKind.TOTAL,
                                  OperationKind.AVERAGE})

    @property
    def is_temporal(self) -> bool:
        return bool(self.kinds & {OperationKind.DURATION, OperationKind.DATE_DIFFERENCE,
                                  OperationKind.DATE_ORDERING, OperationKind.TIMELINE,
                                  OperationKind.EXISTENCE_CHECK})

    def to_dict(self) -> list[dict]:
        return [operation.to_dict() for operation in self.operations]


def _trigger_for(spec: OperationSpec, text: str) -> str:
    for cue in spec.cues:
        match = re.search(cue, text, re.IGNORECASE)
        if match:
            return match.group(0)
    return ""


def detect(text: str) -> OperationPlan:
    """Which operations this question requires.

    Several may apply at once, and that is usually correct: "how many years
    after the war was the relic forged" is a date difference *and* an existence
    check, and a plan that runs only one of them answers half the question.
    """
    plan = OperationPlan()
    for spec in REGISTRY:
        if spec.matches(text):
            plan.operations.append(
                DetectedOperation(kind=spec.kind, spec=spec, trigger=_trigger_for(spec, text))
            )
    return plan
