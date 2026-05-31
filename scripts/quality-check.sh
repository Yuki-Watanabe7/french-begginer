#!/usr/bin/env bash
set -euo pipefail

cd backend
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest

cd ../frontend
npm run lint
npm run build