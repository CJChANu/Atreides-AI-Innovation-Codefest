# Limitations, failures and open gaps

Honest accounting of what does not work, what we tried that failed, and what we
deliberately chose not to do. Everything here is reproducible from the current
code against the real archive.

## What is not built yet

Phases 1–3 are complete. The following are designed but **not implemented**, and
the README does not claim otherwise:

- vector retrieval and the four-way score fusion (weights exist in config, unused)
- the HTTP API and the web user interface
- LLM relation extraction over novel prose

## Where the loop currently fails

Measured on the 20 development questions — reproduce with `scripts/run_eval.py`:

| Sub-track | Cited answers | Notes |
|---|---|---|
| **1C** (our primary) | **2 / 2** | both are conflict-resolution questions |
| **1B** (our secondary) | **7 / 7** | |
| 1A (not our track) | 6 / 11 | the remaining 5 need a value that exists only as artwork |
| **total** | **15 / 20** | |

The distribution is the point: we are at 2/2 on the sub-track we targeted and 7/7
on the one we extended into. Two changes moved these numbers. 1A went from 2/11
to 6/11 when the chart-plate reader landed (see below): those four answers were
drawn as bars, and reading the drawing rather than the OCR text recovers them
exactly. 1B's last miss — "a relation stated only in prose" — closed when the
prose fallback landed: retrieval had always found the right passage, and what was
missing was the step that reads a value out of it.

The remaining 1A gap is an **ingestion** limitation, not a reasoning one — those
answers are painted rather than plotted (a banner emblem, an object held in a
portrait), and no amount of better searching recovers them without a vision model.

What the loop does instead of guessing: **each remaining miss names the exact
image file the user should open**, e.g.

```
ANSWER  Not established in text. The archive shows this on Heraldry plate:
        Faction House Morvain (atmo_heraldry_faction_house_morvain.png),
        but its content is pictorial — no label could be read from it.
        ⚠ PARTIAL
```

Every miss is reported as PARTIAL with an explicit stop reason. None is
presented as an answer.

## External API reality (measured 8 Sep 2026, on our own accounts)

Both keys work. Neither hosted service is usable at the scale this project needs
on a free tier, and the system is built to say so rather than hang.

| Service | Key status | What actually happens |
|---|---|---|
| OpenRouter (LLM) | works | `meta-llama/llama-3.3-70b-instruct:free` returns **404 — no longer free**. `nvidia/nemotron-3-super-120b-a12b:free` works and is now the default. Free-tier model IDs churn, so this is a `.env` setting by design. |
| Voyage (embeddings) | works | A single call returns correct 1024-dim vectors. Bulk indexing returns **429**: without a payment method the account is capped at **3 requests/min and 10,000 tokens/min** — about **two hours** for this corpus. |

**Consequence, and the decision:** the shipped vector index is local LSA. The
hosted path stays wired, tested and one config change away — `build_indexes.py`
times a hosted batch, estimates the full build, and falls back with a printed
reason if it would exceed two minutes:

```
note  hosted embeddings unavailable (HTTPError: HTTP Error 429); used local LSA
```

This is not a workaround for a missing capability. LSA is deterministic, offline
and free, which for a live demo on a rate-limited tier is worth more than a
marginal quality gain — and its benefit over keyword-only is measured (D15).

**What LLM assistance actually buys**, on the 20 development questions:

| | cited | answered | multi-hop found | ms/question |
|---|---:|---:|---:|---:|
| hybrid + loop | 15 | 15 | 5 | ~7 |
| hybrid + loop + LLM | 15 | 15 | 5 | ~1,400 |

It adds **no cited answers** — the citations come from the fact store either way,
which is the intended design — and it costs roughly 200× the latency. Earlier
measurements credited it with three extra multi-hop chains; those are now found
deterministically, by the prose fallback and the multi-fact decomposition, so the
LLM's remaining contribution on this question set is phrasing, not coverage.

That is the point of the fallback path rather than an apology for it: when the
free tier rate-limits us mid-demo — and it does — the deterministic run answers
exactly as many questions, with the same citations. Results still vary slightly
between runs, because a rate-limited call falls back; that variance is visible in
the trace as fallback events.

## Known limitations in what *is* built

### Multi-part questions are split, but only on facts
A question asking for several things is decomposed into one sub-question per
requested `(subject, attribute)` pair, and the answer is withheld until every one
has been searched for. That covers comparisons ("the threat ratings of A and B"),
repeated attributes on one subject ("where *and in which year* was it forged"),
and calculations.

It does **not** cover sub-clauses that are not attribute lookups. "Did its forging
site appear in two conflicts, and was the housing location affected by either?"
decomposes to the facts it names — forging site, housing — and the reasoning
about conflicts falls through to full-text retrieval. The parts that *are*
lookups are answered and cited; the rest is retrieved as context and reported as
unresolved rather than being asserted.
**Planned fix:** clause-level decomposition, where each conjunct is analysed as
its own question and may itself be a hop or a conflict check.

### Attribute routing is a fixed policy, not a learned one
Which source can answer which attribute is a hand-written set
(`plate_facts.FIGURE_ATTRIBUTES`): measurements come from plates, everything else
from tables and prose. This is what stops the system searching a portrait for a
relic's housing location. It is also a list someone has to maintain — a new
numeric attribute added to the archive would be looked for in text only until the
set is updated.

### The prose fallback reads a fixed set of phrasings
`prose_facts.py` reads a value out of a sentence when no table records it, which
is how the Cinder-Wrought Aegis' forging year (stated once, in a contract about a
different relic) becomes answerable. Each pattern requires the archive's own
wording around the value and the subject named in the same sentence, or in the one
immediately before it.

The cost of that strictness is recall: a value stated in a phrasing we have not
seen is still missed, and the module will not guess from a bare number near a
name. Sentences that hedge — "the forged year is contested among sources" — are
deliberately skipped, so a documented disagreement is never read as a fact. Table
values always win over prose, because a table is a stated record.

### Question phrasings the analyzer does not cover
Attribute matching is phrase-based against a fixed vocabulary. Phrasings with no
attribute phrase at all ("what object are they holding") fall through to
`open_question` and full-text search, which retrieves the right article but cannot
extract a value from it.
**Planned fix:** LLM-assisted attribute matching as a *fallback* behind the
rule-based path, so it can only ever add coverage, never overrule an index match.

### Pictorial plates cannot be described
Heraldry paintings and portraits carry no printed labels, so there is nothing for
OCR to recover — and OCR over artwork returns convincing garbage
("f ti teh Walia i { =| | eee"). We only quote a plate when its text contains a
*recognised label*, and otherwise report the plate as pictorial and name the file.
**Planned fix:** a vision-model pass over heraldry and portrait plates (Phase 2).

### Chart plates: now read geometrically (was: could not be read)
Several figure plates draw their value as a bar against labelled reference bars.
Plain OCR recovers the reference numbers and not the bar, so a number lifted from
the text alone is as likely to be a scale tick as the answer — which is why
`extract_plate_facts` still refuses them (decision D7).

`src/graph/plate_chart.py` now reads them from the drawing instead. Bars are
solid rectangles, so their pixel length is exact; the subject's bar is drawn in
its own colour and labelled with the subject's *name*, while the references carry
tier names. Fitting length against the reference values calibrates a scale that
the subject's bar is then read against.

The calibration is also an error check, and it earns its keep: tesseract misreads
this archive's stylised digits often enough to matter — it returns "25" for the
Thrice-Bound Lantern's bold "55", and "95" for a "55" reference on the
Thrice-Bound Edge plate. Neither survives the geometry, because a bar shorter
than the "85" bar cannot be a 95. The line is therefore fitted pairwise and the
outliers dropped, and a value is reported only when the drawing and the printing
agree — or, on a small integer scale, when the drawing alone lands cleanly on a
step and the disagreement is stated in the trace.

**Effect:** all five chart plates now yield facts — Emberdeep's garrison strength
(1,114), the Marsh Revenant's threat rating (4), and the attunement costs of the
Thrice-Bound Edge (94), the Thrice-Bound Lantern (55) and the Cinder-Wrought
Aegis (34). The Aegis' cost exists nowhere else in the archive.

**Still limited:** the reader needs at least two reference bars and a subject bar
in a distinct colour. A chart drawn any other way, or one whose subject bar is
unlabelled, returns nothing and falls back to naming the plate as before. It also
never *invents* precision: above a small integer scale the geometry is
proportional only, so an unreadable printed number means no answer rather than an
estimate.

### Multi-line table cells are truncated
The fact extractor matches key/value rows line by line, so a codex cell that wraps
across two lines keeps only the first. Example, from p.41 of the bestiary:
`Manifestation | Hidden, indistinct form accompanied by the` — the continuation
`unmistakable image of weeping` is dropped from the *fact*, though it remains in
the chunk text and is fully retrievable.
**Planned fix:** join continuation lines before matching.

### PDF section paths are heuristic
PDFs carry no structure tags, so headings are recovered by a shape heuristic
(short, title-cased, unpunctuated). It is right often enough to be useful and
wrong sometimes. This costs a section *label*; it never costs a page citation,
because page numbers come from the page itself.

### OCR errors are recorded but not corrected
Scanned pages average ~0.95 word confidence, and the errors are visible in the
output (`Attunement Cos` for `Attunement Cost`, a leading `ithe` for `The`). We
store per-chunk confidence but do not yet use fuzzy matching or alias expansion to
recover from these at query time.
**Planned fix:** fuzzy alias resolution in the retrieval layer (Phase 2).

### The graph is only as complete as its explicit sources
Edges come from wiki links and table rows. Relations stated only in novel prose —
which is where much of the causal history lives — are not yet in the graph. This
is mitigated by searching text and graph together, and by treating the graph as an
accelerator rather than the sole truth, but a purely narrative multi-hop chain
would currently be missed.
**Planned fix:** LLM relation extraction over chronicle prose, benchmarked against
the deterministic baseline (Phase 3).

### The loop cannot chain more than two hops
Decomposition builds at most one bridge step. A three-hop question ("who leads the
faction that rules the region containing X") would resolve two hops and then
report the third as unsupported — correctly, but incompletely.
**Planned fix:** recursive bridge steps bounded by `AEA_MAX_GRAPH_HOPS`, which is
already in the configuration and currently unused by the loop.

### Conflict detection is exact-match after normalisation
Two facts conflict when their normalised values differ. It therefore catches
`391 AS` vs `Contested` and ignores `Contested` vs `contested`, but it would not
recognise `391 AS` and `the three hundred and ninety-first year` as the same
claim, nor `c. 390 AS` as compatible.

### No entity disambiguation across similar names
The archive contains `Maelis Wrenfield`, `Maelis Greyfen` and
`Maelis Harrowick the Pale`; also `Ederon Fellgard` and `Ederon Coldwater`.
Normalisation keeps these distinct, which is correct, but we do not yet detect
when a source uses a bare first name. A question about "Maelis" alone would
retrieve all three without ranking between them.

## What we tried that did not work

### Marking a sub-question satisfied because *something* was retrieved
The loop originally satisfied a step whenever full-text search returned passages.
That produced answers reading "Not established by the archive" directly above
"all required sub-questions are supported" — a gap presented as confidence, which
is the worst failure mode available to a system whose whole claim is groundedness.
Sub-questions now separate `attempted` from `satisfied`; a step with no citable
value fails, and the answer is labelled PARTIAL. Regression test:
`test_an_unanswerable_question_is_not_reported_as_supported`.

### Reading the hop direction out of the question's grammar
Our first hop planner assumed the first relation mentioned was the first hop. That
answers "the accord won by Ederon Fellgard's faction" correctly and "the faction
that won the War of Drowned Light" backwards. Rather than add grammar rules, we
ask the index which relation the named subject actually records. One rule, both
phrasings.

### A generic "does this look like language" test for OCR output
Our first guard against artwork OCR required three-plus real words and a high
alphanumeric ratio. The heraldry noise `"f ti teh Walia i { =| | eee | (i"` passes
both — it has three "words" and an 81% ratio — and was surfaced as an answer. We
replaced the heuristic with a rule that matches how the rest of the system works:
a plate is quotable only when we can identify *what its text is labelling*, via a
known label phrase. Anything else is a picture we can point at but must not
paraphrase.

### Deriving the displayed answer from the rendered evidence chain
A convenience that broke as soon as reverse lookup landed: in a forward lookup the
answer is the fact's *value*, but in a reverse lookup it is the fact's *subject*.
Parsing the last chain line gave the right string for one and the wrong one for
the other. The answer is now set explicitly by whichever step produced it.

### Extracting tables before text on a PDF page
Our first PDF parser emitted each page's tables and then its text. The codexes put
the entity name in a heading *directly above* its table, so this orphaned every
codex table from the only thing that says what it describes — subjects fell back
to the document title, and `Codex Vaeloria II` became the subject of 227 tables.
Reordering to text-then-tables, and binding the page's first heading-shaped line
into the table's caption and section path, fixed it.

### Following only `[[wikilinks]]` for typed edges
The infobox edge extractor originally required a wiki link in the value. Codex
tables state values as plain text, so **the most authoritative source in the
archive contributed no typed edges at all**. Accepting name-shaped plain values
(capitalised, no digits) took typed edges from 110 to 218.

### Asserting a source-reliability ordering in a retrieval test
We wrote a test asserting that a wiki article outranks a ballad for the same
query. It failed: on that corpus the ballad genuinely was the better lexical
match. The test was wrong, not the code — reliability is a 20% nudge, and making
it dominant would hide exactly the low-reliability sources that reveal conflicts.
We rewrote the test to assert the property we actually want.

### Binding only the nearest heading during chunking
A wiki article consisting of an infobox produced a chunk headed `Infobox`, with
the article's own subject absent from its text — invisible to a search for the
thing it describes. Caught by the integration test; fixed by binding the full
section path.

## Deliberate non-goals

- No external world knowledge. The world is invented; an answer that is not in the
  archive must be reported as unsupported, not filled in.
- No hidden chain-of-thought. The trace is an audit record of observable actions —
  queries issued, evidence retrieved, edges traversed, why it stopped.
- No question-specific rules. Final judging uses an unpublished question set, so
  tuning to the twenty development questions would be self-defeating.
