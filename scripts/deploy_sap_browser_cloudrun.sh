#!/usr/bin/env bash
# Explicit administrator deployment. Never run from chat or a browser callback.
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
set -a
[ ! -f "$ROOT/.env" ] || source "$ROOT/.env"
set +a
PROJECT="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
REGION="${SAP_CLOUD_REGION:-us-central1}"
SERVICE="${SAP_CLOUD_SERVICE:-sap-browser-demo}"
RUNTIME_SA="${SAP_CLOUD_SERVICE_ACCOUNT:?Set a dedicated existing SAP worker service account email}"
STATE_BUCKET="${SAP_AUTH_STATE_BUCKET:?Set a dedicated private SAP auth state bucket name}"
INVOKERS="${SAP_CLOUD_INVOKER_ACCOUNTS:?Comma-separated TSE and Agent Engine runtime service account emails}"
: "${SAP_BROWSER_URL:?Set SAP_BROWSER_URL}"
: "${SAP_DEPLOY_CHECK_USER:?Set SAP_DEPLOY_CHECK_USER=tse:actual-tse-email}"
TOKEN_SECRET="${SAP_CLOUD_TOKEN_SECRET:-sap-browser-token}"
STATE_SECRET="${SAP_CLOUD_STATE_SECRET:-sap-browser-state-key}"
PYTHON="$ROOT/.venvAgents/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
export PROJECT REGION SERVICE STATE_BUCKET
"$PYTHON" - <<'PY'
import os,re
from scripts.check_sap_deployment import validate_sap_deployment
from domains.sap.policy import tenant_url
tenant_url(os.environ['SAP_BROWSER_URL'])
for key in ('SAP_CLOUD_SERVICE_ACCOUNT','SAP_CLOUD_INVOKER_ACCOUNTS'):
    if not all(re.fullmatch(r'[a-zA-Z0-9_.-]+@(?:[a-zA-Z0-9.-]+\.iam|developer)\.gserviceaccount\.com', x.strip()) for x in os.environ[key].split(',')):
        raise SystemExit('Invalid service account email')
if not os.environ['SAP_DEPLOY_CHECK_USER'].startswith('tse:'):
    raise SystemExit('SAP_DEPLOY_CHECK_USER must be a trusted TSE identity')
PY
# Fail before creating resources if the selected runtime identity does not exist.
gcloud iam service-accounts describe "$RUNTIME_SA" --project="$PROJECT" >/dev/null
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export SAP_DEPLOY_WORK="$WORK"
"$PYTHON" - <<'PY'
import os,secrets,base64
from pathlib import Path
p=Path(os.environ['SAP_DEPLOY_WORK'])
token=os.getenv('SAP_COMPUTER_USE_TOKEN') or secrets.token_urlsafe(32)
if len(token)<32: raise SystemExit('SAP_COMPUTER_USE_TOKEN must have at least 32 characters')
(p/'token').write_text(token)
(p/'state-key').write_bytes(base64.urlsafe_b64encode(secrets.token_bytes(32)))
PY

# IAM is scoped to this service, these secrets, and the dedicated private bucket.
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --project="$PROJECT"
gcloud storage buckets describe "gs://$STATE_BUCKET" --project="$PROJECT" >/dev/null 2>&1 \
  || gcloud storage buckets create "gs://$STATE_BUCKET" --project="$PROJECT" --location="$REGION" --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://$STATE_BUCKET" --public-access-prevention
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$RUNTIME_SA" --role=roles/aiplatform.user --condition=None >/dev/null
gcloud storage buckets add-iam-policy-binding "gs://$STATE_BUCKET" --member="serviceAccount:$RUNTIME_SA" --role=roles/storage.objectUser >/dev/null
if gcloud secrets describe "$TOKEN_SECRET" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud secrets versions add "$TOKEN_SECRET" --data-file="$WORK/token" --project="$PROJECT" >/dev/null
else
  gcloud secrets create "$TOKEN_SECRET" --data-file="$WORK/token" --replication-policy=automatic --project="$PROJECT" >/dev/null
fi
# Preserve the encryption key on redeploy: replacing it would invalidate saved logins.
gcloud secrets describe "$STATE_SECRET" --project="$PROJECT" >/dev/null 2>&1 \
  || gcloud secrets create "$STATE_SECRET" --data-file="$WORK/state-key" --replication-policy=automatic --project="$PROJECT" >/dev/null
for secret in "$TOKEN_SECRET" "$STATE_SECRET"; do
  gcloud secrets add-iam-policy-binding "$secret" --project="$PROJECT" --member="serviceAccount:$RUNTIME_SA" --role=roles/secretmanager.secretAccessor >/dev/null
done
gcloud artifacts repositories describe cloud-run-source-deploy --project="$PROJECT" --location="$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create cloud-run-source-deploy --project="$PROJECT" --location="$REGION" --repository-format=docker
IMAGE="$REGION-docker.pkg.dev/$PROJECT/cloud-run-source-deploy/$SERVICE:$(date +%Y%m%d%H%M%S)"
cat > "$WORK/build.yaml" <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-t', '$IMAGE', '-f', 'services/sap_computer_use/Dockerfile', '.']
images: ['$IMAGE']
timeout: 1800s
EOF
"$PYTHON" - <<'PY'
import json,os
from pathlib import Path
env={'GCP_PROJECT_ID':os.environ['PROJECT'], 'SAP_BROWSER_EXECUTION_MODE':'cloud',
     'SAP_BROWSER_URL':os.environ['SAP_BROWSER_URL'], 'SAP_AUTH_STATE_BUCKET':os.environ['STATE_BUCKET'],
     'SAP_COMPUTER_USE_MODEL':os.getenv('SAP_COMPUTER_USE_MODEL','gemini-3.8-flash'),
     'SAP_COMPUTER_USE_LOCATION':os.getenv('SAP_COMPUTER_USE_LOCATION','global'),
     'SAP_LOGIN_ALLOWED_ORIGINS':os.getenv('SAP_LOGIN_ALLOWED_ORIGINS',''),
     'SAP_LOGIN_START_URL':os.getenv('SAP_LOGIN_START_URL',''),
     'SAP_COMPUTER_USE_GOLDEN_PATH':'true', 'SAP_COMPUTER_USE_DEMO_MODE':'computer-use',
     'SAP_CLOUD_MAX_SESSIONS':os.getenv('SAP_CLOUD_MAX_SESSIONS','4'), 'SAP_CLOUD_IDLE_SECONDS':'900'}
Path(os.environ['SAP_DEPLOY_WORK']+'/env.yaml').write_text(json.dumps(env))
PY
gcloud builds submit --project="$PROJECT" --config="$WORK/build.yaml" --suppress-logs "$ROOT"
gcloud run deploy "$SERVICE" --project="$PROJECT" --region="$REGION" --image="$IMAGE" \
  --service-account="$RUNTIME_SA" --no-allow-unauthenticated --memory=4Gi --cpu=2 \
  --timeout=240 --concurrency=8 --min=0 --min-instances=default --max-instances=1 --no-cpu-throttling \
  --env-vars-file="$WORK/env.yaml" \
  --set-secrets="SAP_COMPUTER_USE_TOKEN=$TOKEN_SECRET:latest,SAP_AUTH_STATE_KEY=$STATE_SECRET:latest" --quiet
IFS=',' read -r -a accounts <<< "$INVOKERS"
for caller in "${accounts[@]}"; do
  caller="${caller//[[:space:]]/}"
  gcloud run services add-iam-policy-binding "$SERVICE" --project="$PROJECT" --region="$REGION" \
    --member="serviceAccount:$caller" --role=roles/run.invoker >/dev/null
done
SAP_CLOUD_DEPLOYED_URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)')"
export SAP_CLOUD_DEPLOYED_URL
"$PYTHON" - <<'PY'
import os
from pathlib import Path
from scripts.sap_local_bridge import update_env
root=Path.cwd();directory=root/'.sap_cloud';directory.mkdir(exist_ok=True,mode=0o700)
values={'SAP_COMPUTER_USE_ENABLED':'true','SAP_BROWSER_EXECUTION_MODE':'cloud',
        'SAP_COMPUTER_USE_IAM_AUTH':'true','SAP_COMPUTER_USE_WORKER_URL':os.environ['SAP_CLOUD_DEPLOYED_URL'],
        'SAP_COMPUTER_USE_TOKEN':Path(os.environ['SAP_DEPLOY_WORK']+'/token').read_text(),
        'SAP_DEPLOY_CHECK_USER':os.environ['SAP_DEPLOY_CHECK_USER']}
update_env(directory/'cloud.env',values)
update_env(root/'.env',values)
print('Cloud SAP worker: '+os.environ['SAP_CLOUD_DEPLOYED_URL'])
print('Saved private configuration to .sap_cloud/cloud.env and root .env. No Agent Engine or TSE deployment performed.')
PY
