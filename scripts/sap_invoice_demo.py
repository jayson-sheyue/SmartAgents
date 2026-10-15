"""Native invoice recognition demo; optional read-only SAP query, no deployment."""
import argparse
import asyncio
import json
import mimetypes
from pathlib import Path
from types import SimpleNamespace

from google.genai import types
from smart_agents.env_runtime import load_runtime_env
from smart_agents.invoice_tools import invoice_extract, sap_query_from_invoice
from scripts.sap_local_bridge import tse_user


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="本地发票 PDF/PNG/JPEG/WebP")
    parser.add_argument("--query-sap", action="store_true", help="识别唯一 PO 后查询 SAP")
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--user", default="sap-demo", help="复用该 ADK 用户专用 SAP 登录态")
    identity.add_argument("--tse-email", help="复用绑定的 TSE 用户专用 SAP 登录态")
    parser.add_argument("--output-dir", default="/private/tmp/sap-invoice-demo")
    args = parser.parse_args()
    load_runtime_env()
    path = Path(args.file).expanduser()
    if path.stat().st_size > 20 * 1024 * 1024:
        parser.error("文件超过 20 MB")
    part = types.Part.from_bytes(data=path.read_bytes(),
        mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    output = Path(args.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)

    async def save_artifact(*, filename, artifact):
        destination = output / Path(filename).name
        destination.write_bytes(artifact.inline_data.data)
        destination.chmod(0o600)
        return 0

    state = {"tse_user_email": tse_user(args.tse_email)[4:], "tse_auth_source": "tse_app"} if args.tse_email else {}
    context = SimpleNamespace(user_id=args.user, state=state, save_artifact=save_artifact,
        user_content=types.Content(role="user", parts=[part]))
    tool = sap_query_from_invoice if args.query_sap else invoice_extract
    result = await tool(context)
    if args.query_sap and result.get("artifacts"):
        result["screenshot_paths"] = [str(output / item["filename"]) for item in result["artifacts"]]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
