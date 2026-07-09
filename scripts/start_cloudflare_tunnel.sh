#!/usr/bin/env bash
# 为本地 REST / 双 MCP 启动 Cloudflare Quick Tunnel（每条隧道一个终端更稳妥）
set -euo pipefail

cat <<'EOF'
Cloudflare Quick Tunnel — 本地服务公网暴露

前置：brew install cloudflare/cloudflare/cloudflared

每个端口单独开一个终端（cloudflared 会打印 trycloudflare.com 域名）：

  # REST（:8001）— bilibili_cloud_agent / etsy_cloud_agent
  cloudflared tunnel --url http://127.0.0.1:8001

  # Bilibili MCP（:8002）
  cloudflared tunnel --url http://127.0.0.1:8002

  # Etsy MCP（:8003）
  cloudflared tunnel --url http://127.0.0.1:8003

将输出的 https 域名写入 .env，例如：

  BILIBILI_REST_SERVER_URL=https://<uuid>.trycloudflare.com
  BILIBILI_MCP_SERVER_URL=https://<uuid>.trycloudflare.com/mcp
  BILIBILI_TUNNEL_HOST=<uuid>.trycloudflare.com
  ETSY_MCP_SERVER_URL=https://<uuid>.trycloudflare.com/mcp
  ETSY_TUNNEL_HOST=<uuid>.trycloudflare.com

调度树云端部署后执行：./scripts/deploy_smart_agents.sh
EOF

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
  exit 0
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "未找到 cloudflared，请先安装：brew install cloudflare/cloudflare/cloudflared" >&2
  exit 1
fi

PORT="${1:-}"
if [ -z "$PORT" ]; then
  echo "用法: $0 <port>   例如 $0 8002" >&2
  echo "或:   $0 --help" >&2
  exit 1
fi

echo "启动 Cloudflare Quick Tunnel → http://127.0.0.1:$PORT"
exec cloudflared tunnel --url "http://127.0.0.1:$PORT"
