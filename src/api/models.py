"""Request and response shapes for the HTTP API.

The response mirrors the investigation state rather than flattening it. A UI that
only showed the answer would hide the thing this system is actually for — the
evidence, the disagreements, and the record of what was searched.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskOptions(BaseModel):
    max_iterations: int = Field(default=6, ge=1, le=100)
    show_trace: bool = True
    allow_llm: bool = True


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    options: AskOptions = Field(default_factory=AskOptions)


class EvidenceRef(BaseModel):
    document_id: str
    document: str
    relative_path: str = ""
    page: int | None = None
    chunk_id: str
    source_class: str
    reliability: float = 0.0
    # The line the value was read from, so the UI can show the source text next
    # to the claim rather than only a reference to it.
    excerpt: str = ""
    # Set for evidence that came from a figure, so the UI can show the plate the
    # answer rests on. Served through /api/figures/{id}/asset, which validates
    # the path against the archive rather than trusting the request.
    figure_id: str = ""


class ClaimOut(BaseModel):
    text: str
    claim_type: str
    confidence: float
    confidence_label: str
    confidence_reasons: list[str] = []
    evidence: list[EvidenceRef] = []


class AskResponse(BaseModel):
    question: str
    answer: str
    # The authoritative completion verdict. `partial` is kept as a convenience
    # mirror of `status.is_partial` so existing clients keep working, but both
    # come from the same evaluation — they cannot disagree.
    investigation_id: str
    status: str
    status_headline: str = ""
    status_reasons: list[str] = []
    unmet_requirements: list[str] = []
    partial: bool
    ai_mode: str
    claims: list[ClaimOut] = []
    evidence_chain: list[str] = []
    conflicts: list[dict[str, Any]] = []
    graph_path: list[str] = []
    trace: list[dict[str, Any]] = []
    sub_questions: list[dict[str, Any]] = []
    calculation: dict[str, Any] = {}
    stop_reason: str
    fallback_events: list[str] = []
    stats: dict[str, Any] = {}
