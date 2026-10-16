"""Manual-login worker smoke; explicit public-test flag simulates only human input APIs.

No credentials enter model contents. Without the flag this only opens the empty
login page. Production users always type their own credentials in TSE's login UI.
"""
import argparse
import asyncio
import base64
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from google import genai
from domains.sap.orangehrm_sessions import OrangeHRMSessions
from domains.sap.orangehrm_demo import EMPLOYEES
from scripts.check_orangehrm_demo import MemoryState


async def main(simulate_public):
    load_dotenv(Path(__file__).resolve().parents[1]/'.env',override=False)
    store=MemoryState();worker=OrangeHRMSessions(state_store=store)
    user='tse:manual-smoke@example.com';client=None
    output=Path('.sap_cloud/diagnostics/orangehrm-human-local');output.mkdir(parents=True,exist_ok=True)
    try:
        ready=await worker.prepare(user)
        assert ready.get('wait_user') and ready.get('logged_in') is False
        snap=await worker.login_snapshot(user)
        (output/'manual-login.png').write_bytes(base64.b64decode(snap['image_base64']))
        print({'initial':'manual_login_required','model_called':False},flush=True)
        if not simulate_public:
            return
        # Explicit test-only simulation of the UI channel using public demo values.
        from domains.sap.orangehrm_demo import DEMO_USER, DEMO_PASSWORD
        page=worker.sessions[user].page
        for name,text in [('username',DEMO_USER),('password',DEMO_PASSWORD)]:
            snap=await worker.login_snapshot(user);box=await page.locator('[name='+name+']').bounding_box()
            await worker.login_action(user,{'kind':'click','x':box['x']+box['width']/2,'y':box['y']+box['height']/2},snap['revision'])
            snap=await worker.login_snapshot(user)
            await worker.login_action(user,{'kind':'text','text':text},snap['revision'])
        snap=await worker.login_snapshot(user);box=await page.locator('button[type=submit]').bounding_box()
        await worker.login_action(user,{'kind':'click','x':box['x']+box['width']/2,'y':box['y']+box['height']/2},snap['revision'])
        await page.wait_for_url(lambda u:urlsplit(str(u)).path in {'/web/index.php/dashboard/index','/web/index.php/pim/viewEmployeeList'},timeout=20000)
        await page.wait_for_load_state('networkidle')
        assert (await worker.status(user))['logged_in']
        await worker.close(user)
        assert (await worker.prepare(user))['logged_in'], 'Manual state did not restore'
        client=genai.Client(vertexai=True,project=os.environ['GCP_PROJECT_ID'],location='global')
        result=await asyncio.wait_for(worker.query(user,client=client,model=os.getenv('SAP_COMPUTER_USE_MODEL','gemini-3.8-flash')),180)
        for pic in result.pop('screenshots',[]):
            (output/pic['filename']).write_bytes(base64.b64decode(pic['base64']))
        (output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        print(json.dumps(result,ensure_ascii=False),flush=True)
        assert result.get('ok') and not result.get('wait_user')
        await worker.logout(user)
        assert (await worker.prepare(user))['logged_in'] is False
        print({'manual_login_restore_query_logout':'passed'},flush=True)
    finally:
        await worker.shutdown()
        if client:await client.aio.aclose()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--simulate-public-input',action='store_true')
    args=parser.parse_args();asyncio.run(main(args.simulate_public_input))
