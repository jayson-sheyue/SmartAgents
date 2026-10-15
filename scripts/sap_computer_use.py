"""Local worker CLI; auth stays in env, never passed in shell arguments."""
import argparse
import asyncio
import json
from pathlib import Path
import os

from smart_agents.env_runtime import load_runtime_env
from smart_agents.sap_tools import _request, sap_query_purchase_order
from scripts.sap_local_bridge import tse_user, BRIDGE_DIR


async def main():
    parser = argparse.ArgumentParser(description="SAP Computer Use 本地验证")
    parser.add_argument("action", choices=["prepare", "query", "close", "status"])
    identity = parser.add_mutually_exclusive_group()
    identity.add_argument("--user-id", default="sap-demo", help="ADK user_id；不要添加 adk: 前缀")
    identity.add_argument("--tse-email", help="使用绑定的 TSE 登录邮箱，与云端浏览器会话相同")
    parser.add_argument("--order", default="")
    args = parser.parse_args()
    load_runtime_env()

    class Context:
        state = {"tse_user_email": tse_user(args.tse_email)[4:], "tse_auth_source": "tse_app"} if args.tse_email else {}
        user_id = args.user_id

        async def save_artifact(self, *, filename, artifact):
            BRIDGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = BRIDGE_DIR / Path(filename).name
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(artifact.inline_data.data)
            return 0

    result = await sap_query_purchase_order(args.order, Context()) if args.action == "query" else await _request(args.action, Context())
    if result.get("artifacts"):
        result["screenshot_paths"] = [str(BRIDGE_DIR / item["filename"]) for item in result["artifacts"]]
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
