"""Describing a contradiction rather than silently resolving it.

The archive is built around disagreement, so a conflict is a *result*, not an
error. We report every competing value with the source that asserts it and the
reliability tier that source belongs to, and we say plainly whether the conflict
is resolvable by that ordering or not.
"""

from __future__ import annotations

from typing import Any

from src.graph.fact_query import AttributeView

# Below this gap in reliability we do not claim the conflict is settled — two
# sources of comparable authority disagreeing is a genuine open question, and
# pretending otherwise would be the exact failure this archive tests for.
DECISIVE_RELIABILITY_GAP = 0.15


def describe_conflict(view: AttributeView, title_of) -> dict[str, Any]:
    groups = view.ordered_groups()
    positions = []
    for _, rows in groups:
        top = max(rows, key=lambda r: r.reliability)
        positions.append({
            "value": top.value_text,
            "source_class": top.source_class,
            "reliability": top.reliability,
            "sources": sorted({
                f"{title_of(r.document_id)}"
                + (f", p.{r.page}" if r.page else "")
                for r in rows
            }),
        })

    gap = positions[0]["reliability"] - positions[1]["reliability"] if len(positions) > 1 else 0.0
    resolvable = gap >= DECISIVE_RELIABILITY_GAP

    return {
        "subject": view.subject_name,
        "attribute": view.attribute,
        "positions": positions,
        "resolvable_by_reliability": resolvable,
        "resolution": (
            f"The {positions[0]['source_class']} record is the more authoritative "
            f"source, so '{positions[0]['value']}' is preferred."
            if resolvable else
            "The competing sources are of comparable authority; the archive does "
            "not settle this and the disagreement is reported as-is."
        ),
    }
