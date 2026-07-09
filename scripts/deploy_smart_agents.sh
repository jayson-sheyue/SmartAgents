#!/usr/bin/env bash
# 部署 smart_agents 到 Agent Engine（同步 skills + 生成 smart_agents/.env）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

set -a && [ -f "$ROOT/.env" ] && source "$ROOT/.env"; set +a

if [ -z "${GCP_PROJECT_ID:-}" ] || [ -z "${GCP_LOCATION:-}" ]; then
  echo "请在仓库根 .env 设置 GCP_PROJECT_ID / GCP_LOCATION" >&2
  exit 1
fi
if [ -z "${SMART_AGENTS_ENGINE_ID:-}" ]; then
  echo "请在仓库根 .env 设置 SMART_AGENTS_ENGINE_ID" >&2
  exit 1
fi

# 1) 打包进 smart_agents/ 的 Skill（adk deploy 只复制该目录）
mkdir -p "$ROOT/smart_agents/skills"
rsync -a --delete "$ROOT/skills/bilibili-rpa/" "$ROOT/smart_agents/skills/bilibili-rpa/"
rsync -a --delete "$ROOT/skills/etsy-review/" "$ROOT/smart_agents/skills/etsy-review/"

# 2) 云端运行时 ADK 读取 smart_agents/.env（根目录 --env_file 已废弃）
cat > "$ROOT/smart_agents/.env" <<EOF
BILIBILI_MCP_SERVER_URL=${BILIBILI_MCP_SERVER_URL:-http://127.0.0.1:8002/mcp}
BILIBILI_TUNNEL_HOST=${BILIBILI_TUNNEL_HOST:-}
ETSY_MCP_SERVER_URL=${ETSY_MCP_SERVER_URL:-http://127.0.0.1:8003/mcp}
ETSY_TUNNEL_HOST=${ETSY_TUNNEL_HOST:-}
GCP_PROJECT_ID=${GCP_PROJECT_ID:-}
RAG_ENABLED=${RAG_ENABLED:-false}
RAG_CORPUS_NAME=${RAG_CORPUS_NAME:-}
RAG_LOCATION=${RAG_LOCATION:-}
RAG_PROJECT_ID=${RAG_PROJECT_ID:-${GCP_PROJECT_ID:-}}
EOF

echo "📦 Skills synced → smart_agents/skills/"
echo "📄 Wrote smart_agents/.env (MCP URLs + RAG)"
echo "🚀 Deploying Engine ${SMART_AGENTS_ENGINE_ID} ..."

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

adk deploy agent_engine smart_agents \
  --project="$GCP_PROJECT_ID" \
  --region="$GCP_LOCATION" \
  --display_name="SmartAgents Dispatcher" \
  --agent_engine_id="$SMART_AGENTS_ENGINE_ID" \
  --adk_app_object=app
