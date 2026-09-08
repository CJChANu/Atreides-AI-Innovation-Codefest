# Working context given to AI assistants

The standing context supplied at the start of each assisted session, so that
generated code matched the team's architecture instead of a generic RAG template.

## Project

Sub-track **1C — Searching the Way a Human Does** (primary), extended with **1B —
Connecting Facts Across Thousands of Pages**. Corpus: the Ashen Era Archive,
read-only, 339 files / ~1,330 pages in PDF, scanned PDF, DOCX, Markdown, plain
text and images.

## Non-negotiable rules

1. **Provenance first.** Every answerable unit keeps document, page or section,
   and source class. A citation is generated from recorded metadata, never
   produced by a model.
2. **The corpus is read-only.** All derived data goes to `data/`.
3. **No external world knowledge.** The world is invented. A fact not in the
   archive is reported as unsupported, never filled in.
4. **Reliability ranks, it does not filter.** A ballad stays retrievable; it just
   scores lower. Deleting low-reliability sources would delete the conflicts.
5. **Bounded, not autonomous.** The investigation loop has hard limits and must
   report which one stopped it.
6. **Deterministic before probabilistic.** Extract what the corpus states
   explicitly before reaching for an LLM, and make the LLM beat that baseline.
7. **Honest degradation.** If OCR is unavailable or a plate is unreadable, say so.
   Never present a gap as an absence of evidence.
8. **No question-specific rules.** Final judging uses an unpublished question set.

## Code conventions

- Python 3.11+, `from __future__ import annotations`, type hints throughout.
- Comments explain *why*, not *what*. A comment that restates the code is noise.
- Parsers own provenance; the chunker may only inherit it.
- No secrets in code. Configuration via environment, `.env` git-ignored.
- Every non-trivial rule gets a test that would fail if the rule were violated.

## Verify, don't assume

Claims about the corpus must be checked against the corpus. The OCR requirement,
the format twins, the plate-only facts and the chart-plate problem were all
discovered this way, and each one changed the design.
