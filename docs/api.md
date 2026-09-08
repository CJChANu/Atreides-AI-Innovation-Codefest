# API

`python run_api.py` → <http://127.0.0.1:8000>. Interactive docs at `/docs`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Web UI |
| `GET` | `/api/health` | Per-subsystem readiness, corpus counts, gateway state |
| `GET` | `/api/indexes/status` | Which indexes are live, plus edge/fact/conflict counts |
| `POST` | `/api/questions` | Run an investigation |
| `GET` | `/api/documents/{document_id}` | Document metadata |
| `GET` | `/api/documents/{document_id}/chunks?page=N` | Extracted evidence — what a citation opens |
| `GET` | `/api/chunks/{chunk_id}` | One citation target |
| `GET` | `/api/figures/{figure_id}/asset` | The original image |

## Asking a question

```bash
curl -s localhost:8000/api/questions -H 'content-type: application/json' -d '{
  "question": "Whose dominion encompasses the lair of the Gravemaw Wyrm?",
  "options": {"max_iterations": 6, "show_trace": true, "allow_llm": true}
}' | jq
```

`allow_llm: false` forces the deterministic path. It is in the API rather than
only in config so a demo can show both modes on the same question and prove the
fallback is real, not a claim.

## Response

```jsonc
{
  "answer": "The Bleeding Crown",
  "partial": false,                   // true whenever the loop stopped early
  "ai_mode": "deterministic",         // or "llm_assisted"
  "claims": [{
    "text": "Marrowwell Abbey's ruled by is The Bleeding Crown.",
    "claim_type": "inferred",         // direct | inferred | conflicting | unsupported
    "confidence": 0.84,
    "confidence_label": "high",
    "evidence": [{
      "document": "Codex Vaeloria I: Gazetteer of the Sundered Realms",
      "relative_path": "codex/codex_vaeloria_i_....pdf",
      "page": 34,
      "chunk_id": "doc-ff2ce...-p0034-s00-c052",
      "source_class": "codex",
      "reliability": 1.0
    }]
  }],
  "evidence_chain": ["Gravemaw Wyrm — lair: Marrowwell Abbey", "..."],
  "graph_path": ["Gravemaw Wyrm", "lair", "Marrowwell Abbey", "ruled by", "The Bleeding Crown"],
  "conflicts": [/* competing values, their sources, and whether reliability settles it */],
  "sub_questions": [/* each with its completion condition and whether it was met */],
  "trace": [/* every iteration: action, query, why, what was searched, what was learned */],
  "stop_reason": "all required sub-questions are supported",
  "fallback_events": ["understanding: no API key configured"],
  "stats": {"iterations": 4, "queries": 4, "graph_expansions": 1, "elapsed_ms": 0.7}
}
```

Every `chunk_id` in a response resolves at `/api/chunks/{chunk_id}` — there is an
integration test asserting exactly that, because a citation that does not resolve
is worse than no citation.

## Security at this boundary

- **Asset routes take an id, never a path.** The filesystem path is looked up in
  the index and then checked to be inside the corpus or the derived-assets
  directory, so a crafted `../../` cannot escape the archive.
- **The corpus is never written to.** No endpoint mutates it.
- **No secret is ever returned.** `/api/health` reports whether a key is
  configured and which model is selected, never the key.
