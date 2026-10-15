import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from domains.shared.optional_mcp import OptionalMcpToolset


class OptionalMcpTests(unittest.IsolatedAsyncioTestCase):
    def make_toolset(self):
        return OptionalMcpToolset(connection_params=StreamableHTTPConnectionParams(url="https://example.com/mcp", timeout=60),
                                  discovery_timeout=0.01, retry_delay=60)

    async def test_hanging_discovery_does_not_block_and_is_not_repeated(self):
        toolset = self.make_toolset()
        async def slow(_context):
            await asyncio.sleep(10)
        with patch("google.adk.tools.mcp_tool.McpToolset.get_tools", new=AsyncMock(side_effect=slow)) as discover:
            self.assertEqual(await toolset.get_tools(), [])
            self.assertEqual(await toolset.get_tools(), [])
            self.assertEqual(discover.await_count, 1)

    async def test_success_keeps_original_tools_and_call_timeout(self):
        toolset = self.make_toolset()
        tools = [object()]
        with patch("google.adk.tools.mcp_tool.McpToolset.get_tools", new=AsyncMock(return_value=tools)):
            self.assertIs(await toolset.get_tools(), tools)
        self.assertEqual(toolset._connection_params.timeout, 60)

    async def test_permission_failure_is_temporarily_skipped(self):
        toolset = self.make_toolset()
        with patch("google.adk.tools.mcp_tool.McpToolset.get_tools", new=AsyncMock(side_effect=PermissionError("403"))) as discover:
            self.assertEqual(await toolset.get_tools(), [])
            self.assertEqual(await toolset.get_tools(), [])
            self.assertEqual(discover.await_count, 1)
