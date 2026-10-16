"""Real Chromium, deterministic OrangeHRM fixture: human-only input and isolation."""
import asyncio
import copy
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

from domains.sap.orangehrm_demo import LOGIN, EMPLOYEES, ROOT, execute_action, run_employee_query
from domains.sap.orangehrm_sessions import OrangeHRMSessions, ScopedAuthStore, MANUAL, PUBLIC
from smart_agents.browser_demo_tools import format_orangehrm_demo_result

A, B = 'tse:alice@example.com', 'tse:bob@example.com'
LOGIN_HTML = '<form method="POST" action="/web/index.php/auth/validate"><input name="username"><input name="password" type="password"><button>Login</button></form>'


class Store:
    def __init__(self): self.data = {}
    def load(self, key): return copy.deepcopy(self.data.get(key, (None, 0)))
    def save(self, key, data, generation):
        assert self.load(key)[1] == generation
        self.data[key] = copy.deepcopy(data), generation + 1
        return generation + 1


class FixtureBrowser:
    def __init__(self, browser): self.browser = browser
    def is_connected(self): return self.browser.is_connected()
    async def close(self): await self.browser.close()
    async def new_context(self, **kwargs):
        context = await self.browser.new_context(**kwargs)
        original_route = context.route
        async def register(pattern, guard):
            async def handler(route):
                async def fixture():
                    path = urlsplit(route.request.url).path
                    if path == '/web/index.php/auth/login':
                        return await route.fulfill(content_type='text/html', body=LOGIN_HTML)
                    if path == '/web/index.php/auth/validate':
                        values = parse_qs(route.request.post_data or '')
                        owner = values.get('username', [''])[0]
                        if owner not in {'alice', 'bob'} or values.get('password') != ['test-private-input']:
                            return await route.fulfill(content_type='text/html',body='<script>location.replace('+repr(LOGIN)+')</script>')
                        return await route.fulfill(content_type='text/html',body='<script>location.replace('+repr(EMPLOYEES)+')</script>',headers={'Set-Cookie': 'fixture_user='+owner+'; Path=/; Secure; HttpOnly; SameSite=Lax'})
                    if path == '/web/index.php/auth/logout':
                        return await route.fulfill(content_type='text/html',body='<script>location.replace('+repr(LOGIN)+')</script>',headers={'Set-Cookie': 'fixture_user=; Max-Age=0; Path=/; Secure'})
                    cookie = await route.request.header_value('cookie') or ''
                    owner = 'alice' if 'fixture_user=alice' in cookie else 'bob' if 'fixture_user=bob' in cookie else None
                    if not owner:
                        return await route.fulfill(content_type='text/html',body='<script>location.replace('+repr(LOGIN)+')</script>')
                    html = '<span class="oxd-userdropdown-name">'+owner+'</span><div class="oxd-table-body"><div class="oxd-table-row">'+owner+'</div></div>'
                    return await route.fulfill(content_type='text/html', body=html)
                # Exercise the real route policy; replace only the approved site's server.
                await guard(NS(request=route.request, continue_=fixture, abort=route.abort))
            await original_route(pattern, handler)
        context.route = register
        return context


class AuthStoreTests(unittest.TestCase):
    def test_legacy_shared_user_and_site_state_cannot_become_manual_state(self):
        store=Store();legacy={'cookies':[], 'origins':[]}
        store.save(A,legacy,0)
        public=ScopedAuthStore(store,PUBLIC);manual=ScopedAuthStore(store)
        public.save(A,legacy,0)
        self.assertEqual(manual.load(A),(None,0))
        manual.save(A,legacy,0)
        self.assertEqual(manual.load(B),(None,0))
        self.assertNotEqual(manual.key(A),public.key(A))
        self.assertIn(ROOT,manual.key(A))
        generation=manual.clear(A,1)
        self.assertEqual(manual.load(A),(None,generation))
        with self.assertRaises(AssertionError):manual.save(A,legacy,1)

    def test_pending_login_never_claims_query_or_screenshot_success(self):
        from smart_agents.sap_response import _cell
        text=format_orangehrm_demo_result({'ok':True,'wait_user':True,'logged_in':False},_cell)
        self.assertIn('/orangehrm/browser',text)
        self.assertIn('尚未执行员工查询',text)
        self.assertNotIn('查询演示已完成',text)
        self.assertNotIn('admin123',text)


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pw=await async_playwright().start()
        self.real=await self.pw.chromium.launch(headless=True)
        self.store=Store();self.worker=OrangeHRMSessions(state_store=self.store)
        self.worker._browser=FixtureBrowser(self.real)

    async def asyncTearDown(self):
        await self.worker.shutdown();await self.pw.stop()

    async def human_login(self, user, account):
        await self.worker.prepare(user)
        page=self.worker.sessions[user].page
        for name,value in [('username',account),('password','test-private-input')]:
            snap=await self.worker.login_snapshot(user)
            box=await page.locator('[name='+name+']').bounding_box()
            await self.worker.login_action(user,{'kind':'click','x':box['x']+3,'y':box['y']+3},snap['revision'])
            snap=await self.worker.login_snapshot(user)
            await self.worker.login_action(user,{'kind':'text','text':value},snap['revision'])
        snap=await self.worker.login_snapshot(user);box=await page.locator('button').bounding_box()
        await self.worker.login_action(user,{'kind':'click','x':box['x']+3,'y':box['y']+3},snap['revision'])
        await page.wait_for_url(EMPLOYEES, timeout=3000)
        self.assertTrue((await self.worker.status(user))['logged_in'])

    async def test_default_requires_human_no_model_or_legacy_cookie(self):
        self.store.save(A,{'cookies':[], 'origins':[]},0)
        client=NS(aio=NS(models=NS(generate_content=AsyncMock())))
        result=await self.worker.query(A,client=client,model='unused')
        self.assertTrue(result['wait_user']);self.assertFalse(result['logged_in'])
        self.assertNotIn('screenshots',result);client.aio.models.generate_content.assert_not_awaited()
        page=self.worker.sessions[A].page
        self.assertEqual(await page.locator('[name=username]').input_value(),'')
        self.assertEqual(await page.locator('[name=password]').input_value(),'')
        with self.assertRaises(PermissionError):
            await execute_action(page,NS(name='type',args={'text':'admin123'}),None)
        await run_employee_query(page=page,client=client)
        client.aio.models.generate_content.assert_not_awaited()

    async def test_two_accounts_restore_logout_and_input_revision_isolation(self):
        await self.human_login(A,'alice');await self.human_login(B,'bob')
        self.assertEqual(await self.worker.sessions[A].page.locator('.oxd-userdropdown-name').inner_text(),'alice')
        self.assertEqual(await self.worker.sessions[B].page.locator('.oxd-userdropdown-name').inner_text(),'bob')
        # Logged-in human views do not expose the business screen for manual mutation.
        snap=await self.worker.login_snapshot(A);self.assertNotIn('image_base64',snap)
        await self.worker.close(A);await self.worker.prepare(A)
        self.assertTrue((await self.worker.status(A))['logged_in'])
        self.assertEqual(await self.worker.sessions[A].page.locator('.oxd-userdropdown-name').inner_text(),'alice')
        await self.worker.logout(A)
        result=await self.worker.prepare(A);self.assertFalse(result['logged_in'])
        self.assertTrue((await self.worker.status(B))['logged_in'])
        snap=await self.worker.login_snapshot(A)
        wrong=await self.worker.login_action(A,{'kind':'text','text':'NEVER-TYPE'},snap['revision']-1)
        self.assertEqual(wrong['error']['code'],'STALE_SCREENSHOT')
        self.assertEqual(await self.worker.sessions[A].page.locator('[name=username]').input_value(),'')

    async def test_pending_tool_finishes_with_login_link_without_artifact_or_extra_model(self):
        from google.adk.agents import Agent
        from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
        from google.adk.runners import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from google.genai import types
        from scripts.test_sap_response import ToolModel
        from domains.sap.orangehrm_sessions import login_required
        from smart_agents.browser_demo_tools import browser_demo_orangehrm_employee
        from smart_agents.sap_response import sap_result_before_model_callback
        model=ToolModel(model='offline',tool_name='browser_demo_orangehrm_employee')
        agent=Agent(name='pending_login',model=model,tools=[browser_demo_orangehrm_employee],
                    before_model_callback=sap_result_before_model_callback)
        sessions=InMemorySessionService();session=await sessions.create_session(app_name='pending_login',user_id='one')
        runner=Runner(agent=agent,app_name='pending_login',session_service=sessions,artifact_service=InMemoryArtifactService())
        response=login_required()
        with patch('smart_agents.browser_demo_tools._request',AsyncMock(return_value=response)):
            events=[e async for e in runner.run_async(user_id='one',session_id=session.id,
                new_message=types.Content(role='user',parts=[types.Part(text='OrangeHRM 查询')]))]
        text=''.join(p.text for e in events if e.content and e.content.role=='model' for p in e.content.parts or [] if p.text)
        self.assertEqual(model._calls,1)
        self.assertIn('/orangehrm/browser',text)
        self.assertNotIn('data:image',text)
        self.assertNotIn('screenshot_delivery_failed',response)
        self.assertNotIn('查询演示已完成',text)

    async def test_switch_while_query_busy_does_not_clear_state(self):
        await self.human_login(A,'alice')
        async with self.worker.sessions[A].lock:
            result=await self.worker.logout(A)
            self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],'ORANGEHRM_BUSY')
        self.assertTrue((await self.worker.status(A))['logged_in'])


if __name__=='__main__':unittest.main()
