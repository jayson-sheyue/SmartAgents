"""Explicit administrator entry point for independently deploying SAP components.

No deployment runs on import. Secrets remain in .env / Secret Manager and are
never passed as command-line values. Existing TSE runtime settings are retained.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.sap_local_bridge import update_env


def run(args, *, capture=False, cwd=ROOT):
    return subprocess.run(args, cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def gcloud(*args, capture=False):
    return run(['gcloud', *args], capture=capture)


def describe(*args):
    return json.loads(gcloud(*args, '--format=json', capture=True))


def configuration(env):
    project = env['GCP_PROJECT_ID']
    region = env.get('SAP_CLOUD_REGION') or env.get('GCP_LOCATION') or 'us-central1'
    service = env.get('SAP_TSE_SERVICE') or 'tse-smart-workspace-jayson'
    tse_region = env.get('SAP_TSE_REGION') or region
    tse = describe('run', 'services', 'describe', service, f'--project={project}', f'--region={tse_region}')
    number = gcloud('projects', 'describe', project, '--format=value(projectNumber)', capture=True).strip()
    # Agent Engine REST also works with gcloud releases without reasoning-engines CLI.
    import requests
    token = gcloud('auth', 'print-access-token', capture=True).strip()
    url = (f'https://{env.get("GCP_LOCATION", region)}-aiplatform.googleapis.com/v1/projects/'
           f'{project}/locations/{env.get("GCP_LOCATION", region)}/reasoningEngines/{env["SMART_AGENTS_ENGINE_ID"]}')
    response = requests.get(url, headers={'Authorization': 'Bearer '+token}, timeout=45)
    response.raise_for_status()
    engine = response.json()
    identity = engine['spec'].get('effectiveIdentity') or engine['spec'].get('serviceAccount')
    if not identity or '@' not in identity:
        raise ValueError('Cannot determine Agent Engine runtime service account')
    runtime = tse['spec']['template']['spec'].get('serviceAccountName') or f'{number}-compute@developer.gserviceaccount.com'
    local = dotenv_values(ROOT/'env/local.env')
    user = env.get('SAP_DEPLOY_CHECK_USER')
    if not user:
        users = [u.strip() for u in (local.get('SAP_WORKER_ALLOWED_USERS') or '').split(',') if u.strip()]
        if len(users) != 1:
            raise ValueError('Set SAP_DEPLOY_CHECK_USER=tse:actual-TSE-email')
        user = users[0]
    values = {
        'SAP_CLOUD_REGION': region, 'SAP_TSE_SERVICE': service, 'SAP_TSE_REGION': tse_region,
        'SAP_CLOUD_SERVICE_ACCOUNT': env.get('SAP_CLOUD_SERVICE_ACCOUNT') or f'sap-browser-worker@{project}.iam.gserviceaccount.com',
        'SAP_AUTH_STATE_BUCKET': env.get('SAP_AUTH_STATE_BUCKET') or f'{project}-private-sap-auth',
        'SAP_CLOUD_INVOKER_ACCOUNTS': ','.join(dict.fromkeys([runtime, identity])),
        'SAP_DEPLOY_CHECK_USER': user,
        'SAP_BROWSER_URL': env.get('SAP_BROWSER_URL') or local.get('SAP_BROWSER_URL') or '',
    }
    if not values['SAP_BROWSER_URL']:
        raise ValueError('Set SAP_BROWSER_URL to the verified SAP application URL')
    update_env(ROOT/'.env', values)
    env.update(values)
    return tse, runtime


def browser(env):
    account = env['SAP_CLOUD_SERVICE_ACCOUNT']
    found = gcloud('iam', 'service-accounts', 'list', f'--project={env["GCP_PROJECT_ID"]}',
                   f'--filter=email:{account}', '--format=value(email)', capture=True).splitlines()
    if account not in found:
        gcloud('iam', 'service-accounts', 'create', account.split('@')[0],
               f'--project={env["GCP_PROJECT_ID"]}', '--display-name=SAP browser worker')
    run(['bash', 'scripts/deploy_sap_browser_cloudrun.sh'])
    env.update({k:v for k,v in dotenv_values(ROOT/'.env').items() if v is not None})


def tse_deploy(env, tse, runtime, path):
    project, region, service = env['GCP_PROJECT_ID'], env['SAP_TSE_REGION'], env['SAP_TSE_SERVICE']
    secret = env.get('SAP_CLOUD_TOKEN_SECRET') or 'sap-browser-token'
    # SmartAgents is the source of truth for this small shared protocol adapter.
    for name in ('sap_transport.py', 'sap_recovery.py'):
        source, target = ROOT/'smart_agents'/name, path/name
        if not target.exists() or source.read_bytes() != target.read_bytes():
            shutil.copyfile(source, target)
    gcloud('secrets', 'add-iam-policy-binding', secret, f'--project={project}',
           f'--member=serviceAccount:{runtime}', '--role=roles/secretmanager.secretAccessor', '--quiet')
    image = f'{region}-docker.pkg.dev/{project}/cloud-run-source-deploy/{service}:sap-{time.strftime("%Y%m%d%H%M%S")}'
    # A clean temporary source context follows .dockerignore, including local venv exclusions.
    with tempfile.TemporaryDirectory() as tmp:
        build = Path(tmp)/'build.json'
        build.write_text(json.dumps({'steps':[{'name':'gcr.io/cloud-builders/docker',
            'args':['build','-t',image,'.']}], 'images':[image], 'timeout':'1800s'}))
        gcloud('builds', 'submit', str(path), f'--project={project}', f'--config={build}',
               f'--ignore-file={path/".dockerignore"}', '--suppress-logs')
    tag = 'sap-cloud'
    gcloud('run', 'services', 'update', service, f'--project={project}', f'--region={region}',
           f'--image={image}', '--no-traffic', f'--tag={tag}',
           '--update-env-vars=SAP_BROWSER_EXECUTION_MODE=cloud,SAP_COMPUTER_USE_IAM_AUTH=true,'
           'SAP_COMPUTER_USE_WORKER_URL='+env['SAP_COMPUTER_USE_WORKER_URL'],
           f'--update-secrets=SAP_COMPUTER_USE_TOKEN={secret}:latest', '--quiet')
    current = describe('run','services','describe',service,f'--project={project}',f'--region={region}')
    revision = current['status']['latestReadyRevisionName']
    tagged = next(t['url'] for t in current['status']['traffic'] if t.get('tag') == tag)
    import requests
    for endpoint in ('/', '/api/system/smart_agents/sap/browser'):
        response = requests.get(tagged+endpoint, allow_redirects=False, timeout=45)
        if response.status_code not in (200,302,303,401):
            raise RuntimeError(f'TSE staged smoke check failed: {endpoint}: {response.status_code}')
    # Promote only a revision that passed HTTP smoke checks; retain all other settings.
    gcloud('run','services','update-traffic',service,f'--project={project}',f'--region={region}',
           f'--to-revisions={revision}=100','--quiet')
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component', choices=['browser','agent','tse','all'], default='all')
    parser.add_argument('--tse-path', type=Path, default=ROOT.parent/'TSEcode/TSE-SMART-WORKSPACE-Final')
    args = parser.parse_args()
    env = {**os.environ, **{k:v for k,v in dotenv_values(ROOT/'.env').items() if v is not None}}
    tse, runtime = configuration(env)
    os.environ.update(env)
    if args.component in ('browser','all'):
        browser(env)
        os.environ.update(env)
    if args.component in ('agent','all'):
        run(['bash', 'scripts/deploy_smart_agents.sh'])
    if args.component in ('tse','all'):
        revision = tse_deploy(env,tse,runtime,args.tse_path.resolve())
        print('TSE revision:',revision)
    print('SAP component deployment completed:',args.component)


if __name__ == '__main__':
    main()
