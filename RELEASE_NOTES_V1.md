# Atradias / Ashen Era Archive — V1 Release Notes

## Overview

V1 delivers the live Atradias archive question-answering system at:

https://atradias.duckdns.org

The deployment exposes a public API that can search the Ashen Era Archive, retrieve evidence from multiple indexed source types, and answer questions using deterministic retrieval or LLM-assisted synthesis.

## Live Deployment

- Deployed on the VPS under `/home/ubuntu/atreides-codefest`.
- Served publicly through nginx at `https://atradias.duckdns.org`.
- Runs as a persistent systemd service: `atradias.service`.
- Backend listens locally on `127.0.0.1:8000` and is reverse-proxied by nginx.
- Health endpoint: `GET /api/health`.
- Question endpoint: `POST /api/questions`.

## Archive Index

Current indexed corpus:

- 321 documents
- 1330 pages
- 2515 searchable chunks
- 227 tables
- 187 figures/images

The system processes archive documents into searchable text chunks, structured facts, tables, and figure references so answers can cite retrieved evidence rather than guessing.

## Question Answering API

Main endpoint:

```http
POST https://atradias.duckdns.org/api/questions
```

Example request:

```json
{
  "question": "When was Gloamreach founded?",
  "options": {
    "max_iterations": 6,
    "show_trace": false,
    "allow_llm": false
  }
}
```

Verified example answer:

```text
When was Gloamreach founded? → 246 AS
```

## Retrieval and Reasoning

V1 supports:

- Keyword search
- Structured fact lookup
- Graph-assisted lookup
- Vector/hybrid retrieval
- Multi-step investigation traces
- Deterministic answers for exact archive facts
- LLM-assisted mode for natural-language evidence synthesis

This allows the app to answer simple direct facts and also support broader archive questions that compare retrieved passages.

## LLM-Assisted Evidence Synthesis

The answer flow was improved so the system can synthesize natural-language answers from retrieved evidence passages instead of only returning strict structured values.

This helps with questions such as:

- comparing wiki and Codex evidence
- explaining source differences in natural language
- summarizing retrieved evidence passages
- handling broader archive questions where exact single-field answers are not enough

Example tested query:

```text
Compare Gloamreach using wiki and Codex evidence
```

The system now returns an evidence-grounded natural-language comparison when enough supporting passages are retrieved.

## Configurable Iteration Budget

The public API option `max_iterations` was increased so deeper archive searches can be requested.

Current V1 limit:

```text
max_iterations <= 1000
```

Recommended usage:

- `6` for normal direct questions
- `12` for ordinary cross-document questions
- `20–30` for harder wiki + Codex + scanned-document comparisons
- higher values only when deep searching is required, because large values may be slower and may hit free LLM/provider limits sooner

## Deployment Automation

V1 includes server-side auto deployment:

- GitHub repository is watched from the VPS.
- A systemd timer checks `origin/main` approximately every minute.
- If a new commit is found, the VPS pulls the latest code, installs dependencies if needed, runs compile checks, restarts the app, and verifies health.
- GitHub Actions was changed to a verification workflow instead of doing SSH deployment directly.

This avoids failed SSH deploy jobs and lets the VPS handle deployment safely.

## GitHub Actions Verification

The CI workflow now verifies that the live VPS deployment becomes ready after a push.

It checks:

- public health endpoint is reachable
- app reports `status: ready`
- indexed corpus is available
- LLM gateway configuration is visible in health output

## Health Status

Verified health output includes:

- status: `ready`
- mode: `full (hybrid retrieval + LLM-assisted)`
- keyword index: enabled
- fact index: enabled
- graph index: enabled
- vector index: enabled
- LLM gateway: configured

## Notes and Limits

- LLM is optional.
- Deterministic mode works without LLM for exact facts.
- LLM-assisted mode is better for natural-language explanations and comparisons.
- Free OpenRouter/NVIDIA models can be rate-limited or overloaded, so very large iteration counts should be used carefully.
- Secrets remain server-side in `.env` and are not committed to GitHub.

## V1 Summary

This release makes Atradias a live, public, auto-deployed archive QA system with:

- working production deployment
- public health and question APIs
- indexed Ashen Era Archive corpus
- deterministic fact answers
- LLM-assisted evidence synthesis
- cross-source comparison support
- GitHub-backed deployment flow
- server-side auto deploy
- GitHub Actions live verification
- increased `max_iterations` support up to `1000`
