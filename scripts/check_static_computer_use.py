"""Real Gemini + headless Chromium smoke check, without SAP or login.

The fixed HTML is fulfilled in memory. The SAP-shaped synthetic URL allows reuse
of the production Golden Path without weakening its tenant URL validation.
No request reaches SAP. UI action coordinates come only from Gemini screenshots.
Run locally with --output PATH, or --serve in a private temporary Cloud Run service.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time

from domains.sap.golden_path import run_golden_path

TEST_URL = 'https://static-cu-test.s4hana.cloud.sap/ui#PurchaseOrder-manage'
TEST_ORDER = '4500000001'
HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Static Computer Use Check</title><style>
body{font:22px Arial;background:#eff4fa;color:#172b4d;margin:0;padding:64px}
main{max-width:1100px;background:white;padding:40px;border-radius:20px}
h1{font-size:34px;margin-top:0}small{color:#52677b}label{display:block;margin:36px 0 12px}
input{font:26px Arial;padding:14px;width:430px;border:2px solid #667a91;border-radius:8px}
button{font:26px Arial;color:white;background:#0866d9;border:0;border-radius:8px;padding:16px 40px;margin-left:20px}
section{margin-top:36px;padding:24px;background:#f1f5fa;border-radius:12px}
td,th{text-align:left;padding:16px;border-bottom:1px solid #cad6e3}
.ok{color:#087b47;font-weight:bold}</style></head><body><main>
<h1>Static Computer Use Check</h1><small>SYNTHETIC TEST DATA · NO SAP CONNECTION · NO LOGIN</small>
<label for="order">Purchase Order</label><input id="order" autocomplete="off"><button id="go">Go</button>
<section id="result">Enter the test order and click Go.</section>
<script>document.getElementById('go').onclick=()=>{
const value=document.getElementById('order').value;
document.getElementById('result').innerHTML=value==='4500000001'
?'<p class="ok">Query completed</p><table><tr><th>Purchase Order</th><th>Supplier</th><th>Status</th></tr><tr><td id="found">4500000001</td><td>Demo Supplier</td><td>Ready</td></tr></table>'
:'No matching test order';};</script></main></body></html>'''


async def check():
    from google import genai
    from playwright.async_api import async_playwright

    started = time.monotonic()
    model = os.getenv('SAP_COMPUTER_USE_MODEL', 'gemini-3.8-flash')
    client = genai.Client(vertexai=True, project=os.environ['GCP_PROJECT_ID'],
                          location=os.getenv('SAP_COMPUTER_USE_LOCATION', 'global'))
    calls, blocked = [], []

    async def generate(**kwargs):
        before = time.monotonic()
        response = await client.aio.models.generate_content(**kwargs)
        content = response.candidates[0].content
        calls.append({'stage': len(calls) + 1,
                      'seconds': round(time.monotonic() - before, 2),
                      'actions': [{'name': part.function_call.name,
                                   'args': dict(part.function_call.args or {})}
                                  for part in content.parts or [] if part.function_call]})
        return response

    observed = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
            try:
                context = await browser.new_context(viewport={'width': 1440, 'height': 900},
                    service_workers='block', accept_downloads=False)

                async def fixed_page(route):
                    if route.request.url == TEST_URL.split('#')[0] and route.request.method == 'GET':
                        await route.fulfill(body=HTML, content_type='text/html')
                    else:
                        blocked.append(route.request.resource_type)
                        await route.abort()

                await context.route('**/*', fixed_page)
                page = await context.new_page()
                result = await asyncio.wait_for(run_golden_path(page, url=TEST_URL,
                    order=TEST_ORDER, mode='computer-use', client=observed, model=model), 150)
                # DOM verifies the effect after the visual actions; it supplies no coordinates.
                matched = await page.locator('#found').inner_text() == TEST_ORDER
                if not matched or len(calls) != 3:
                    raise RuntimeError('Static result verification failed')
                png = result.pop('screenshot')
                return {'ok': True, 'environment': 'headless_chromium', 'model': model,
                        'data_source': 'fixed_in_memory_html_no_sap',
                        'verified_order': TEST_ORDER, 'model_calls': calls,
                        'blocked_browser_requests': blocked,
                        'seconds': round(time.monotonic() - started, 2),
                        'screenshot_base64': base64.b64encode(png).decode()}
            finally:
                await browser.close()
    finally:
        await client.aio.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('/tmp/static-computer-use-check'))
    args = parser.parse_args()
    if args.serve:
        from fastapi import FastAPI
        import uvicorn
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        lock = asyncio.Lock()

        @app.get('/health')
        async def health():
            return {'ok': True, 'test': 'static_computer_use'}

        @app.post('/run')
        async def run():
            if lock.locked():
                return {'ok': False, 'error': 'Test already running'}
            async with lock:
                try:
                    return await check()
                except Exception as exc:
                    return {'ok': False, 'error_type': type(exc).__name__, 'error': str(exc)[:800]}

        uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', '8080')), access_log=False)
    else:
        result = asyncio.run(check())
        args.output.mkdir(parents=True, exist_ok=True)
        png = base64.b64decode(result.pop('screenshot_base64'))
        (args.output / 'result.png').write_bytes(png)
        (args.output / 'result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
