#!/usr/bin/env bash
# HEAD が origin/main を含むことを確認する。
# Cloud Agent の作業ツリーは起動時のスナップショットなので、リモートの main より
# 遅れていることがある。ローカルの main からはブランチを切らない。
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"

main_ref="${MAIN_REF:-origin/main}"

if [[ -z "${MAIN_REF:-}" ]]; then
  git fetch origin main
fi

if git merge-base --is-ancestor "$main_ref" HEAD; then
  exit 0
fi

if [[ "$(git rev-parse --is-shallow-repository)" == "true" ]]; then
  git fetch --unshallow origin
  if git merge-base --is-ancestor "$main_ref" HEAD; then
    exit 0
  fi
fi

echo "HEAD は ${main_ref} ($(git rev-parse --short "$main_ref")) を含んでいません。" >&2
echo "HEAD: $(git rev-parse --short HEAD) $(git log -1 --format=%s)" >&2
echo "新しい作業は origin/main から切り、既存ブランチは次で取り込んでからやり直してください。" >&2
echo "  git fetch origin main && git merge origin/main" >&2
exit 1
