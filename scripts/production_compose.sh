#!/usr/bin/env bash
# 家庭内本番（compose.production.yml）専用の docker compose 呼び出し。
# 開発用 docker-compose.yml やリポジトリ直下の .env を暗黙に重ねないよう、
# compose ファイル・project 名・env ファイルを固定する。
#
#   bash scripts/production_compose.sh up -d --build
#   bash scripts/production_compose.sh ps
#   bash scripts/production_compose.sh exec backend python -m app.persistence.readiness
#
# env ファイルの既定は production.env（Git 管理外）。FRENCH_PRODUCTION_ENV_FILE で変更できる。
# `config` の出力には API キーが展開されるので、貼り付け・共有しない。
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
env_file="${FRENCH_PRODUCTION_ENV_FILE:-$root/production.env}"

if [[ ! -f "$env_file" ]]; then
  echo "$env_file がありません。production.env.example をコピーして作成してください。" >&2
  exit 1
fi

# compose の変数展開はシェルの環境変数を env ファイルより優先する。
# 開発シェルの OPENAI_API_KEY などが本番へ紛れ込まないよう、env ファイルだけを正にする。
unset OPENAI_API_KEY FRENCH_BIND_ADDRESS FRENCH_HTTP_PORT FRENCH_ALLOWED_HOSTS FRENCH_TUTOR_VOLUME
export FRENCH_APP_COMMIT=$(git -C "$root" rev-parse HEAD)
export FRENCH_APP_DIRTY=false
if [[ -n "$(git -C "$root" status --porcelain --untracked-files=normal -- backend/app backend/Dockerfile backend/pyproject.toml backend/uv.lock)" ]]; then
  export FRENCH_APP_DIRTY=true
fi

exec docker compose \
  --project-directory "$root" \
  --project-name french-production \
  --file "$root/compose.production.yml" \
  --env-file "$env_file" \
  "$@"
