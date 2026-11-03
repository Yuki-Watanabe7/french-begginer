#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
bash "$root/scripts/ensure_branch_includes_main.sh"

cd "$root/backend"
uv sync --locked --group dev
uv run --group dev ruff check .
uv run --group dev ruff format --check .
uv run --group dev pytest

cd "$root/frontend"
npm ci --include=dev
npm run lint
npm run test
npm run build
npm run build:readonly
