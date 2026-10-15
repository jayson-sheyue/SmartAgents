"""Regression checks for transport classification; no external services."""
import json
import unittest
from types import SimpleNamespace

from domains.shared.mcp_guard import make_mcp_fail_fast_after_tool


class McpGuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guard = make_mcp_fail_fast_after_tool(mcp_url="https://example.com/mcp", label="Test")
        self.ctx = SimpleNamespace(state={})
        self.tool = SimpleNamespace(name="feishu_doc_search")

    async def test_successful_network_related_document_is_preserved(self):
        for response in (
            {"ok": True, "data": {"items": [{"title": "SSL connection timeout troubleshooting"}]}},
            {"content": [{"type": "text", "text": json.dumps({"ok": True, "data": {"title": "网络 503"}})}]},
        ):
            self.assertIsNone(await self.guard(self.tool, {}, self.ctx, response))
        self.assertFalse(self.ctx.state)

    async def test_cli_timeout_is_not_mcp_outage(self):
        response = {"ok": False, "error": {"code": "CLI_TIMEOUT", "message": "CLI timeout", "retryable": True}}
        self.assertIsNone(await self.guard(self.tool, {}, self.ctx, response))
        self.assertFalse(self.ctx.state)

    async def test_transport_failure_is_recognized_inside_mcp_content(self):
        response = {"content": [{"type": "text", "text": json.dumps({
            "ok": False, "error": {"code": "SESSION_ERROR", "message": "Session not found"},
        })}]}
        result = await self.guard(self.tool, {}, self.ctx, response)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "MCP_UNAVAILABLE")

    async def test_business_failure_with_network_words_is_preserved(self):
        response = {"ok": False, "error": {"code": "INVALID_ARGUMENT", "message": "搜索 SSL 网络文档的参数无效"}}
        self.assertIsNone(await self.guard(self.tool, {}, self.ctx, response))
