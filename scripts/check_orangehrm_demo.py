"""Real screenshot/model login, employee search and second-browser session reuse check."""
import asyncio
import base64
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from domains.sap.orangehrm_demo import run_orangehrm_demo


class MemoryState:
    # Local validation only. Production always uses encrypted private GCS storage.
    def __init__(self):
        self.values = {}
    def load(self, user):
        return self.values.get(user, (None, 0))
    def save(self, user, state, generation):
        if self.values.get(user, (None, 0))[1] != generation:
            raise ValueError('Stale state')
        self.values[user] = state, generation + 1
        return generation + 1


async def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    client = genai.Client(vertexai=True, project=os.environ['GCP_PROJECT_ID'],
                          location=os.getenv('SAP_COMPUTER_USE_LOCATION', 'global'))
    store = MemoryState()
    try:
        for number in (1, 2):
            result = await asyncio.wait_for(run_orangehrm_demo(client=client,
                state_store=store, user_id='local-validation',
                model=os.getenv('SAP_COMPUTER_USE_MODEL', 'gemini-3.8-flash')), 180)
            output = Path('.sap_cloud/diagnostics/orangehrm-local') / str(number)
            output.mkdir(parents=True, exist_ok=True)
            for image in result.pop('screenshots', []):
                (output / image['filename']).write_bytes(base64.b64decode(image['base64']))
            (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            if not result.get('ok') or (number == 2 and not result.get('session_reused')):
                raise SystemExit(1)
    finally:
        await client.aio.aclose()


if __name__ == '__main__':
    asyncio.run(main())
