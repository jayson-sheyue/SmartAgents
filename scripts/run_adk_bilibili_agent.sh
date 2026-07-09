#!/usr/bin/env bash
# 本地 adk run bilibili_agent — B 站 Skill Agent（进程内工具，无需 MCP/REST）
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

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec adk run bilibili_agent "$@"
