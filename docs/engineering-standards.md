# Engineering standards

The bar every change must meet before it merges.
`docs/Technical_spec.md` is the source of truth for behavior; this file is the source of truth for quality.
Where the spec is silent, choose the simplest design that is correct, secure and easy to maintain.

## Scope

- Build what the task and the spec ask for, nothing more.
- No speculative options, plugin points, config for fixed values or unused code.
- Touch only the files the task needs.
- Reviewer decisions still open in the spec (sowing window, root-zone water capacity, adequacy threshold, `kc_end`, rice extra allowance, scoring weights, heat and rain thresholds) live in one module, `engine/params.py`, each marked `PLACEHOLDER: pending reviewer` with the spec's suggested value.

## Code

- Python 3.13, type hints on every public function, small pure functions where the spec says pure.
- Standard library first; only dependencies already in `pyproject.toml` unless the task needs a new one.
- No network call in tests.
  The language model, the SMS gateway, AppEEARS and the embedding model are behind small interfaces with fakes in tests.
- Errors are handled where they can be acted on; no bare `except`, no silent `pass`.
- Configuration comes from environment variables listed in the spec, read in one place.
  No secret, password, key or phone number in the repo, logs or test fixtures.
- `ruff check` and `ruff format --check` pass with no new ignores.
- Plain ASCII hyphen "-" in text; never the long dash.

## Tests

- Every behavior in the task's acceptance list has a test.
- Tests are deterministic, fast and independent of order.
- `tools/ci.sh` passes.

## HTTP and security

- Routes, methods and access levels match the spec's endpoint table exactly.
- Every admin route depends on one session check; without a valid session it redirects to login.
- State-changing forms carry a CSRF token tied to the session; requests without it are rejected.
- Passwords are compared through Argon2 verification only.
- Session cookies are signed, `HttpOnly`, `Secure`, `SameSite=Lax`, 8-hour expiry.
- Login and `/simulate` are rate-limited per IP.
- The webhook verifies its secret, deduplicates on message ID, answers 200 within 1 second and does the work in the background.
- Templates escape all output; farmer text is never rendered as HTML.
- SQL uses parameters only; never string formatting.
- Phone numbers are stored only as keyed hashes (`PHONE_HASH_SECRET`).
- Admin pages send `Cache-Control: no-store` and `X-Robots-Tag: noindex`.

## Performance

- Nothing heavy at request time: indicators are precomputed; the embedding model and vectors load once at startup.
- No N+1 queries; SQLite in WAL mode.

## UI

- Server-rendered Jinja2, plain CSS, one small vanilla JS file for the simulator; the chart is HTML and CSS with no third-party script.
- Works at 360 px wide with no horizontal scroll, 16 px side gutters, tap targets at least 44 px.
- Light and dark color schemes both legible; text contrast at least WCAG AA.
- Visible keyboard focus, labels on every input, semantic headings, alt text where images carry meaning.
- Consistent spacing scale and type scale; nothing overlaps, clips or misaligns at any captured width.
- No console errors.

## Commits

- No commits by workers; the pipeline commits.
- No tool, model or assistant names in code, comments or docs, except in `AI_USE.md`, which the spec requires.
