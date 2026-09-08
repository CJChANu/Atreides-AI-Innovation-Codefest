# Build order and status

Phases are ordered so that each one is independently demonstrable and each later
phase is measured against the one before it.

## Phase 1 — Foundation ✅ complete

Ingest every format with provenance; keyword index; deterministic graph and fact
extraction; OCR; tests.

Verified on the full archive: 339 documents (321 indexed), 1,330 pages, 2,547
chunks, 227 tables, 187 figures, 417 entities, 1,912 edges, 1,499 facts, 34
conflicts. 50 tests passing.

## Phase 2 — Semantic retrieval and fusion

- Embedding adapter behind a cache (an unchanged chunk is embedded once, ever)
- Vector index, local-first so the system runs without network access
- Four-way fusion: BM25 + vector + entity overlap + source quality
- Fuzzy alias resolution to survive OCR damage
- Vision-model pass over chart plates (closes the `1a_001/004/007/013` gap)
- **Ablation harness**: vector-only vs keyword-only vs hybrid vs hybrid+graph, so
  the fusion weights are evidence-backed rather than asserted

## Phase 3 — The investigation loop (the 1C core) ✅ complete

Query understanding, decomposition with completion conditions, the bounded state
machine, graph/fact expansion from discovered entities, a named stop reason on
every answer, and a JSON trace.

All seven 1B and both 1C development questions resolve with page citations. See
`docs/investigation-protocol.md`.

## Phase 4 — Verification and grounded answers ◐ mostly complete

Done: the claim model (direct / inferred / conflicting / unsupported), bounded
confidence scoring, reliability-aware conflict reporting, the grounded answer and
trace renderer, and figure-plate evidence when a value exists only on an
illustration.

Remaining: the HTTP API and a web UI rendering the same payload the CLI prints,
with the cited page image inline.

## Phase 5 — Hardening

Adversarial tests (alias variants, three-plus hops, evidence split across formats,
OCR damage, codex-vs-ballad conflict, no-answer questions, table-only and
figure-only evidence, over-broad questions); rate-limit backoff and caching;
reproducible setup; honest documentation of every failed approach.
