# -*- coding: utf-8 -*-
"""
bilibili_cloud_agent_mcp/agent.py — B 站云端 MCP + Skill Agent（ADK 部署入口）

【调用链】
  Playground / adk run
    → load_skill('bilibili-rpa') + MCP tools
    → BILIBILI_MCP_SERVER_URL（Cloudflare Tunnel :8002 或本机 127.0.0.1:8002）
    → mcp_server/bilibili_mcp.py → rpa_tools.py → bilibili_tools.py

【与 bilibili_cloud_agent（REST）的区别】
  - 执行层：McpToolset 直连 MCP 协议（非 HTTP REST 包装函数）
  - 编排层：SkillToolset + GCP Skill Registry + 本地 skills/ 兜底

【本地 adk run】
  终端 1: python mcp_server/bilibili_mcp.py --http
  终端 2: BILIBILI_MCP_SERVER_URL=http://127.0.0.1:8002/mcp ./scripts/run_adk_bilibili_cloud_agent_mcp.sh

子 Agent 逻辑见 smart_agents/bilibili_mcp_sub.py（与调度树共用）。
"""

from __future__ import annotations

import os

from smart_agents.bilibili_mcp_sub import build_bilibili_mcp_sub_agent
from smart_agents.vertex import vertex_model

BILIBILI_MCP_SERVER_URL = os.getenv("BILIBILI_MCP_SERVER_URL", "http://127.0.0.1:8002/mcp").rstrip("/")
if not BILIBILI_MCP_SERVER_URL.endswith("/mcp"):
    BILIBILI_MCP_SERVER_URL = f"{BILIBILI_MCP_SERVER_URL.rstrip('/')}/mcp"
if "BILIBILI_MCP_SERVER_URL" not in os.environ:
    print("ℹ️ 未在 .env 配置 BILIBILI_MCP_SERVER_URL，本地默认 http://127.0.0.1:8002/mcp")

print(f"🔌 MCP 端点：{BILIBILI_MCP_SERVER_URL}")
print("☁️ 正在初始化 MCP + Skill Agent（P0 envelope）...")

root_agent = build_bilibili_mcp_sub_agent(
    model=vertex_model,
    mcp_server_url=BILIBILI_MCP_SERVER_URL,
)
bilibili_cloud_agent_mcp = root_agent

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        pid = os.getenv("GCP_PROJECT_ID", "<GCP_PROJECT_ID>")
        loc = os.getenv("GCP_LOCATION", "us-central1")
        eid = os.getenv("BILIBILI_MCP_AGENT_ENGINE_ID", "<BILIBILI_MCP_AGENT_ENGINE_ID>")
        print("🚀 部署命令:")
        print(
            f"  adk deploy agent_engine bilibili_cloud_agent_mcp "
            f"--project={pid} --region={loc} "
            f'--display_name="Bilibili Cloud MCP Agent" '
            f"--agent_engine_id={eid}"
        )
    else:
        print("💡 本地: ./scripts/run_adk_bilibili_cloud_agent_mcp.sh")
        print("💡 需先: python mcp_server/bilibili_mcp.py --http")
