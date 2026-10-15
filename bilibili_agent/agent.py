# -*- coding: utf-8 -*-
"""
bilibili_agent — B 站 MCP + Skill Agent

L1 工具：domains/bilibili/bilibili_tools.py
MCP：mcp_server/bilibili_mcp.py :8002

本地：
  python mcp_server/bilibili_mcp.py --http
  ./scripts/run_adk_bilibili_agent.sh
"""

from __future__ import annotations

import os

from domains.bilibili.builder import build_bilibili_agent
from domains.shared.mcp_health import assert_mcp_reachable
from domains.shared.runtime_mode import normalize_mcp_url
from smart_agents.vertex import vertex_model

BILIBILI_MCP_SERVER_URL = normalize_mcp_url(
    os.getenv("BILIBILI_MCP_SERVER_URL", "http://127.0.0.1:8002/mcp")
)
assert_mcp_reachable(BILIBILI_MCP_SERVER_URL, label="Bilibili MCP")

print(f"🔌 Bilibili MCP：{BILIBILI_MCP_SERVER_URL}")
print("📺 正在初始化 Bilibili Agent（MCP + Skill）...")

root_agent = build_bilibili_agent(
    model=vertex_model,
    mcp_server_url=BILIBILI_MCP_SERVER_URL,
    standalone=True,
)
bilibili_agent = root_agent
