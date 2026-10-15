# -*- coding: utf-8 -*-
"""Bilibili MCP 子 Agent — re-export from domains builder."""

from domains.bilibili.builder import build_bilibili_agent, build_bilibili_mcp_sub_agent
from domains.bilibili.registry import AGENT_NAME, SKILL_ID

__all__ = ["AGENT_NAME", "SKILL_ID", "build_bilibili_agent", "build_bilibili_mcp_sub_agent"]
