#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
bash "$root/scripts/ensure_branch_includes_main.sh"

cd "$root/backend"
uv sync --locked --group dev
uv run --group dev ruff check . ../scripts/prepare_public_readonly.py
uv run --group dev ruff format --check . ../scripts/prepare_public_readonly.py
uv run --group dev pytest

cd "$root/frontend"
npm ci --include=dev
npm run lint
npm run test
npm run build
npm run build:readonly

# 配布候補は Git の外へ。合成教材のみを検査し、アップロードはしない。
readonly_check_root=$(mktemp -d)
trap 'rm -rf "$readonly_check_root"' EXIT
cd "$root/backend"
uv run python ../scripts/prepare_public_readonly.py \
  --snapshot ../docs/operations/public-snapshot.synthetic.json \
  --out "$readonly_check_root/public"
