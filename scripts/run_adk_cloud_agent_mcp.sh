#!/usr/bin/env bash
# 本地 adk run cloud_agent_mcp — Vertex 代理 + 本机 MCP（免 ngrok）
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
# 本机 MCP HTTP（mcp_server/bilibili_mcp.py --http :8002）
export MCP_SERVER_URL="${MCP_SERVER_URL:-http://127.0.0.1:8002/mcp}"

source "$ROOT/.venvAgents/bin/activate"
exec adk run cloud_agent_mcp "$@"
