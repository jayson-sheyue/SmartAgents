#!/usr/bin/env bash
# 飞书群聊/私聊 → smart_agents（本地 ADK Runner + 双 MCP）
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

export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost,.local}"
export BILIBILI_MCP_SERVER_URL="${SMART_AGENTS_BILIBILI_MCP_SERVER_URL:-${BILIBILI_MCP_SERVER_URL:-}}"
export ETSY_MCP_SERVER_URL="${SMART_AGENTS_ETSY_MCP_SERVER_URL:-${ETSY_MCP_SERVER_URL:-}}"
if [ -z "${BILIBILI_MCP_SERVER_URL}" ] || [ -z "${ETSY_MCP_SERVER_URL}" ]; then
  echo "请在 .env 设置 Cloud Run BILIBILI_MCP_SERVER_URL / ETSY_MCP_SERVER_URL" >&2
  exit 1
fi

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

python "$ROOT/scripts/check_runtime_env.py" --mode feishu

if ! python -c "import lark_oapi" 2>/dev/null; then
  pip install -r "$ROOT/integrations/feishu/requirements.txt"
fi

exec python -m integrations.feishu.bridge "$@"
