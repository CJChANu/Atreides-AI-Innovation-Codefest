# Limitations, failures and open gaps

Honest accounting of what does not work, what we tried that failed, and what we
deliberately chose not to do. Everything here is reproducible from the current
code against the real archive.

## What is not built yet

Phase 1 is complete. The following are designed but **not implemented**, and the
README does not claim otherwise:

- vector retrieval and the four-way score fusion (weights exist in config, unused)
- query understanding and sub-question decomposition
- the iterative investigation loop — the 1C core
- claim classification, confidence scoring, grounded answer generation
- the HTTP API and the user interface

## Known limitations in what *is* built

### Chart plates cannot be read
Several figure plates draw their value as a bar against a labelled axis. OCR
recovers the axis ticks and not the bar, so a number lifted from such a plate is
as likely to be an axis maximum as the answer. We detect these and extract
nothing rather than assert a value we cannot justify (see decision D7).

**Effect:** four plate facts we would like are unavailable — Emberdeep's garrison
total and the attunement costs on the Thrice-Bound Edge, the Thrice-Bound Lantern
and the Cinder-Wrought Aegis. Sample questions `1a_001`, `1a_004`, `1a_007` and
`1a_013` therefore cannot currently be answered from the plate.
**Planned fix:** a vision-model pass over the plate image (Phase 2).

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
