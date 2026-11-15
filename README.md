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

## Deploy

Target: one Linux VPS with a domain, Caddy and systemd.
Paths below match `deploy/agrichat.service` and `deploy/Caddyfile`.

1. Point a domain or subdomain at the VPS.
2. Create the service user and install the app.
   Install uv to a system path, because `sudo` does not see a per-user install.
   Keep the Python that uv downloads inside `/opt/agrichat`, because the service cannot read `/root` or `/home`.
   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
   sudo useradd --system --home /opt/agrichat --shell /usr/sbin/nologin agrichat
   sudo git clone <repository-url> /opt/agrichat
   cd /opt/agrichat
   sudo env UV_PYTHON_INSTALL_DIR=/opt/agrichat/.python /usr/local/bin/uv sync --frozen --no-dev
   sudo chown -R agrichat:agrichat /opt/agrichat/data
   readlink -f /opt/agrichat/.venv/bin/python
   ```
   The last command must print a path under `/opt/agrichat` or `/usr`, never under `/root` or `/home`.
   Do not copy `data/kb/raw/` or `data/crops/raw/da/` to the server or the public repository.
3. Write the environment file, readable only by the service user:
   ```sh
   sudo install -d -m 0750 -o root -g agrichat /etc/agrichat
   sudo install -m 0600 -o agrichat -g agrichat deploy/.env.example /etc/agrichat/agrichat.env
   sudoedit /etc/agrichat/agrichat.env
   ```
   Fill in every variable you use; `deploy/.env.example` lists all of them.
4. Install and start the service.
   It binds to `127.0.0.1:8000` and restarts on failure.
   With `EMBEDDING_MODEL` set, the first start downloads the model into `/var/cache/agrichat`, so it is slow and needs network access.
   ```sh
   sudo cp deploy/agrichat.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now agrichat
   ```
5. Edit the site address in `deploy/Caddyfile`, install it as `/etc/caddy/Caddyfile` and reload Caddy: `sudo systemctl reload caddy`.
   Caddy obtains the certificate and redirects HTTP to HTTPS.
6. Set the httpSMS webhook URL to `https://<domain>/webhook/httpsms` with the value of `WEBHOOK_SECRET`.
7. Open the public URL in a private window and run the five end-to-end exchanges in the simulator.
   Check `https://<domain>/health` returns `{"ok":true}`.
