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

import time

from src.common.config import InvestigationBudget
from src.graph.fact_query import AttributeView, FactQuery, FactRow
from src.graph.query import GraphQuery
from src.orchestration.planner import decompose, next_action
from src.orchestration.state import (
    Intent,
    Investigation,
    Iteration,
    Question,
    StopReason,
    SubQuestion,
)
from src.orchestration.understanding import QuestionAnalyzer
from src.retrieval.figures import FigureIndex
from src.retrieval.keyword import KeywordIndex
from src.storage.db import ArchiveStore
from src.verification.claims import build_claims
from src.verification.conflicts import describe_conflict

# How many text hits to keep per search. Enough to show the evidence, small
# enough that a trace stays readable.
TEXT_HITS = 6

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


class Investigator:
    def __init__(self, store: ArchiveStore, budget: InvestigationBudget) -> None:
        self.store = store
        self.budget = budget
        self.analyzer = QuestionAnalyzer(store)
        self.facts = FactQuery(store)
        self.graph = GraphQuery(store)
        self.keyword = KeywordIndex(store)
        self.figures = FigureIndex(store)

    def investigate(self, text: str) -> Investigation:
        started = time.perf_counter()
        question = self.analyzer.analyze(text)
        self._orient_hop(question)
        state = Investigation(question=question, sub_questions=decompose(question))

        if not question.entities and question.intent is not Intent.INVERSE_HOP:
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
            # archive has no more to give on this question.
            stale_rounds = 0 if progressed else stale_rounds + 1
            if stale_rounds >= self.budget.stale_rounds_before_stop:
                state.stop_reason = StopReason.NO_NEW_EVIDENCE
                break

        return self._finish(state, started)

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
            "inverse_lookup": self._act_inverse_lookup,
            "conflict_check": self._act_conflict_check,
            "resolve_conflict": self._act_resolve_conflict,
            "text_search": self._act_text_search,
        }.get(action, self._act_text_search)
        return handler(question, step, state, iteration, learned)

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
        hits = self.keyword.search(name, limit=TEXT_HITS)
        iteration.retrieval_modes.append("keyword")
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

        query = f"{subject_name or ''} {attribute or ''}".strip()
        hits = self.keyword.search(query, limit=TEXT_HITS)
        iteration.retrieval_modes.append("keyword")
        iteration.retrieved_chunks = [h.chunk_id for h in hits]
        if hits:
            iteration.new_claims = [f"passage: {' '.join(hits[0].content.split())[:120]}…"]
        # Passages are context, not an answer. This step asked for a *value*, and
        # retrieving prose that might mention one does not meet that condition —
        # marking it satisfied here is how a system ends up reporting "all
        # sub-questions supported" above the words "not established".
        step.fail(f"no recorded value for {attribute}; "
                  f"{len(hits)} passage(s) retrieved as context only")
        return bool(hits)

    def _act_inverse_lookup(self, question, step, state, iteration, learned) -> bool:
        """No subject named: find subjects whose attribute matches the question."""
        iteration.retrieval_modes = ["facts", "keyword"]
        hits = self.keyword.search(question.text, limit=TEXT_HITS)
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
        iteration.retrieval_modes = ["keyword"]
        hits = self.keyword.search(question.text, limit=TEXT_HITS)
        iteration.retrieved_chunks = [h.chunk_id for h in hits]
        if hits:
            iteration.new_claims = [f"{h.citation()}" for h in hits[:3]]
        if hits:
            step.satisfy([], f"{len(hits)} passages retrieved")
            return True
        step.fail("no passages retrieved")
        return False

    def _try_figure(self, question, step, state, iteration, attribute) -> bool:
        """Look for the value on a figure plate, and say so if it is unreadable."""
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

        # Found the plate, cannot read the value off it. Saying that is far more
        # useful than reporting the text record's "None recorded" as the answer.
        iteration.new_claims.append(
            f"the value is shown on {hit.caption} as a plotted scale, not a printed "
            f"number; OCR cannot recover it"
        )
        state.evidence_chain.append(
            f"{hit.caption} — value drawn on a scale; not machine-readable"
        )
        state.answer_value = (
            f"Not established in text. The value is shown on {hit.caption}, "
            f"but it is plotted rather than printed and cannot be read reliably."
        )
        step.fail("value exists only as a chart plate")
        return True

    # -- helpers ------------------------------------------------------------

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
