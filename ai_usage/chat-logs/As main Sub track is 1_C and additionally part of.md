<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# As main Sub track is 1:C and additionally part of 1:B, our solution is given below for that we need to create standard solution plan with including our solution, what are the system or AI system components and how should be the system work.

1. Ingest the archive
Read all PDFs, DOCX, Markdown, plain text, scans, tables, and images.
Preserve document ID, page number, section, and source type for every chunk.
Extract tables and images separately and link them to their pages.
2. Build three indexes
Keyword index for exact names and terms.
Vector index for semantic similarity.
Knowledge graph for entities and relationships.
This hybrid approach prevents dependence on only one retrieval method.
3. Understand the question
Identify main topic, entities, and expected answer type.
Break complex questions into sub-questions.
Determine required relationships and whether multiple search steps are needed.
4. Plan the investigation
Create a search plan based on sub-questions.
Decide which entities to search first.
Prepare to expand through the graph after initial results.
5. Search iteratively (Sub-track 1C core)
Repeat the following loop:
Search using current query and known entities.
Extract new entities, relationships, and claims.
Expand through the knowledge graph to connected facts.
Check which sub-questions still lack evidence.
Generate the next search query based on missing information.
Stop when all required facts are supported or when no new evidence appears.
6. Verify evidence
Ensure every major claim has a source and page reference.
Detect contradictions between sources.
Classify claims as direct, inferred, conflicting, or unsupported.
Apply source reliability rules (codex > wiki > ballad, etc.).
7. Generate grounded answer
Produce a structured response containing:
Concise answer.
Evidence chain showing how facts connect.
Document and page citations for each claim.
Confidence level for each part of the answer.
Explanation of any conflicts or uncertainties.
Reason why the investigation stopped.
8. Show the investigation to the user
Display:
Final answer first.
Search steps taken.
Evidence supporting each claim.
Knowledge graph connections used.
Conflicting sources if any.
Why the assistant concluded the search.

create the improved technical solution plan with architecture diagrams and all the things included document PDF and Docx

Created the complete technical solution plan with:

- Hybrid PDF/DOCX/Markdown/TXT/scan/table/image ingestion.
- Page- and section-level provenance tracking.
- Keyword, vector, and knowledge-graph indexes.
- Iterative Sub-track 1C investigation loop.
- Multi-hop Sub-track 1B relationship expansion.
- Query decomposition and search planning.
- Evidence verification and contradiction detection.
- Confidence scoring and source-reliability handling.
- Grounded answer generation with citations.
- User-visible investigation trace.
- System architecture and workflow diagrams.
- Data models, API design, technology stack, testing strategy, demo plan, repository structure, team responsibilities, limitations, and implementation phases.

The detailed report is available in the generated document.

<span style="display:none">[^1_1][^1_2]</span>

<div align="center">⁂</div>

[^1_1]: AI_Competition_Challenge_Final.pdf

[^1_2]: Document Corpus link.txt


---

# create the next version of improved technical solution plan with architecture diagrams and all the things included document PDF and Docx

Version 2 Solution Idea

1. Ingest the archive
Read every archive format:
PDFs with selectable text.
Scanned PDFs.
DOCX files.
Markdown files.
Plain-text files.
Tables.
Images, figure plates, maps, diagrams, heraldry, and charts.
For every extracted item, preserve:
Document ID.
Original file path.
Source type.
Page number or line range.
Section/heading.
Table ID or figure/image ID.
OCR confidence where OCR was used.
Source reliability category.
Original asset reference.
Extract tables and images as separate evidence objects, but link them to their original document, page, nearby text, caption, and section.
2. Build four knowledge indexes
Build four complementary indexes instead of relying on one search method:
Keyword index for exact fictional names, dates, titles, numbers, aliases, and table values.
Vector index using an embedding model for semantic similarity, paraphrases, and differently worded questions.
Knowledge graph for entities and relationships across the archive.
Fact and claim store for structured facts, evidence links, conflicts, source reliability, and confidence.
This hybrid approach prevents failure when a fact is missed by one retrieval method.
Exact name or date → Keyword/BM25 search
Paraphrased user question → Vector semantic search
Cross-document connection → Knowledge graph traversal
Structured table fact → Fact store lookup
Conflicting claims → Claim/conflict store
3. Create the AI service layer
Use external AI services as controlled tools, not as the source of truth.
Add:
LLM API for question understanding, planning, query rewriting, candidate fact extraction, answer writing, and optional visual reasoning.
Embedding model/API for vector search.
Optional vision-capable model for diagrams, maps, charts, symbols, figure plates, and images that OCR cannot understand.
Optional reranker to choose the strongest evidence from keyword and vector search results.
The AI model must never answer from its own general knowledge. It can only reason over evidence retrieved from the archive.
4. Understand the question
When a user asks a question, use both rules and an LLM to understand it.
Identify:
Main topic.
Known entities.
Possible aliases.
Relations being asked about.
Expected answer type.
Required evidence.
Whether it is a direct lookup, conflict-resolution question, multi-hop question, visual question, comparison, timeline question, or impact-analysis question.
Whether multiple investigation steps are necessary.
For example:
Question:
“Who rules the place where the Gravemaw Wyrm lives?”

Structured understanding:

- Main entity: Gravemaw Wyrm
- Required relation 1: lair / location
- Required relation 2: ruled by
- Answer type: faction or ruler
- Multi-hop required: yes
- Required evidence:

1. Evidence for the Wyrm’s location
2. Evidence for who rules that location
The LLM produces structured JSON, but the system validates all entities and relations against the archive indexes.

5. Plan the investigation
Create an investigation plan from the structured question.
The planner should:
Break the question into answerable sub-questions.
Decide which fact or entity to search first.
Select the best retrieval routes.
Create exact, semantic, relation-based, alias-based, and graph-neighbor query variants.
Define what evidence is required before each sub-question is considered solved.
Decide whether tables, figures, OCR, or vision analysis should be checked.
Set limits for iterations, graph hops, LLM calls, time, and query count.
Example plan:
Main question:
Who rules the place where the Gravemaw Wyrm lives?

Sub-question 1:
Where is the Gravemaw Wyrm’s lair?

Sub-question 2:
Who rules the location found in sub-question 1?

Sub-question 3:
Do authoritative sources disagree about the ruling faction?

Completion conditions:

- A page-cited source supports the Wyrm’s location.
- A page-cited source supports the location’s ruler.
- Conflicts have been checked.

6. Search iteratively across the archive
This is the core Sub-track 1C behavior.
Repeat the following loop:
Search the current sub-question using:
Exact fact lookup.
Keyword/BM25 search.
Vector semantic search.
Knowledge graph traversal.
Linked tables and figures.
OCR results.
Vision analysis when relevant.
Merge, deduplicate, and rerank the evidence candidates.
Read the strongest retrieved evidence.
Use the LLM to extract candidate entities, relationships, facts, and missing information from retrieved passages.
Validate candidate claims against the original chunk, table, figure, or image.
Add verified entities and relationships to the investigation state.
Expand through the graph when newly discovered entities create the next search direction.
Check which sub-questions are still missing valid evidence.
Ask the LLM for the next targeted query only when there is a defined evidence gap.
Stop when:
All required evidence is supported.
No useful evidence appears after repeated searches.
The configured investigation budget is reached.
The user asks for a shorter answer.
The system must record every iteration so the user can see what it searched and why.
7. Extract and verify claims
The LLM can extract candidate claims from prose, but the system must verify every one.
For each claim, store:
Subject.
Predicate/relation.
Object/value.
Claim type.
Source chunk/table/figure.
Page or line range.
Evidence text span.
Extraction method.
Source reliability.
OCR/vision confidence where applicable.
Claim confidence.
Verification status.
Classify every claim as:
Direct — explicitly stated in a source.
Inferred — derived from a documented chain of verified facts.
Conflicting — supported by sources that disagree.
Unsupported — suggested by the LLM but not proven by archive evidence.
Unsupported claims must never appear as factual answers.
8. Resolve conflicts and calculate confidence
Detect conflicts when sources provide different values for the same relationship.
For example:
Question:
When was Gloamreach founded?

Codex:
246 AS

Wiki:
Contested

System response:
The Codex records Gloamreach as founded in 246 AS, while the wiki
marks the date as contested. Because the codex is the more authoritative
source under the configured reliability policy, 246 AS is the best-supported
answer, but the archive contains a conflicting secondary record.
Apply source reliability rules:
Official codex/data record → highest reliability
Primary official document → high reliability
Wiki article → secondary reliability
Novel narrative → useful contextual evidence
Letter/ledger/trial transcript → assess speaker and context
Ballad/rumor → low reliability unless corroborated
Confidence should depend on:
Source reliability.
Number of independent supporting documents.
Whether the claim is direct or inferred.
Number of graph hops.
OCR confidence.
Vision-analysis confidence.
Presence of unresolved conflicts.
Evidence quality and citation validity.
9\. Handle visual evidence properly
For images, diagrams, maps, heraldry, and charts:
Retrieve the original figure/image.
Read caption and nearby text.
Use OCR.
If OCR is insufficient, call a vision-capable model.
Store the visual model’s structured observation with the figure ID and page.
Verify whether the observation is supported by labels, caption, nearby text, or repeated visual evidence.
Show uncertainty when the image cannot be read reliably.
Do not make up visual facts.
Example:
Safe response:
“The answer is not established in readable text. The relevant evidence appears
to be pictorial on Heraldry Plate: House Morvain. The image is available for
manual review.”

Careful visual response:
“A vision model identifies a black stag-like central emblem on the House Morvain
banner, but the plate contains no readable confirming label. This should be
treated as partial visual evidence.”
10\. Generate a grounded answer
Generate the final answer only from verified claims.
The LLM may make the response clear and natural, but it must receive only:
Verified direct claims.
Verified inferred claim chains.
Valid citations.
Conflicts.
Confidence values.
Stop reason.
Relevant tables/figures/images.
The answer should include:
Concise direct answer.
Evidence chain showing how facts connect.
Page-level citations.
Claim type: direct, inferred, conflicting, or partial.
Confidence for each major claim.
Conflicts and uncertainty.
Relevant table, image, figure, or source page.
Investigation stop reason.
Example:
Answer:
The Bleeding Crown rules the territory where the Gravemaw Wyrm lairs.

Evidence chain:

1. The Gravemaw Wyrm’s lair is identified as Marrowwell Abbey
[Codex of Beasts, p.12].
2. Marrowwell Abbey is recorded as ruled by the Bleeding Crown
[Regional Codex, p.34].

Claim type:
Inferred from two direct cited facts.

Confidence:
High.

Investigation stop reason:
Both required sub-questions have page-cited evidence and no unresolved
conflict was found.
11\. Build API and user interface
Create a real product interface, not only a command-line script.
The user interface should show:
Search box for questions.
Final answer first.
Citations as clickable page/document references.
Evidence chain.
Direct/inferred/conflicting claim labels.
Confidence and uncertainty.
Source reliability.
Conflicts.
Related documents.
Openable pages, tables, figures, and image assets.
Investigation timeline.
Search queries performed.
Knowledge graph path.
Stop reason.
Whether the system used LLM assistance or deterministic fallback.
API endpoints should provide:
POST /api/questions
GET /api/investigations/{id}
GET /api/investigations/{id}/trace
GET /api/investigations/{id}/evidence
GET /api/investigations/{id}/graph
GET /api/documents/{document_id}
GET /api/documents/{document_id}/pages/{page}
GET /api/assets/{asset_id}
GET /api/indexes/status
GET /api/health
12\. Add reliability, security, and fallback controls
The product must be reliable even when APIs fail.
Implement:
API keys only in environment variables.
No secrets in Git, logs, screenshots, or error messages.
LLM output JSON validation.
Embedding/vector index versioning.
Prompt version tracking.
Model/provider version tracking.
Caching for embeddings, LLM plans, reranking, visual analysis, and completed investigations.
Exponential retry/backoff for rate limits and transient failures.
Timeout limits.
Circuit breakers for repeated API failures.
Investigation budgets.
Duplicate query prevention.
Safe deterministic fallback mode.
When APIs fail:
LLM unavailable:
Use rule-based question understanding and deterministic planner.

Embedding service unavailable:
Use FTS5, fact store, and graph retrieval.

Vision unavailable:
Use OCR/caption/nearby text and report visual uncertainty.

Reranker unavailable:
Use transparent weighted hybrid score.
The system must never fail by hallucinating when an external API is unavailable.
13\. Evaluate the complete product
Compare these modes:
Keyword-only retrieval.
Vector-only retrieval.
Keyword + vector hybrid retrieval.
Hybrid retrieval + graph expansion.
Deterministic investigation loop.
LLM-assisted hybrid investigation loop.
Full multimodal system with visual evidence support.
Measure:
Cited-answer coverage.
Citation correctness.
Relevant page/document recall.
Semantic/paraphrase retrieval success.
Multi-hop completion.
Conflict detection.
Unsupported claim count.
Visual evidence accuracy.
OCR failure handling.
API failure fallback success.
Latency.
Cost per question.
Reproducibility.
Final product idea
Build a multimodal archive intelligence platform that reads, indexes, searches, connects, and verifies information across PDFs, scans, documents, tables, images, and narrative sources. Use LLMs and embeddings to understand natural language, find paraphrased evidence, plan investigations, extract candidate claims, analyze visual material, and write clear explanations. Use deterministic provenance, graph/fact logic, conflict detection, reliability policies, and citation validation to ensure the assistant never treats an AI-generated statement as archive truth without evidence.

Version 2 of the technical solution plan has been created.

It includes:

- Full PDF, scanned PDF, DOCX, Markdown, TXT, table, image, map, diagram, chart, and heraldry ingestion.
- Complete document and asset provenance tracking.
- Four knowledge indexes:
    - Keyword/BM25 index.
    - Vector index.
    - Knowledge graph.
    - Fact, claim, and conflict store.
- Controlled AI service layer for:
    - LLM question understanding.
    - Investigation planning.
    - Claim extraction.
    - Embeddings.
    - Reranking.
    - Optional vision analysis.
- Structured question understanding and sub-question decomposition.
- Iterative Sub-track 1C investigation workflow.
- Multi-hop Sub-track 1B graph traversal.
- Claim verification and classification.
- Source reliability and contradiction resolution.
- Confidence calculation.
- Visual evidence and uncertainty handling.
- Grounded answer generation.
- API endpoint specifications.
- Product-style UI layout.
- Security controls and API failure fallbacks.
- Evaluation metrics and ablation testing.
- Technology stack.
- Repository structure.
- Team responsibilities.
- Demonstration plan.
- Implementation roadmap.
- Limitations and mitigation strategies.
- Multiple architecture and workflow diagrams.

The full Version 2 report is available as the generated document.

<span style="display:none">[^2_1][^2_2]</span>

<div align="center">⁂</div>

[^2_1]: AI_Competition_Challenge_Final.pdf

[^2_2]: Document Corpus link.txt


---

# Final Consolidated Technical Solution Plan

## Multimodal Archive Intelligence Assistant

**Primary track:** Sub-track 1C — Searching the Way a Human Does\
**Additional track:** Sub-track 1B — Connecting Facts Across Thousands of Pages\
**Supporting capability:** Sub-track 1A-style multimodal evidence retrieval

## 1. Executive Summary

The proposed system is a provenance-first, multimodal archive intelligence assistant for the Ashen Era Archive. It ingests PDFs, scanned PDFs, DOCX, Markdown, plain text, tables, figures, maps, diagrams, images, and other archive assets. It preserves document and page-level provenance, builds four complementary indexes, understands complex questions, plans and executes bounded iterative investigations, connects facts across documents, verifies claims, detects conflicts, and generates answers only from verified archive evidence.

The archive is fictional and deeply interconnected; therefore, general model knowledge is not a valid source of truth. The official challenge describes approximately 415 documents and 1,277 pages in mixed formats, including novels, wiki articles, codexes, ephemera, scans, tables, and images. It also states that sources may differ in reliability.[^3_1]

The central design rule is:

> AI services may interpret, plan, rank, extract, and explain. They may never become the source of truth. The archive and its verified evidence objects remain the source of truth.

## 2. Problem and Scope

### Problem

Important facts may be spread across narrative text, tables, scanned pages, diagrams, maps, images, and records. A single similarity search may retrieve only one part of an answer. The assistant must behave like a human investigator: find an initial fact, identify what is missing, use the discovered information to search again, connect evidence across documents, and stop only when the answer is adequately supported.

### Track mapping

| Capability | Role |
| :-- | :-- |
| Sub-track 1C | Primary: iterative planning, searching, evidence-gap detection, and stopping |
| Sub-track 1B | Multi-hop entity and relationship linking across documents |
| Sub-track 1A | Supporting ability to retrieve and display tables, figures, maps, diagrams, and images |

### Goals

- Read all supplied archive formats.
- Preserve complete provenance for every evidence object.
- Build keyword, vector, graph, and fact/claim indexes.
- Understand direct, multi-hop, visual, comparison, timeline, impact, and conflict questions.
- Execute bounded iterative searches.
- Verify claims against original evidence.
- Explain source conflicts and uncertainty.
- Display page citations, evidence chains, graph paths, and investigation traces.
- Continue safely when external AI services fail.


### Non-goals

- General web search.
- Using external world knowledge to fill archive gaps.
- Presenting unsupported LLM suggestions as facts.
- Hiding conflicts or budget-based stopping.
- Modifying the read-only corpus.


## 3. High-Level Architecture

```text
+--------------------------------------------------------------------------------+
|                              USER INTERFACE                                   |
| Search | Answer | Citations | Evidence chain | Graph | Timeline | Conflicts    |
| Page viewer | Table viewer | Figure viewer | Confidence | Fallback status      |
+------------------------------------------+-------------------------------------+
                                           |
                                           v
+--------------------------------------------------------------------------------+
|                              APPLICATION API                                  |
| Question API | Investigation API | Document API | Asset API | Health/Index API |
+------------------------------------------+-------------------------------------+
                                           |
                                           v
+--------------------------------------------------------------------------------+
|                         INVESTIGATION CONTROL PLANE                            |
| Understand -> Decompose -> Plan -> Search -> Extract -> Verify -> Expand       |
|             -> Check gaps -> Continue or Stop -> Generate                       |
| Budgets | Cache | Retry | Circuit breaker | Duplicate prevention | Fallback   |
+----------------------+-------------------+-------------------+-------------------+
                       |                   |                   |
                       v                   v                   v
+----------------------+--+    +----------+----------+    +----------------------+
| Retrieval Orchestrator |    | AI Service Gateway   |    | Verification Engine  |
| keyword | vector       |    | LLM | embeddings     |    | claim validation     |
| fact | graph | visual  |    | reranker | vision    |    | conflicts | confidence|
+------------+-----------+    +-----------------------+    +----------+-----------+
             |                                                           |
             v                                                           v
+--------------------------------------------------------------------------------+
|                              FOUR INDEXES                                     |
| Keyword/BM25 | Vector embeddings | Knowledge graph | Fact/claim/conflict store  |
+------------------------------------------+-------------------------------------+
                                           |
                                           v
+--------------------------------------------------------------------------------+
|                         CANONICAL EVIDENCE STORE                              |
| Chunks | OCR text | Tables | Figures | Images | Captions | Metadata | File hash |
+------------------------------------------+-------------------------------------+
                                           |
                                           v
+--------------------------------------------------------------------------------+
|                           INGESTION PIPELINE                                  |
| PDF | scanned PDF | DOCX | Markdown | TXT | tables | maps | diagrams | charts  |
+--------------------------------------------------------------------------------+
```

The data plane stores archive-derived objects. The control plane coordinates question understanding, retrieval, graph traversal, verification, fallbacks, and answer generation. This separation allows indexes to be rebuilt independently and investigations to be reproduced against a fixed archive version.

## 4. Ingestion and Provenance

### Supported inputs

| Input | Processing | Evidence object |
| :-- | :-- | :-- |
| Selectable PDF | Text extraction with page boundaries | Page-aware text chunks |
| Scanned PDF | Page rendering, OCR, OCR confidence, original image | OCR chunks plus page image |
| DOCX | Paragraphs, headings, tables, embedded images, headers, footers | Structured chunks and assets |
| Markdown | Headings, paragraphs, tables, links, images | Section-aware chunks |
| Plain text | Line ranges and logical blocks | Line-aware chunks |
| Tables | Cell matrix, headers, captions, normalized text | Table object and structured facts |
| Images/figures | Asset extraction, caption linking, OCR, context | Visual evidence object |
| Maps/diagrams/charts | OCR, labels, caption, optional vision | Visual evidence with uncertainty |

### Ingestion flow

```text
Archive folder
    |
    v
Discover files -> hash and stable document ID -> format detector
    |
    +--> PDF text extraction
    +--> scanned PDF rendering and OCR
    +--> DOCX structure extraction
    +--> Markdown parser
    +--> TXT line parser
    +--> table extractor
    +--> image and figure extractor
    |
    v
Structure/provenance normalizer
    |
    v
Canonical chunks, tables, OCR, figures, images, metadata
    |
    v
Build keyword, vector, graph, and claim indexes
```


### Canonical evidence record

```json
{
  "evidence_id": "ev-doc17-p12-fig03",
  "document_id": "doc17",
  "document_version": 1,
  "original_path": "codex/beasts.pdf",
  "source_type": "pdf_scan",
  "page_start": 12,
  "page_end": 12,
  "section_path": ["Codex of Beasts", "Gravemaw Wyrm"],
  "object_type": "figure",
  "table_id": null,
  "figure_id": "fig03",
  "caption": "Lair distribution map",
  "nearby_evidence_ids": ["ev-doc17-p12-c01"],
  "ocr_confidence": 0.88,
  "vision_confidence": null,
  "source_reliability": "official_codex",
  "original_asset_ref": "assets/doc17/page12/fig03.png"
}
```

Every chunk must retain document ID, original path, source type, page or line range, section, table or figure ID, OCR/vision confidence, reliability, and original asset reference. Tables and images are separate evidence objects linked to their source page, caption, nearby text, and section. Ingestion is idempotent using hashes and parser versions; the original corpus remains read-only.

## 5. Four Knowledge Indexes

```text
                    +-------------------------+
                    | Canonical evidence      |
                    | chunks/tables/media     |
                    +------------+------------+
                                 |
       +-------------------------+-------------------------+
       |                         |                         |
       v                         v                         v
+--------------+          +--------------+          +----------------+
| Keyword/BM25 |          | Vector index |          | Knowledge graph|
| exact terms  |          | semantic     |          | entities/edges |
+--------------+          +--------------+          +----------------+
       |                         |                         |
       +-------------------------+-------------------------+
                                 v
                    +-------------------------+
                    | Fact/claim/conflict     |
                    | store with provenance   |
                    +-------------------------+
```

| Need | Index |
| :-- | :-- |
| Exact fictional names, titles, aliases | Keyword/BM25 |
| Dates, numbers, table values | Keyword/BM25 plus fact store |
| Paraphrased questions | Vector index |
| Cross-document relationships | Knowledge graph |
| Structured subject-relation-value facts | Fact store |
| Conflicting values | Claim/conflict store |
| Visual questions | Visual evidence, OCR, linked text |

Each index stores corpus version, document version, parser version, model version, build timestamp, and configuration hash. Investigations record the exact index versions used.

## 6. AI Service Gateway

```text
+------------------------------------------------+
|              AI SERVICE GATEWAY                |
+------------------------------------------------+
| LLM | embeddings | reranker | vision            |
| JSON/schema validation                         |
| Prompt/model version registry                  |
| Cache | retry/backoff | timeout                |
| Circuit breaker | usage/cost logging           |
| Deterministic fallback selector               |
+------------------------------------------------+
```


### Controlled uses

| AI service | Allowed purpose | Protection |
| :-- | :-- | :-- |
| LLM | Question understanding, planning, query rewriting, candidate extraction, answer writing | Structured JSON and evidence-only prompts |
| Embeddings | Semantic document and query representations | Versioned model and vector index |
| Reranker | Selecting strongest candidates | Ranks only retrieved archive evidence |
| Vision model | Diagrams, maps, charts, symbols, images | Store observation, figure ID, confidence, and support status |

The final answer generator receives only verified claims, valid citations, conflicts, confidence data, relevant assets, trace summary, and stop reason. It must not answer from general knowledge.

## 7. Question Understanding and Planning

The system combines deterministic rules with an LLM. Rules identify question words, dates, numbers, quoted terms, and aliases. The LLM handles complex intent and relation interpretation. Its output is schema-validated and matched against archive entities.

```json
{
  "raw_question": "Who rules the place where the Gravemaw Wyrm lives?",
  "intent": "multi_hop_relation_lookup",
  "entities": ["Gravemaw Wyrm"],
  "relations": ["lairs_in", "ruled_by"],
  "answer_type": "ruler_or_faction",
  "requires_multi_hop": true,
  "required_evidence": ["Wyrm location", "location ruler", "conflict check"]
}
```

The planner creates sub-questions, retrieval routes, exact/semantic/alias/graph query variants, completion criteria, visual-check requirements, and limits for iterations, graph hops, LLM calls, time, and query count.

Example:

```text
1. Where is the Gravemaw Wyrm's lair?
2. Who rules that location?
3. Do authoritative sources disagree?

Completion requires a page-cited answer for each sub-question.
```


## 8. Iterative Sub-track 1C Investigation

```text
START
  |
  v
Understand -> Decompose -> Plan -> Search current evidence gap
  |
  v
Merge and rerank keyword/vector/fact/graph/visual results
  |
  v
Extract candidate entities, relations, and claims
  |
  v
Validate against original text/table/figure/image
  |
  v
Update facts, graph, and investigation state
  |
  v
Evidence complete? ---- no ----> Generate next targeted query/graph expansion
  |                                      |
 yes                                      +----> Search again
  |
  v
Check conflicts -> Calculate confidence -> Generate grounded answer -> STOP
```


### Search routes

- Exact fact lookup.
- Keyword/BM25.
- Vector semantic search.
- Knowledge graph traversal.
- Linked tables and figures.
- OCR results.
- Vision analysis when text and OCR are insufficient.

The system asks for a next query only when a defined evidence gap remains. Every iteration records the active sub-question, query variants, routes, retrieved evidence, new entities, candidate claims, verified claims, remaining gaps, next action, and decision reason.

### Stopping rules

Stop when all required evidence is supported, no useful evidence appears after repeated attempts, the budget is reached, or the user requests a shorter answer. The UI must show the actual stop reason. Budget and no-progress stops create partial or low-confidence answers when evidence remains missing.

## 9. Claims, Facts, and Verification

```json
{
  "claim_id": "claim-042",
  "subject": "Marrowwell Abbey",
  "predicate": "ruled_by",
  "object": "Bleeding Crown",
  "claim_type": "direct",
  "source_evidence_ids": ["ev-doc42-p34-c01"],
  "page": 34,
  "source_reliability": "official_codex",
  "claim_confidence": 0.94,
  "verification_status": "verified"
}
```

| Class | Meaning | Output behavior |
| :-- | :-- | :-- |
| Direct | Explicit source statement | Present directly |
| Inferred | Derived from verified claim chain | Show all links |
| Conflicting | Competing values have support | Report disagreement and reliability |
| Unsupported | Suggested but unproven | Exclude from factual answer |
| Partial visual | Visual observation incompletely confirmed | Show image and uncertainty |

A claim is verified only if its evidence object exists, its page or line range is valid, the source supports the subject/relation/value, and OCR/vision limitations are recorded. An LLM-generated statement alone can never become verified.

## 10. Source Reliability and Conflicts

| Source category | Default treatment |
| :-- | :-- |
| Official codex/data record | Highest reliability for specifications and structured facts |
| Primary official document | High reliability for recorded events |
| Wiki article | Secondary; verify important claims |
| Novel narrative | Contextual; consider viewpoint and incompleteness |
| Letter/ledger/trial transcript | Assess author, purpose, and context |
| Ballad/rumor | Low unless corroborated |

The challenge explicitly notes that archive sources may disagree, such as a tavern ballad and official codex entry. Normalize claims into subject–predicate–object/value triples. Group identical subject/predicate claims and create conflict records when values differ.[^3_1]

Example:

```text
Codex: Gloamreach was founded in 246 AS.
Wiki: The date is contested.

Output: 246 AS is the best-supported recorded date because the codex has
higher reliability, but the secondary conflict is reported.
```

Confidence depends on source reliability, independent supporting documents, direct/inferred status, graph hops, OCR confidence, vision confidence, evidence quality, citation validity, and unresolved conflicts.

## 11. Visual Evidence

```text
Retrieve image/figure
      |
      v
Read caption and nearby text
      |
      +--> OCR labels and text
      +--> Vision model if necessary
      |
      v
Structured observation with confidence
      |
      v
Verify using labels, caption, context, or repeated evidence
      |
      v
Display original asset and uncertainty
```

The system must not invent unreadable visual facts. If evidence cannot be confirmed, it should say that the answer is not established in readable text and provide the original figure for manual review. A vision observation without confirming labels is partial visual evidence, not a direct archive fact.

## 12. Grounded Answer Generation

The final response contains:

1. Concise direct answer.
2. Evidence chain showing connected facts.
3. Document, page, section, and asset citations.
4. Claim type for each major conclusion.
5. Confidence and confidence reasons.
6. Conflicts and uncertainty.
7. Relevant tables, figures, or images.
8. Investigation trace and stopping reason.

Example:

```text
The Bleeding Crown rules the territory where the Gravemaw Wyrm lairs.

Evidence chain:
1. The Wyrm's lair is identified as Marrowwell Abbey [Codex, p. 12].
2. Marrowwell Abbey is recorded as ruled by the Bleeding Crown [Codex, p. 34].

Claim type: Inferred from two direct claims.
Confidence: High.
Stop reason: All required sub-questions have page-cited evidence.
```


## 13. API Design

```text
POST /api/questions
GET  /api/investigations/{id}
GET  /api/investigations/{id}/trace
GET  /api/investigations/{id}/evidence
GET  /api/investigations/{id}/graph
GET  /api/documents/{document_id}
GET  /api/documents/{document_id}/pages/{page}
GET  /api/assets/{asset_id}
GET  /api/indexes/status
GET  /api/health
```

Example request:

```json
{
  "question": "Who rules the place where the Gravemaw Wyrm lives?",
  "options": {
    "max_iterations": 6,
    "max_graph_hops": 3,
    "max_llm_calls": 12,
    "include_visual_evidence": true,
    "show_trace": true,
    "fallback_allowed": true
  }
}
```


## 14. User Interface

```text
+--------------------------------------------------------------------------------+
|                         ASHEN ARCHIVE INTELLIGENCE                            |
+--------------------------------------------------------------------------------+
| [ Ask a question about the archive...                                ] [Ask] |
+--------------------------------------------------------------------------------+
| FINAL ANSWER                                      Confidence: High             |
| The Bleeding Crown rules the territory ...                                       |
| Claim type: Inferred                                                            |
+--------------------------------------------------------------------------------+
| EVIDENCE CHAIN                                                                  |
| Wyrm -> lairs_in -> Abbey                         [Open document p.12]          |
| Abbey -> ruled_by -> Bleeding Crown                [Open document p.34]         |
+--------------------------------------------------------------------------------+
| RELATED TABLES/FIGURES | CONFLICTS | INVESTIGATION TIMELINE | GRAPH            |
+--------------------------------------------------------------------------------+
```

Required UI features include search, answer-first display, clickable citations, evidence chain, claim labels, confidence, source reliability, conflict panel, related documents, openable pages/assets, investigation timeline, performed queries, graph path, stop reason, and AI/fallback mode.

## 15. Reliability, Security, and Fallbacks

### Controls

- API keys only in environment variables or ignored `.env` files.
- No secrets in Git, logs, screenshots, chat exports, or errors.
- JSON schema validation for AI output.
- Model, prompt, and index version tracking.
- Caching for embeddings, plans, extraction, reranking, visual analysis, and completed investigations.
- Retry with exponential backoff, timeouts, and circuit breakers.
- Iteration, hop, token, cost, and latency budgets.
- Duplicate query prevention.
- Citation and provenance validation.
- Safe deterministic fallback mode.

The challenge guidance specifically recommends environment variables, caching, and exponential backoff because free services can rate-limit requests.[^3_1]

### Fallback matrix

| Failure | Fallback |
| :-- | :-- |
| LLM unavailable | Rule-based understanding and deterministic planner |
| Embedding unavailable | BM25/FTS5, fact store, and graph retrieval |
| Vision unavailable | OCR, captions, and nearby text |
| Reranker unavailable | Transparent weighted hybrid score |
| Graph unavailable | Fact store plus lexical/vector retrieval |
| Provider rate limit | Cache, retry, alternate provider, or reduced plan |

The system must report partial or insufficient evidence instead of hallucinating.

## 16. Evaluation Plan

The corpus provides 20 development questions and final judging uses a separate unpublished set of similar style.[^3_1]

### Ablation modes

1. Keyword-only retrieval.
2. Vector-only retrieval.
3. Keyword plus vector.
4. Hybrid plus graph expansion.
5. Deterministic investigation loop.
6. LLM-assisted investigation loop.
7. Full multimodal system.

### Metrics

| Metric | Purpose |
| :-- | :-- |
| Cited-answer coverage | Factual claims with citations |
| Citation correctness | Citation actually supports claim |
| Page/document recall | Relevant source retrieval |
| Semantic retrieval success | Paraphrase performance |
| Multi-hop completion | Cross-document reasoning |
| Conflict detection | Competing source identification |
| Unsupported claim count | Grounding safety |
| Visual accuracy | Visual evidence quality |
| OCR robustness | Scan handling |
| Fallback success | API-failure resilience |
| Latency and cost | Operational efficiency |
| Reproducibility | Repeatable results |

Test aliases, OCR corruption, three-hop questions, table-only evidence, figure-only evidence, conflicting sources, no-answer questions, malformed JSON, timeouts, rate limits, and index failures.

## 17. Technology Stack

| Layer | Recommended | Lightweight alternative |
| :-- | :-- | :-- |
| Backend | FastAPI | Spring Boot gateway or Flask |
| PDF/DOCX | PyMuPDF and python-docx | Same with fewer adapters |
| OCR | Tesseract or configured OCR API | Local OCR |
| Keyword | OpenSearch/Elasticsearch | SQLite FTS5 |
| Vector | Qdrant/pgvector | Chroma local mode |
| Graph | Neo4j/Memgraph | NetworkX or relational edges |
| Fact store | PostgreSQL | SQLite |
| Assets | S3-compatible storage | Local filesystem |
| Frontend | React/Next.js | Minimal React UI |
| AI | OpenAI-compatible gateway | Provider adapters behind common interface |
| Packaging | Docker Compose | Virtual environment and scripts |
| Testing | Pytest and evaluation runner | JSON test harness |

The competition permits any language, framework, model, or service and states that paid services are not required.[^3_1]

## 18. Repository Structure

```text
<team-name>/
├── .git/
├── README.md
├── pyproject.toml
├── docker-compose.yml
├── .env.example
├── src/
│   ├── api/ config/ ingestion/ evidence/
│   ├── indexes/keyword/ vector/ graph/ claims/
│   ├── ai_gateway/ investigation/ verification/
│   ├── generation/ fallback/ common/
├── tests/unit/ integration/ evaluation/ failure_modes/
├── scripts/ingest_archive.py build_indexes.py run_evaluation.py
├── docs/architecture.md data-model.md investigation-protocol.md
├── docs/api.md decisions.md limitations.md diagrams/
├── data/README.md
├── ai_usage/ai-usage-disclosure.md chat-logs/
├── configuration-example/
└── submission_report.pdf
```

The official requirements include complete Git history, README, architecture/design documentation, diagrams, limitations, AI usage disclosure, chat logs, and a maximum five-page report.[^3_1]

## 19. Team Responsibilities

| Role | Responsibilities |
| :-- | :-- |
| Ingestion/provenance engineer | Parsers, OCR, tables, assets, IDs, provenance |
| Retrieval/index engineer | BM25, vector, graph, fact store, fusion |
| AI/investigation engineer | Gateway, planner, iterative loop, budgets, fallbacks |
| Verification/product engineer | Claims, conflicts, UI, evaluation, demo |

All team members must understand the complete architecture and be able to explain and modify the system. The competition explicitly evaluates genuine human–AI collaboration and warns that generic one-shot AI output is insufficient.[^3_1]

## 20. Key Decisions

- **Hybrid retrieval:** exact names and values require lexical search; paraphrases require vectors; multi-hop reasoning requires a graph; structured facts and conflicts require a claim store.
- **Separate claims from graph edges:** every relationship needs evidence, confidence, and verification status.
- **Bounded state machine:** provides human-like search without uncontrolled loops.
- **AI gateway:** centralizes provider switching, caching, retries, logging, and fallbacks.
- **Verification before generation:** the model explains verified evidence instead of deciding truth.
- **Visual uncertainty:** original assets and confidence remain visible when OCR or vision is incomplete.


## 21. Limitations and Mitigations

| Limitation | Mitigation |
| :-- | :-- |
| OCR errors | Confidence, aliases, fuzzy search, original-page viewer |
| Vision ambiguity | Require labels/context and show uncertainty |
| Entity resolution errors | Canonical IDs, aliases, confidence, trace |
| Incomplete graph | Search graph and source indexes together |
| LLM extraction errors | Schema validation and evidence verification |
| Conflicting sources | Report reliability and unresolved conflict |
| API rate limits | Cache, retry, backoff, provider fallback |
| Large graph neighborhoods | Hop limits, relation filters, deduplication |
| Unpublished test questions | General behavior tests, no hard-coded answers |

## 22. Demonstration Plan

The official video must be ten minutes or less and include at least three to four minutes of live, unedited end-to-end demonstration on real inputs.[^3_1]

1. Show ingestion and four-index health.
2. Ask a multi-hop question.
3. Display structured understanding and investigation plan.
4. Show exact, vector, fact, and graph retrieval.
5. Show graph expansion and next query.
6. Show claim verification and conflict checking.
7. Display final answer with clickable citations.
8. Open a cited page, table, or image.
9. Show timeline, graph path, confidence, and stop reason.
10. Demonstrate fallback or API failure handling.

## 23. Implementation Roadmap

### Phase 1: Vertical slice

Selectable PDF ingestion, provenance, keyword search, vector route, question endpoint, citations, and basic answer UI.

### Phase 2: Complete ingestion

Scans, OCR, DOCX, Markdown, TXT, tables, figures, images, maps, captions, and linked assets.

### Phase 3: Four-index fabric

Graph, entity resolution, fact store, claim schema, conflicts, index versions, and health APIs.

### Phase 4: Investigation controller

Question understanding, decomposition, planning, iterative retrieval, graph expansion, budgets, and stop reasons.

### Phase 5: Verification and multimodality

Claim validation, reliability, confidence, contradiction detection, OCR uncertainty, vision, and partial answers.

### Phase 6: Product hardening

UI trace, page/asset viewer, caching, retries, circuit breakers, fallback modes, tests, and Docker setup.

### Phase 7: Submission readiness

README, diagrams, decisions, limitations, evaluation, AI disclosure, chat logs, meaningful commit history, demo, and five-page report.

## 24. Final Checklist

- [ ] All document and asset formats are ingested.
- [ ] Page, line, section, table, figure, and source metadata are preserved.
- [ ] Four indexes build and report health.
- [ ] Questions produce validated structured plans.
- [ ] Iterative loop searches until evidence is complete or budget stops it.
- [ ] Multi-hop graph paths are visible.
- [ ] Claims are verified before generation.
- [ ] Conflicts and reliability are displayed.
- [ ] Visual uncertainty is handled safely.
- [ ] Citations open the correct source page or asset.
- [ ] API failures trigger transparent fallbacks.
- [ ] Evaluation includes ablations and failure modes.
- [ ] README works from a clean environment.
- [ ] Secrets are excluded from Git.
- [ ] AI usage disclosure and chat logs are included.
- [ ] Full Git history, diagrams, limitations, demo video, and PDF report are ready.


## 25. Final Positioning

> **A provenance-first multimodal archive investigator that combines four knowledge indexes with bounded iterative planning, multi-hop graph reasoning, claim verification, conflict-aware confidence, visual evidence handling, and reliable fallback behavior.**

The differentiator is the complete evidence lifecycle: preserve the archive, retrieve through complementary indexes, investigate until requirements are satisfied, validate every claim, expose conflicts and uncertainty, and show exactly what was searched and why the system stopped. This directly addresses the mixed formats, cross-document relationships, source disagreements, and iterative-search requirements of the Ashen Era Archive challenge.[^3_1]

<span style="display:none">[^3_2]</span>

<div align="center">⁂</div>

[^3_1]: AI_Competition_Challenge_Final.pdf

[^3_2]: Document Corpus link.txt

