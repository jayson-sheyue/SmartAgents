"""Real Chromium + fake model + local HTML fixture. No SAP/Google network calls."""
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from google.genai import types
from playwright.async_api import async_playwright

from domains.sap.browser import BrowserSession, SapBrowserWorker
from domains.sap.golden_path import run_golden_path


class BrowserSmoke(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_reopens_browser_after_last_window_is_closed(self):
        url = "https://your-tenant.s4hana.cloud.sap/ui#PurchaseOrder-manage"
        html = '<div id="shell-header">Manage Purchase Orders</div>'
        with tempfile.TemporaryDirectory() as directory:
            worker = SapBrowserWorker(url=url, profile_dir=Path(directory))
            async with async_playwright() as p:
                worker._playwright = p
                launch = p.chromium.launch_persistent_context
                async def fixture_context(*args, **kwargs):
                    kwargs["headless"] = True
                    context = await launch(*args, **kwargs)
                    await context.route("https://your-tenant.s4hana.cloud.sap/**",
                        lambda route: route.fulfill(body=html, content_type="text/html"))
                    return context
                with patch.object(p.chromium, "launch_persistent_context", side_effect=fixture_context) as launcher:
                    first = await worker.prepare("test")
                    self.assertTrue(first["logged_in"])
                    session = worker.sessions["test"]
                    profile = worker.profile_path("test")
                    await session.context.add_cookies([{"name": "demo-session", "value": "fixture",
                        "url": "https://your-tenant.s4hana.cloud.sap", "expires": 2000000000}])
                    # Explicit close of the context represents closing its last window.
                    await session.context.close()
                    self.assertFalse((await worker.status("test"))["browser_open"])
                    self.assertEqual((await worker.query("test", "4500071250"))["error"]["code"], "LOGIN_REQUIRED")
                    reopened = await worker.prepare("test")
                    self.assertTrue(reopened["logged_in"])
                    self.assertIsNot(worker.sessions["test"], session)
                    self.assertEqual(launcher.call_count, 2)
                    self.assertEqual(launcher.call_args.args[0], str(profile))
                    cookies = await worker.sessions["test"].context.cookies()
                    self.assertTrue(any(cookie["name"] == "demo-session" for cookie in cookies))
                    # Disconnect cleanup must also tolerate a manually closed window.
                    await worker.sessions["test"].context.close()
                    await worker.close("test")
                    self.assertFalse((await worker.status("test"))["browser_open"])

    async def test_golden_screenshot_waits_for_ui5_busy_overlay(self):
        url = "https://your-tenant.s4hana.cloud.sap/ui#PurchaseOrder-manage"
        html = """<label for="po">Purchase Order:</label><input id="po">
        <button onclick="document.getElementById('result').textContent=document.getElementById('po').value;
        document.getElementById('busy').style.display='block';
        setTimeout(()=>document.getElementById('busy').style.display='none',1000)">Go</button>
        <div id="result"></div><div id="busy" class="sapUiLocalBusyIndicator" style="display:none">Loading</div>"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.route("https://your-tenant.s4hana.cloud.sap/**", lambda route: route.fulfill(body=html, content_type="text/html"))
                result = await run_golden_path(page, url=url, order="4500071250", mode="script")
                self.assertTrue(result["ok"])
                self.assertTrue(result["screenshot"].startswith(b"\x89PNG"))
                self.assertFalse(await page.locator("#busy").is_visible())
            finally:
                await browser.close()

    async def test_real_browser_query_and_write_interception(self):
        url = "https://your-tenant.s4hana.cloud.sap/ui"
        html = """<html><body><div id="shell-header">Manage Purchase Orders</div>
        <label>Purchase Order:</label><input><button style="position:absolute;left:550px;top:350px;width:180px;height:100px"
         onclick="document.getElementById('detail').innerHTML='<h1>Purchase Order</h1><h2>4500071250</h2><p>Carbon Tec Inc.</p>'">
        Standard PO</button><div id="detail"></div></body></html>"""
        responses = [types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
            role="model", parts=[types.Part(function_call=types.FunctionCall(
                name="click_at", args={"x": 500, "y": 500}, id="c1"))]))]),
            types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
                role="model", parts=[types.Part(text=json.dumps({"purchase_order": "4500071250",
                    "supplier": "Carbon Tec Inc.", "items": []}))]))])]
        generate = AsyncMock(side_effect=responses)
        client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
        with tempfile.TemporaryDirectory() as directory:
            worker = SapBrowserWorker(url=url, profile_dir=Path(directory), client=client)
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
                async def fixture(route):
                    await route.fulfill(body=html, content_type="text/html")
                await context.route(url, fixture)
                page = await context.new_page()
                await page.goto(url)
                # Keep the local fixture for the worker's deterministic app bootstrap.
                worker.sessions["test"] = BrowserSession(context, page)
                result = await worker.query("test", "4500071250")
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["data"]["supplier"], "Carbon Tec Inc.")
                self.assertTrue(generate.call_args.kwargs["contents"][2].parts[0]
                                .function_response.parts[0].inline_data.data.startswith(b"\x89PNG"))
                # Guard remains installed after a completed query, including delayed writes.
                allowed = await page.evaluate("""async () => {
                  try { await fetch('/sap/opu/odata/Orders', {method:'PATCH',body:'{}'}); return true; }
                  catch(e) { return false; }
                }""")
                self.assertFalse(allowed)
                await browser.close()


if __name__ == "__main__":
    unittest.main()
