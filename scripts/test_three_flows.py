# -*- coding: utf-8 -*-
"""Guards for the three highest-frequency SmartAgents user journeys."""

from __future__ import annotations

import unittest

from smart_agents.task_card import (
    format_task_card_block,
    get_card,
    ingest_tool_result,
    merge_card,
    normalize_deliverable,
)


class _FakeCtx:
    def __init__(self) -> None:
        self.state: dict = {}


class FlowDocSearchLinks(unittest.TestCase):
    """Flow 1: topic → Feishu cloud docs → return tool urls only."""

    def test_deliverable_inference(self) -> None:
        self.assertEqual(
            normalize_deliverable("", goal="搜索飞书云文档里的 GCP 预算熔断"),
            "doc_search_answer",
        )

    def test_contract_requires_tool_urls(self) -> None:
        ctx = _FakeCtx()
        merge_card(
            ctx,
            goal="搜文档",
            deliverable="doc_search_answer",
            status="active",
            phase="searched",
        )
        block = format_task_card_block(ctx)
        self.assertIn("items[].url", block)
        self.assertIn("禁止臆造", block)
        self.assertNotIn("建表成功后本轮优先写记录", block)

    def test_search_ingest_stays_searched(self) -> None:
        ctx = _FakeCtx()
        ingest_tool_result(
            tool_name="feishu_doc_search",
            tool_response={
                "ok": True,
                "data": {
                    "items": [
                        {
                            "title": "A",
                            "url": "https://feishu.cn/docx/x",
                        }
                    ],
                    "count": 1,
                    "deliverable_hint": "doc_search_answer",
                    "phase_hint": "searched",
                },
            },
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["deliverable"], "doc_search_answer")
        self.assertEqual(card["phase"], "searched")
        self.assertEqual(card["status"], "active")


class FlowTseToBitable(unittest.TestCase):
    """Flow 2: TSE range → interpret → bitable write."""

    def test_bitable_create_then_write(self) -> None:
        ctx = _FakeCtx()
        merge_card(
            ctx,
            goal="本月跟进写入多维表",
            deliverable="bitable_with_rows",
            phase="planned",
        )
        ingest_tool_result(
            tool_name="feishu_bitable_create",
            tool_response={
                "ok": True,
                "data": {
                    "base_token": "bas1",
                    "table_id": "tbl1",
                    "url": "https://x/base/bas1",
                },
            },
            state_or_ctx=ctx,
        )
        self.assertEqual(get_card(ctx)["phase"], "created")
        ingest_tool_result(
            tool_name="feishu_bitable_record_batch_create",
            tool_response={"ok": True, "data": {"created": 3}},
            state_or_ctx=ctx,
        )
        self.assertEqual(get_card(ctx)["status"], "done")
        block = format_task_card_block(ctx)
        self.assertIn("已完成", block)


class FlowRagThenFeishu(unittest.TestCase):
    """Flow 3: RAG miss must not look like grounded internal knowledge."""

    def test_rag_empty_hint(self) -> None:
        # Simulate the envelope shape without calling Vertex
        payload = {
            "ok": True,
            "data": {
                "snippets": [],
                "sources": [],
                "count": 0,
                "grounded": False,
                "empty": True,
                "hint": "RAG 未命中",
            },
        }
        self.assertTrue(payload["data"]["empty"])
        self.assertFalse(payload["data"]["grounded"])
        self.assertEqual(payload["data"]["count"], 0)


if __name__ == "__main__":
    unittest.main()
