"""Bound discovery of optional MCP tools without changing tool call timeouts."""
from __future__ import annotations

import asyncio
import logging
import time

from google.adk.tools.mcp_tool import McpToolset

logger = logging.getLogger(__name__)


class OptionalMcpToolset(McpToolset):
    def __init__(self, *, discovery_timeout: float = 8, retry_delay: float = 60, **kwargs):
        super().__init__(**kwargs)
        self._discovery_timeout = discovery_timeout
        self._retry_delay = retry_delay
        self._retry_after = 0.0

    async def get_tools(self, readonly_context=None):
        if time.monotonic() < self._retry_after:
            return []
        started = time.monotonic()
        try:
            tools = await asyncio.wait_for(
                super().get_tools(readonly_context), timeout=self._discovery_timeout
            )
            if tools:
                return tools
        except Exception as exc:
            logger.warning("Optional MCP discovery unavailable url=%s elapsed=%.3fs error=%s",
                           self._connection_params.url, time.monotonic() - started, type(exc).__name__)
        self._retry_after = time.monotonic() + self._retry_delay
        return []
