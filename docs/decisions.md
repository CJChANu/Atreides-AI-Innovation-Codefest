# Key technical decisions

Each entry records what we chose, what we rejected, and — where it applies — the
evidence from the archive that settled it.

---

## D1 — SQLite + FTS5 instead of OpenSearch or a vector service

**Chosen:** one SQLite file holding documents, chunks, the BM25 index, the graph
and the facts.

**Rejected:** OpenSearch/Elasticsearch for keyword search; Neo4j for the graph; a
separate Postgres for metadata.

**Why:** a judge must be able to run this from the README alone. Every service we
add is a way for that to fail on a machine we have never seen. FTS5 is a genuine
BM25 implementation, ships inside Python's stdlib `sqlite3`, and is fast enough at
this scale — the whole archive indexes in under a minute. The storage layer
exposes plain methods rather than an ORM, so swapping SQLite for
Postgres/Neo4j later would not touch the investigation logic.

**Cost we accepted:** no distributed scaling and no built-in fuzzy matching. At
1,330 pages neither matters.

---

## D2 — PDF wins over its DOCX twin

**Chosen:** when the same document ships as both `.pdf` and `.docx`, index the PDF
and record the DOCX as `superseded_by`.

**Why:** eleven documents in the archive ship in both formats. Indexing both would
double-count every fact they contain and — worse — make contradiction detection
see a document disagreeing with itself. We keep the PDF because **only the PDF
carries page numbers**, and a citation without a page is worth much less to a user
who has to go and check it.

**Cost we accepted:** DOCX heading structure is richer than our PDF heading
heuristic. We judged page-accurate citation the more valuable of the two.

*Effect: 339 files discovered, 321 indexed, 18 recorded as twins.*

---

## D3 — Structure-aware chunking, with tables and figures atomic

**Chosen:** chunk on document structure; never split a table or a figure; bind the
full section path into the chunk text; overlap prose only.

**Rejected:** fixed-size sliding windows.

**Why:** a fixed window cuts this archive in exactly the wrong places. A codex
infobox row separated from the entity name above it becomes an orphan number
("Attunement cost | 12" — of what?). Half a table is worse than no table.

**A bug this caught.** Our first version bound only the *nearest* heading. A wiki
article whose content is an infobox therefore produced a chunk headed `Infobox`
with the article's own subject nowhere in its text — invisible to a search for the
thing it describes. The integration test found it; the fix binds the full section
path (`Gauntlet of Sorrowfell > Infobox`).

---

## D4 — Reliability is a ranking signal, never a filter

**Chosen:** eleven source tiers from `codex` (1.00) down to `ballad` (0.25),
classified structurally from the file's path. Reliability contributes 20% of the
keyword score and travels with every fact.

**Rejected:** dropping or hiding low-reliability sources.

**Why:** the archive is *built* around disagreement — the README warns that
in-world authors are unreliable. Deleting ballads would delete the conflicts that
several questions are actually about. A ballad may well be the best lexical match
for a query, and it must stay retrievable; reliability nudges the ranking and
informs confidence, it does not censor.

We wrote a test asserting a wiki article would outrank a ballad, and it failed.
The test was wrong, not the code: on that corpus the ballad genuinely was the
better lexical match. We rewrote the test to assert what we actually intend —
low-reliability sources stay retrievable, and source quality breaks ties.

---

## D5 — Deterministic graph and fact extraction before any LLM

**Chosen:** build the knowledge graph from evidence the corpus states explicitly —
wiki `[[links]]` and infobox/codex table rows — before reaching for a model.

**Why:** this yields 417 entities and 1,912 fully-cited edges with **zero
hallucination risk and zero API cost**. It also sets a real baseline: when LLM
extraction is added for prose-only sources in Phase 3, it has to earn its place
against something that already works, rather than being assumed to help.

Infobox edges are typed (`seated_at`, `forged_at`, `ruled_by`) and carry
confidence 0.9; generic wiki-link edges carry 0.6. Traversal prefers typed edges,
because those are what multi-hop questions actually follow.

**A gap this exposed.** Our first extractor only followed `[[wikilinks]]`, so the
codex — the *most authoritative* source in the archive — contributed no edges at
all, because it states values as plain text (`Ruling power | The Bleeding Crown`).
Typed edges went from 110 to 218 once we accepted name-shaped plain values.

---

## D6 — OCR is mandatory, not optional

**Chosen:** OCR the 17 scanned PDFs and the figure plates, storing per-chunk
confidence.

**Why:** we verified that the scans contain **zero extractable characters**, and
that most of them have **no twin in another format** — without OCR that content is
simply absent from the index. Separately, the Weeping Lurker's threat rating
appears in no table and no sentence in the entire archive: it is printed on
`plate_08_creature_weeping_lurker.png`. A text-only pipeline cannot answer that
question at all.

The adapter degrades honestly: if `tesseract` is absent it reports
`available = False` and ingestion says so in its summary, rather than silently
indexing empty pages and later answering "no evidence found".

---

## D7 — Refusing to assert values read off chart plates

**Chosen:** detect chart-style plates and extract **nothing** from them.

**Why:** several plates draw their value as a bar against a labelled axis. OCR
reads the axis ticks perfectly and the bar not at all, so
`"Attunement Cost 20 Novice tolerance Adept tolerance Master tolerance"` gives us
a number that is as likely to be an axis maximum as the answer. We would rather
report "not established" than publish a number we cannot justify.

The detector looks for two or more scale-legend markers (`tolerance`, `minimum`,
`standard`, `measured in`, `per the … scale`). This keeps ten plate facts we can
defend — including the Weeping Lurker's threat rating of 3 and Greyfell Citadel's
garrison of 3,095 — and discards four we could not.

**Proper fix, deferred:** a vision-model pass to read the plotted bar. Phase 2.

---

## D8 — Bounded state machine, not an autonomous agent

**Chosen:** the 1C loop is a state machine with hard limits on iterations,
queries, graph hops, stale rounds and wall-clock time, and it must report which
limit stopped it.

**Rejected:** an unconstrained "keep going until satisfied" agent.

**Why:** reproducibility and demonstrability. An unbounded loop cannot be
rate-limit-safe on a free API tier, cannot be debugged from a trace, and cannot be
safely demonstrated live. A budget stop is reported as *partial / low confidence*
and is never presented as certainty.

---

## D9 — Configuration in one place, secrets never in the repo

Fusion weights, chunk sizes and the investigation budget live in
`src/common/config.py`, read from the environment. They are configuration, not
claims of universal optimality — they change only when the evaluation harness
shows a consistent improvement across the development set, never to make one
question pass.

Keys are read from a git-ignored `.env`; `configuration-example/.env.example`
contains placeholders only.
