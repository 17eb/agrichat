# AgriChat

SMS crop-rotation advice for rainfed rice farmers in Batac, Ilocos Norte, built on NASA POWER and SMAP data.

- Behavior: `docs/Technical_spec.md`
- Background and decisions: `docs/Project_overview.md`
- Quality bar: `docs/engineering-standards.md`
- Checks: `sh tools/ci.sh`

## Setup

- Install: `uv sync --frozen`
- Retrieval is optional.
  Set `EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2` to enable knowledge-base retrieval for WHY answers.
  Leave it unset to use the fixed reason phrases with the stored source tag.
