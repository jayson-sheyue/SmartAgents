#!/usr/bin/env python3
"""
cloud_agent 本地入口 — 加载 cloud_agent/agent.py，避免与 cloud_agent/ 包名冲突。
"""

import importlib.util
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_AGENT_PATH = Path(__file__).resolve().parent / "cloud_agent" / "agent.py"
_spec = importlib.util.spec_from_file_location("cloud_agent_deploy_agent", _AGENT_PATH)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

root_agent = _mod.root_agent
cloud_agent = _mod.cloud_agent

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        pid = os.getenv("GCP_PROJECT_ID", "<GCP_PROJECT_ID>")
        loc = os.getenv("GCP_LOCATION", "us-central1")
        eid = os.getenv("REST_AGENT_ENGINE_ID", "<REST_AGENT_ENGINE_ID>")
        print("🚀 部署命令:")
        print(
            f"  adk deploy agent_engine cloud_agent "
            f"--project={pid} --region={loc} "
            f'--display_name="Bilibili-Cloud-Agent" '
            f"--agent_engine_id={eid}"
        )
    else:
        print("💡 本地交互: adk run cloud_agent")
        print("💡 前置: local_node/server.py + ngrok 8001")
