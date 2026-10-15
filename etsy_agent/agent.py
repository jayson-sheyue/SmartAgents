# -*- coding: utf-8 -*-
"""
etsy_agent — Etsy MCP + Skill Agent（评论 + 上架素材生图）

L1 工具：domains/etsy/
MCP：mcp_server/etsy_mcp.py :8003

本地：
  python mcp_server/etsy_mcp.py --http
  ./scripts/run_adk_etsy_agent.sh
"""

from __future__ import annotations

import os

from domains.etsy.builder import build_etsy_agent
from domains.shared.mcp_health import assert_mcp_reachable
from domains.shared.runtime_mode import normalize_mcp_url

ETSY_MCP_URL = normalize_mcp_url(os.getenv("ETSY_MCP_SERVER_URL", "http://127.0.0.1:8003/mcp"))
assert_mcp_reachable(ETSY_MCP_URL, label="Etsy MCP")

print(f"🔌 Etsy MCP：{ETSY_MCP_URL}")
print("🛍️ 正在初始化 Etsy Agent（MCP + Skill）...")
root_agent = build_etsy_agent(mcp_server_url=ETSY_MCP_URL, standalone=True)
etsy_agent = root_agent
