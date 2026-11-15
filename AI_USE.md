# AI use

This file describes where AI models are used in AgriChat and what people checked.

## In the running system

- **Intent extraction.**
  A small chat model, called through the `openai` SDK, reads a free-text SMS into a JSON command (intent, barangay, water, crop, priority, confidence).
  It is called only when the keyword parser fails, at temperature 0, and its output is validated against a schema.
  Low confidence, an invalid result or an `OTHER` intent falls back to a fixed reply.
  The model name, endpoint and key come from `LLM_MODEL`, `LLM_ENDPOINT` and `LLM_KEY`, and the model is on only when `LLM_ENABLED=true`.
  The deployed model and version are recorded here at deployment: PENDING, not yet chosen.
- **Answer wording.**
  The model is not used to word replies.
  Every reply comes from a fixed template filled with engine output.
- **Retrieval.**
  The embedding model `paraphrase-multilingual-MiniLM-L12-v2`, run locally through `sentence-transformers`, ranks short passages from the knowledge base for WHY answers.
  It is optional (`EMBEDDING_MODEL`) and does not generate text.
  It runs through `sentence-transformers` 6.3.0, as pinned in `uv.lock`; the model weights are downloaded on first start from the Hugging Face hub at the revision current then.
- **Chart library.**
  The home page chart uses Chart.js 4.4.7, loaded from `cdn.jsdelivr.net` with the subresource integrity hash `sha384-vsrfeLOOY6KuIYKDlmVH5UiBmgIdB1oEf7p01YgWHuqmOHfZr374+odEv96n9tNC`.
  It is a plain charting library, not an AI component.
- **Recommendations.**
  The crop ranking, scores and reason codes come from the deterministic engine in `engine/`, not from a model.
- **Privacy.**
  The model never sees phone numbers.
  Each prompt and output is logged with the template ID.

## In development

AI coding assistants were used to draft code, tests and documentation in this repository.
Their output was treated as untrusted drafts.

## What people verified

- Every change was reviewed by a person against `docs/Technical_spec.md` and `docs/engineering-standards.md`, and `tools/ci.sh` (lint, format, tests) passes.
- Dataset values were checked against the cited sources, and each file's terms are in `PROVENANCE.md`.
- The El Nino hindcast in `validation/results/` compares engine output with past seasons.
- Knowledge-base chunks were sampled for audit in `data/kb/kb_audit_sample.csv`.
- Retrieval quality is scored with `validation/retrieval_test.py`.
- Reviewer-set thresholds are marked as placeholders in `engine/params.py` until a domain reviewer confirms them.

## Media

No AI-generated image or video is used in the project.
Any added later will carry a visible watermark.
