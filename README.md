# AgriChat

SMS crop-rotation advice for rainfed rice farmers in Batac, Ilocos Norte, built on NASA POWER and SMAP data.

A farmer texts a short command.
A deterministic engine scores the candidate crops for the next sowing window from water-budget indicators and replies in under 150 characters.
A language model is used only to read free text into a command, and the system works with it switched off.
One FastAPI process serves the SMS webhook, the public website with a simulator, and a small admin panel.

- Behavior: `docs/Technical_spec.md`
- Background and decisions: `docs/Project_overview.md`
- Quality bar: `docs/engineering-standards.md`
- Data sources and terms: `PROVENANCE.md`
- AI use: `AI_USE.md`
- License: Apache-2.0, see `LICENSE`

## Run locally

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

1. Install: `uv sync --frozen`
2. Copy `deploy/.env.example` to `.env`, fill in what you need, and load it with `set -a; . ./.env; set +a`.
   With nothing set, the app starts with the model, retrieval and the SMS gateway unused.
   `DB_PATH` defaults to `data/agrichat.db`; the tables are created and seeded at startup.
3. Start: `.venv/bin/uvicorn app.main:app --reload`
4. Open `http://127.0.0.1:8000/` for the simulator and `http://127.0.0.1:8000/health` for a liveness check.

Retrieval is optional.
Set `EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2` to enable knowledge-base retrieval for WHY answers.
Leave it unset to use the fixed reason phrases with the stored source tag.

To use the admin panel, create the password hash and a session secret, and put both in the environment:

```sh
.venv/bin/python -c "import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass.getpass()))"
.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"
```

The first value is `ADMIN_PASSWORD_HASH`, the second is `SESSION_SECRET`.
Keep the hash inside single quotes in `.env`, because it contains `$` characters that the shell would otherwise expand.
The session cookie is marked `Secure`, so sign in over HTTPS or on `localhost` only.

## Run the pipeline

The source data is already in `data/`, and `PROVENANCE.md` lists where each file came from.

- Rebuild the indicators from the POWER, ONI and crop tables: `.venv/bin/python -m pipeline.build_indicators`
  This writes `data/indicators.csv`.
- Fetch SMAP Level 4 soil moisture through AppEEARS: `EARTHDATA_USER=... EARTHDATA_PASS=... .venv/bin/python -m scripts.fetch_smap`
  Add `--process-only` to rebuild from `data/smap/raw` without the network.
  Check the result with `.venv/bin/python -m scripts.check_smap`.
  The Earthdata credentials stay in the environment and never go in the repo.
- Run the El Nino hindcast: `.venv/bin/python -m validation.hindcast`
  Results go to `validation/results/`.
- Score retrieval against a question file: `.venv/bin/python -m validation.retrieval_test questions.csv`
- Regenerate `PROVENANCE.md` after editing `data/provenance.csv`: `.venv/bin/python -m scripts.build_provenance`

## Run tests

- All checks (lint, format check, tests): `sh tools/ci.sh`
- Tests only: `.venv/bin/python -m pytest`
- Lint and format: `.venv/bin/ruff check .` and `.venv/bin/ruff format .`

Tests make no network call; the SMS gateway, the language model and the embedding model are replaced by fakes.

## Demo Resources

- Music: https://www.youtube.com/watch?v=p7ZsBPK656s
- News Clip: https://www.youtube.com/watch?v=qVex5fKhLFI&t=21s

## Presentaton
- https://drive.google.com/file/d/1mINYZ-VFFZEX-tZkdK7goZ7xZMak-hb8/view?usp=sharing

## Deployed at:
-agrichat-proxy.vercel.app



