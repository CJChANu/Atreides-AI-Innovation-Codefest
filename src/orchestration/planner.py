"""Decompose a question into sub-questions, and decide what to search next.

Two responsibilities, both of which exist to stop the loop terminating early:

* **Decomposition** gives every question an explicit list of things that must be
  established, each with a completion condition. Without that the loop cannot
  tell "answered" from "attempted" and would stop as soon as it found *something*
  — which for a two-hop question means stopping at the definition.
* **Next-query planning** turns an unsatisfied sub-question plus everything
  learned so far into the next concrete action. This is the part that makes the
  search iterative rather than a fixed pipeline: the second query is a function of
  the first query's results.
"""

from __future__ import annotations

from src.orchestration.state import Intent, Question, SubQuestion


def decompose(question: Question) -> list[SubQuestion]:
    """Build the sub-questions this investigation must satisfy."""
    primary = question.primary
    name = primary[1] if primary else "the subject"

    if question.intent is Intent.RELATION_HOP:
        bridge = question.bridge_attribute or "related entity"
        target = question.attribute or "attribute"
        return [
            SubQuestion("locate", f"What does the archive record about {name}?",
                        f"at least one recorded fact about {name}"),
            SubQuestion("bridge", f"What is {name}'s {bridge.replace('_', ' ')}?",
                        f"a value for {bridge} that names a known subject"),
            SubQuestion("target", f"What is that subject's {target.replace('_', ' ')}?",
                        f"a value for {target} on the bridged subject"),
            SubQuestion("conflict", "Do sources disagree on any step of this chain?",
                        "every step checked for competing values"),
        ]

    if question.intent is Intent.CALCULATION and question.calculation:
        # One sub-question per operand, each with its own completion condition.
        # This is the structural fix for answering arithmetic with half the
        # inputs: "compute" cannot be reached until every operand is grounded,
        # so a missing value stops the answer instead of being skipped over.
        subs = [
            SubQuestion(f"operand:{index}",
                        f"What {operand.attribute.replace('_', ' ')} is recorded "
                        f"for {operand.subject_name}?",
                        f"a numeric value for {operand.attribute.replace('_', ' ')} "
                        f"on {operand.subject_name}, with a citation")
            for index, operand in enumerate(question.operands)
        ]
        subs.append(SubQuestion(
            "compute",
            f"What is {question.calculation.formula(question.operands)}?",
            "every operand grounded in evidence, and the arithmetic performed",
        ))
        subs.append(SubQuestion(
            "conflict", "Do sources disagree about any operand?",
            "competing values checked for each operand",
        ))
        return subs

    if question.intent is Intent.TEMPORAL_CHECK:
        subject = question.entities[0][1] if question.entities else "the subject"
        place = question.entities[1][1] if len(question.entities) > 1 else "the place"
        return [
            SubQuestion("origin", f"When did {subject} come into existence?",
                        f"a recorded origin year for {subject}, with a citation"),
            SubQuestion("events", f"What dated events does the archive record at {place}?",
                        f"every dated event naming {place}, read from the event's own record"),
            SubQuestion("relation", f"What does the archive record linking {subject} to {place}?",
                        f"the recorded relationship between {subject} and {place}"),
            SubQuestion("temporal", f"Do the dates allow {subject} to have been at {place}?",
                        "the origin year compared against every event year, with the "
                        "conclusion that follows"),
            SubQuestion("conflict", "Do sources disagree about any of those dates?",
                        "competing values checked for each date used"),
        ]

    if question.intent is Intent.MULTI_FACT and question.operands:
        # One atomic sub-question per requested fact, then a step that assembles
        # them. Splitting before retrieval is what stops a four-part question
        # being marked complete after answering its first part.
        subs = [
            SubQuestion(f"operand:{index}",
                        f"What {requirement.attribute.replace('_', ' ')} is recorded "
                        f"for {requirement.subject_name}?",
                        f"a recorded value for {requirement.attribute.replace('_', ' ')} "
                        f"on {requirement.subject_name}, with a citation")
            for index, requirement in enumerate(question.operands)
        ]
        subs.append(SubQuestion(
            "assemble", "What do those facts say together?",
            "every requested fact established, or explicitly reported as missing",
        ))
        subs.append(SubQuestion(
            "conflict", "Do sources disagree about any of them?",
            "competing values checked for each requested fact",
        ))
        return subs

    if question.intent is Intent.INVERSE_HOP:
        target = question.attribute or "attribute"
        return [
            SubQuestion("inverse", f"Which subjects record a {target.replace('_', ' ')} matching the question?",
                        "at least one subject found by inverse lookup"),
            SubQuestion("conflict", "Do sources disagree about it?",
                        "competing values checked"),
        ]

    if question.intent in {Intent.ATTRIBUTE_LOOKUP, Intent.CONFLICT_RESOLUTION}:
        attribute = (question.attribute or "attribute").replace("_", " ")
        subs = [
            SubQuestion("locate", f"What does the archive record about {name}?",
                        f"at least one recorded fact about {name}"),
            SubQuestion("target", f"What {attribute} is recorded for {name}?",
                        f"at least one recorded value for {attribute}"),
            SubQuestion("conflict", f"Do sources disagree about {name}'s {attribute}?",
                        "competing values enumerated and ranked by source reliability"),
        ]
        if question.expects_conflict:
            # The question already signals that the asker expects disagreement
            # ("the *true* founding year"), so resolving it is not optional.
            subs.append(
                SubQuestion("resolve", f"Which recorded {attribute} is the most authoritative?",
                            "a most-reliable value identified, with the competing value named")
            )
        return subs

    return [
        SubQuestion("locate", f"What does the archive say about {name}?",
                    "relevant passages retrieved"),
        SubQuestion("evidence", "Is there a directly supporting passage?",
                    "at least one passage that addresses the question"),
    ]


def next_action(question: Question, pending: list[SubQuestion], learned: dict) -> tuple[str, str, str]:
    """Choose the next (action, query, reason) from what is still missing.

    `learned` carries results from earlier iterations — notably the bridged
    subject discovered by a `bridge` step, which is what the `target` step then
    searches. That dependency is the whole point of an iterative loop.
    """
    if not pending:
        return "stop", "", "every sub-question is satisfied"

    step = pending[0]
    primary = question.primary
    name = primary[1] if primary else question.text

    if step.key == "origin":
        return ("origin_lookup", name,
                f"whether {name} could have been present anywhere depends first on "
                f"when it came into existence")

    if step.key == "events":
        place = question.entities[1][1] if len(question.entities) > 1 else name
        return ("event_scan", place,
                f"the archive records events on the *event's* page, not the place's, "
                f"so {place}'s history is found by searching from the event end")

    if step.key == "relation":
        place = question.entities[1][1] if len(question.entities) > 1 else name
        return ("relation_check", f"{name} {place}",
                f"what the archive actually records linking {name} to {place} — "
                f"present custody is not evidence of past presence")

    if step.key == "temporal":
        return ("temporal_compare", question.text,
                "compare the origin year against each event year and state what "
                "the ordering rules out")

    if step.key.startswith("operand:"):
        index = int(step.key.split(":", 1)[1])
        operand = question.operands[index]
        attribute = operand.attribute.replace("_", " ")
        return ("operand_lookup", f"{operand.subject_name} {attribute}",
                f"the calculation needs {operand.subject_name}'s {attribute}; "
                f"read it before any arithmetic is attempted")

    if step.key == "assemble":
        missing = question.ungrounded_operands
        if missing:
            return ("report_gap", ", ".join(o.describe() for o in missing),
                    f"{len(missing)} of the {len(question.operands)} requested facts "
                    f"are not recorded; the answer must say which")
        return ("assemble", question.text,
                "every requested fact is established, so they can be reported together")

    if step.key == "compute":
        missing = question.ungrounded_operands
        if missing:
            return ("report_gap", missing[0].describe(),
                    f"the calculation cannot proceed: no value was found for "
                    f"{missing[0].describe()}")
        return ("compute", question.calculation.formula(question.operands) if
                question.calculation else "", "every operand is grounded, so the "
                "arithmetic can be performed and shown")

    if step.key == "locate":
        return "fact_scan", name, f"establish what the archive records about {name}"

    if step.key == "bridge":
        bridge = question.bridge_attribute or ""
        return ("fact_lookup", f"{name} {bridge.replace('_', ' ')}",
                f"the question asks about {name}'s {bridge.replace('_', ' ')} before its "
                f"{(question.attribute or '').replace('_', ' ')}; that link must be resolved first")

    if step.key == "target":
        bridged = learned.get("bridged_name")
        subject = bridged or name
        attribute = (question.attribute or "").replace("_", " ")
        reason = (f"follow the discovered link to {bridged} and read its {attribute}"
                  if bridged else f"read the {attribute} recorded for {subject}")
        return "fact_lookup", f"{subject} {attribute}", reason

    if step.key == "inverse":
        attribute = (question.attribute or "").replace("_", " ")
        return "inverse_lookup", f"{attribute} {question.text}", \
            f"no subject was named, so search for subjects whose {attribute} matches"

    if step.key == "conflict":
        return "conflict_check", name, "check whether any source contradicts the values found"

    if step.key == "resolve":
        return "resolve_conflict", name, \
            "the question asks for the true value, so competing values must be ranked"

    return "text_search", question.text, "fall back to full-text retrieval"
