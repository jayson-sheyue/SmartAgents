#!/usr/bin/env bash
# 飞书群聊/私聊 → smart_agents（本地 ADK Runner + 双 MCP）
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
export BILIBILI_MCP_SERVER_URL="${SMART_AGENTS_BILIBILI_MCP_SERVER_URL:-http://127.0.0.1:8002/mcp}"
export ETSY_MCP_SERVER_URL="${SMART_AGENTS_ETSY_MCP_SERVER_URL:-http://127.0.0.1:8003/mcp}"

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

if ! python -c "import lark_oapi" 2>/dev/null; then
  pip install -r "$ROOT/integrations/feishu/requirements.txt"
fi

exec python -m integrations.feishu.bridge "$@"
