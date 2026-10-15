"""Form scope, non-submission, native keyboard and two-image delivery."""
import asyncio
import base64
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from google.genai import types

from domains.sap.form_demo import (FORM_URL, NOTES, TEXT, approved_form_url,
    execute_form_action, fields_verified, permitted_control)
from services.sap_computer_use.server import create_app
from smart_agents.browser_demo_tools import browser_demo_fill_form

VERIFIED = {'text': TEXT, 'notes': NOTES, 'dropdown': '2', 'dropdown_label': 'Two',
            'checked_checkbox': False, 'default_checkbox': True, 'checked_radio': False,
            'default_radio': True, 'protected_untouched': True}


class FormPolicyTests(unittest.TestCase):
    def test_only_exact_form_pages_and_all_field_evidence_count(self):
        self.assertTrue(approved_form_url(FORM_URL))
        for url in ('https://www.selenium.dev.evil.test/selenium/web/web-form.html',
                    FORM_URL + '?redirect=https://evil.test', 'http://www.selenium.dev/selenium/web/web-form.html',
                    'https://www.selenium.dev/selenium/web/other.html'):
            self.assertFalse(approved_form_url(url))
        self.assertTrue(fields_verified(VERIFIED))
        for key in VERIFIED:
            changed = dict(VERIFIED); changed[key] = None
            self.assertFalse(fields_verified(changed), key)

    def test_submit_button_and_result_page_are_outside_scope(self):
        self.assertFalse(approved_form_url('https://www.selenium.dev/selenium/web/submitted-form.html'))
        self.assertFalse(permitted_control({'tag': 'BUTTON', 'type': 'submit', 'text': 'Submit'}))

    def test_password_file_and_unrelated_controls_are_never_permitted(self):
        for name, kind in (('my-password', 'password'), ('my-file', 'file'), ('my-date', 'text')):
            self.assertFalse(permitted_control({'name': name, 'type': kind, 'tag': 'INPUT'}))


class FormExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_chromium_native_dropdown_keeps_keyboard_selection(self):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={'width': 1440, 'height': 900})
                await page.set_content('<form><input name="my-text"><select name="my-select">'
                    '<option>Open this select menu</option><option value="1">One</option>'
                    '<option value="2">Two</option><option value="3">Three</option></select></form>')
                box = await page.locator('select').bounding_box()
                await execute_form_action(page, NS(name='click', args={
                    'x': (box['x'] + box['width'] / 2) * 1000 / 1440,
                    'y': (box['y'] + box['height'] / 2) * 1000 / 900}))
                await execute_form_action(page, NS(name='press_key', args={'key': 'Escape'}))
                await execute_form_action(page, NS(name='press_key', args={'key': 't'}))
                self.assertEqual(await page.locator('select').input_value(), '2')
                box = await page.locator('input').bounding_box()
                await execute_form_action(page, NS(name='click', args={
                    'x': (box['x'] + box['width'] / 2) * 1000 / 1440,
                    'y': (box['y'] + box['height'] / 2) * 1000 / 900}))
                self.assertEqual(await page.locator('select').input_value(), '2')
            finally:
                await browser.close()

    async def test_native_select_keys_and_password_typing_boundaries(self):
        page = NS(keyboard=NS(press=AsyncMock(), type=AsyncMock()))
        with patch('domains.sap.form_demo.control_at', AsyncMock(return_value={'name': 'my-select', 'tag': 'SELECT'})):
            await execute_form_action(page, NS(name='press_key', args={'key': 'ArrowDown'}))
            page.keyboard.press.assert_awaited_once_with('ArrowDown')
            await execute_form_action(page, NS(name='press_key', args={'key': 't'}))
            self.assertEqual(page.keyboard.press.await_args.args, ('t',))
            with self.assertRaises(PermissionError):
                await execute_form_action(page, NS(name='press_key', args={'key': 'Enter'}))
        with patch('domains.sap.form_demo.control_at', AsyncMock(return_value={'name': 'my-password', 'tag': 'INPUT'})):
            with self.assertRaises(PermissionError):
                await execute_form_action(page, NS(name='type', args={'text': TEXT}))
        page.keyboard.type.assert_not_awaited()

    async def test_submit_and_model_confirmation_requests_are_not_executed(self):
        page = NS(mouse=NS(click=AsyncMock()))
        control = {'tag': 'BUTTON', 'type': 'submit', 'text': 'Submit'}
        call = NS(name='click', args={'x': 400, 'y': 400})
        with patch('domains.sap.form_demo.control_at', AsyncMock(return_value=control)), \
             patch('domains.sap.form_demo.form_state', AsyncMock(return_value={})):
            with self.assertRaises(PermissionError):
                await execute_form_action(page, call)
        page.mouse.click.assert_not_awaited()
        with patch('domains.sap.form_demo.control_at', AsyncMock(return_value=control)), \
             patch('domains.sap.form_demo.form_state', AsyncMock(return_value=VERIFIED)):
            with self.assertRaises(PermissionError):
                await execute_form_action(page, call)
        page.mouse.click.assert_not_awaited()
        call.args['safety_decision'] = {'decision': 'require_confirmation'}
        with self.assertRaisesRegex(PermissionError, 'CONFIRMATION_REQUIRED'):
            await execute_form_action(page, call)

    async def test_form_and_store_share_private_concurrency_limit(self):
        worker = NS(execution_location='cloud_browser', shutdown=AsyncMock(), client=object(), model='test')
        app = create_app(worker, 't' * 40)
        started, finish = asyncio.Event(), asyncio.Event()
        async def run(**kwargs):
            started.set(); await finish.wait(); return {'ok': True}
        with patch('domains.sap.form_demo.run_form_demo', run):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                self.assertEqual((await client.post('/demo/form-controls', json={'user_id': 'tse:a@example.com'})).status_code, 401)
                headers = {'Authorization': 'Bearer ' + 't' * 40}
                self.assertEqual((await client.post('/demo/form-controls', headers=headers, json={'user_id': 'adk:a'})).status_code, 403)
                task = asyncio.create_task(client.post('/demo/form-controls', headers=headers, json={'user_id': 'tse:a@example.com'}))
                await asyncio.wait_for(started.wait(), 3)
                busy = await client.post('/demo/demoblaze', headers=headers, json={'user_id': 'tse:b@example.com'})
                self.assertEqual(busy.json()['error']['code'], 'WEB_DEMO_BUSY')
                finish.set(); result = await task
                self.assertTrue(result.json()['ok']); self.assertEqual(result.headers['cache-control'], 'no-store')

    async def test_two_images_and_verified_fields_reach_adk_without_summary_model(self):
        from google.adk.agents import Agent
        from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
        from google.adk.runners import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from scripts.test_sap_response import ToolModel
        from smart_agents.sap_response import sap_result_before_model_callback
        from smart_agents.artifact_callbacks import deliver_session_artifacts_callback
        model = ToolModel(model='offline', tool_name='browser_demo_fill_form')
        agent = Agent(name='form_check', model=model, tools=[browser_demo_fill_form],
                      before_model_callback=sap_result_before_model_callback,
                      after_agent_callback=deliver_session_artifacts_callback)
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name='form_check', user_id='one')
        runner = Runner(agent=agent, app_name='form_check', session_service=sessions,
                        artifact_service=InMemoryArtifactService())
        result = {'ok': True, 'fields': VERIFIED, 'submitted': False, 'seconds': 50,
                  'screenshots': [{'filename': name, 'base64': base64.b64encode(b'png-test').decode()}
                                  for name in ('form-before.png', 'form-filled.png')]}
        with patch('smart_agents.browser_demo_tools._request', AsyncMock(return_value=result)):
            events = [event async for event in runner.run_async(user_id='one', session_id=session.id,
                new_message=types.Content(role='user', parts=[types.Part(text='演示表单控件')]))]
        text = '\n'.join(p.text for e in events if e.content and e.content.role == 'model'
                         for p in e.content.parts or [] if p.text)
        self.assertEqual(model._calls, 1)
        self.assertNotIn('screenshots', result)
        self.assertEqual(text.count('data:image/png;base64,'), 2)
        self.assertIn('Two', text); self.assertIn('未提交', text)


if __name__ == '__main__':
    unittest.main()
