#!/usr/bin/env bash
# 部署 Bilibili MCP 到 Cloud Run
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

set -a && [ -f "$ROOT/.env" ] && source "$ROOT/.env"; set +a

PROJECT="${GCP_PROJECT_ID:?请在 .env 设置 GCP_PROJECT_ID}"
REGION="${GCP_LOCATION:-${CLOUD_RUN_REGION:-us-central1}}"
SERVICE="${BILIBILI_MCP_CLOUD_RUN_SERVICE:-bilibili-mcp}"
BUCKET="${MCP_ARTIFACT_GCS_BUCKET:-${ETSY_IMAGE_GCS_BUCKET:-}}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}:latest"

if [ -z "$BUCKET" ]; then
  echo "⚠️ 未设置 MCP_ARTIFACT_GCS_BUCKET：Excel 导出会失败。" >&2
fi

# 确保 Artifact Registry repo 存在（忽略已存在错误）
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
    args: ['build', '-t', '${IMAGE}', '-f', 'services/bilibili_mcp/Dockerfile', '.']
images:
  - '${IMAGE}'
timeout: 1200s
EOF

echo "🔨 Building ${IMAGE} ..."
gcloud builds submit --project="${PROJECT}" --config="${BUILD_YAML}" "${ROOT}"

echo "🚀 Deploying ${SERVICE} ..."
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --allow-unauthenticated \
  --memory=1Gi \
  --cpu=1 \
  --timeout=120 \
  --session-affinity \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT},MCP_DISABLE_DNS_REBINDING=1,MCP_STATELESS_HTTP=1,FASTMCP_STATELESS_HTTP=true,FASTMCP_JSON_RESPONSE=true,MCP_ARTIFACT_GCS_BUCKET=${BUCKET},MCP_ARTIFACT_GCS_PREFIX=${MCP_ARTIFACT_GCS_PREFIX:-mcp-artifacts/}" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" --project="${PROJECT}" --region="${REGION}" --format='value(status.url)')"
MCP_URL="${URL%/}/mcp"
echo ""
echo "✅ Bilibili MCP: ${MCP_URL}"
echo "请写入仓库根 .env："
echo "  BILIBILI_MCP_SERVER_URL=${MCP_URL}"
echo "然后执行 ./scripts/deploy_smart_agents.sh 更新 Agent Engine"
