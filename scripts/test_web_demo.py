"""Scope, result grounding and chat-image contracts for the guest web demo."""
import asyncio
import base64
from decimal import Decimal
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from domains.sap.web_demo import PRODUCTS, approved_url, execute, money, verified_cart
from services.sap_computer_use.server import create_app
from smart_agents.browser_demo_tools import browser_demo_compare_laptops, format_browser_demo_result


class PolicyTests(unittest.TestCase):
    def test_navigation_scope_and_price_evidence(self):
        for url in ('https://www.demoblaze.com/', 'https://www.demoblaze.com/prod.html?idp_=8',
                    'https://www.demoblaze.com/cart.html'):
            self.assertIs(approved_url(url), True)
        for url in ('http://www.demoblaze.com/', 'https://www.demoblaze.com.evil.test/',
                    'https://name:pass@www.demoblaze.com/', 'https://www.demoblaze.com:443/',
                    'https://www.demoblaze.com/order', 'https://www.demoblaze.com/?redirect=https://evil.test'):
            self.assertFalse(approved_url(url))
        self.assertEqual(money('$790 *includes tax'), Decimal('790'))
        self.assertEqual(money('700'), Decimal('700'))
        with self.assertRaises(ValueError):
            money('Unavailable')


class DemoTests(unittest.IsolatedAsyncioTestCase):
    async def test_checkout_early_and_duplicate_cart_additions_are_blocked(self):
        page = NS(evaluate=AsyncMock(), mouse=NS(click=AsyncMock()))
        call = NS(name='click', args={'x': 400, 'y': 400})
        for label, observed, added in (('Place Order', PRODUCTS, True), ('Log in', PRODUCTS, False),
                                       ('Add to cart', (), False), ('Add to cart', PRODUCTS, True)):
            page.evaluate.return_value = {'label': label, 'href': '#', 'product': '', 'input': False}
            with self.assertRaises(PermissionError):
                await execute(page, call, observed_products=observed, added=added)
        page.mouse.click.assert_not_awaited()
        page.evaluate.return_value = {'label': 'Add to cart', 'href': '#', 'product': '', 'input': False}
        self.assertTrue(await execute(page, call, observed_products=PRODUCTS))
        page.mouse.click.assert_awaited_once()
        call.args['safety_decision'] = {'decision': 'require_confirmation'}
        with self.assertRaisesRegex(PermissionError, 'CONFIRMATION_REQUIRED'):
            await execute(page, call, observed_products=PRODUCTS)

    async def test_cart_requires_cheapest_observed_item_one_row_and_matching_total(self):
        products = {PRODUCTS[0]: {'price': '790'}, PRODUCTS[1]: {'price': '700'}}
        cells = NS(all_text_contents=AsyncMock(return_value=['', PRODUCTS[1], '700', 'Delete']))
        row = NS(locator=Mock(return_value=cells))
        rows = NS(all=AsyncMock(return_value=[row]))
        total = NS(inner_text=AsyncMock(return_value='700'))
        page = NS(url='https://www.demoblaze.com/cart.html',
                  locator=Mock(side_effect=lambda selector: rows if selector == '#tbodyid tr' else total))
        self.assertEqual((await verified_cart(page, products))['name'], PRODUCTS[1])
        total.inner_text.return_value = '1400'
        self.assertIsNone(await verified_cart(page, products))
        total.inner_text.return_value = '790'; cells.all_text_contents.return_value = ['', PRODUCTS[0], '790']
        self.assertIsNone(await verified_cart(page, products))
        rows.all.return_value = [row, row]
        self.assertIsNone(await verified_cart(page, products))

    async def test_private_endpoint_reuses_auth_and_isolates_browser_work(self):
        worker = NS(execution_location='cloud_browser', shutdown=AsyncMock(), client=object(), model='test-model')
        app = create_app(worker, 't' * 40)
        with patch('domains.sap.web_demo.run_demoblaze_demo', AsyncMock(return_value={'ok': True})) as run:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                self.assertEqual((await client.post('/demo/demoblaze', json={'user_id': 'tse:a@example.com'})).status_code, 401)
                headers = {'Authorization': 'Bearer ' + 't' * 40}
                self.assertEqual((await client.post('/demo/demoblaze', headers=headers, json={'user_id': 'adk:a'})).status_code, 403)
                result = await client.post('/demo/demoblaze', headers=headers, json={'user_id': 'tse:a@example.com'})
                self.assertTrue(result.json()['ok']); self.assertEqual(result.headers['cache-control'], 'no-store')
            run.assert_awaited_once_with(client=worker.client, model=worker.model)

    async def test_image_is_an_artifact_not_a_model_tool_payload(self):
        context = NS(state={}, save_artifact=AsyncMock(return_value=2))
        data = {'ok': True, 'screenshot_base64': base64.b64encode(b'png-test').decode(),
                'products': [{'name': PRODUCTS[1], 'price': '700'}],
                'cart': {'name': PRODUCTS[1], 'quantity': 1, 'total': '700'}, 'seconds': 35}
        with patch('smart_agents.browser_demo_tools._request', AsyncMock(return_value=data)):
            result = await browser_demo_compare_laptops(context)
        self.assertNotIn('screenshot_base64', result)
        self.assertEqual(result['artifacts'][0]['version'], 2)
        text = format_browser_demo_result(result, str)
        self.assertIn('700', text); self.assertNotIn('SAP', text); self.assertIn('未提交订单', text)

    async def test_adk_delivers_one_image_without_post_tool_model_wait(self):
        from google.adk.agents import Agent
        from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
        from google.adk.runners import Runner
        from google.adk.sessions.in_memory_session_service import InMemorySessionService
        from google.genai import types
        from scripts.test_sap_response import ToolModel
        from smart_agents.sap_response import sap_result_before_model_callback
        from smart_agents.artifact_callbacks import deliver_session_artifacts_callback
        model = ToolModel(model='offline', tool_name='browser_demo_compare_laptops')
        agent = Agent(name='browser_check', model=model, tools=[browser_demo_compare_laptops],
                      before_model_callback=sap_result_before_model_callback,
                      after_agent_callback=deliver_session_artifacts_callback)
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name='browser_check', user_id='one')
        runner = Runner(agent=agent, app_name='browser_check', session_service=sessions,
                        artifact_service=InMemoryArtifactService())
        result = {'ok': True, 'products': [], 'cart': {'name': PRODUCTS[1], 'quantity': 1, 'total': '700'},
                  'seconds': 40, 'screenshot_base64': base64.b64encode(b'png-test').decode()}
        with patch('smart_agents.browser_demo_tools._request', AsyncMock(return_value=result)):
            events = [event async for event in runner.run_async(user_id='one', session_id=session.id,
                new_message=types.Content(role='user', parts=[types.Part(text='演示商城比价')]))]
        text = '\n'.join(p.text for e in events if e.content and e.content.role == 'model'
                         for p in e.content.parts or [] if p.text)
        self.assertEqual(model._calls, 1)
        self.assertEqual(text.count('data:image/png;base64,'), 1)
        self.assertIn('700', text)


if __name__ == '__main__':
    unittest.main()
