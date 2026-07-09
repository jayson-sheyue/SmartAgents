#!/usr/bin/env bash
# 本地 adk run smart_agents — 调度 Agent + 双 MCP 子 Agent
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
# smart_agents 本地联调：默认强制本机双 MCP（避免 .env 只配 B 站隧道、Etsy 走 127.0.0.1 的混用）
# 若需 Cloudflare Tunnel，请显式：export SMART_AGENTS_BILIBILI_MCP_SERVER_URL=... SMART_AGENTS_ETSY_MCP_SERVER_URL=...
export BILIBILI_MCP_SERVER_URL="${SMART_AGENTS_BILIBILI_MCP_SERVER_URL:-http://127.0.0.1:8002/mcp}"
export ETSY_MCP_SERVER_URL="${SMART_AGENTS_ETSY_MCP_SERVER_URL:-http://127.0.0.1:8003/mcp}"

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec adk run smart_agents "$@"
