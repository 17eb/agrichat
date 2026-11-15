#!/bin/sh
# Local and remote CI: lint, format check, tests. Exit non-zero on any failure.
set -eu
cd "$(dirname "$0")/.."
echo "== ruff check"
uv run --frozen ruff check .
echo "== ruff format --check"
uv run --frozen ruff format --check .
echo "== pytest"
uv run --frozen pytest
echo "ci: pass"
