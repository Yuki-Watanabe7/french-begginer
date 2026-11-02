#!/usr/bin/env bash
# 家庭内本番 DB の整合バックアップを1つ作る（Issue #220）。backend は起動中のままでよい。
#
#   bash scripts/production_backup.sh
#   FRENCH_BACKUP_DIR=/Volumes/USB/french-tutor bash scripts/production_backup.sh
#
# 保存先の既定は ~/FrenchTutorBackups。中身は暗号化していない SQLite（教材本文・学習履歴）
# なので、リポジトリ・公開教材・CI に置かない。手順は docs/operations/sqlite-backup-runbook.md。
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd -P)
umask 077
dir="${FRENCH_BACKUP_DIR:-$HOME/FrenchTutorBackups}"
mkdir -p "$dir"
dir=$(cd "$dir" && pwd -P)
if [[ "$dir/" == "$root/"* ]]; then
  echo "バックアップをリポジトリ内に置かないでください: $dir" >&2
  exit 1
fi

name="tutor-$(date -u +%Y%m%dT%H%M%SZ).db"
if [[ -e "$dir/$name" ]]; then
  echo "同名のバックアップがあります。少し待ってからやり直してください: $dir/$name" >&2
  exit 1
fi
partial="$dir/.$name.partial"
trap 'rm -f "$partial"' EXIT

backup=(bash "$root/scripts/production_compose.sh" run --rm --no-deps -T backend
  python -m app.persistence.backup)
"${backup[@]}" export > "$partial"
# 受け取ったファイルを同じイメージで開き直し、転送で壊れていないことを確かめる。
"${backup[@]}" verify < "$partial"
mv "$partial" "$dir/$name"

echo "保存しました: $dir/$name"
echo "この PC 上のコピーです。PC の故障・紛失にも備えるなら、別の機器へもコピーしてください（任意）。"
