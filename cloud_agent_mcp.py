"""cloud_agent_mcp 本地入口 — 从 deploy 目录加载 agent，避免与包名冲突。"""

import importlib.util
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_AGENT_PATH = Path(__file__).resolve().parent / "cloud_agent_mcp" / "agent.py"
_spec = importlib.util.spec_from_file_location(
    "cloud_agent_mcp_deploy_agent", _AGENT_PATH
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

root_agent = _mod.root_agent
cloud_agent_mcp = _mod.cloud_agent_mcp

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        pid = os.getenv("GCP_PROJECT_ID", "<GCP_PROJECT_ID>")
        loc = os.getenv("GCP_LOCATION", "us-central1")
        eid = os.getenv("MCP_AGENT_ENGINE_ID", "<MCP_AGENT_ENGINE_ID>")
        print("🚀 部署命令:")
        print(
            f"  adk deploy agent_engine cloud_agent_mcp "
            f"--project={pid} --region={loc} "
            f'--display_name="Bilibili Cloud MCP Agent" '
            f"--agent_engine_id={eid}"
        )
    else:
        print("💡 本地: ./scripts/run_adk_cloud_agent_mcp.sh")
        print("💡 需先: python mcp_server/bilibili_mcp.py --http")
