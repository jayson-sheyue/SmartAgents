"""Offline contract/security/loop tests; never connect to SAP or charge model tokens."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from google.genai import types
from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from pydantic import PrivateAttr

from domains.sap.browser import BrowserSession, SapBrowserWorker
from domains.sap.policy import allow_request, read_only_batch, tenant_url, validate_order
from services.sap_computer_use.server import create_app
from smart_agents.sap_tools import _identity, sap_query_purchase_order, sap_enabled

URL = "https://your-tenant.s4hana.cloud.sap/ui#Shell-home"
ORDER = "4500071250"


def batch(method="GET", nested=False):
    return (f"--b\r\nContent-Type: {'multipart/mixed; boundary=c' if nested else 'application/http'}\r\n"
            f"Content-Transfer-Encoding: binary\r\n\r\n{method} Orders HTTP/1.1\r\n\r\n\r\n--b--\r\n").encode()


class PolicyTests(unittest.TestCase):
    def test_read_batch_and_write_batch(self):
        self.assertTrue(read_only_batch("multipart/mixed; boundary=b", batch()))
        for verb in ("POST", "PATCH", "DELETE", "PUT"):
            self.assertFalse(read_only_batch("multipart/mixed; boundary=b", batch(verb)))
        self.assertFalse(read_only_batch("multipart/mixed; boundary=b", batch(nested=True)))

    def test_malformed_and_empty_batches_fail_closed(self):
        for payload in (b"", b"GET Orders HTTP/1.1", b"--b--\r\n"):
            self.assertFalse(read_only_batch("multipart/mixed; boundary=b", payload))
        self.assertFalse(read_only_batch("application/json", b"{}"))

    def test_network_scope_and_methods(self):
        self.assertTrue(allow_request(URL, "GET", "", b"", URL))
        self.assertFalse(allow_request("https://evil.example", "GET", "", b"", URL))
        self.assertFalse(allow_request(URL, "POST", "", b"", URL))
        self.assertTrue(allow_request(URL.split("/ui")[0] + "/odata/$batch", "POST",
                                     "multipart/mixed; boundary=b", batch(), URL))
        self.assertTrue(allow_request("https://ui5.sap.com/resources/icons.woff", "GET", "", b"", URL, "font"))
        self.assertFalse(allow_request("https://ui5.sap.com/anything", "GET", "", b"", URL, "document"))
        self.assertTrue(allow_request("https://ui5.sap.com/1.140/resources/sap/Component.js", "GET", "", b"", URL, "xhr"))
        self.assertFalse(allow_request("https://ui5.sap.com/api/orders", "GET", "", b"", URL, "xhr"))

    def test_invalid_tenant_and_order(self):
        self.assertEqual(validate_order(ORDER), ORDER)
        for number in ("123", "4500071250;delete", "٤٥٠٠٠٧١٢٥٠"):
            with self.assertRaises(ValueError):
                validate_order(number)
        for url in ("http://my.s4hana.cloud.sap", "https://evil.example", "https://user:pass@my.s4hana.cloud.sap"):
            with self.assertRaises(ValueError):
                tenant_url(url)

    def test_identity_from_trusted_context_not_model_args(self):
        context = SimpleNamespace(user_id="one", state={})
        self.assertEqual(_identity(context), "adk:one")
        context.state = {"tse_user_email": "User@Example.com", "tse_auth_source": "tse_app"}
        self.assertEqual(_identity(context), "tse:user@example.com")
        with self.assertRaises(ValueError):
            _identity(SimpleNamespace(state={}))

    def test_disabled_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(sap_enabled())


class Locator:
    def __init__(self, present=True):
        self.present = present
        self.first = self

    async def count(self):
        return int(self.present)

    async def is_visible(self):
        return self.present

    async def wait_for(self, **kwargs):
        pass


class Page:
    url = URL
    viewport_size = {"width": 1280, "height": 800}

    def __init__(self):
        self.mouse = SimpleNamespace(click=AsyncMock(), move=AsyncMock(), wheel=AsyncMock())
        self.keyboard = SimpleNamespace(press=AsyncMock(), type=AsyncMock())
        self.detail = True
        self.label = "Go"
        self.goto = AsyncMock()

    def is_closed(self):
        return False

    def locator(self, selector):
        return Locator("password" not in selector)

    def get_by_text(self, text, exact=False):
        return Locator(self.detail)

    async def evaluate(self, script, args=None):
        return {"label": self.label, "password": False, "input": True} if args else True

    async def screenshot(self, **kwargs):
        return b"screenshot"

    async def wait_for_timeout(self, value):
        pass

    async def wait_for_load_state(self, state, timeout):
        pass


def model_response(*parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(
        content=types.Content(role="model", parts=list(parts)))])


class LoopTests(unittest.IsolatedAsyncioTestCase):
    def worker(self, responses=()):
        generate = AsyncMock(side_effect=list(responses))
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        worker = SapBrowserWorker(url=URL, profile_dir=Path("/tmp/test-sap"), client=client)
        worker._save_login = AsyncMock()
        return worker, generate

    async def test_screenshot_action_feedback_and_result(self):
        result = {"purchase_order": ORDER, "supplier": "Carbon Tec Inc.", "items": []}
        worker, generate = self.worker([
            model_response(types.Part(function_call=types.FunctionCall(name="click_at", id="c1", args={"x": 500, "y": 500}))),
            model_response(types.Part(text=json.dumps(result))),
        ])
        page = Page()
        response = await worker._loop(page, ORDER, [])
        self.assertTrue(response["ok"])
        page.mouse.click.assert_awaited_once_with(640.0, 400.0)
        contents = generate.call_args.kwargs["contents"]
        feedback = contents[2].parts[0].function_response
        self.assertEqual(feedback.id, "c1")
        self.assertEqual(feedback.parts[0].inline_data.data, b"screenshot")
        self.assertIsNone(response["data"]["order_date"])

    async def test_confirmation_stops_before_any_action(self):
        worker, _ = self.worker([model_response(types.Part(function_call=types.FunctionCall(
            name="click_at", args={"x": 50, "y": 50, "safety_decision": {"decision": "require_confirmation"}})))])
        page = Page()
        response = await worker._loop(page, ORDER, [])
        self.assertEqual(response["error"]["code"], "CONFIRMATION_REQUIRED")
        page.mouse.click.assert_not_awaited()

    async def test_premature_not_found_is_repaired_when_order_is_visible(self):
        data = {"purchase_order": ORDER, "items": []}
        worker, generate = self.worker([
            model_response(types.Part(text='{"error":"NOT_FOUND"}')),
            model_response(types.Part(text=json.dumps(data))),
        ])
        result = await worker._loop(Page(), ORDER, [])
        self.assertTrue(result["ok"])
        self.assertEqual(generate.await_count, 2)

    async def test_wrong_order_and_unopened_detail_rejected(self):
        worker, _ = self.worker()
        page = Page()
        data = {"purchase_order": "4500000000", "items": []}
        self.assertFalse((await worker._finish(page, ORDER, json.dumps(data), []))["ok"])
        page.detail = False
        data["purchase_order"] = ORDER
        self.assertFalse((await worker._finish(page, ORDER, json.dumps(data), []))["ok"])

    async def test_mutating_buttons_and_unrelated_input_blocked(self):
        worker, _ = self.worker()
        page = Page()
        for label in ("Edit", "Create", "Copy", "Save", "Delete", "Post Goods Receipt"):
            page.label = label
            with self.assertRaises(PermissionError):
                await worker._action(page, "click_at", {"x": 500, "y": 500}, ORDER)
        page.label = ""
        with self.assertRaises(PermissionError):
            await worker._action(page, "type_text_at", {"x": 10, "y": 10, "text": "password"}, ORDER)
        page.mouse.click.assert_not_awaited()

    async def test_new_model_actions_wait_type_and_press_key(self):
        worker, _ = self.worker()
        page = Page()
        await worker._action(page, "wait", {"seconds": 1}, ORDER)
        await worker._action(page, "type", {"text": ORDER}, ORDER)
        page.keyboard.type.assert_awaited_once_with(ORDER)
        await worker._action(page, "press_key", {"key": "Enter"}, ORDER)
        await worker._action(page, "scroll", {"direction": "down", "magnitude_in_pixels": 1200}, ORDER)
        page.mouse.wheel.assert_awaited_once_with(0, 1200)
        with self.assertRaises(PermissionError):
            await worker._action(page, "type", {"text": "other"}, ORDER)
        with self.assertRaises(ValueError):
            await worker._action(page, "wait", {"seconds": 10000}, ORDER)

    async def test_navigation_only_to_tenant_order_pages(self):
        worker, _ = self.worker()
        page = Page()
        page.goto = AsyncMock()
        await worker._action(page, "navigate", {"url": URL.replace("Shell-home", "PurchaseOrder-manage")}, ORDER)
        for target in ("https://evil.example", URL.replace("Shell-home", "PurchaseOrder-create")):
            with self.assertRaises(PermissionError):
                await worker._action(page, "navigate", {"url": target}, ORDER)
        page.goto.assert_awaited_once()

    async def test_missing_session_and_busy_user(self):
        worker, _ = self.worker()
        self.assertEqual((await worker.query("one", ORDER))["error"]["code"], "LOGIN_REQUIRED")
        session = BrowserSession(SimpleNamespace(), Page())
        worker.sessions["one"] = session
        await session.lock.acquire()
        self.assertEqual((await worker.query("one", ORDER))["error"]["code"], "SAP_BUSY")
        self.assertEqual((await worker.query("two", ORDER))["error"]["code"], "LOGIN_REQUIRED")
        session.lock.release()
        self.assertNotEqual(worker.profile_path("one"), worker.profile_path("two"))

    async def test_timeout_does_not_claim_success_and_keeps_guard(self):
        worker, _ = self.worker()
        worker.timeout = .01
        context = SimpleNamespace(route=AsyncMock(), unroute=AsyncMock())
        worker.sessions["one"] = BrowserSession(context, Page())
        async def slow(*args):
            await asyncio.sleep(1)
        worker._loop = slow
        response = await worker.query("one", ORDER)
        self.assertEqual(response["error"]["code"], "SAP_TIMEOUT")
        self.assertFalse(worker.sessions["one"].lock.locked())
        context.unroute.assert_not_awaited()

    async def test_auth_and_user_forwarding(self):
        worker, _ = self.worker()
        worker.query = AsyncMock(return_value={"ok": True})
        app = create_app(worker, "t" * 32)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            body = {"user_id": "adk:one", "purchase_order": ORDER}
            self.assertEqual((await client.post("/query", json=body)).status_code, 401)
            self.assertEqual((await client.post("/query", json=body,
                headers={"Authorization": "Bearer " + "t" * 32})).status_code, 200)
        worker.query.assert_awaited_once_with("adk:one", ORDER)

    async def test_client_invalid_order_never_sends_request(self):
        with patch("smart_agents.sap_tools._request", new_callable=AsyncMock) as request:
            response = await sap_query_purchase_order("bad", SimpleNamespace())
            self.assertFalse(response["ok"])
            request.assert_not_awaited()

    async def test_golden_screenshot_is_saved_and_removed_from_model_json(self):
        import base64
        context = SimpleNamespace(state={}, save_artifact=AsyncMock(return_value=0))
        with patch("smart_agents.sap_tools._request", new_callable=AsyncMock,
                   return_value={"ok": True, "screenshot_base64": base64.b64encode(b"image").decode()}):
            result = await sap_query_purchase_order(ORDER, context)
        context.save_artifact.assert_awaited_once()
        self.assertNotIn("screenshot_base64", result)
        self.assertEqual(result["artifacts"][0]["mime_type"], "image/png")

    async def test_actual_adk_runner_tool_and_worker_identity_contract(self):
        class Model(BaseLlm):
            _called: bool = PrivateAttr(default=False)

            async def generate_content_async(self, llm_request, stream=False):
                if not self._called:
                    self._called = True
                    part = types.Part(function_call=types.FunctionCall(
                        name="sap_query_purchase_order", args={"purchase_order": ORDER}))
                else:
                    part = types.Part(text="已查询")
                yield LlmResponse(content=types.Content(role="model", parts=[part]))

        worker, _ = self.worker()
        worker.query = AsyncMock(return_value={"ok": True, "data": {"purchase_order": ORDER}})
        app = create_app(worker, "t" * 32)
        agent = Agent(name="sap_contract", model=Model(model="offline"), tools=[sap_query_purchase_order])
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="sap_contract", user_id="adk-user", state={
            "tse_user_email": "owner@example.com", "tse_auth_source": "tse_app"})
        runner = Runner(app_name="sap_contract", agent=agent, session_service=sessions)
        original_client = httpx.AsyncClient

        def client(**kwargs):
            return original_client(transport=httpx.ASGITransport(app=app), **kwargs)

        with patch.dict("os.environ", {"SAP_COMPUTER_USE_ENABLED": "true",
                "SAP_COMPUTER_USE_WORKER_URL": "http://127.0.0.1:8010", "SAP_COMPUTER_USE_TOKEN": "t" * 32}), \
                patch("smart_agents.sap_tools.httpx.AsyncClient", side_effect=client):
            events = [event async for event in runner.run_async(user_id="adk-user", session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="查询 SAP " + ORDER)]))]
        worker.query.assert_awaited_once_with("tse:owner@example.com", ORDER)
        responses = [part.function_response.response for event in events if event.content
                     for part in event.content.parts if part.function_response]
        self.assertTrue(responses[0]["ok"])


if __name__ == "__main__":
    unittest.main()
