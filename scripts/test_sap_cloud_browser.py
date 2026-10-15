"""Cloud contracts and real headless Chromium. No SAP/Gemini/cloud traffic."""
import asyncio
import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import os
import tempfile
import subprocess
from unittest.mock import AsyncMock,Mock,patch

from cryptography.fernet import Fernet,InvalidToken
from google.api_core.exceptions import NotFound
from google.genai import types
import httpx

from domains.sap.cloud_browser import CloudSapBrowserWorker
from domains.sap.cloud_state import CloudStateStore
from services.sap_computer_use.server import create_app
from smart_agents.sap_recovery import sap_recovery_text
from smart_agents.sap_tools import sap_query_purchase_order,sap_instruction,_request
from scripts.check_sap_deployment import validate_sap_online
from smart_agents import sap_transport

URL='https://your-tenant.s4hana.cloud.sap/ui#PurchaseOrder-manage'
A='tse:one@example.com';B='tse:two@example.com';TOKEN='t'*40

class MemoryState:
    def __init__(self):self.states={}
    def load(self,user):
        data=self.states.get(user)
        return copy.deepcopy(data) if data else (None,0)
    def save(self,user,state,generation):
        assert generation == self.states.get(user,({},0))[1]
        self.states[user]=(copy.deepcopy(state),generation+1)
        return generation+1

class Blob:
    def __init__(self,name):self.name=name;self.data=None;self.generation=0
    def reload(self,**kwargs):
        if self.data is None:raise NotFound('absent')
    def download_as_bytes(self,if_generation_match,**kwargs):
        assert if_generation_match==self.generation
        return self.data
    def upload_from_string(self,data,content_type,if_generation_match,**kwargs):
        assert if_generation_match==self.generation
        self.data=data;self.generation+=1

class Bucket:
    def __init__(self):self.blobs={}
    def blob(self,name):return self.blobs.setdefault(name,Blob(name))

class StateTests(unittest.TestCase):
    def test_per_user_encryption_restore_and_optimistic_generation(self):
        bucket=Bucket();key=Fernet.generate_key().decode();store=CloudStateStore(bucket,key)
        state={'cookies':[{'name':'SAP_SESSION','value':'PRIVATE_COOKIE'}],'origins':[]}
        self.assertEqual(store.load(A),(None,0))
        self.assertEqual(store.save(A,state,0),1)
        self.assertEqual(store.load(A),(state,1))
        self.assertEqual(store.load(B),(None,0))
        name=next(iter(bucket.blobs));self.assertNotIn('one@example',name)
        self.assertNotIn(b'PRIVATE_COOKIE',bucket.blobs[name].data)
        with self.assertRaises(AssertionError):store.save(A,state,0)
        with self.assertRaises(InvalidToken):CloudStateStore(bucket,Fernet.generate_key().decode()).load(A)

    def test_bad_login_origins_and_limits_are_rejected(self):
        for target in ('http://evil.example','https://user:pass@example.com','https://example.com/path','https://example.com?token=secret'):
            with self.assertRaises(ValueError):CloudSapBrowserWorker(url=URL,profile_dir=Path('/tmp'),state_store=MemoryState(),login_origins=[target])
        with self.assertRaises(ValueError):CloudSapBrowserWorker(url=URL,profile_dir=Path('/tmp'),state_store=MemoryState(),max_sessions=1000)

    def test_two_auth_headers_cached_and_no_cli_fallback_in_runtime(self):
        sap_transport._cache.clear()
        with patch('google.oauth2.id_token.fetch_id_token',return_value='fake-identity') as identity:
            for _ in range(2):
                headers=sap_transport.worker_headers('https://test.run.app',TOKEN,iam=True)
                self.assertEqual(headers['Authorization'],'Bearer '+TOKEN)
                self.assertEqual(headers['X-Serverless-Authorization'],'Bearer fake-identity')
        identity.assert_called_once()
        sap_transport._cache.clear()
        with patch('google.oauth2.id_token.fetch_id_token',side_effect=RuntimeError('secret')),patch.object(sap_transport.subprocess,'run') as command:
            with self.assertRaisesRegex(ValueError,'caller identity unavailable'):
                sap_transport.worker_headers('https://test.run.app',TOKEN,iam=True)
        command.assert_not_called()

    def test_deploy_script_private_service_preserves_key_and_syncs_only_sap(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory);(work/'scripts').mkdir();(work/'bin').mkdir()
            (work/'scripts/deploy_sap_browser_cloudrun.sh').write_bytes((root/'scripts/deploy_sap_browser_cloudrun.sh').read_bytes())
            for name in ('sap_local_bridge.py','check_sap_deployment.py'):
                (work/'scripts'/name).symlink_to(root/'scripts'/name)
            for name in ('domains','smart_agents','.venvAgents'):(work/name).symlink_to(root/name)
            env={'GCP_PROJECT_ID':'fake-project','SAP_CLOUD_SERVICE_ACCOUNT':'worker@fake-project.iam.gserviceaccount.com',
                'SAP_AUTH_STATE_BUCKET':'fake-private-auth','SAP_CLOUD_INVOKER_ACCOUNTS':'123-compute@developer.gserviceaccount.com,agent@fake-project.iam.gserviceaccount.com',
                'SAP_BROWSER_URL':URL,'SAP_DEPLOY_CHECK_USER':A,'SAP_COMPUTER_USE_TOKEN':TOKEN}
            (work/'.env').write_text('\n'.join(k+'='+v for k,v in env.items())+'\nUNRELATED_FEATURE=keep\n')
            fake=work/'bin/gcloud';fake.write_text('''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['FAKE_GCLOUD_LOG'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1:4]==['run','services','describe']:print('https://fake-sap.run.app')
''');fake.chmod(0o700)
            log=work/'calls.jsonl'
            result=subprocess.run(['bash','scripts/deploy_sap_browser_cloudrun.sh'],cwd=work,env={**os.environ,**env,
                'PATH':str(work/'bin')+os.pathsep+os.environ['PATH'],'FAKE_GCLOUD_LOG':str(log)},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertNotIn(TOKEN,result.stdout+result.stderr)
            calls=[json.loads(line) for line in log.read_text().splitlines()]
            deploy=next(c for c in calls if c[:2]==['run','deploy'])
            self.assertIn('--no-allow-unauthenticated',deploy);self.assertIn('--max-instances=1',deploy)
            self.assertIn('--min=0',deploy);self.assertIn('--min-instances=default',deploy)
            self.assertIn('--no-cpu-throttling',deploy)
            self.assertFalse(any(c[:3]==['secrets','versions','add'] and c[3]=='sap-browser-state-key' for c in calls))
            self.assertIn('UNRELATED_FEATURE=keep',(work/'.env').read_text())
            self.assertIn("SAP_BROWSER_EXECUTION_MODE='cloud'",(work/'.env').read_text())
            self.assertEqual((work/'.sap_cloud/cloud.env').stat().st_mode & 0o777,0o600)

class ContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_unapproved_sso_origin_is_reported_without_entering_credentials(self):
        worker=CloudSapBrowserWorker(url=URL,profile_dir=Path('/tmp'),state_store=MemoryState())
        page=SimpleNamespace(url='https://tenant.accounts.cloud.sap/login',is_closed=lambda:False,
            keyboard=SimpleNamespace(type=AsyncMock()),screenshot=AsyncMock())
        worker.sessions[A]=SimpleNamespace(page=page,lock=asyncio.Lock())
        worker.revisions[A]=1
        worker._logged_in=AsyncMock(return_value=False)
        worker._ready=AsyncMock(return_value={'ok':True,'logged_in':False})
        result=await worker.login_action(A,{'kind':'text','text':'private-value'},1)
        self.assertEqual(result['error']['code'],'LOGIN_ORIGIN_BLOCKED')
        self.assertEqual(result['current_origin'],'https://tenant.accounts.cloud.sap')
        self.assertNotIn('private-value',str(result))
        page.keyboard.type.assert_not_awaited()
        result=await worker.login_snapshot(A)
        self.assertEqual(result['current_origin'],'https://tenant.accounts.cloud.sap')
        page.screenshot.assert_not_awaited()

    async def test_private_app_auth_cloud_identity_and_no_legacy_snapshot(self):
        worker=SimpleNamespace(execution_location='cloud_browser',shutdown=AsyncMock(),status=AsyncMock(return_value={'ok':True}),
            prepare=AsyncMock(return_value={'ok':True,'wait_user':True,'logged_in':False,'browser_login_required':True,'user_prompt':'云端登录'}),
            login_snapshot=AsyncMock(return_value={'ok':True,'revision':1,'image_base64':'YWJj'}),login_action=AsyncMock(return_value={'ok':True}))
        app=create_app(worker,TOKEN)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            r=await client.post('/prepare',json={'user_id':A});self.assertEqual(r.status_code,401)
            headers={'Authorization':'Bearer '+TOKEN}
            r=await client.post('/prepare',headers=headers,json={'user_id':'adk:other'});self.assertEqual(r.status_code,403)
            r=await client.post('/prepare',headers=headers,json={'user_id':A})
            self.assertEqual(r.json()['execution_location'],'cloud_browser');self.assertTrue(r.json()['browser_login_required'])
            r=await client.post('/snapshot',headers=headers,json={'user_id':A});self.assertEqual(r.status_code,403)
            r=await client.post('/login/action',headers=headers,json={'user_id':B,'revision':1,'action':{'kind':'text','text':'private'}})
            self.assertEqual(r.status_code,200)
            worker.login_action.assert_awaited_once_with(B,{'kind':'text','text':'private'},1)
            self.assertEqual(r.headers['cache-control'],'no-store')

    async def test_cloud_query_pauses_with_remote_link_and_preserves_location(self):
        login={'ok':False,'execution_location':'cloud_browser','error':{'code':'LOGIN_REQUIRED'}}
        prepared={'ok':True,'logged_in':False,'wait_user':True,'execution_location':'cloud_browser',
                  'browser_login_required':True,'user_prompt':'[云端登录](/api/system/smart_agents/sap/browser)'}
        with patch('smart_agents.sap_tools._request',AsyncMock(side_effect=[login,prepared])):
            result=await sap_query_purchase_order('4500071250',SimpleNamespace())
        self.assertEqual(result['execution_location'],'cloud_browser');self.assertTrue(result['wait_user'])
        self.assertIn('/sap/browser',result['user_prompt']);self.assertFalse(result['ok'])

    async def test_cloud_recovery_and_instruction_never_request_local_tunnel(self):
        with patch.dict('os.environ',{'SAP_BROWSER_EXECUTION_MODE':'cloud'}):
            for code in ('SAP_UNAVAILABLE','SAP_AUTH_FAILED','BROWSER_START_FAILED','LOGIN_REQUIRED'):
                text=sap_recovery_text({'ok':False,'error':{'code':code}})
                self.assertNotIn('scripts.sap_bridge_service',text)
                self.assertNotIn('bash scripts/deploy_smart_agents.sh',text)
            self.assertIn('独立会话',sap_instruction())

    async def test_cloud_deployment_gate_does_not_read_local_binding_or_start_service(self):
        env={'SAP_COMPUTER_USE_ENABLED':'true','SAP_BROWSER_EXECUTION_MODE':'cloud',
             'SAP_COMPUTER_USE_WORKER_URL':'https://sap.example.com','SAP_COMPUTER_USE_TOKEN':TOKEN,
             'SAP_DEPLOY_CHECK_USER':A,'SAP_COMPUTER_USE_IAM_AUTH':'false'}
        response=httpx.Response(200,json={'ok':True,'execution_location':'cloud_browser','logged_in':False},request=httpx.Request('POST','https://sap.example.com/status'))
        client=AsyncMock();client.__aenter__.return_value=client;client.post.return_value=response
        with patch('scripts.check_sap_deployment.dotenv_values') as local,patch('httpx.AsyncClient',return_value=client):
            result=await validate_sap_online(env)
        local.assert_not_called();self.assertFalse(result['logged_in'])

class RealHeadlessTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_users_manual_login_restore_and_three_computer_use_actions(self):
        from playwright.async_api import async_playwright
        from domains.sap.golden_path import run_golden_path
        login='''<html><body><input id="who"><button id="signin" onclick="document.cookie='SAPSESSION='+document.getElementById('who').value+';path=/;Secure';window.open('/ui')">Login</button></body></html>'''
        app='''<html><body><div id="shell-header">My Home</div><label for="po">Purchase Order</label><input id="po"><button id="go" onclick="document.getElementById('result').textContent=document.getElementById('po').value">Go</button><div id="result"></div></body></html>'''
        store=MemoryState();worker=CloudSapBrowserWorker(url=URL,profile_dir=Path('/tmp'),state_store=store,max_sessions=2)
        async with async_playwright() as pw:
            real=await pw.chromium.launch(headless=True)
            original=real.new_context
            async def context(**kwargs):
                c=await original(**kwargs)
                async def fixture(route):
                    headers=await route.request.all_headers()
                    await route.fulfill(body=app if 'SAPSESSION=' in headers.get('cookie','') else login,content_type='text/html')
                await c.route('https://your-tenant.s4hana.cloud.sap/**',fixture)
                return c
            worker._playwright=pw;worker._browser=real
            with patch.object(real,'new_context',side_effect=context):
                self.assertTrue((await worker.prepare(A))['wait_user']);self.assertTrue((await worker.prepare(B))['wait_user'])
                self.assertIsNot(worker.sessions[A].context,worker.sessions[B].context)
                snap=await worker.login_snapshot(A);self.assertTrue(base64.b64decode(snap['image_base64']).startswith(b'\x89PNG'))
                async def click(selector):
                    frame=await worker.login_snapshot(A)
                    box=await worker.sessions[A].page.locator(selector).bounding_box()
                    return await worker.login_action(A,{'kind':'click','x':box['x']+box['width']/2,'y':box['y']+box['height']/2},frame['revision'])
                await click('#who');frame=await worker.login_snapshot(A)
                blocked=await worker.login_action(A,{'kind':'text','text':'wrong'},frame['revision']-1)
                self.assertEqual(blocked['error']['code'],'STALE_SCREENSHOT')
                await worker.login_action(A,{'kind':'text','text':'alice'},frame['revision'])
                await click('#signin')
                self.assertTrue((await worker.status(A))['logged_in']);self.assertFalse((await worker.status(B))['logged_in'])
                frame=await worker.login_snapshot(A);self.assertNotIn('image_base64',frame)
                guard=await worker.login_action(A,{'kind':'text','text':'must-not-type'},100)
                self.assertTrue(guard['logged_in'])
                await worker.close(A);self.assertTrue((await worker.prepare(A))['logged_in'])
                self.assertNotIn(B,store.states)
                page=worker.sessions[A].page
                calls=[]
                async def generate(**kwargs):
                    calls.append(kwargs)
                    stage=len(calls)
                    box=await page.locator('#go' if stage==3 else '#po').bounding_box()
                    args={'x':(box['x']+box['width']/2)*1000/1440,'y':(box['y']+box['height']/2)*1000/900}
                    if stage==2:args['text']='4500071250'
                    content=types.Content(role='model',parts=[types.Part(function_call=types.FunctionCall(
                        name='type_text_at' if stage==2 else 'click_at',args=args,id=str(stage)))])
                    return SimpleNamespace(candidates=[SimpleNamespace(content=content)])
                fake=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
                worker.client=fake
                cloud_app=create_app(worker,TOKEN)
                with patch.dict(os.environ,{'SAP_COMPUTER_USE_GOLDEN_PATH':'true','SAP_COMPUTER_USE_DEMO_MODE':'computer-use'}):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=cloud_app),base_url='http://test') as client:
                        response=await client.post('/query',headers={'Authorization':'Bearer '+TOKEN},json={'user_id':A,'purchase_order':'4500071250'})
                self.assertEqual(response.status_code,200)
                result=response.json()
                self.assertTrue(result['ok']);self.assertEqual(result['mode'],'computer-use');self.assertEqual(len(calls),3)
                self.assertTrue(base64.b64decode(result['screenshot_base64']).startswith(b'\x89PNG'))
                self.assertEqual(result['execution_location'],'cloud_browser')
                self.assertTrue(calls[0]['contents'][0].parts[1].inline_data.data.startswith(b'\x89PNG'))
            await real.close()

if __name__=='__main__':unittest.main()
