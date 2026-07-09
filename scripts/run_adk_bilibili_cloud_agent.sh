#!/usr/bin/env bash
# 本地 adk run bilibili_cloud_agent（B 站 REST + Skill）
# - 把 Shell 里的 HTTPS_PROXY 转成 VERTEX_HTTP_PROXY（仅 Vertex 用）
# - 清掉全局 HTTP_PROXY，避免 httpx 自动代理 TLS 失败
# - 本地 REST 仍直连 127.0.0.1:8001
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a && [ -f "$ROOT/.env" ] && source "$ROOT/.env"; set +a

if [ -z "${VERTEX_HTTP_PROXY:-}" ]; then
  if [ -n "${HTTPS_PROXY:-}" ]; then
    export VERTEX_HTTP_PROXY="$HTTPS_PROXY"
  elif [ -n "${https_proxy:-}" ]; then
    export VERTEX_HTTP_PROXY="$https_proxy"
  elif [ -n "${HTTP_PROXY:-}" ]; then
    export VERTEX_HTTP_PROXY="$HTTP_PROXY"
  elif [ -n "${http_proxy:-}" ]; then
    export VERTEX_HTTP_PROXY="$http_proxy"
  fi
fi

for v in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy; do
  unset "$v" 2>/dev/null || true
done

export NO_PROXY="${NO_PROXY:-127.0.0.1,localhost,.local}"
export BILIBILI_REST_SERVER_URL="${BILIBILI_REST_SERVER_URL:-http://127.0.0.1:8001}"

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
exec adk run bilibili_cloud_agent "$@"
