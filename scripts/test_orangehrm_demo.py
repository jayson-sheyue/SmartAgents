"""Login boundaries, private state isolation, verified results and image delivery."""
import asyncio
import base64
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from cryptography.fernet import Fernet
from google.genai import types

from domains.sap.cloud_state import CloudStateStore
from domains.sap.orangehrm_demo import (ROOT, LOGIN, EMPLOYEES, approved_url, approved_request,
    choose_employee, execute_action, permitted_control, restricted_state, verified_result)
from services.sap_computer_use.server import create_app
from smart_agents.browser_demo_tools import browser_demo_orangehrm_employee, format_orangehrm_demo_result

ROW = dict(employee_id='00392',first_name='Charlotte',last_name='Smith',job_title='',employment_status='',sub_unit='')


class PolicyTests(unittest.TestCase):
    def test_exact_origin_read_only_routes_and_public_login_only(self):
        self.assertTrue(approved_url(LOGIN)); self.assertTrue(approved_url(EMPLOYEES))
        for url in (ROOT+'/web/index.php/pim/addEmployee', LOGIN+'?redirect=https://evil.test',
                    LOGIN.replace('https:', 'http:'), LOGIN.replace('orangehrmlive.com', 'orangehrmlive.com.evil.test')):
            self.assertFalse(approved_url(url))
        self.assertTrue(approved_request(ROOT+'/web/index.php/auth/validate','POST','document'))
        self.assertTrue(approved_request(ROOT+'/web/index.php/api/v2/pim/employees?limit=50','GET','xhr'))
        for method in ('POST','PATCH','PUT','DELETE'):
            self.assertFalse(approved_request(ROOT+'/web/index.php/api/v2/pim/employees',method,'xhr'))
        self.assertFalse(approved_request(ROOT+'/web/index.php/auth/requestResetPassword','POST','document'))
        self.assertFalse(approved_request('https://evil.test/','GET','image'))

    def test_only_real_records_and_completed_filtered_search_count(self):
        self.assertEqual(choose_employee([dict(ROW,employee_id='malicious'),ROW]),ROW)
        with self.assertRaises(ValueError): choose_employee([])
        state={'filter':ROW['employee_id'],'rows':[ROW],'loading':False}
        self.assertTrue(verified_result(state,ROW['employee_id'],True))
        self.assertFalse(verified_result(state,ROW['employee_id'],False))
        for changes in ({'rows':[]},{'loading':True},{'filter':'wrong'}, {'rows':[dict(ROW,employee_id='wrong')]}):
            self.assertFalse(verified_result(dict(state,**changes),ROW['employee_id'],True))

    def test_unrelated_and_mutating_controls_blocked(self):
        for text in ('Add','Delete','Save','Login','Reset Password'):
            self.assertFalse(permitted_control({'tag':'BUTTON','text':text},False))
        self.assertFalse(permitted_control({'tag':'INPUT','label':'Employee Name'},False))
        self.assertTrue(permitted_control({'tag':'INPUT','label':'Employee Id'},False))
        self.assertTrue(permitted_control({'tag':'INPUT','name':'password'},True))
        self.assertFalse(permitted_control({'tag':'A','text':'PIM','href':'https://evil.test'},False))

    def test_state_namespace_user_isolation_and_origin_filter(self):
        from scripts.test_sap_cloud_browser import Bucket
        bucket=Bucket();key=Fernet.generate_key().decode()
        sap=CloudStateStore(bucket,key); hr=CloudStateStore(bucket,key,prefix='orangehrm-auth')
        cookie={'domain':'opensource-demo.orangehrmlive.com','secure':True,'name':'session','value':'private'}
        state=restricted_state({'cookies':[cookie,dict(cookie,domain='evil.test')],
                               'origins':[{'origin':ROOT,'localStorage':[]},{'origin':'https://evil.test'}]})
        self.assertEqual(len(state['cookies']),1);self.assertEqual(len(state['origins']),1)
        hr.save('tse:one@example.com',state,0)
        self.assertEqual(sap.load('tse:one@example.com'),(None,0))
        self.assertEqual(hr.load('tse:two@example.com'),(None,0))
        self.assertEqual(hr.load('tse:one@example.com')[0],state)
        self.assertNotIn(b'private',next(iter(bucket.blobs.values())).data)
        with self.assertRaises(ValueError): CloudStateStore(bucket,key,prefix='../bad')


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_personal_password_and_model_confirmation_never_executed(self):
        page=NS(url=LOGIN,keyboard=NS(press=AsyncMock(),type=AsyncMock()))
        with patch('domains.sap.orangehrm_demo.control_at',AsyncMock(return_value={'tag':'INPUT','name':'password'})):
            with self.assertRaises(PermissionError):
                await execute_action(page,NS(name='type',args={'text':'personal-secret'}),None)
        with self.assertRaisesRegex(PermissionError,'CONFIRMATION_REQUIRED'):
            await execute_action(page,NS(name='click',args={'x':10,'y':10,'safety_decision':{'decision':'require_confirmation'}}),None)
        page.keyboard.type.assert_not_awaited()

    async def test_private_endpoint_forwards_bound_user_and_shares_concurrency(self):
        worker=NS(execution_location='cloud_browser',shutdown=AsyncMock(),client=object(),model='test')
        store=object();app=create_app(worker,'t'*40,orangehrm_store=store)
        start,finish=asyncio.Event(),asyncio.Event()
        async def run(user,**kw):
            self.assertEqual(user,'tse:one@example.com')
            start.set();await finish.wait();return {'ok':True}
        with patch('domains.sap.orangehrm_sessions.OrangeHRMSessions.query',side_effect=run):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
                data={'user_id':'tse:one@example.com'};h={'Authorization':'Bearer '+'t'*40}
                self.assertEqual((await c.post('/demo/orangehrm',json=data)).status_code,401)
                self.assertEqual((await c.post('/demo/orangehrm',headers=h,json={'user_id':'adk:any'})).status_code,403)
                task=asyncio.create_task(c.post('/demo/orangehrm',headers=h,json=data))
                await asyncio.wait_for(start.wait(),2)
                busy=await c.post('/demo/form-controls',headers=h,json=data)
                self.assertEqual(busy.json()['error']['code'],'WEB_DEMO_BUSY')
                finish.set();self.assertTrue((await task).json()['ok'])

    async def test_adk_delivers_two_images_and_reuse_evidence_without_summary_call(self):
        from google.adk.agents import Agent
        from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
        from google.adk.runners import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from scripts.test_sap_response import ToolModel
        from smart_agents.sap_response import sap_result_before_model_callback
        model=ToolModel(model='offline',tool_name='browser_demo_orangehrm_employee')
        agent=Agent(name='hr_check',model=model,tools=[browser_demo_orangehrm_employee],
                    before_model_callback=sap_result_before_model_callback)
        sessions=InMemorySessionService();session=await sessions.create_session(app_name='hr_check',user_id='one')
        runner=Runner(agent=agent,app_name='hr_check',session_service=sessions,artifact_service=InMemoryArtifactService())
        result={'ok':True,'session_reused':True,'employee_id':ROW['employee_id'],'employees':[ROW],'seconds':20,
                'screenshots':[{'filename':f,'base64':base64.b64encode(b'png-test').decode()}
                               for f in ('orangehrm-before.png','orangehrm-result.png')]}
        with patch('smart_agents.browser_demo_tools._request',AsyncMock(return_value=result)):
            events=[e async for e in runner.run_async(user_id='one',session_id=session.id,
                new_message=types.Content(role='user',parts=[types.Part(text='OrangeHRM 演示')]))]
        text='\n'.join(p.text for e in events if e.content and e.content.role=='model' for p in e.content.parts or [] if p.text)
        self.assertEqual(model._calls,1);self.assertEqual(text.count('data:image/png;base64,'),2)
        self.assertIn('你亲自登录',text);self.assertIn('Charlotte Smith',text);self.assertNotIn('screenshots',result)
        self.assertNotIn('已复用',format_orangehrm_demo_result({'ok':False,'error':{'message':'Failed'}},str))


if __name__=='__main__':unittest.main()
