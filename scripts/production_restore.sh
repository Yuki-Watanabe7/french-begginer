#!/usr/bin/env bash
# production_backup.sh で作ったバックアップを家庭内本番 DB へ戻す（Issue #220）。
#
#   bash scripts/production_restore.sh ~/FrenchTutorBackups/tutor-20261103T120000Z.db
#
# web / backend を止めて書込をなくしてから差し替え、起動と readiness の確認まで行う。
# 差し替え前の DB は消さず、同じ volume に tutor-before-restore-<時刻>.db として残す。
# 検査に失敗したら DB は変えずに停止したまま終わる（元の DB で再開するなら up -d --wait）。
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
backup="${1:?usage: production_restore.sh <バックアップの .db ファイル>}"
if [[ ! -f "$backup" ]]; then
  echo "ファイルがありません: $backup" >&2
  exit 1
fi

compose=(bash "$root/scripts/production_compose.sh")
"${compose[@]}" stop web backend
"${compose[@]}" run --rm --no-deps -T backend \
  python -m app.persistence.backup restore < "$backup"
"${compose[@]}" up -d --wait
"${compose[@]}" exec -T backend python -m app.persistence.readiness
