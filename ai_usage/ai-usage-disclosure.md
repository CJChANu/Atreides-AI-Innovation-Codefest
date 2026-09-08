# AI Usage Disclosure

Required by §4.1 of the challenge document. Honest disclosure carries no penalty;
misrepresentation does.

## Tools used

| Tool | Model | Used for |
|---|---|---|
| Claude Code (CLI / desktop) | Claude Opus 5 | Implementation of the Phase 1 modules, test authoring, documentation drafting, and interactive investigation of the corpus |

Full conversation exports are in [`chat-logs/`](chat-logs/) as plain `.txt`, per
§4.1.

## How the work was actually divided

**The team decided; the assistant implemented and investigated.**

Decided by the team, before any code was written:

- Sub-track choice: **1C primary, 1B secondary**, with figure/table evidence
  borrowed from 1A where it supports an answer.
- The architecture in `Technical Solution Plan — Ashen Era Intelligent Document
  Assistant.pdf`: provenance-first ingestion, three complementary indexes, a
  **bounded** investigation state machine rather than an autonomous agent,
  claim-level verification, and a user-visible trace.
- The source-reliability policy as a *ranking* signal rather than a filter.
- The rule that a citation is generated from recorded metadata, never from a
  language model.
- The build order in `docs/roadmap.md`.

Done with AI assistance:

- Writing the parser, chunker, storage, graph and fact-extraction modules against
  the team's schema and interfaces.
- Writing the test suite.
- Drafting documentation from the team's decisions.

**Empirically established against the real corpus, not assumed** — each of these
changed the design:

- The 17 `*.scan.pdf` files yield **zero** extractable characters, and most have
  no twin in another format → OCR is a correctness requirement, not an optional
  extra (decision D6).
- The Weeping Lurker's threat rating exists in **no table and no sentence** in the
  archive — only on a figure plate → text-only retrieval cannot answer that class
  of question at all.
- Eleven documents ship as both PDF and DOCX → format-twin resolution, to stop a
  document contradicting itself (D2).
- Several plates encode their value as a *bar chart*; OCR returns the axis ticks →
  we refuse to assert those numbers rather than publish a plausible wrong one (D7).

## Where AI output was wrong and the team corrected it

These are recorded in `docs/limitations.md` as well, because they are part of the
engineering record:

1. **Table-before-text PDF parsing.** The first generated parser emitted each
   page's tables before its text. The codexes place the entity name in a heading
   directly above its table, so every codex table lost its subject and fell back
   to the document title. Caught by inspecting extracted facts against the source
   PDF; fixed by reordering and binding the page heading.
2. **Wikilink-only edge extraction.** The first graph builder required a
   `[[link]]` in a table value. Codex tables state values as plain text, so the
   most authoritative source in the archive contributed **no typed edges at all**.
   Caught by grouping edges by predicate and noticing codex absence; fixed by
   accepting name-shaped plain values (typed edges 110 → 218).
3. **Nearest-heading chunk binding.** A wiki article consisting of an infobox
   produced a chunk headed `Infobox` with the article's subject absent from its
   text — unfindable by a search for the thing it describes. Caught by an
   integration test we wrote to check exactly this; fixed by binding the full
   section path.
4. **A test that asserted the wrong policy.** We wrote a test asserting a wiki
   article outranks a ballad. It failed, and the team's judgement was that the
   *test* was wrong: reliability is a 20% nudge, and making it dominant would hide
   the low-reliability sources that reveal conflicts. The test was rewritten to
   assert the intended property.
5. **Case-only "conflicts".** Initial conflict detection reported 60 conflicts,
   many of them `Contested` vs `contested`. The team added a normalised
   comparison key; 34 real conflicts remain.

## What was *not* AI-generated

- The sub-track choice and the solution architecture.
- The reliability tiers and their weights.
- The decision to refuse chart-plate values rather than guess.
- Every trade-off recorded in `docs/decisions.md`.

## Verification

Every claim in the README and in `docs/` is reproducible from the committed code:

```bash
python scripts/ingest_archive.py --reset
python scripts/build_indexes.py
pytest
```

Every team member can explain, justify and modify any module in this repository,
as required by §4.1.
