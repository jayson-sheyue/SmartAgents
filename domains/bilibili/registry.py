# -*- coding: utf-8 -*-
"""Bilibili tool registry.

Manifest constants are import-safe for Agent Engine / A2A.
L1 TOOL_IMPLEMENTATIONS load lazily when MCP servers need them.
"""

from __future__ import annotations

from typing import Any, Callable

from domains.shared.manifest import DomainManifest

MANIFEST = DomainManifest.load("bilibili")

AGENT_NAME = MANIFEST.agent_name
STANDALONE_NAME = MANIFEST.standalone_name
SKILL_IDS = MANIFEST.skills
MCP_TOOL_NAMES = MANIFEST.mcp_tools


def _load_tool_implementations() -> dict[str, Callable[..., dict[str, Any]]]:
    from domains.bilibili.bilibili_tools import (
        tool_export_hot_videos_excel,
        tool_fetch_hot_videos,
    )

    return {
        "fetch_hot_videos": tool_fetch_hot_videos,
        "export_hot_videos_excel": tool_export_hot_videos_excel,
    }


def __getattr__(name: str) -> Any:
    if name == "TOOL_IMPLEMENTATIONS":
        value = _load_tool_implementations()
        globals()["TOOL_IMPLEMENTATIONS"] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
