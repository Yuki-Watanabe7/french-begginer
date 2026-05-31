#!/usr/bin/env bash
set -euo pipefail

cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest

cd ../frontend
npm run lint
npm test