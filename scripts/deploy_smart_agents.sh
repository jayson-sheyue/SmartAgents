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
if [ -z "${BILIBILI_MCP_SERVER_URL:-}" ] || [[ "${BILIBILI_MCP_SERVER_URL}" == *"127.0.0.1"* ]]; then
  echo "请设置 Cloud Run BILIBILI_MCP_SERVER_URL（先 ./scripts/deploy_bilibili_mcp_cloudrun.sh）" >&2
  exit 1
fi
if [ -z "${ETSY_MCP_SERVER_URL:-}" ] || [[ "${ETSY_MCP_SERVER_URL}" == *"127.0.0.1"* ]]; then
  echo "请设置 Cloud Run ETSY_MCP_SERVER_URL（先 ./scripts/deploy_etsy_mcp_cloudrun.sh）" >&2
  exit 1
fi
if [ -z "${FEISHU_MCP_SERVER_URL:-}" ] || [[ "${FEISHU_MCP_SERVER_URL}" == *"127.0.0.1"* ]]; then
  echo "请设置 Cloud Run FEISHU_MCP_SERVER_URL（先 ./scripts/deploy_feishu_mcp_cloudrun.sh）" >&2
  exit 1
fi

# Check before creating files or attempting any cloud update; do not load local.env.
"$ROOT/.venvAgents/bin/python" -m scripts.check_sap_deployment --online

# 1) 打包进 smart_agents/ 的 Skill（adk deploy 只复制该目录）
mkdir -p "$ROOT/smart_agents/skills"
rsync -a --delete "$ROOT/skills/bilibili-trend/" "$ROOT/smart_agents/skills/bilibili-trend/"
rsync -a --delete "$ROOT/skills/etsy-review/" "$ROOT/smart_agents/skills/etsy-review/"
rsync -a --delete "$ROOT/skills/etsy-listing-assets/" "$ROOT/smart_agents/skills/etsy-listing-assets/"
rsync -a --delete "$ROOT/skills/feishu-ops/" "$ROOT/smart_agents/skills/feishu-ops/"
rsync -a --delete "$ROOT/skills/tse-to-bitable/" "$ROOT/smart_agents/skills/tse-to-bitable/"
# 清理已废弃 skill 目录
rm -rf "$ROOT/smart_agents/skills/bilibili-rpa" "$ROOT/smart_agents/skills/bilibili-trend-rpa"

# 2) 云端运行时 ADK 读取 smart_agents/.env
cat > "$ROOT/smart_agents/.env" <<EOF
BILIBILI_MCP_SERVER_URL=${BILIBILI_MCP_SERVER_URL}
ETSY_MCP_SERVER_URL=${ETSY_MCP_SERVER_URL}
FEISHU_MCP_SERVER_URL=${FEISHU_MCP_SERVER_URL}
MCP_ARTIFACT_GCS_BUCKET=${MCP_ARTIFACT_GCS_BUCKET:-${ETSY_IMAGE_GCS_BUCKET:-}}
GCP_PROJECT_ID=${GCP_PROJECT_ID:-}
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
CODE_EXEC_ALLOWED_GCS_BUCKETS=${CODE_EXEC_ALLOWED_GCS_BUCKETS:-tse-medias-asia,${MCP_ARTIFACT_GCS_BUCKET:-},${ETSY_IMAGE_GCS_BUCKET:-}}
SMART_AGENTS_ENGINE_ID=${SMART_AGENTS_ENGINE_ID:-}
SAP_COMPUTER_USE_ENABLED=${SAP_COMPUTER_USE_ENABLED:-false}
INVOICE_RECOGNITION_MODEL=${INVOICE_RECOGNITION_MODEL:-gemini-3.8-flash}
EOF

# Agent Engine 拒绝空 env value；会话 Key 为主，TSE_API_KEY 仅在非空时写入
if [ -n "${TSE_API_KEY:-}" ]; then
  printf 'TSE_API_KEY=%s\n' "${TSE_API_KEY}" >> "$ROOT/smart_agents/.env"
fi
# Optional worker settings must survive deployment; never print their values.
for sap_env_key in SAP_COMPUTER_USE_WORKER_URL SAP_COMPUTER_USE_TOKEN SAP_BROWSER_EXECUTION_MODE SAP_COMPUTER_USE_IAM_AUTH SAP_DEPLOY_CHECK_USER; do
  if [ -n "${!sap_env_key:-}" ]; then
    printf '%s=%s\n' "$sap_env_key" "${!sap_env_key}" >> "$ROOT/smart_agents/.env"
  fi
done
chmod 600 "$ROOT/smart_agents/.env"

echo "📦 Skills synced → smart_agents/skills/ (bilibili-trend, etsy-*, feishu-ops, tse-to-bitable)"
echo "📄 Wrote smart_agents/.env (Cloud Run MCP URLs)"
echo "🚀 Deploying Engine ${SMART_AGENTS_ENGINE_ID} ..."

source "$ROOT/.venvAgents/bin/activate"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:$PYTHONPATH}"

python "$ROOT/scripts/deploy_smart_agents.py"
