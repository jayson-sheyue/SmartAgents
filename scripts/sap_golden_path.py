"""Fixed SAP PoC; python -m scripts.sap_golden_path --mode script|computer-use."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from playwright.async_api import async_playwright

from domains.sap.golden_path import DEMO_ORDER, DEMO_URL, run_golden_path, save_screenshot
from smart_agents.env_runtime import load_runtime_env


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["script", "computer-use"], default="script")
    parser.add_argument("--order", default=DEMO_ORDER)
    parser.add_argument("--url", default=DEMO_URL)
    parser.add_argument("--output", default="/private/tmp/sap-golden-path-result.png")
    parser.add_argument("--login", action="store_true", help="首次登录时由人在新窗口登录后按回车")
    args = parser.parse_args()
    load_runtime_env()
    profile = Path(".sap_browser_profiles") / hashlib.sha256(b"adk:sap-demo").hexdigest()
    saved = profile / "login-state.json"
    state = json.loads(saved.read_text()) if saved.exists() else {"cookies": []}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        # Reuse our own dedicated login cookies; don't copy user Chrome or old app caches.
        context = await browser.new_context(storage_state={"cookies": state["cookies"], "origins": []},
                                            viewport={"width": 1440, "height": 900}, accept_downloads=False)
        page = await context.new_page()
        if args.login:
            await page.goto(args.url, wait_until="domcontentloaded")
            await asyncio.to_thread(input, "请在该窗口登录 SAP，进入订单页面后按回车：")
        try:
            result = await asyncio.wait_for(run_golden_path(page, url=args.url, order=args.order, mode=args.mode), 120)
            print(json.dumps(await save_screenshot(result, Path(args.output)), ensure_ascii=False, indent=2))
        except Exception as exc:
            print(json.dumps({"ok": False, "error": type(exc).__name__,
                              "message": str(exc)[:250]}, ensure_ascii=False))
            raise SystemExit(1)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
