"""Run the real, fixed guest-store Computer Use demo with local headless Chromium."""
import asyncio
import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai

from domains.sap.web_demo import run_demoblaze_demo


async def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    client = genai.Client(vertexai=True, project=os.environ['GCP_PROJECT_ID'],
                          location=os.getenv('SAP_COMPUTER_USE_LOCATION', 'global'))
    try:
        result = await asyncio.wait_for(run_demoblaze_demo(client=client,
            model=os.getenv('SAP_COMPUTER_USE_MODEL', 'gemini-3.8-flash')), 180)
    finally:
        await client.aio.aclose()
    output = Path('.sap_cloud/diagnostics/demoblaze-local')
    output.mkdir(parents=True, exist_ok=True)
    png = result.pop('screenshot_base64', None)
    if png:
        (output / 'result.png').write_bytes(base64.b64decode(png))
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get('ok'):
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
