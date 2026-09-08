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

## D9 — Rule-based query understanding, not an LLM call

**Chosen:** parse the question by longest-matching against the 417 entities and
the fixed attribute set we actually indexed.

**Rejected:** an LLM structured-output call as the primary path.

**Why:** the archive's vocabulary is invented and *closed*. "Vharencrag Fortress"
is only recognisable because we indexed it — and a name we have not indexed is a
name we could not have cited anyway. Matching against the index is therefore both
more accurate than a general NER model and impossible to hallucinate with. It also
runs with no API key, no network and no rate limit, which is what makes a live
demonstration on a free tier safe.

An LLM pass can refine the parse when a key is configured, but it may only fill
gaps — it is not allowed to overrule an entity matched against the index.

---

## D10 — The loop decides hop direction from the data, not the grammar

"The faction that won the War of Drowned Light" and "the accord won by Ederon
Fellgard's faction" use the same two relations in opposite orders. Parsing that
distinction from English is fragile.

Instead we ask the index: whichever of the two relations the *named subject*
actually records is the first hop. This is one rule that handles both phrasings
and any future one, and it fails safely — if neither relation is recorded, the
question is reported as unanswerable rather than answered from the wrong end.

---

## D11 — Three retrieval directions, ordered by citability

A relationship is often recorded from one side only: a faction's wiki page may
carry no "Victor of" row while every war's page names its victor. The fact is in
the archive either way.

The loop therefore tries, in order: the forward fact, the inverse relation, the
reverse index (search from the other end), the graph, full text, then figure
plates. The ordering is by **how well each result can be cited**, not by how
likely each is to return something — a page-citable fact beats a plausible
passage every time.

---

## D12 — A step that retrieves passages but no value has *failed*

**The bug this fixes was ours.** An earlier version marked a sub-question
satisfied when full-text search returned passages, on the reasoning that we had
"found something". The result was answers reading:

```
ANSWER  Not established by the archive.
STOPPED BECAUSE  all required sub-questions are supported
```

That is the single most damaging thing a system like this can do — it converts a
gap into false confidence. Sub-questions now carry a separate `attempted` flag:
a step that was investigated and produced no citable value is recorded as failed,
the stop reason becomes `INSUFFICIENT_EVIDENCE`, and the answer is labelled
PARTIAL. There is a regression test.

---

## D13 — Confidence is bounded by structure, not by judgement

A single source is capped at 0.92 however authoritative it is — one record is one
record. Corroboration counts only across *distinct documents*, so the same codex
row appearing in two chunks is not two sources. Each hop costs 0.12, because each
link is another chance to have followed the wrong one. An unresolved conflict is
capped at 0.55.

A conflict is only reported as *resolved* when the reliability gap between the
competing sources is decisive (≥0.15). A codex against a ballad is settled; two
wiki articles against each other is a genuine open question, and saying so is more
useful than picking one.

---

## D14 — One AI gateway, never direct provider calls

**Chosen:** every external AI call goes through `src/ai_gateway`. No other module
may import a provider SDK or open a socket to one.

**Why:** retries, backoff, caching, timeouts, the circuit breaker, usage
accounting, schema validation and fallback all become properties of the *system*
rather than things each call site has to remember. It also means "what happens
when the LLM is down?" has one answer, in one file, that can be demonstrated.

The retry policy and the circuit breaker are separate on purpose. Retry handles
one call hitting a blip; the breaker handles the provider being *down*. Without
the breaker a six-iteration investigation against a dead endpoint costs six
timeouts and a live demo stalls; with it, the first failure trips the circuit and
every later call falls back instantly.

---

## D15 — Local LSA embeddings, and measured fusion weights

**Chosen:** Latent Semantic Analysis fitted on the archive itself, and a
lexical/semantic split of 0.50/0.30 rather than the plan's proposed 0.35/0.45.

**Why LSA rather than a hosted or pretrained embedding model:** the vocabulary is
invented. Nothing in a public embedding space knows that "Vharencrag" and
"fortress" co-occur, but this corpus does. LSA is also deterministic (a cited
answer reproduces for a judge), free, offline (a rate limit cannot break a live
demo), and builds the whole 2,547-chunk index in 7 seconds to 2.4 MB. When an
embedding API key is configured the adapter uses it instead and records the model
name in the index so the two are never silently mixed.

**Why the weights changed — and this one is worth reading.** On the 20 supplied
development questions, hybrid retrieval changed nothing: 10 cited answers with or
without the vector index. The honest reading is that those questions reuse the
archive's own vocabulary almost verbatim, so BM25 already wins them — it is a
property of the question set, not evidence about embeddings.

So we wrote a 10-question paraphrase probe, deliberately worded to avoid archive
vocabulary ("which side came out on top in the drowned light conflict"), and
measured document recall:

| split | R@1 | R@3 | R@5 |
|---|---|---|---|
| keyword only | 5/10 | 7/10 | 7/10 |
| 0.35 / 0.45 *(plan's proposal)* | **4/10** | 7/10 | 8/10 |
| **0.50 / 0.30 *(chosen)*** | **5/10** | 7/10 | **8/10** |

The plan's vector-leaning default *lost* a top-1 hit for no gain at depth 5.
At 0.50/0.30 the hybrid matches keyword-only on precision and beats it on recall.
`scripts/sweep_weights.py` reproduces the table, so the weights are evidence
rather than a guess.

---

## D16 — The LLM may add, never overrule

**Chosen:** LLM assistance is strictly additive, and every guard is code rather
than prompt instruction.

- A suggested entity is resolved through the archive index before it is accepted;
  a name the archive does not contain is dropped.
- An attribute or intent the rules already matched is never replaced.
- Relations outside the supported vocabulary are quarantined as candidates and
  shown in the trace, never traversed.
- An extracted claim must cite an evidence id *we supplied*, and its subject and
  value must actually occur in that passage. Rejections are written into the
  trace, because they are the visible evidence that the gate works.

**Why not just prompt carefully:** a prompt is a request; a validator is a
guarantee. The corpus is fictional and unavailable to any public model, so
anything the model "knows" about the Ashen Era is by definition invented.

---

## D17 — Configuration in one place, secrets never in the repo

Fusion weights, chunk sizes and the investigation budget live in
`src/common/config.py`, read from the environment. They are configuration, not
claims of universal optimality — they change only when the evaluation harness
shows a consistent improvement across the development set, never to make one
question pass.

Keys are read from a git-ignored `.env`; `configuration-example/.env.example`
contains placeholders only.
