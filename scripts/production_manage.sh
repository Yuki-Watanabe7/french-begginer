#!/usr/bin/env bash
# 日常操作。鍵/デバイス設定は FRENCH_BACKUP_CONFIG（Git 管理外）を明示する。
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
action="${1:-}"
case "$action" in
  start|stop|upgrade) ;;
  *) echo 'usage: production_manage.sh start|stop|upgrade' >&2; exit 2 ;;
esac
: "${FRENCH_BACKUP_CONFIG:?私的 backup 設定 JSON の絶対パスを指定してください}"
backup() {
  uv run --project "$root/backend" --no-sync python "$root/scripts/production_backup.py" \
    backup --config "$FRENCH_BACKUP_CONFIG" "$@"
}
if [[ "$action" == start ]]; then
  # sleep 等で日次を逃していたら起動時に補う。未達は隠さないが学習再開は妨げない。
  if ! backup --reason daily --if-due; then
    echo 'バックアップ未達。再開しますが、status と機器接続を確認してください。' >&2
  fi
  bash "$root/scripts/production_compose.sh" up -d --wait
else
  # 先に入口・書込を止める。失敗時も停止を維持し、更新を続行しない。
  bash "$root/scripts/production_compose.sh" stop web backend
  reason=shutdown
  if [[ "$action" == upgrade ]]; then reason=pre-upgrade; fi
  backup --reason "$reason"
  if [[ "$action" == upgrade ]]; then
    bash "$root/scripts/production_compose.sh" up -d --build --wait
    bash "$root/scripts/production_compose.sh" exec -T backend python -m app.persistence.readiness
  fi
fi
