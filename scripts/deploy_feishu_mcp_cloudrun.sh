#!/usr/bin/env bash
# 部署 Feishu MCP（内嵌 lark-cli）到 Cloud Run
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

set -a && [ -f "$ROOT/.env" ] && source "$ROOT/.env"; set +a

PROJECT="${GCP_PROJECT_ID:?请在 .env 设置 GCP_PROJECT_ID}"
REGION="${GCP_LOCATION:-${CLOUD_RUN_REGION:-us-central1}}"
SERVICE="${FEISHU_MCP_CLOUD_RUN_SERVICE:-feishu-mcp}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/cloud-run-source-deploy/${SERVICE}:latest"

if [ -z "${FEISHU_APP_ID:-}" ] || { [ -z "${FEISHU_APP_SECRET:-}" ] && [ -z "${FEISHU_APP_TOKEN:-}" ]; }; then
  echo "⚠️ 未设置 FEISHU_APP_ID + FEISHU_APP_SECRET：Bot 调用会失败。" >&2
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
    args: ['build', '-t', '${IMAGE}', '-f', 'services/feishu_mcp/Dockerfile', '.']
images:
  - '${IMAGE}'
timeout: 1800s
EOF

echo "🔨 Building ${IMAGE} ..."
gcloud builds submit --project="${PROJECT}" --config="${BUILD_YAML}" "${ROOT}"

APP_ID="${FEISHU_APP_ID:-}"
APP_SECRET="${FEISHU_APP_SECRET:-${FEISHU_APP_TOKEN:-}}"

ENV_FILE="$(mktemp)"
trap 'rm -f "${BUILD_YAML}" "${ENV_FILE}"' EXIT
# YAML env-vars-file avoids comma/special-char breakage in --set-env-vars
python3 - "${ENV_FILE}" "${PROJECT}" "${APP_ID}" "${APP_SECRET}" "${FEISHU_BASE_WEB_ORIGIN:-https://your-tenant.feishu.cn}" <<'PY'
import sys
from pathlib import Path

path, project, app_id, app_secret, web_origin = sys.argv[1:6]

def yq(s: str) -> str:
    # Minimal YAML double-quoted scalar escape
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

lines = [
    f"GCP_PROJECT_ID: {yq(project)}",
    "MCP_DISABLE_DNS_REBINDING: \"1\"",
    "MCP_STATELESS_HTTP: \"1\"",
    "FASTMCP_STATELESS_HTTP: \"true\"",
    "FASTMCP_JSON_RESPONSE: \"true\"",
    f"FEISHU_APP_ID: {yq(app_id)}",
    f"FEISHU_APP_SECRET: {yq(app_secret)}",
    f"LARKSUITE_CLI_APP_ID: {yq(app_id)}",
    f"LARKSUITE_CLI_APP_SECRET: {yq(app_secret)}",
    'FEISHU_OAUTH_FIRESTORE_COLLECTION: "feishu_user_oauth"',
    'FEISHU_OAUTH_PENDING_COLLECTION: "feishu_oauth_pending"',
    f"FEISHU_BASE_WEB_ORIGIN: {yq(web_origin.rstrip('/'))}",
]
Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"env_file keys ok; app_id_len={len(app_id)} secret_len={len(app_secret)} origin={web_origin}")
PY

echo "🚀 Deploying ${SERVICE} ..."
gcloud run deploy "${SERVICE}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --allow-unauthenticated \
  --memory=1Gi \
  --cpu=1 \
  --timeout=180 \
  --session-affinity \
  --env-vars-file="${ENV_FILE}" \
  --quiet

URL="$(gcloud run services describe "${SERVICE}" --project="${PROJECT}" --region="${REGION}" --format='value(status.url)')"
MCP_URL="${URL%/}/mcp"

# OAuth tokens live in Firestore (feishu_user_oauth); grant Cloud Run runtime SA access
RUNTIME_SA="$(gcloud run services describe "${SERVICE}" --project="${PROJECT}" --region="${REGION}" --format='value(spec.template.spec.serviceAccountName)')"
if [ -z "${RUNTIME_SA}" ] || [ "${RUNTIME_SA}" = "" ]; then
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')"
  RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
fi
echo "🔐 Ensuring Firestore access for ${RUNTIME_SA} ..."
gcloud projects add-iam-policy-binding "${PROJECT}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/datastore.user" \
  --condition=None \
  --quiet >/dev/null || true

echo ""
echo "✅ Feishu MCP: ${MCP_URL}"
echo "请写入仓库根 .env："
echo "  FEISHU_MCP_SERVER_URL=${MCP_URL}"
echo "然后执行 ./scripts/deploy_smart_agents.sh 更新 Agent Engine"
