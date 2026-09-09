"""The bounded investigation loop — the 1C core.

A human expert reads what they find, learns from it, notices what is still
missing, and goes looking again. This is that, as a state machine with hard
limits:

    understand → decompose → [ search → extract → expand → assess → re-plan ]* →
    verify → answer

Three properties matter more than cleverness here:

* **It always terminates**, and it always knows *why* it stopped. A budget stop is
  reported as partial, never as certainty.
* **Each query is a function of the previous results.** The `target` step searches
  the subject that the `bridge` step discovered. Remove that dependency and this
  is a pipeline, not an investigation.
* **Every step is recorded.** The trace a user reads is the same object the loop
  ran on, so it cannot drift from what actually happened.
"""

from __future__ import annotations

import re
import time

from src.common.config import InvestigationBudget
from src.common.provenance import reliability_of
from src.graph.fact_query import AttributeView, FactQuery, FactRow
from src.graph.fact_query import _to_fact as _fact_row
from src.graph.facts import numeric_value
from src.graph.plate_facts import is_figure_attribute, routes_to_figure
from src.graph.prose_facts import extract as prose_extract
from src.graph.prose_facts import search_queries as prose_queries
from src.graph.query import GraphQuery
from src.graph.timeline import Timeline
from src.reasoning.temporal import (
    CUSTODY_ATTRIBUTES,
    ORIGIN_ATTRIBUTES,
    Span,
    TemporalVerdict,
    check_anachronism,
    describe_ordering,
    order_by_year,
    parse_year,
)
from src.orchestration.planner import decompose, next_action
from src.orchestration.state import (
    Intent,
    Investigation,
    Iteration,
    Operand,
    Question,
    StopReason,
    SubQuestion,
)
from src.orchestration.understanding import QuestionAnalyzer
from src.orchestration.llm_assist import merge_understanding, verify_extracted_claims
from src.retrieval.figures import FigureIndex
from src.retrieval.hybrid import HybridRetriever
from src.retrieval.keyword import KeywordIndex
from src.storage.db import ArchiveStore
from src.verification.claims import build_claims
from src.verification.conflicts import describe_conflict

# How many text hits to keep per search. Enough to show the evidence, small
# enough that a trace stays readable.
TEXT_HITS = 6

# Prose fallback searches wider than a normal lookup. The sentence stating a
# value is often in a document *about something else* — the Aegis' forging year
# is item two of a contract concerning a different relic — so it ranks below the
# subject's own pages and is missed at the usual depth.
PROSE_HITS = 12

# "Least", "smallest", "fewest" invert a superlative. Without this, a question
# asking which conflict was *least* costly is answered with the most costly one.
_LEAST = re.compile(r"\b(least|lowest|smallest|fewest|weakest|shortest)\b", re.IGNORECASE)

# Relations the archive records from one side only. Reading the stored row from
# the other end is the same assertion, so a lookup may fall back to the inverse.
INVERSE_ATTRIBUTES = {
    "victor": "victor_of",
    "victor_of": "victor",
    "member_of": "has_member",
    "has_member": "member_of",
    "seat": "seat_of",
    "seat_of": "seat",
}


def _inverse_of(attribute: str) -> str:
    return INVERSE_ATTRIBUTES.get(attribute, attribute)


# Values that are the archive explicitly declining to state something. Treating
# these as answers is how a system ends up confidently reporting "None recorded"
# as an artifact's attunement cost — when the number is printed on a plate.
NOT_RECORDED = (
    "none recorded", "not recorded", "no year is stated", "not established",
    "unknown", "unrecorded",
)


def _is_non_value(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in NOT_RECORDED)


def _format_result(kind: str, result: float) -> str:
    """Render a computed number at a precision the inputs actually justify.

    The operands are whole numbers read off tables and plates, so a percentage
    is quoted to two decimals and a count to none. Printing more digits than the
    inputs support would dress an estimate up as a measurement.
    """
    if kind == "percentage":
        return f"{result:.2f}%"
    if kind == "ratio":
        return f"{result:.3f}".rstrip("0").rstrip(".")
    if abs(result - round(result)) < 1e-9:
        return f"{round(result):,}"
    return f"{result:,.2f}"


class Investigator:
    def __init__(self, store: ArchiveStore, budget: InvestigationBudget, *,
                 gateway=None, retriever: HybridRetriever | None = None,
                 vision=None) -> None:
        self.store = store
        self.budget = budget
        self.analyzer = QuestionAnalyzer(store)
        self.facts = FactQuery(store)
        self.graph = GraphQuery(store)
        self.keyword = KeywordIndex(store)
        self.figures = FigureIndex(store)
        self.timeline = Timeline(store)
        # Both optional. Absent, the loop is exactly the deterministic system it
        # was before — which is the fallback mode, not a degraded special case.
        self.gateway = gateway
        self.retriever = retriever
        # Optional. Absent, figures are reported as unreadable rather than guessed.
        self.vision = vision

    @property
    def llm_available(self) -> bool:
        return bool(self.gateway and self.gateway.available)

    def _text_search(self, query: str, entities: list[str] | None = None, limit: int = TEXT_HITS):
        """Retrieve passages through the hybrid retriever when it is wired in."""
        if self.retriever is not None:
            return self.retriever.search(query, limit=limit, entities=entities)
        return self.keyword.search(query, limit=limit)

    def investigate(self, text: str) -> Investigation:
        started = time.perf_counter()
        question = self.analyzer.analyze(text)

        # LLM assistance is additive: it may fill gaps the rules left, never
        # overrule an entity that was matched against the archive index.
        if self.llm_available:
            outcome = merge_understanding(
                question, self.gateway.understand_question(text), self.analyzer
            )
            state_notes = outcome.notes
        else:
            state_notes = []
            if self.gateway is not None:
                self.gateway.note_fallback("understanding: deterministic parser used")

        self._orient_hop(question)
        state = Investigation(question=question, sub_questions=decompose(question))
        state.assist_notes = state_notes
        state.ai_mode = "llm_assisted" if self.llm_available else "deterministic"

        # A superlative legitimately names no entity — "which conflict had the
        # most casualties" gets its candidates from the archive, not the question
        # — so it must not be turned away by the no-entity guard.
        needs_entity = question.intent not in {Intent.INVERSE_HOP, Intent.ANALYSIS}
        if not question.entities and needs_entity:
            # Nothing in the question matches anything we indexed. Say so rather
            # than running six iterations that cannot succeed.
            self._text_fallback(state, question.text)
            state.stop_reason = StopReason.NO_ENTITY
            return self._finish(state, started)

        learned: dict = {}
        stale_rounds = 0

        while True:
            stop = self._budget_stop(state, started)
            if stop is not None:
                state.stop_reason = stop
                break

            pending = state.actionable
            if not pending:
                # Nothing left worth querying. Whether that is success or an
                # honest dead end depends on what is still unsatisfied.
                state.stop_reason = (StopReason.INSUFFICIENT_EVIDENCE
                                     if state.unresolved else StopReason.ALL_SUPPORTED)
                break

            action, query, reason = next_action(question, pending, learned)
            if action == "stop":
                state.stop_reason = StopReason.ALL_SUPPORTED
                break

            # A conflict step reads values the loop has already gathered; it
            # issues no query. When nothing competes there is nothing for it to
            # do, and spending an iteration and a query on it both pads the trace
            # and eats budget that a later step may need. Settle it in place.
            if self._settle_trivial_conflict(action, pending[0], learned):
                continue

            iteration = Iteration(number=len(state.iterations) + 1,
                                  sub_question=pending[0].text, action=action,
                                  query=query, reason=reason)
            state.queries_issued += 1

            progressed = self._run_action(action, question, pending[0], state,
                                          iteration, learned)

            iteration.unresolved = [s.text for s in state.unresolved]
            iteration.next_action = (
                next_action(question, state.actionable, learned)[0]
                if state.actionable else "verify"
            )
            state.iterations.append(iteration)

            # A round that produced no new evidence is the honest signal that the
            # archive has no more to give on this question — but only once every
            # *required* fact has actually been looked for. A question that names
            # four things and stalls on the first must still try the other three:
            # stopping there reports "no new evidence" about a search that never
            # happened.
            stale_rounds = 0 if progressed else stale_rounds + 1
            if (stale_rounds >= self.budget.stale_rounds_before_stop
                    and not self._required_work_remains(state)):
                state.stop_reason = StopReason.NO_NEW_EVIDENCE
                break

        return self._finish(state, started)

    @staticmethod
    def _required_work_remains(state: Investigation) -> bool:
        """True while a required fact has not yet been searched for.

        Only the operand steps count. A conflict check or an assembly step has
        nothing of its own to find — they read what the lookups gathered — so
        they must never keep an exhausted investigation alive.
        """
        return any(step.key.startswith("operand:") and not step.attempted
                   for step in state.sub_questions)

    @staticmethod
    def _settle_trivial_conflict(action: str, step: SubQuestion, learned: dict) -> bool:
        """Close a conflict step that has nothing to compare, without a query.

        Returns True when the step was settled here. The sub-question is still
        marked and still carries a note, so the trace records that the check
        happened and what it found — it just does not consume an iteration to
        re-read values already in hand.
        """
        if action not in {"conflict_check", "resolve_conflict"}:
            return False
        views: list[AttributeView] = learned.get("views", [])
        if any(view.is_conflicting for view in views):
            return False

        if action == "conflict_check":
            step.satisfy([], "no competing values recorded for any value read"
                             if views else "no values were read, so nothing could conflict")
            return True

        # Nothing to rank. Asking for "the *true* threat rating" when only one
        # rating is recorded is answered by that rating — the question presumed a
        # disagreement the archive does not have. Failing the step instead marked
        # the whole investigation unresolved and reported a correct answer as
        # partial, which is the opposite of what the evidence supports.
        if not views:
            step.fail("no values were found to rank")
            return True

        _, rows = views[0].best()
        step.satisfy(rows, f"only one value is recorded, so it stands without "
                           f"ranking: '{rows[0].value_text}' "
                           f"({rows[0].source_class})")
        return True

    def _orient_hop(self, question: Question) -> None:
        """Decide which of the two relations in a hop question comes first.

        "the faction that won the War of Drowned Light" and "the accord won by
        Ederon Fellgard's faction" use the same two relations in opposite orders.
        Rather than guess from grammar, we ask the data: whichever relation the
        named subject actually records is the first hop.
        """
        if question.intent is not Intent.RELATION_HOP or question.primary is None:
            return
        subject_id = question.primary[0]
        bridge, target = question.bridge_attribute, question.attribute
        if not bridge or not target:
            return

        recorded = set(self.facts.attributes_of(subject_id))
        bridge_ok = bridge in recorded or _inverse_of(bridge) in recorded
        target_ok = target in recorded or _inverse_of(target) in recorded
        if target_ok and not bridge_ok:
            question.bridge_attribute, question.attribute = target, bridge

    # -- actions ------------------------------------------------------------

    def _run_action(self, action: str, question: Question, step: SubQuestion,
                    state: Investigation, iteration: Iteration, learned: dict) -> bool:
        handler = {
            "fact_scan": self._act_fact_scan,
            "fact_lookup": self._act_fact_lookup,
            "operand_lookup": self._act_operand_lookup,
            "origin_lookup": self._act_origin_lookup,
            "event_scan": self._act_event_scan,
            "relation_check": self._act_relation_check,
            "temporal_compare": self._act_temporal_compare,
            "assemble": self._act_assemble,
            "aggregate_scan": self._act_aggregate_scan,
            "analyse": self._act_analyse,
            "compute": self._act_compute,
            "report_gap": self._act_report_gap,
            "inverse_lookup": self._act_inverse_lookup,
            "conflict_check": self._act_conflict_check,
            "resolve_conflict": self._act_resolve_conflict,
            "text_search": self._act_text_search,
        }.get(action, self._act_text_search)
        return handler(question, step, state, iteration, learned)

    def _act_operand_lookup(self, question, step, state, iteration, learned) -> bool:
        """Read one operand of a calculation, and record whether it is grounded.

        Deliberately strict: a calculation needs a *number*, so a value that is
        present but not numeric ("None recorded") leaves the operand ungrounded
        rather than being carried into the arithmetic.
        """
        index = int(step.key.split(":", 1)[1])
        operand = question.operands[index]
        iteration.retrieval_modes = ["facts"]

        view = self.facts.lookup(operand.subject_id, operand.attribute)
        if view is None:
            # No table holds it. Before giving up, read the prose — the archive
            # states some values only in a sentence, and a source that has been
            # retrieved but not read is not a source that failed.
            #
            # No plate fallback here on purpose: values printed or drawn on
            # plates are already lifted into the fact store at build time, and a
            # step that "succeeded" by naming a plate it could not read would
            # leave the operand ungrounded while looking satisfied — exactly the
            # confusion the operand split exists to remove.
            if self._try_prose(operand, step, state, iteration):
                return True
            operand.note = f"no {operand.attribute.replace('_', ' ')} recorded"
            step.fail(operand.note)
            iteration.new_claims = [f"{operand.describe()}: nothing recorded"]
            return False

        _, rows = view.best()
        display = rows[0].value_text
        number = next((row.value_number for row in rows if row.value_number is not None), None)

        if _is_non_value(display):
            # The source explicitly declines to state this. It is not an answer,
            # whether or not the requirement wanted a number.
            operand.note = f"the archive records '{display}'"
            step.fail(operand.note)
            iteration.new_claims = [f"{operand.describe()}: '{display}'"]
            return False

        if operand.must_be_numeric and number is None:
            operand.note = (f"the archive records '{display}' for "
                            f"{operand.attribute.replace('_', ' ')}, which is not a number")
            step.fail(operand.note)
            iteration.new_claims = [f"{operand.describe()}: '{display}' is not numeric"]
            return False

        operand.value = number
        operand.value_text = display
        operand.evidence = rows
        learned.setdefault("views", []).append(view)
        iteration.new_claims = [f"{operand.describe()} = {display}"]
        state.evidence_chain.append(f"{operand.subject_name} — "
                                    f"{operand.attribute.replace('_', ' ')}: {display}")
        step.satisfy(rows, f"{operand.attribute} = {display}")
        return True

    # -- temporal reasoning -------------------------------------------------

    def _act_origin_lookup(self, question, step, state, iteration, learned) -> bool:
        """Establish when the subject came into existence.

        Which attribute carries that depends on what the subject *is* — a relic
        is forged, a hold is founded, a person is born — so rather than guess
        from an entity type we do not reliably have, try each in turn and record
        which one answered. The prose fallback applies here too: the Aegis' only
        recorded forging year is a sentence in a contract about another relic.
        """
        primary = question.primary
        if primary is None:
            step.fail("no subject named")
            return False
        subject_id, name = primary
        iteration.retrieval_modes = ["facts"]

        origin = self.timeline.origin_of(subject_id)
        if origin is not None:
            learned["origin_year"] = origin.year
            learned["origin_attribute"] = origin.attribute
            learned["origin_rows"] = [origin.row]
            iteration.new_claims = [
                f"{name} · {origin.attribute.replace('_', ' ')} = {origin.year} AS"]
            state.evidence_chain.append(
                f"{name} — {origin.attribute.replace('_', ' ')}: {origin.year} AS")
            step.satisfy([origin.row], f"origin year {origin.year} AS")
            return True

        # No table records it. Try each origin attribute through the prose reader.
        for attribute in ORIGIN_ATTRIBUTES:
            operand = Operand(subject_id=subject_id, subject_name=name, attribute=attribute)
            if self._try_prose(operand, step, state, iteration):
                year = parse_year(operand.value_text)
                if year is None:
                    continue
                learned["origin_year"] = year
                learned["origin_attribute"] = attribute
                learned["origin_rows"] = operand.evidence
                return True

        step.fail(f"no recorded origin year for {name}")
        iteration.new_claims.append(f"no origin year recorded for {name}")
        return False

    def _act_event_scan(self, question, step, state, iteration, learned) -> bool:
        """Find the dated events naming the place, from the events' own records."""
        if len(question.entities) < 2:
            step.fail("no place named")
            return False
        place = question.entities[1][1]
        iteration.retrieval_modes = ["facts", "graph"]

        events = self.timeline.events_at(place)
        if not events:
            step.fail(f"no dated events recorded at {place}")
            return False

        learned["events"] = events
        iteration.new_claims = [event.describe() for event in events]
        for event in events:
            state.evidence_chain.append(
                f"{event.subject_name} — {event.attribute.replace('_', ' ')}: "
                f"{event.place} in {event.year} AS")
        step.satisfy([event.row for event in events],
                     f"{len(events)} dated event(s) at {place}")
        return True

    def _act_relation_check(self, question, step, state, iteration, learned) -> bool:
        """What the archive actually records linking the subject to the place.

        This is the half of the answer that is not arithmetic. "Housed in
        Gloamreach" is a statement about where the relic is *now*; reading it as
        evidence of where it was during an earlier event is the specific mistake
        the question is asking about, so the recorded relation has to be named.
        """
        primary = question.primary
        if primary is None or len(question.entities) < 2:
            step.fail("nothing to relate")
            return False
        subject_id, name = primary
        place = question.entities[1][1]
        iteration.retrieval_modes = ["facts"]

        rows = self.store.connection.execute(
            "SELECT * FROM facts WHERE subject_id = ? AND value_text LIKE ?",
            (subject_id, f"%{place}%"),
        ).fetchall()
        if not rows:
            step.satisfy([], f"the archive records no direct link between {name} and {place}")
            return True

        found = [_fact_row(row) for row in rows]
        custody = [row for row in found if row.attribute in CUSTODY_ATTRIBUTES]
        learned["relation_rows"] = found
        learned["custody_rows"] = custody
        for row in found:
            iteration.new_claims.append(
                f"{name} · {row.attribute.replace('_', ' ')} = {row.value_text}")
            state.evidence_chain.append(
                f"{name} — {row.attribute.replace('_', ' ')}: {row.value_text}")
        step.satisfy(found, f"{len(found)} recorded link(s) to {place}")
        return True

    def _act_temporal_compare(self, question, step, state, iteration, learned) -> bool:
        """Compare the origin year against each event year, and say what follows."""
        iteration.retrieval_modes = ["arithmetic"]
        year = learned.get("origin_year")
        events = learned.get("events") or []
        name = question.primary[1] if question.primary else "the subject"
        place = question.entities[1][1] if len(question.entities) > 1 else "the place"

        if year is None or not events:
            missing = "an origin year" if year is None else f"any dated event at {place}"
            state.answer_value = (
                f"Not established. Answering this needs both {name}'s origin year and "
                f"the dated events at {place}; the archive does not record {missing}.")
            step.fail(f"cannot compare: missing {missing}")
            return False

        verdict = TemporalVerdict()
        attribute = learned.get("origin_attribute", "origin")
        for event in events:
            verdict.findings.append(check_anachronism(
                subject=name, subject_attribute=attribute, subject_year=year,
                event=event.subject_name, event_place=event.place, event_year=event.year,
            ))

        custody = learned.get("custody_rows") or []
        if custody:
            row = custody[0]
            verdict.custody_note = (
                f"The archive records {name} as {row.attribute.replace('_', ' ')} "
                f"{row.value_text}, which establishes where it is kept, not where it "
                f"was during an earlier event.")

        state.answer_value = verdict.summarise()
        state.computation = {
            "kind": "temporal",
            "formula": f"{name} {attribute.replace('_', ' ')} {year} AS vs events at {place}",
            "operands": [
                {"subject": name, "attribute": attribute, "value": year,
                 "value_text": f"{year} AS", "grounded": True},
                *[{"subject": event.subject_name, "attribute": event.attribute,
                   "value": event.year, "value_text": f"{event.place} in {event.year} AS",
                   "grounded": True} for event in events],
            ],
            "result": None,
            "result_text": state.answer_value,
            "findings": [
                {"event": finding.event, "event_year": finding.event_year,
                 "subject_year": finding.subject_year, "gap_years": finding.gap,
                 "rules_out_presence": finding.impossible}
                for finding in verdict.findings
            ],
        }
        iteration.new_claims = [finding.explain() for finding in verdict.findings]
        state.evidence_chain.append(f"Compared: {state.computation['formula']}")

        evidence = list(learned.get("origin_rows") or [])
        evidence += [event.row for event in events]
        step.satisfy(evidence, verdict.summarise()[:120])
        return True

    def _try_prose(self, operand, step, state, iteration) -> bool:
        """Look for the value stated in a sentence, when no table records it.

        Retrieval already finds the right passage for these; what was missing was
        reading it. The match is pinned to the sentence it came from, so the
        claim cites a real chunk and a reader can check the wording.
        """
        iteration.retrieval_modes.append("hybrid" if self.retriever else "keyword")
        for query in prose_queries(operand.subject_name, operand.attribute):
            hits = self._text_search(query, entities=[operand.subject_name],
                                     limit=PROSE_HITS)
            state.queries_issued += 1
            iteration.retrieved_chunks.extend(hit.chunk_id for hit in hits)
            for hit in hits:
                found = prose_extract(hit.content, operand.subject_name, operand.attribute)
                if found is None:
                    continue
                row = self._row_from_hit(hit, operand, found.value_text)
                operand.value = numeric_value(found.value_text)
                operand.value_text = found.value_text
                operand.evidence = [row]
                operand.note = "read from prose; no table records it"
                iteration.new_claims.append(
                    f"{operand.describe()} = {found.value_text} — stated in prose, not a "
                    f"table: “{found.quote()}”"
                )
                state.evidence_chain.append(
                    f"{operand.subject_name} — {operand.attribute.replace('_', ' ')}: "
                    f"{found.value_text}"
                )
                step.satisfy([row], f"{operand.attribute} = {found.value_text} (from prose)")
                return True
        return False

    def _row_from_hit(self, hit, operand, value_text: str) -> FactRow:
        """A citable fact row for a value read out of a retrieved passage."""
        return FactRow(
            subject_id=operand.subject_id, subject_name=operand.subject_name,
            attribute=operand.attribute, value_text=value_text,
            value_key=value_text.lower(), value_number=numeric_value(value_text),
            chunk_id=hit.chunk_id, document_id=hit.document_id,
            page=getattr(hit, "page", None), source_class=hit.source_class,
            reliability=reliability_of(hit.source_class),
        )

    def _act_aggregate_scan(self, question, step, state, iteration, learned) -> bool:
        """Gather every recorded value of one attribute, across the whole archive.

        A superlative names no subject — "which conflict had the most casualties"
        — so the candidates cannot come from the question. They come from the
        fact store, which is exactly the navigational use it is for: it tells us
        which subjects to look at, and each row still carries the chunk that
        justifies it.
        """
        attribute = question.analysis.split(":", 1)[1] if ":" in question.analysis else ""
        if not attribute:
            step.fail("no attribute to aggregate")
            return False
        iteration.retrieval_modes = ["facts"]

        rows = self.store.connection.execute(
            """SELECT * FROM facts
               WHERE attribute = ? AND value_number IS NOT NULL
               ORDER BY value_number DESC""",
            (attribute,),
        ).fetchall()
        if not rows:
            step.fail(f"no subject records a {attribute.replace('_', ' ')}")
            return False

        # One row per subject: the most reliable value each subject records.
        best: dict[str, FactRow] = {}
        for row in rows:
            fact = _fact_row(row)
            held = best.get(fact.subject_id)
            if held is None or fact.reliability > held.reliability:
                best[fact.subject_id] = fact
        candidates = sorted(best.values(), key=lambda f: f.value_number or 0, reverse=True)

        learned["candidates"] = candidates
        iteration.new_claims = [
            f"{fact.subject_name} · {attribute} = {fact.value_text}"
            for fact in candidates[:5]
        ]
        step.satisfy(candidates[:5],
                     f"{len(candidates)} subject(s) record a {attribute.replace('_', ' ')}")
        return True

    def _act_analyse(self, question, step, state, iteration, learned) -> bool:
        """Apply the question's operation to the values gathered for it."""
        iteration.retrieval_modes = ["arithmetic"]
        kind = question.analysis

        if kind.startswith("superlative:"):
            return self._analyse_superlative(question, step, state, iteration, learned)
        if kind == "duration":
            return self._analyse_duration(question, step, state, iteration)
        if kind == "ordering":
            return self._analyse_ordering(question, step, state, iteration)
        if kind == "comparison":
            return self._analyse_comparison(question, step, state, iteration)
        step.fail(f"no handler for analysis {kind!r}")
        return False

    def _analyse_superlative(self, question, step, state, iteration, learned) -> bool:
        attribute = question.analysis.split(":", 1)[1]
        candidates = learned.get("candidates") or []
        if not candidates:
            step.fail("nothing to rank")
            return False
        wants_least = bool(_LEAST.search(question.text))
        ordered = sorted(candidates, key=lambda f: f.value_number or 0,
                         reverse=not wants_least)
        winner = ordered[0]
        ranked = ", ".join(f"{f.subject_name} {f.value_text}" for f in ordered[:5])
        state.answer_value = f"{winner.subject_name} ({winner.value_text})"
        state.computation = {
            "kind": "superlative", "attribute": attribute,
            "formula": f"{'lowest' if wants_least else 'highest'} recorded "
                       f"{attribute.replace('_', ' ')}",
            "operands": [
                {"subject": f.subject_name, "attribute": attribute,
                 "value": f.value_number, "value_text": f.value_text, "grounded": True}
                for f in ordered[:5]
            ],
            "result": winner.value_number, "result_text": state.answer_value,
        }
        iteration.new_claims = [f"ranked: {ranked}"]
        state.evidence_chain.append(
            f"Ranked {len(candidates)} recorded values; "
            f"{'lowest' if wants_least else 'highest'} is {winner.subject_name}")
        step.satisfy(ordered[:3], f"{winner.subject_name} = {winner.value_text}")
        return True

    def _analyse_duration(self, question, step, state, iteration) -> bool:
        start, end = question.operands[0], question.operands[1]
        first, last = parse_year(start.value_text), parse_year(end.value_text)
        if first is None or last is None:
            step.fail("a start or end year could not be read as a year")
            return False
        span = Span(label=start.subject_name, start=first, end=last)
        state.answer_value = f"{span.duration} years ({first} AS to {last} AS)"
        state.computation = {
            "kind": "duration", "formula": f"{last} AS − {first} AS",
            "operands": [
                {"subject": o.subject_name, "attribute": o.attribute,
                 "value": parse_year(o.value_text), "value_text": o.value_text,
                 "grounded": True} for o in question.operands
            ],
            "result": span.duration, "result_text": state.answer_value,
        }
        iteration.new_claims = [span.describe()]
        state.evidence_chain.append(f"Computed: {last} AS − {first} AS = {span.duration} years")
        step.satisfy([row for o in question.operands for row in o.evidence], span.describe())
        return True

    def _analyse_ordering(self, question, step, state, iteration) -> bool:
        items = [(o.subject_name, parse_year(o.value_text)) for o in question.operands]
        dated = [(name, year) for name, year in items if year is not None]
        if len(dated) < 2:
            step.fail("fewer than two of the values are years")
            return False
        ordered = order_by_year(dated)
        state.answer_value = f"{ordered[0][0]} — {describe_ordering(dated)}"
        state.computation = {
            "kind": "ordering", "formula": "earliest first",
            "operands": [
                {"subject": name, "attribute": question.operands[0].attribute,
                 "value": year, "value_text": f"{year} AS", "grounded": True}
                for name, year in ordered
            ],
            "result": ordered[0][1], "result_text": state.answer_value,
        }
        iteration.new_claims = [describe_ordering(dated)]
        state.evidence_chain.append(f"Ordered by year: {describe_ordering(dated)}")
        step.satisfy([row for o in question.operands for row in o.evidence],
                     f"earliest is {ordered[0][0]}")
        return True

    def _analyse_comparison(self, question, step, state, iteration) -> bool:
        values = [(o.subject_name, o.value, o.value_text) for o in question.operands]
        usable = [(name, value, text) for name, value, text in values if value is not None]
        if len(usable) < 2:
            step.fail("fewer than two of the values are numbers")
            return False
        ordered = sorted(usable, key=lambda item: item[1], reverse=True)
        top, rest = ordered[0], ordered[1]
        attribute = question.operands[0].attribute.replace("_", " ")
        state.answer_value = (
            f"{top[0]} ({top[2]}) — larger than {rest[0]} ({rest[2]}) "
            f"by {top[1] - rest[1]:,.0f}")
        state.computation = {
            "kind": "comparison", "formula": f"{top[0]} {attribute} vs {rest[0]} {attribute}",
            "operands": [
                {"subject": name, "attribute": question.operands[0].attribute,
                 "value": value, "value_text": text, "grounded": True}
                for name, value, text in ordered
            ],
            "result": top[1] - rest[1], "result_text": state.answer_value,
        }
        iteration.new_claims = [state.answer_value]
        state.evidence_chain.append(f"Compared: {state.answer_value}")
        step.satisfy([row for o in question.operands for row in o.evidence], state.answer_value)
        return True

    def _act_assemble(self, question, step, state, iteration, learned) -> bool:
        """Report every requested fact together, once each one is established."""
        iteration.retrieval_modes = ["facts"]
        parts = [f"{operand.describe()}: {operand.value_text}"
                 for operand in question.operands]
        state.answer_value = "; ".join(parts)
        state.computation = {
            "kind": "multi_fact",
            "formula": "",
            "operands": [
                {"subject": operand.subject_name, "attribute": operand.attribute,
                 "value": operand.value, "value_text": operand.value_text,
                 "grounded": True,
                 "citations": [row.citation(self.facts.title_of(row.document_id))
                               for row in operand.evidence[:2]]}
                for operand in question.operands
            ],
            "result": None,
            "result_text": state.answer_value,
        }
        iteration.new_claims = parts
        step.satisfy([row for operand in question.operands for row in operand.evidence],
                     f"all {len(question.operands)} requested facts established")
        return True

    def _act_compute(self, question, step, state, iteration, learned) -> bool:
        """Perform the arithmetic, once every operand is grounded."""
        calculation = question.calculation
        if calculation is None:
            step.fail("no calculation to perform")
            return False

        iteration.retrieval_modes = ["arithmetic"]
        values = [operand.value for operand in question.operands]
        if any(value is None for value in values):
            return self._act_report_gap(question, step, state, iteration, learned)

        result = calculation.apply([value for value in values if value is not None])
        if result is None:
            step.fail("the operands do not support this calculation "
                      "(a denominator of zero, or a missing term)")
            return False

        formula = calculation.formula(question.operands)
        substituted = " ".join(
            f"{operand.subject_name} {operand.attribute.replace('_', ' ')} = {operand.value_text}"
            for operand in question.operands
        )
        rendered = _format_result(calculation.kind, result)

        # "The difference between A and B" asks how far apart they are, not which
        # way round they were named. Reporting a bare negative number answers a
        # question nobody asked, so quote the magnitude and say which is larger.
        if calculation.kind == "difference" and result < 0:
            larger = question.operands[calculation.denominator]
            smaller = question.operands[calculation.numerator]
            rendered = (f"{_format_result(calculation.kind, abs(result))} "
                        f"({larger.subject_name} is the larger)")
            formula = (f"{larger.describe()} − {smaller.describe()}")
        state.answer_value = rendered
        state.computation = {
            "kind": calculation.kind,
            "formula": formula,
            "operands": [
                {"subject": operand.subject_name, "attribute": operand.attribute,
                 "value": operand.value, "value_text": operand.value_text,
                 "citations": [row.citation(self.facts.title_of(row.document_id))
                               for row in operand.evidence[:2]]}
                for operand in question.operands
            ],
            "result": result,
            "result_text": rendered,
        }
        iteration.new_claims = [f"{formula} = {rendered}", substituted]
        state.evidence_chain.append(f"Computed: {formula} = {rendered}")
        step.satisfy([row for operand in question.operands for row in operand.evidence],
                     f"{formula} = {rendered}")
        return True

    def _act_report_gap(self, question, step, state, iteration, learned) -> bool:
        """Refuse the calculation, naming exactly which operand is missing.

        This is the difference between a wrong answer and a useful one. The
        question named two quantities; if the archive only holds one, saying so —
        and saying which — is the honest result, and the value we *did* find is
        still worth reporting as context.
        """
        iteration.retrieval_modes = ["facts"]
        missing = question.ungrounded_operands
        found = [operand for operand in question.operands if operand.grounded]

        names = ", ".join(operand.describe() for operand in missing)
        detail = "; ".join(operand.note for operand in missing if operand.note)
        held = "; ".join(f"{operand.describe()} = {operand.value_text}" for operand in found)

        if question.calculation is not None:
            state.answer_value = (
                f"Not established. This asks for "
                f"{question.calculation.formula(question.operands)}, but the archive "
                f"records no value for {names}"
                + (f" ({detail})" if detail else "")
                + (f". It does record {held}." if held else ".")
            )
        else:
            # A part-answered question leads with what it *did* establish. The
            # asker wanted several facts; burying the three we found under the
            # one we did not is the least useful way to report that.
            state.answer_value = (
                (f"{held}. " if held else "")
                + f"Not recorded: {names}"
                + (f" ({detail})" if detail else "")
                + f". {len(found)} of {len(question.operands)} requested facts established."
            )
        state.computation = {
            "kind": question.calculation.kind if question.calculation else "multi_fact",
            "formula": question.calculation.formula(question.operands)
                       if question.calculation else "",
            "operands": [
                {"subject": operand.subject_name, "attribute": operand.attribute,
                 "value": operand.value, "value_text": operand.value_text,
                 "grounded": operand.grounded, "note": operand.note}
                for operand in question.operands
            ],
            "result": None,
            "result_text": "not established",
        }
        if question.calculation is not None:
            iteration.new_claims = [f"calculation refused: no value for {names}"]
            state.evidence_chain.append(f"Calculation not possible: {names} is not recorded")
        else:
            iteration.new_claims = [f"{len(missing)} requested fact(s) not recorded: {names}"]
            state.evidence_chain.append(f"Not recorded anywhere searched: {names}")
        step.fail(f"missing: {names}")
        return False

    def _act_fact_scan(self, question, step, state, iteration, learned) -> bool:
        """Establish that the subject exists and see what is recorded about it."""
        primary = question.primary
        if primary is None:
            step.fail("no subject named")
            return False
        subject_id, name = primary
        iteration.retrieval_modes = ["facts", "graph"]

        attributes = self.facts.attributes_of(subject_id)
        if attributes:
            iteration.new_claims = [f"{name} has recorded: {', '.join(attributes[:8])}"]
            learned["attributes"] = attributes
            step.satisfy([], f"{len(attributes)} attributes recorded for {name}")
            return True

        # No structured facts: fall back to text so the question is not abandoned.
        hits = self._text_search(name, entities=[name])
        iteration.retrieval_modes.append("hybrid" if self.retriever else "keyword")
        iteration.retrieved_chunks = [h.chunk_id for h in hits]
        if hits:
            step.satisfy([], f"no structured facts; {len(hits)} passages retrieved")
            return True
        step.fail(f"nothing recorded about {name}")
        return False

    def _act_fact_lookup(self, question, step, state, iteration, learned) -> bool:
        """Read one attribute off one subject — the workhorse step."""
        is_bridge = step.key == "bridge"
        attribute = question.bridge_attribute if is_bridge else question.attribute
        subject_id = learned.get("bridged_id") if step.key == "target" else None
        if subject_id is None:
            primary = question.primary
            if primary is None:
                step.fail("no subject to look up")
                return False
            subject_id = primary[0]

        iteration.retrieval_modes = ["facts"]
        view = self.facts.lookup(subject_id, attribute) if attribute else None

        if view is None and attribute:
            # The same relationship is recorded from one side only: a conflict
            # names its `victor`, a faction lists what it is `victor_of`. Reading
            # the stored row from the other end is the same fact, not a guess.
            inverse = _inverse_of(attribute)
            if inverse != attribute:
                view = self.facts.lookup(subject_id, inverse)
                if view is not None:
                    iteration.new_claims.append(
                        f"no '{attribute}' recorded for {view.subject_name}; "
                        f"read the inverse relation '{inverse}' instead"
                    )

        if view is None:
            return self._lookup_fallback(question, step, state, iteration,
                                          subject_id, attribute)

        value, rows = view.best()
        display = rows[0].value_text
        iteration.new_claims = [f"{view.subject_name} · {attribute} = {display}"]
        state.evidence_chain.append(
            f"{view.subject_name} — {attribute.replace('_', ' ')}: {display}"
        )
        learned.setdefault("views", []).append(view)

        if is_bridge:
            # Follow the value into the next subject. This is the graph expansion
            # that makes the following iteration's query different from this one's.
            targets = self.facts.resolve_hop_targets(display)
            targets = self._filter_targets(question, targets)
            if targets:
                learned["bridged_id"], learned["bridged_name"] = targets[0]
                iteration.new_entities = [name for _, name in targets]
                state.graph_expansions += 1
                step.satisfy(rows, f"bridged to {targets[0][1]}")
                return True
            step.satisfy(rows, f"value '{display}' does not name a known subject")
            return True

        # A target value may also list several entities ("The Winter Reckoning;
        # The Leaden Accord"); the question's constraint word picks the right one.
        targets = self._filter_targets(question, self.facts.resolve_hop_targets(display))
        if targets and len(self.facts.resolve_hop_targets(display)) > 1:
            display = targets[0][1]
            iteration.new_claims.append(f"narrowed to {display} using the question's wording")
            state.evidence_chain[-1] = (
                f"{view.subject_name} — {view.attribute.replace('_', ' ')}: {display}"
            )
        if _is_non_value(display) and not is_bridge:
            # The text record explicitly declines to state this. Before accepting
            # that, check whether the value is on a plate instead.
            if self._try_figure(question, step, state, iteration, attribute):
                return True

        state.answer_value = display
        step.satisfy(rows, f"{attribute} = {display}")
        return True

    def _lookup_fallback(self, question, step, state, iteration, subject_id, attribute):
        """No structured value on this subject: try the reverse index, then the
        graph, then text, before giving up.

        The reverse index matters more than it looks. A faction's wiki page may
        simply not carry a "Victor of" row, while every war's page names its
        victor. The fact "The Silent Choir won the War of Drowned Light" is in the
        archive either way — it is just stored on the war. Searching from the
        other end finds it without inventing anything.
        """
        subject_name = self._name_of(subject_id, question, state)
        if attribute and subject_name:
            iteration.retrieval_modes.append("facts:reverse")
            reverse = self.facts.subjects_with_value(attribute, subject_name)
            if reverse:
                names = self._filter_targets(
                    question, [(r.subject_id, r.subject_name) for r in reverse]
                )
                chosen = names[0][1] if names else reverse[0].subject_name
                rows = [r for r in reverse if r.subject_name == chosen] or reverse[:1]
                iteration.new_claims.append(
                    f"no '{attribute}' recorded on {subject_name}; found it recorded "
                    f"from the other side: {chosen} · {attribute} = {subject_name}"
                )
                state.evidence_chain.append(f"{chosen} — {attribute.replace('_', ' ')}: {subject_name}")
                state.graph_expansions += 1
                state.answer_value = chosen
                step.satisfy(rows, f"reverse lookup: {chosen}")
                return True

        iteration.retrieval_modes.append("graph")
        neighbours = self.graph.neighbours(subject_id, predicates=[attribute] if attribute else None)
        if neighbours:
            state.graph_expansions += 1
            names = [n.name for n in neighbours[:4]]
            iteration.new_entities = names
            iteration.new_claims = [f"graph: {attribute} → {', '.join(names)}"]
            state.answer_value = state.answer_value or ", ".join(names)
            step.satisfy([], f"graph edge found: {', '.join(names)}")
            return True

        # Nothing in text or the graph. The value may only exist on a plate.
        if attribute and self._try_figure(question, step, state, iteration, attribute):
            return True

        # Or it may be stated in a sentence that no table mirrors. This is the
        # same fallback the multi-fact path uses, and the single-lookup case is
        # the common one: "in which year was the Aegis forged" has an answer in
        # the corpus, in prose, in a document about a different relic.
        if attribute and subject_name:
            operand = Operand(subject_id=subject_id, subject_name=subject_name,
                              attribute=attribute)
            if self._try_prose(operand, step, state, iteration):
                state.answer_value = state.answer_value or operand.value_text
                return True

        query = f"{subject_name or ''} {attribute or ''}".strip()
        hits = self._text_search(query, entities=[subject_name] if subject_name else None)
        iteration.retrieval_modes.append("hybrid" if self.retriever else "keyword")
        iteration.retrieved_chunks = [h.chunk_id for h in hits]
        if hits:
            iteration.new_claims = [f"passage: {' '.join(hits[0].content.split())[:120]}…"]
            if hasattr(hits[0], "explain"):
                iteration.new_claims.append(f"top hit scored {hits[0].explain()}")

        # Narrative sources state relations in prose that no table records. The
        # LLM may propose claims from those passages, but each one is checked
        # against the passage it cites before it is allowed to count.
        if hits and self.llm_available:
            extracted = self._llm_claims_from(hits, attribute or "", subject_name, iteration)
            if extracted:
                step.satisfy([], f"claim extracted from narrative: {extracted[0]}")
                state.evidence_chain.append(extracted[0])
                state.answer_value = state.answer_value or extracted[0]
                return True
        # Passages are context, not an answer. This step asked for a *value*, and
        # retrieving prose that might mention one does not meet that condition —
        # marking it satisfied here is how a system ends up reporting "all
        # sub-questions supported" above the words "not established".
        step.fail(f"no recorded value for {attribute}; "
                  f"{len(hits)} passage(s) retrieved as context only")
        return bool(hits)

    def _act_inverse_lookup(self, question, step, state, iteration, learned) -> bool:
        """No subject named: find subjects whose attribute matches the question."""
        iteration.retrieval_modes = ["facts", "hybrid" if self.retriever else "keyword"]
        hits = self._text_search(question.text)
        iteration.retrieved_chunks = [h.chunk_id for h in hits]
        if hits:
            step.satisfy([], f"{len(hits)} candidate passages")
            return True
        step.fail("no candidate passages")
        return False

    def _act_conflict_check(self, question, step, state, iteration, learned) -> bool:
        """Check every value read so far for a competing value."""
        iteration.retrieval_modes = ["facts"]
        views: list[AttributeView] = learned.get("views", [])
        found = False
        for view in views:
            if view.is_conflicting:
                found = True
                state.conflicts.append(describe_conflict(view, self.facts.title_of))
                iteration.new_claims.append(
                    f"conflict: {view.subject_name} · {view.attribute} has "
                    f"{len(view.groups)} competing values"
                )
        step.satisfy([], f"{len(state.conflicts)} conflict(s) found" if found
                     else "no competing values recorded")
        return found

    def _act_resolve_conflict(self, question, step, state, iteration, learned) -> bool:
        """Rank competing values by source reliability, and say what was rejected."""
        iteration.retrieval_modes = ["facts"]
        views: list[AttributeView] = learned.get("views", [])
        target = next((v for v in views if v.attribute == question.attribute), None)
        if target is None:
            step.fail("no competing values to rank")
            return False

        _, rows = target.best()
        winner = rows[0]
        state.answer_value = winner.value_text
        others = [g for k, g in target.ordered_groups() if g is not rows]
        if others:
            rejected = ", ".join(f"'{g[0].value_text}' ({g[0].source_class})" for g in others)
            state.evidence_chain.append(
                f"Resolved by source reliability: {winner.source_class} "
                f"({winner.reliability:.2f}) over {rejected}"
            )
            iteration.new_claims = [f"resolved to '{winner.value_text}' from {winner.source_class}"]
        step.satisfy(rows, f"most authoritative value is '{winner.value_text}' "
                            f"from a {winner.source_class} source")
        return True

    def _act_text_search(self, question, step, state, iteration, learned) -> bool:
        iteration.retrieval_modes = ["hybrid" if self.retriever else "keyword"]
        entities = [name for _, name in question.entities]
        query = question.text
        # When earlier steps have already learned something, let the LLM propose a
        # query aimed at what is still missing rather than repeating the question.
        if self.llm_available and state.evidence_chain:
            suggested = self.gateway.suggest_queries(
                question.text, state.evidence_chain, step.text
            )
            if suggested:
                query = suggested[0]
                iteration.query = query
                iteration.reason = f"LLM proposed a query targeting the remaining gap: {query!r}"
                state.queries_issued += len(suggested) - 1
        hits = self._text_search(query, entities=entities)
        iteration.retrieved_chunks = [h.chunk_id for h in hits]
        if hits:
            iteration.new_claims = [f"{h.citation()}" for h in hits[:3]]
        if hits:
            step.satisfy([], f"{len(hits)} passages retrieved")
            return True
        step.fail("no passages retrieved")
        return False

    def _try_figure(self, question, step, state, iteration, attribute) -> bool:
        """Look for the value on a figure plate, and say so if it is unreadable.

        Only for attributes a plate could actually carry. Every entity has a
        plate of some kind — a portrait, a banner, a landscape — and offering one
        of those as the explanation for a missing housing location is worse than
        saying nothing: it tells the reader to open a painting that was never
        going to answer them, and it buries the fact that the value is a text
        lookup that failed.
        """
        if not routes_to_figure(attribute):
            return False
        primary = question.primary
        if primary is None:
            return False
        name = primary[1]
        iteration.retrieval_modes.append("figures")
        hits = self.figures.for_subject(name)
        if not hits:
            return False

        hit = hits[0]
        iteration.retrieved_chunks.append(hit.figure_id)
        if hit.readable:
            iteration.new_claims.append(
                f"the text record states no {attribute}; the plate prints: "
                f"{' '.join(hit.ocr_text.split())[:100]}"
            )
            state.evidence_chain.append(f"{hit.caption} — {' '.join(hit.ocr_text.split())[:80]}")
            state.answer_value = f"see figure: {' '.join(hit.ocr_text.split())[:80]}"
            step.satisfy([], f"value found on plate {hit.figure_id}")
            return True

        # Found the plate, cannot read the value off it by OCR. Before reporting
        # that, try actually looking at it: the archive's artwork carries answers
        # that no text route can reach, and "we could not read it" is only honest
        # once every route including sight has been attempted.
        if hit.pictorial and self.vision is not None and self.vision.available:
            observation = self.vision.describe(hit.figure_id, hit.asset_path,
                                               question.text)
            iteration.retrieval_modes.append("vision")
            state.visual_observations.append(observation.to_dict())
            if observation.usable:
                iteration.new_claims.append(
                    f"{hit.caption}: {observation.description[:200]}")
                state.evidence_chain.append(
                    f"{hit.caption} — visual reading: {observation.description[:160]}")
                state.answer_value = observation.description
                state.visual_gaps.append(
                    f"{hit.caption} was read by a vision model, not stated in text")
                step.satisfy([], f"visual observation of {hit.figure_id} "
                                 f"({observation.status.value})")
                return True
            state.visual_gaps.append(f"{hit.caption}: {observation.note}")

        # Found the plate, cannot read the value off it. Naming the plate and the
        # reason is far more useful than reporting "None recorded" as the answer —
        # it tells the user exactly which page to open.
        if hit.pictorial:
            detail = ("its content is pictorial — no label could be read from it")
            note = "value exists only as artwork"
        else:
            detail = ("the value is plotted on a scale rather than printed, so it "
                      "cannot be read reliably")
            note = "value exists only as a chart plate"

        iteration.new_claims.append(f"{hit.caption}: {detail}")
        state.evidence_chain.append(f"{hit.caption} — {detail}")
        state.answer_value = (
            f"Not established in text. The archive shows this on {hit.caption} "
            f"({hit.asset_path.rsplit('/', 1)[-1]}), but {detail}."
        )
        step.fail(note)
        return True

    # -- helpers ------------------------------------------------------------

    def _llm_claims_from(self, hits, attribute: str, subject_name: str, iteration) -> list[str]:
        """Ask the LLM for claims in these passages, then verify each one."""
        allowed = {h.chunk_id: h.content for h in hits}
        gap = f"{subject_name} {attribute}".strip() or "the question"
        proposed = self.gateway.extract_claims(gap, [(h.chunk_id, h.content) for h in hits])
        if not proposed:
            return []

        kept, rejected = verify_extracted_claims(proposed, allowed)
        for reason in rejected:
            # Rejections are shown, not hidden: they are the evidence that the
            # verification gate is doing something.
            iteration.new_claims.append(f"REJECTED unsupported LLM claim: {reason}")
        return [f"{c['subject']} — {c['predicate']}: {c['value']}" for c in kept]

    def _name_of(self, subject_id: str, question: Question, state: Investigation) -> str:
        """Display name for a subject, preferring what the loop already learned."""
        for view in ():
            pass
        row = self.store.connection.execute(
            "SELECT subject_name FROM facts WHERE subject_id = ? LIMIT 1", (subject_id,)
        ).fetchone()
        if row:
            return row["subject_name"]
        return question.primary[1] if question.primary else ""

    @staticmethod
    def _filter_targets(question: Question, targets: list[tuple[str, str]]):
        """Narrow multi-valued hops using a constraint word from the question.

        "Which *accord* was won by …" must not answer with a war, even though the
        faction won both.
        """
        if not question.filter_terms or len(targets) < 2:
            return targets
        narrowed = [t for t in targets
                    if any(term in t[1].lower() for term in question.filter_terms)]
        return narrowed or targets

    def _budget_stop(self, state: Investigation, started: float) -> StopReason | None:
        if len(state.iterations) >= self.budget.max_iterations:
            return StopReason.ITERATION_BUDGET
        if state.queries_issued >= self.budget.max_queries:
            return StopReason.QUERY_BUDGET
        if time.perf_counter() - started >= self.budget.max_seconds:
            return StopReason.TIME_BUDGET
        return None

    def _text_fallback(self, state: Investigation, text: str) -> None:
        hits = self.keyword.search(text, limit=TEXT_HITS)
        state.iterations.append(Iteration(
            number=1, sub_question="Is anything in the archive relevant?",
            action="text_search", query=text, retrieval_modes=["keyword"],
            retrieved_chunks=[h.chunk_id for h in hits],
            reason="no indexed entity matched the question, so fall back to full-text search",
        ))
        state.queries_issued += 1

    def _finish(self, state: Investigation, started: float) -> Investigation:
        state.elapsed_seconds = time.perf_counter() - started
        state.claims = build_claims(state, self.facts)
        return state
