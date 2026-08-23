#!/usr/bin/env bash
set -euo pipefail

cd backend
uv sync --locked --group dev
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev pytest

cd ../frontend
npm ci --include=dev
npm run lint
npm run test
npm run build