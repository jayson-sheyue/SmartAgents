#!/usr/bin/env bash
# 部署 Etsy MCP 到 Cloud Run（同步生图，timeout 拉高）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

set -a && [ -f "$ROOT/.env" ] && source "$ROOT/.env"; set +a

PROJECT="${GCP_PROJECT_ID:?请在 .env 设置 GCP_PROJECT_ID}"
REGION="${GCP_LOCATION:-${CLOUD_RUN_REGION:-us-central1}}"
SERVICE="${ETSY_MCP_CLOUD_RUN_SERVICE:-etsy-mcp}"
BUCKET="${MCP_ARTIFACT_GCS_BUCKET:-${ETSY_IMAGE_GCS_BUCKET:-}}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}:latest"

if [ -z "${ETSY_KEYSTRING:-}" ] && [ -z "${ETSY_API_KEY:-}" ]; then
  echo "⚠️ 未设置 ETSY_KEYSTRING / ETSY_API_KEY：评论 API 会失败。" >&2
fi
if [ -z "$BUCKET" ]; then
  echo "⚠️ 未设置 MCP_ARTIFACT_GCS_BUCKET / ETSY_IMAGE_GCS_BUCKET：Excel/生图会失败。" >&2
fi

gcloud artifacts repositories describe cloud-run-source-deploy \
  --project="${PROJECT}" --location="${REGION}" >/dev/null 2>&1 \
  || gcloud artifacts repositories create cloud-run-source-deploy \
       --project="${PROJECT}" --location="${REGION}" --repository-format=docker \
       --description="SmartAgents MCP images"

BUILD_YAML="$(mktemp)"
trap 'rm -f "${BUILD_YAML}"' EXIT
cat > "${BUILD_YAML}" <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-t', '${IMAGE}', '-f', 'services/etsy_mcp/Dockerfile', '.']
images:
  - '${IMAGE}'
timeout: 1800s
EOF

echo "🔨 Building ${IMAGE} ..."
gcloud builds submit --project="${PROJECT}" --config="${BUILD_YAML}" "${ROOT}"

# 注意：密钥以 env 注入（教学）；生产请改 Secret Manager
ENV_VARS="GCP_PROJECT_ID=${PROJECT}"
ENV_VARS+=",MCP_DISABLE_DNS_REBINDING=1"
ENV_VARS+=",MCP_STATELESS_HTTP=1"
ENV_VARS+=",FASTMCP_STATELESS_HTTP=true"
ENV_VARS+=",FASTMCP_JSON_RESPONSE=true"
ENV_VARS+=",MCP_ARTIFACT_GCS_BUCKET=${BUCKET}"
ENV_VARS+=",MCP_ARTIFACT_GCS_PREFIX=${MCP_ARTIFACT_GCS_PREFIX:-mcp-artifacts/}"
ENV_VARS+=",ETSY_IMAGE_GCS_BUCKET=${ETSY_IMAGE_GCS_BUCKET:-${BUCKET}}"
ENV_VARS+=",ETSY_IMAGE_GCS_PREFIX=${ETSY_IMAGE_GCS_PREFIX:-etsy/}"
ENV_VARS+=",ETSY_IMAGE_MODEL=${ETSY_IMAGE_MODEL:-gemini-3.1-flash-image}"
ENV_VARS+=",ETSY_IMAGE_LOCATION=${ETSY_IMAGE_LOCATION:-global}"
ENV_VARS+=",ETSY_KEYSTRING=${ETSY_KEYSTRING:-}"
ENV_VARS+=",ETSY_SHARED_SECRET=${ETSY_SHARED_SECRET:-}"
ENV_VARS+=",ETSY_API_KEY=${ETSY_API_KEY:-}"

echo "🚀 Deploying ${SERVICE} ..."
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --allow-unauthenticated \
  --memory=2Gi \
  --cpu=2 \
  --timeout=300 \
  --session-affinity \
  --set-env-vars="${ENV_VARS}" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" --project="${PROJECT}" --region="${REGION}" --format='value(status.url)')"
MCP_URL="${URL%/}/mcp"
echo ""
echo "✅ Etsy MCP: ${MCP_URL}"
echo "请写入仓库根 .env："
echo "  ETSY_MCP_SERVER_URL=${MCP_URL}"
echo "然后执行 ./scripts/deploy_smart_agents.sh 更新 Agent Engine"
