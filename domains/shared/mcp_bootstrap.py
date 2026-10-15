# -*- coding: utf-8 -*-
"""Register domain tools on a FastMCP instance from registry."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP


def register_tools(mcp: FastMCP, implementations: dict[str, Callable[..., Any]]) -> None:
    """Bind L1 implementations to MCP tool names (single registration path)."""
    for name, impl in implementations.items():
        mcp.tool(name=name)(impl)
