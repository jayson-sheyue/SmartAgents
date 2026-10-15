# -*- coding: utf-8 -*-
"""Resolve runtime mode — MCP only."""

from __future__ import annotations

import os
from typing import Literal

RuntimeMode = Literal["mcp"]


def resolve_runtime_mode(explicit: str | None = None) -> RuntimeMode:
    """All agents use MCP tool transport. Legacy inprocess/rest values map to mcp."""
    return "mcp"


def normalize_mcp_url(url: str) -> str:
    u = url.rstrip("/")
    return u if u.endswith("/mcp") else f"{u}/mcp"
