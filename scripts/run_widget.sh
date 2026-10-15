#!/usr/bin/env bash
# 启动 Web Widget 中转（:8000）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=lib/load_env.sh
source "$ROOT/scripts/lib/load_env.sh"
load_smartagents_env "$ROOT"

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

source "$ROOT/.venvAgents/bin/activate"
exec python "$ROOT/local_node/widget_server.py"
