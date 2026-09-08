# The investigation protocol

How the assistant searches the way a human expert does — and, just as important,
how it knows when to stop.

## The loop

```
understand → decompose → ┌ search → extract → expand → assess ┐ → verify → answer
                         └───────── re-plan ─────────────────┘
```

Every iteration records what it did, what it learned, what is still missing, and
why it chose the next action. That record *is* the trace the user sees — there is
no separately-written explanation that could drift from what happened.

## 1. Understand

Rule-based, against what we actually indexed. The archive has a closed vocabulary
— 417 entities and a fixed attribute set — so longest-match against the index is
both more accurate and more auditable than a general NER model, and it works with
no API key.

The output is an `Intent`:

| Intent | Trigger | Example |
|---|---|---|
| `attribute_lookup` | entity + attribute | "the garrison strength of Greyfell Citadel" |
| `conflict_resolution` | + a conflict marker | "in which year was X **actually** forged" |
| `relation_hop` | two relations | "whose dominion encompasses the **lair of** X" |
| `inverse_hop` | attribute, no entity | "which faction has X as a member" |
| `open_question` | anything else | falls back to full-text retrieval |

**Conflict markers** — *actually, truly, precise, in fact, definitive* — are the
tell for a 1C question. The asker already suspects the sources disagree, and both
1C development questions use one.

**Hop orientation is decided by the data, not by grammar.** "The faction that won
the War of Drowned Light" and "the accord won by Ederon Fellgard's faction" use
the same two relations in opposite orders. Rather than parse that, we ask which
relation the named subject actually records, and make that the first hop.

## 2. Decompose

Each question becomes sub-questions **with explicit completion conditions**.
Without the completion condition the loop cannot distinguish *answered* from
*attempted*, and a two-hop question stops at the definition.

A hop question, for example:

| Step | Sub-question | Completion condition |
|---|---|---|
| `locate` | What does the archive record about X? | at least one recorded fact |
| `bridge` | What is X's *lair*? | a value that names a known subject |
| `target` | What is *that subject's* ruler? | a value for the target attribute |
| `conflict` | Do sources disagree on any step? | every step checked |

A conflict-resolution question adds a `resolve` step: *which recorded value is the
most authoritative?*

## 3. Search — three directions, tried in citability order

For each unsatisfied sub-question the loop picks an action and issues one query.
The retrieval attempts are ordered by how well each can be cited, not by how
likely each is to return something:

1. **Forward fact lookup** — `subject.attribute`. Directly citable to a page.
2. **Inverse relation** — a war names its `victor`; a faction lists what it is
   `victor_of`. Reading the stored row from the other end is the same assertion.
3. **Reverse index** — search *from the other end*: which subjects record this
   attribute pointing at our subject? A faction's page may carry no "Victor of"
   row while every war names its victor. The fact is in the archive either way.
4. **Graph neighbours** — typed edges first.
5. **Keyword/BM25** — full-text, as context.
6. **Figure plates** — when the text record says "None recorded", that is often
   the archive pointing at an illustration.

## 4. Expand

When a `bridge` step resolves a value into a known subject, that subject becomes
the search target for the next iteration. **This is the whole point of the loop.**
The trace makes the dependency explicit:

```
[2] fact_lookup  query: 'Gravemaw Wyrm lair'
    why : the question asks about the lair before its ruler; that link must
          be resolved first
    learned      : Gravemaw Wyrm · lair = Marrowwell Abbey
    new entities : Marrowwell Abbey
[3] fact_lookup  query: 'Marrowwell Abbey ruled by'
    why : follow the discovered link to Marrowwell Abbey and read its ruled by
```

Query 3 could not have been written before query 2 returned.

Multi-valued results are narrowed by a constraint word from the question: "which
**accord** was won" must not answer with a war, even when the faction won both.

## 5. Assess and stop

The loop stops for exactly one of six reasons, and it always says which:

| Stop reason | Meaning | Answer labelled |
|---|---|---|
| `ALL_SUPPORTED` | every sub-question satisfied | complete |
| `INSUFFICIENT_EVIDENCE` | investigated, nothing found | **partial** |
| `NO_NEW_EVIDENCE` | two consecutive rounds added nothing | **partial** |
| `NO_ENTITY` | nothing in the question matches the index | **partial** |
| `ITERATION_BUDGET` / `QUERY_BUDGET` / `TIME_BUDGET` | ran out of room | **partial** |

A step that retrieves passages but no citable value is marked **failed, not
satisfied**. This matters: an earlier version satisfied such steps and produced
answers reading "all required sub-questions are supported" directly above "not
established by the archive". There is now a regression test for it.

## 6. Verify

Every claim is classified:

- **direct** — a source states it;
- **inferred** — it follows from a chain of stated facts (every hop target);
- **conflicting** — sources disagree, and both positions are carried;
- **unsupported** — nothing grounds it, so it never reaches the answer text.

Confidence is bounded by structure rather than judgement: a single source is
capped at 0.92 however authoritative, corroboration counts only across *distinct
documents*, each hop costs 0.12, and an unresolved conflict is capped at 0.55.

A conflict is only called resolved when the reliability gap between the competing
sources is decisive. Two comparable sources disagreeing is a genuine open question
and is reported as one.

## 7. Answer

Assembled from verified claims — not written by a language model. Every sentence
traces to a fact row naming its document and page, so there is no path by which a
fluent but ungrounded statement reaches the user.

Order is deliberate: **answer, evidence, conflicts, trace, stop reason.** A reader
who trusts the system should not have to scroll; a reader who does not should be
able to check every step.
