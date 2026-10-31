#!/usr/bin/env bash
# 家庭内本番の入口とアクセス境界を外側から確かめる（Issue #219）。
# ホスト自身と、同じ LAN の別端末（Mac / Windows の Git Bash・WSL など curl がある環境）で実行する。
#
#   bash scripts/probe_production_boundary.sh <host> [port]
#   例: bash scripts/probe_production_boundary.sh 192.168.1.20
#
# 学習履歴は作らない（状態を持たない動詞の採点 API だけを同一オリジンで呼ぶ）。
# TTS は拒否されることだけを確かめ、費用が発生する成功リクエストは送らない。
set -uo pipefail

host="${1:?使い方: probe_production_boundary.sh <host> [port]}"
port="${2:-8080}"
base="http://${host}:${port}"
origin="$base"
failures=0

pass() { printf 'PASS  %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }

status() {
  curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 --max-time 10 "$@"
}

expect_status() {
  local want="$1" label="$2"
  shift 2
  local got
  got=$(status "$@")
  if [[ "$got" == "$want" ]]; then pass "$label ($got)"; else fail "$label: want $want, got $got"; fi
}

expect_unreachable() {
  local label="$1" url="$2"
  if curl -s -o /dev/null --connect-timeout 3 --max-time 5 "$url"; then
    fail "$label: 接続できてしまった ($url)"
  else
    pass "$label: 接続不可"
  fi
}

answer='{"verb":"être","tense":"présent","pronoun":"je","answer":"suis"}'

echo "== 入口 $base"
expect_status 200 "GET /health（nginx → backend）" "$base/health"
expect_status 200 "GET /（React）" "$base/"
expect_status 200 "直接 URL の再読込（SPA fallback）" "$base/tutor/reload-check"
expect_status 200 "同一オリジンの書込（採点・状態なし）" \
  -X POST -H 'Content-Type: application/json' -H "Origin: $origin" -d "$answer" \
  "$base/api/answers/check"

echo "== 公開しないポート"
expect_unreachable "backend 8000 の直接接続" "http://${host}:8000/health"
expect_unreachable "Vite 5173 の直接接続" "http://${host}:5173/"

echo "== Host / Origin / 有料 GET"
expect_status 400 "未知 Host（DNS rebinding 相当）" -H 'Host: attacker.example' "$base/health"
expect_status 403 "別 Origin からの書込" \
  -X POST -H 'Content-Type: application/json' -H 'Origin: http://evil.example' -d "$answer" \
  "$base/api/answers/check"
expect_status 403 "Origin を示さない書込" \
  -X POST -H 'Content-Type: application/json' -d "$answer" "$base/api/answers/check"
expect_status 403 "独自ヘッダーなしの TTS（<audio src> 相当）" "$base/api/tts/speak?text=probe"
expect_status 403 "別 Origin からの TTS" \
  -H 'X-French-Tutor-Request: 1' -H 'Origin: http://evil.example' \
  "$base/api/tts/speak?text=probe"

acao=$(curl -s -o /dev/null -D - --connect-timeout 3 --max-time 10 -X OPTIONS \
  -H 'Origin: http://evil.example' -H 'Access-Control-Request-Method: POST' \
  "$base/api/answers/check" | tr -d '\r' | grep -i '^access-control-allow-origin:' || true)
if [[ -z "$acao" ]]; then pass "preflight に CORS 許可を返さない"; else fail "preflight: $acao"; fi

echo
if ((failures > 0)); then
  echo "$failures 件失敗。docs/operations/local-lan-runbook.md の切り分け手順を参照。"
  exit 1
fi
echo "すべて期待どおり。"
