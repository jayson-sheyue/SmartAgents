#!/usr/bin/env bash
# 本地 adk run bilibili_cloud_agent_mcp — B 站 MCP + Skill（默认本机 :8002）
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
export BILIBILI_MCP_SERVER_URL="${BILIBILI_MCP_SERVER_URL:-http://127.0.0.1:8002/mcp}"

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec adk run bilibili_cloud_agent_mcp "$@"
