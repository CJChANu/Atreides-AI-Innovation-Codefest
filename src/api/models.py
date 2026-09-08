"""Request and response shapes for the HTTP API.

The response mirrors the investigation state rather than flattening it. A UI that
only showed the answer would hide the thing this system is actually for — the
evidence, the disagreements, and the record of what was searched.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AskOptions(BaseModel):
    max_iterations: int = Field(default=6, ge=1, le=12)
    show_trace: bool = True
    allow_llm: bool = True


class AskRequest(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    options: AskOptions = Field(default_factory=AskOptions)


class EvidenceRef(BaseModel):
    document_id: str
    document: str
    relative_path: str = ""
    page: int | None = None
    chunk_id: str
    source_class: str
    reliability: float = 0.0


class ClaimOut(BaseModel):
    text: str
    claim_type: str
    confidence: float
    confidence_label: str
    evidence: list[EvidenceRef] = []


class AskResponse(BaseModel):
    question: str
    answer: str
    partial: bool
    ai_mode: str
    claims: list[ClaimOut] = []
    evidence_chain: list[str] = []
    conflicts: list[dict[str, Any]] = []
    graph_path: list[str] = []
    trace: list[dict[str, Any]] = []
    sub_questions: list[dict[str, Any]] = []
    stop_reason: str
    fallback_events: list[str] = []
    stats: dict[str, Any] = {}
