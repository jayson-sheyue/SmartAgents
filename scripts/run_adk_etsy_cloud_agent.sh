#!/usr/bin/env bash
# 本地 adk run etsy_cloud_agent — Etsy REST + Skill（经 ETSY_REST_SERVER_URL / 本机 :8001）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a && [ -f "$ROOT/.env" ] && source "$ROOT/.env"; set +a

if [ -z "${VERTEX_HTTP_PROXY:-}" ]; then
  for v in HTTPS_PROXY https_proxy HTTP_PROXY http_proxy; do
    if [ -n "${!v:-}" ]; then
      export VERTEX_HTTP_PROXY="${!v}"
      break
    fi
  done
fi
for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy; do
  unset "$v" 2>/dev/null || true
done

export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost,.local}"
export ETSY_REST_SERVER_URL="${ETSY_REST_SERVER_URL:-http://127.0.0.1:8001}"

source "$ROOT/.venvAgents/bin/activate"
exec adk run etsy_cloud_agent "$@"
