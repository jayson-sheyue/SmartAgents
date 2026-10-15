#!/usr/bin/env bash
# 并行第二 Engine：部署 SmartAgents A2A 包装（不替换 xiaozhi / SMART_AGENTS_ENGINE_ID）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

set -a
[ -f "$ROOT/.env" ] && source "$ROOT/.env"
set +a

if [ -z "${GCP_PROJECT_ID:-}" ] || [ -z "${GCP_LOCATION:-}" ]; then
  echo "请在仓库根 .env 设置 GCP_PROJECT_ID / GCP_LOCATION" >&2
  exit 1
fi
if [ -z "${BILIBILI_MCP_SERVER_URL:-}" ] || [[ "${BILIBILI_MCP_SERVER_URL}" == *"127.0.0.1"* ]]; then
  echo "请设置 Cloud Run BILIBILI_MCP_SERVER_URL" >&2
  exit 1
fi
if [ -z "${ETSY_MCP_SERVER_URL:-}" ] || [[ "${ETSY_MCP_SERVER_URL}" == *"127.0.0.1"* ]]; then
  echo "请设置 Cloud Run ETSY_MCP_SERVER_URL" >&2
  exit 1
fi

mkdir -p "$ROOT/smart_agents/skills"
rsync -a --delete "$ROOT/skills/bilibili-trend/" "$ROOT/smart_agents/skills/bilibili-trend/"
rsync -a --delete "$ROOT/skills/etsy-review/" "$ROOT/smart_agents/skills/etsy-review/"
rsync -a --delete "$ROOT/skills/etsy-listing-assets/" "$ROOT/smart_agents/skills/etsy-listing-assets/"
rm -rf "$ROOT/smart_agents/skills/bilibili-rpa" "$ROOT/smart_agents/skills/bilibili-trend-rpa"

cat > "$ROOT/smart_agents/.env" <<EOF
BILIBILI_MCP_SERVER_URL=${BILIBILI_MCP_SERVER_URL}
ETSY_MCP_SERVER_URL=${ETSY_MCP_SERVER_URL}
MCP_ARTIFACT_GCS_BUCKET=${MCP_ARTIFACT_GCS_BUCKET:-${ETSY_IMAGE_GCS_BUCKET:-}}
GCP_PROJECT_ID=${GCP_PROJECT_ID:-}
GCP_LOCATION=${GCP_LOCATION:-}
RAG_ENABLED=${RAG_ENABLED:-false}
RAG_CORPUS_NAME=${RAG_CORPUS_NAME:-}
RAG_LOCATION=${RAG_LOCATION:-}
RAG_PROJECT_ID=${RAG_PROJECT_ID:-${GCP_PROJECT_ID:-}}
GCP_DATA_MCP_ENABLED=${GCP_DATA_MCP_ENABLED:-false}
TSE_FIRESTORE_PROJECT_ID=${TSE_FIRESTORE_PROJECT_ID:-}
TSE_FIRESTORE_DATABASE=${TSE_FIRESTORE_DATABASE:-}
TSE_API_BASE_URL=${TSE_API_BASE_URL:-}
CODE_EXECUTION_ENABLED=${CODE_EXECUTION_ENABLED:-false}
CODE_EXEC_LOCATION=${CODE_EXEC_LOCATION:-us-central1}
SMART_AGENTS_ENGINE_ID=${SMART_AGENTS_ENGINE_ID:-}
EOF

if [ -n "${TSE_API_KEY:-}" ]; then
  printf 'TSE_API_KEY=%s\n' "${TSE_API_KEY}" >> "$ROOT/smart_agents/.env"
fi

echo "📦 A2A skills synced; Cloud Run MCP URLs written"
source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"
python "$ROOT/scripts/deploy_smart_agents_a2a.py"
