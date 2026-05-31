#!/usr/bin/env bash
set -euo pipefail

cd backend
uv sync --locked --extra dev
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest

cd ../frontend
npm ci --include=dev
npm run lint
npm run build