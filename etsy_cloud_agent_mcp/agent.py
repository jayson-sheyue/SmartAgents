# -*- coding: utf-8 -*-
"""
etsy_cloud_agent_mcp/agent.py — Etsy MCP + Skill Agent（ADK）

调用链：
  adk run → load_skill('etsy-review') + McpToolset
  → ETSY_MCP_SERVER_URL → mcp_server/etsy_mcp.py → etsy_tools.py

子 Agent 逻辑见 smart_agents/etsy_mcp_sub.py（与调度树共用）。
"""

from __future__ import annotations

import os

from smart_agents.etsy_mcp_sub import build_etsy_mcp_sub_agent
from smart_agents.vertex import vertex_model

ETSY_MCP_SERVER_URL = os.getenv("ETSY_MCP_SERVER_URL", "http://127.0.0.1:8003/mcp").rstrip("/")
if not ETSY_MCP_SERVER_URL.endswith("/mcp"):
    ETSY_MCP_SERVER_URL = f"{ETSY_MCP_SERVER_URL.rstrip('/')}/mcp"

print(f"🔌 Etsy MCP 端点：{ETSY_MCP_SERVER_URL}")
print("🛍️ 正在初始化 Etsy MCP + Skill Agent...")

root_agent = build_etsy_mcp_sub_agent(
    model=vertex_model,
    mcp_server_url=ETSY_MCP_SERVER_URL,
)
etsy_cloud_agent_mcp = root_agent
