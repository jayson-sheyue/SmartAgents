# -*- coding: utf-8 -*-
"""Etsy MCP 子 Agent — re-export from domains builder."""

from domains.etsy.builder import build_etsy_agent, build_etsy_mcp_sub_agent
from domains.etsy.registry import AGENT_NAME

__all__ = ["AGENT_NAME", "build_etsy_agent", "build_etsy_mcp_sub_agent"]
