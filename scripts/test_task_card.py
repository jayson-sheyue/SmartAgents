# -*- coding: utf-8 -*-
"""Unit tests for session Task Card (no live ADK / Feishu)."""

from __future__ import annotations

import unittest
import asyncio
import json
from types import SimpleNamespace

from smart_agents.task_card import (
    STATE_KEY,
    format_task_card_block,
    get_card,
    ingest_tool_result,
    is_active,
    merge_card,
    normalize_deliverable,
    unwrap_tool_envelope,
    task_card_upsert,
    task_card_complete,
    make_task_card_after_tool,
    task_card_before_tool,
)


class _FakeCtx:
    def __init__(self) -> None:
        self.state: dict = {}


class TaskCardTests(unittest.TestCase):
    def test_merge_and_format_active(self) -> None:
        ctx = _FakeCtx()
        merge_card(
            ctx,
            goal="写10条新闻到多维表格",
            deliverable="bitable_with_rows",
            phase="planned",
            base_token="basXXX",
            table_id="tblYYY",
            url="https://example/base/basXXX",
            next_action="feishu_bitable_record_batch_create",
        )
        card = get_card(ctx)
        self.assertTrue(is_active(card))
        self.assertEqual(card["table_id"], "tblYYY")
        self.assertEqual(card["phase"], "planned")
        block = format_task_card_block(ctx)
        self.assertIn("写10条新闻", block)
        self.assertIn("tblYYY", block)
        self.assertIn("完成契约", block)
        self.assertIn("bitable", block.lower())

    def test_ingest_create_and_write(self) -> None:
        ctx = _FakeCtx()
        ingest_tool_result(
            tool_name="feishu_bitable_create",
            tool_response={
                "ok": True,
                "data": {
                    "base_token": "basA",
                    "table_id": "tblB",
                    "url": "https://x/base/basA",
                    "table_name": "今日新闻",
                },
            },
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["status"], "active")
        self.assertEqual(card["phase"], "created")
        self.assertEqual(card["table_id"], "tblB")
        self.assertEqual(card["deliverable"], "bitable_with_rows")
        self.assertIn("batch_create", card["next_action"])

        ingest_tool_result(
            tool_name="feishu_bitable_record_batch_create",
            tool_response={"ok": True, "data": {"created": 10}},
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["status"], "done")
        self.assertEqual(card["phase"], "done")
        self.assertFalse(is_active(card))

    def test_create_without_write_stays_active(self) -> None:
        ctx = _FakeCtx()
        ingest_tool_result(
            tool_name="feishu_bitable_create",
            tool_response={
                "ok": True,
                "data": {
                    "base_token": "basA",
                    "table_id": "tblB",
                    "url": "https://x/base/basA",
                },
            },
            state_or_ctx=ctx,
        )
        self.assertEqual(get_card(ctx)["status"], "active")
        self.assertNotEqual(get_card(ctx)["phase"], "done")

    def test_doc_search_phase_not_bitable(self) -> None:
        ctx = _FakeCtx()
        ingest_tool_result(
            tool_name="feishu_doc_search",
            tool_response={
                "ok": True,
                "data": {
                    "items": [{"title": "GCP budget"}],
                    "deliverable_hint": "doc_search_answer",
                    "phase_hint": "searched",
                    "next_action": "report_search_results_to_user",
                },
            },
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["deliverable"], "doc_search_answer")
        self.assertEqual(card["phase"], "searched")
        self.assertEqual(card["status"], "active")
        block = format_task_card_block(ctx)
        self.assertIn("文档搜索", block)
        self.assertNotIn("建表成功后本轮优先写记录", block)

    def test_oauth_start_blocks(self) -> None:
        ctx = _FakeCtx()
        merge_card(
            ctx,
            goal="写表",
            deliverable="bitable_with_rows",
            status="active",
            phase="planned",
        )
        ingest_tool_result(
            tool_name="feishu_oauth_start",
            tool_response={
                "ok": True,
                "data": {
                    "verification_url": "https://open.feishu.cn/oauth",
                },
            },
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["status"], "blocked")
        self.assertEqual(card["phase"], "blocked")
        self.assertEqual(card["blocked_reason"], "waiting_user_oauth")

    def test_need_tse_api_key_blocks(self) -> None:
        ctx = _FakeCtx()
        merge_card(
            ctx,
            goal="分析商机写表",
            deliverable="bitable_with_rows",
            status="active",
            phase="planned",
        )
        ingest_tool_result(
            tool_name="ask_tse_workspace",
            tool_response={
                "ok": False,
                "error": {"code": "NEED_TSE_API_KEY", "message": "no key"},
                "user_prompt": "请在私聊发送 Key",
                "wait_user": True,
                "blocked_reason": "waiting_tse_api_key",
            },
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["status"], "blocked")
        self.assertEqual(card["blocked_reason"], "waiting_tse_api_key")
        block = format_task_card_block(ctx)
        self.assertIn("等待 TSE API Key", block)

    def test_calendar_create_done(self) -> None:
        ctx = _FakeCtx()
        ingest_tool_result(
            tool_name="feishu_calendar_create",
            tool_response={
                "ok": True,
                "data": {"event_id": "evt1", "summary": "sync"},
            },
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["deliverable"], "calendar_event")
        self.assertEqual(card["status"], "done")
        self.assertEqual(card["phase"], "done")

    def test_im_send_done(self) -> None:
        ctx = _FakeCtx()
        ingest_tool_result(
            tool_name="feishu_im_send_text",
            tool_response={"ok": True, "data": {"message_id": "om_1"}},
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["deliverable"], "im_message_sent")
        self.assertEqual(card["status"], "done")

    def test_sheet_write_done(self) -> None:
        ctx = _FakeCtx()
        ingest_tool_result(
            tool_name="feishu_sheet_write_csv",
            tool_response={"ok": True, "data": {"updated": 3}},
            state_or_ctx=ctx,
        )
        card = get_card(ctx)
        self.assertEqual(card["deliverable"], "sheet_updated")
        self.assertEqual(card["status"], "done")

    def test_normalize_deliverable(self) -> None:
        self.assertEqual(
            normalize_deliverable("bitable"),
            "bitable_with_rows",
        )
        self.assertEqual(
            normalize_deliverable("", goal="搜索飞书云文档预算"),
            "doc_search_answer",
        )

    def test_unwrap_mcp_content(self) -> None:
        wrapped = {
            "content": [
                {
                    "type": "text",
                    "text": '{"ok": true, "data": {"base_token": "basZ", "table_id": "tblZ"}}',
                }
            ]
        }
        env = unwrap_tool_envelope(wrapped)
        assert env is not None
        self.assertTrue(env["ok"])
        ctx = _FakeCtx()
        ingest_tool_result(
            tool_name="feishu_bitable_create",
            tool_response=wrapped,
            state_or_ctx=ctx,
        )
        self.assertEqual(get_card(ctx)["base_token"], "basZ")

    def test_table_list_recovers_id(self) -> None:
        ctx = _FakeCtx()
        merge_card(ctx, goal="write", base_token="bas1", status="active")
        ingest_tool_result(
            tool_name="feishu_bitable_table_list",
            tool_response={
                "ok": True,
                "data": {
                    "base_token": "bas1",
                    "tables": [
                        {"table_id": "tblRecovered", "name": "数据表"},
                    ],
                },
            },
            state_or_ctx=ctx,
        )
        self.assertEqual(get_card(ctx)["table_id"], "tblRecovered")

    def test_extract_tables_helper(self) -> None:
        from domains.feishu.feishu_cli_tools import _extract_tables_from_list_payload

        tables = _extract_tables_from_list_payload(
            {"tables": [{"table_id": "tbl1", "name": "A"}, {"id": "tbl2", "name": "B"}]}
        )
        self.assertEqual(len(tables), 2)
        self.assertEqual(tables[0]["table_id"], "tbl1")

    def test_tool_ok_injects_hints(self) -> None:
        from domains.feishu.feishu_cli_tools import _tool_ok

        env = _tool_ok("feishu_doc_search", {"items": []})
        self.assertEqual(env["data"]["deliverable_hint"], "doc_search_answer")
        self.assertEqual(env["data"]["phase_hint"], "searched")

    def test_normalize_doc_search_res_units(self) -> None:
        from domains.feishu.feishu_cli_tools import _normalize_doc_search_items

        items, meta = _normalize_doc_search_items(
            {
                "total": 1,
                "has_more": False,
                "res_units": [
                    {
                        "title_highlighted": "<h>GCP</h> 预算熔断",
                        "summary_highlighted": "说明",
                        "entity_type": "DOC",
                        "result_meta": {
                            "url": "https://feishu.cn/docx/doxABC",
                            "token": "doxABC",
                        },
                    }
                ],
            }
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "GCP 预算熔断")
        self.assertEqual(items[0]["url"], "https://feishu.cn/docx/doxABC")
        self.assertEqual(items[0]["doc_token"], "doxABC")
        self.assertTrue(items[0]["url_from_tool"])
        self.assertEqual(meta["total"], 1)

    def test_normalize_doc_search_empty(self) -> None:
        from domains.feishu.feishu_cli_tools import _normalize_doc_search_items

        items, _meta = _normalize_doc_search_items({"res_units": [], "total": 0})
        self.assertEqual(items, [])


class CreateMissingTableIdNote(unittest.TestCase):
    def test_create_coords_dig(self) -> None:
        from domains.feishu.feishu_cli_tools import _extract_bitable_create_coords

        coords = _extract_bitable_create_coords(
            {"app_token": "basX", "default_table_id": "tblY", "url": "https://u"}
        )
        self.assertEqual(coords["base_token"], "basX")
        self.assertEqual(coords["table_id"], "tblY")


class TaskCardRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.ctx = _FakeCtx()
        self.rows = [{"客户": "A"}, {"客户": "B"}, {"客户": "C"}]
        task_card_upsert(self.ctx, goal="写入三个客户", deliverable="bitable_with_rows",
                         pending_records_json=json.dumps({"create_records": self.rows}))

    def test_handoff_update_preserves_payload_and_block(self):
        task_card_upsert(self.ctx, status="blocked", blocked_reason="waiting_user_oauth")
        task_card_upsert(self.ctx, next_action="oauth_complete")
        card = get_card(self.ctx)
        self.assertEqual(card["status"], "blocked")
        self.assertEqual(card["blocked_reason"], "waiting_user_oauth")
        self.assertEqual(json.loads(card["pending_records_json"])["create_records"], self.rows)

    def test_explicit_resume_clears_block(self):
        task_card_upsert(self.ctx, status="blocked", blocked_reason="waiting_user_oauth")
        task_card_upsert(self.ctx, status="active", next_action="write")
        self.assertEqual(get_card(self.ctx)["phase"], "in_progress")
        self.assertEqual(get_card(self.ctx)["blocked_reason"], "")

    def test_large_payload_survives_handoff(self):
        rows = [{"text": "x" * 50000}]
        result = task_card_upsert(self.ctx, pending_records_json=json.dumps(rows))
        self.assertTrue(result["ok"])
        self.assertEqual(json.loads(get_card(self.ctx)["pending_records_json"]), rows)

    def test_invalid_payload_does_not_replace_original(self):
        original = get_card(self.ctx)
        result = task_card_upsert(self.ctx, pending_records_json='[{"broken":')
        self.assertFalse(result["ok"])
        self.assertEqual(get_card(self.ctx), original)

    def test_partial_batches_finish_only_after_last_batch(self):
        for i, row in enumerate(self.rows):
            ingest_tool_result(tool_name="feishu_bitable_record_batch_create",
                               args={"records_json": json.dumps([row])},
                               tool_response={"ok": True, "data": {"created": 1}}, state_or_ctx=self.ctx)
            card = get_card(self.ctx)
            self.assertEqual(card["written_record_count"], i + 1)
            self.assertEqual(card["expected_record_count"], 3)
            self.assertEqual(card["status"], "done" if i == 2 else "active")
            if i < 2:
                self.assertEqual(json.loads(card["pending_records_json"])["create_records"], self.rows[i + 1:])
        self.assertTrue(task_card_complete(self.ctx)["ok"])

    def test_unknown_partial_result_pauses_without_losing_rows(self):
        ingest_tool_result(tool_name="feishu_bitable_record_batch_create",
                           tool_response={"ok": True, "data": {"created": 1}}, state_or_ctx=self.ctx)
        card = get_card(self.ctx)
        self.assertEqual(card["status"], "blocked")
        self.assertEqual(card["blocked_reason"], "write_result_uncertain")
        self.assertEqual(json.loads(card["pending_records_json"])["create_records"], self.rows)

    def test_blocked_or_pending_task_cannot_be_completed(self):
        self.assertFalse(task_card_complete(self.ctx)["ok"])
        task_card_upsert(self.ctx, status="blocked", blocked_reason="waiting_user_oauth")
        self.assertFalse(task_card_complete(self.ctx)["ok"])
        self.assertEqual(get_card(self.ctx)["status"], "blocked")

    def test_upsert_cannot_bypass_completion(self):
        self.assertFalse(task_card_upsert(self.ctx, status="done")["ok"])
        self.assertFalse(task_card_upsert(self.ctx, phase="done")["ok"])

    def test_calendar_requires_corresponding_success(self):
        ctx = _FakeCtx()
        task_card_upsert(ctx, goal="约会", deliverable="calendar_event")
        ingest_tool_result(tool_name="feishu_sheet_read", tool_response={"ok": True, "data": {}}, state_or_ctx=ctx)
        self.assertNotEqual(get_card(ctx)["status"], "done")
        self.assertFalse(task_card_complete(ctx)["ok"])

    def test_write_timeout_preserves_rows_and_blocks_retry(self):
        ingest_tool_result(tool_name="feishu_bitable_record_batch_create",
                           tool_response={"ok": False, "error": {"code": "CLI_TIMEOUT"}}, state_or_ctx=self.ctx)
        self.assertEqual(get_card(self.ctx)["blocked_reason"], "write_result_uncertain")
        self.assertEqual(json.loads(get_card(self.ctx)["pending_records_json"])["create_records"], self.rows)

    def test_blocked_write_is_intercepted_but_read_and_oauth_are_allowed(self):
        task_card_upsert(self.ctx, status="blocked", blocked_reason="write_result_uncertain")
        response = task_card_before_tool(SimpleNamespace(name="feishu_bitable_record_batch_create"), {}, self.ctx)
        self.assertFalse(response["ok"])
        ingest_tool_result(tool_name="feishu_bitable_record_batch_create", tool_response=response, state_or_ctx=self.ctx)
        self.assertEqual(get_card(self.ctx)["status"], "blocked")
        for name in ("feishu_bitable_record_list", "feishu_oauth_complete"):
            self.assertIsNone(task_card_before_tool(SimpleNamespace(name=name), {}, self.ctx))

    def test_field_read_does_not_unblock_uncertain_write(self):
        task_card_upsert(self.ctx, status="blocked", blocked_reason="write_result_uncertain")
        ingest_tool_result(tool_name="feishu_bitable_field_list",
                           tool_response={"ok": True, "data": {"base_token": "bas1", "table_id": "tbl1"}}, state_or_ctx=self.ctx)
        self.assertEqual(get_card(self.ctx)["status"], "blocked")

    def test_callback_snapshot_and_duplicate_event(self):
        self.ctx.function_call_id = "batch-1"
        callback = make_task_card_after_tool()
        tool = SimpleNamespace(name="feishu_bitable_record_batch_create")
        args = {"records_json": json.dumps([self.rows[0]])}
        response = {"ok": True, "data": {"created": 1}}
        first = asyncio.run(callback(tool, args, self.ctx, response))
        second = asyncio.run(callback(tool, args, self.ctx, response))
        self.assertEqual(first["meta"]["task_card"]["pending_record_count"], 2)
        self.assertEqual(second["meta"]["task_card"]["written_record_count"], 1)
        self.assertNotIn("pending_records_json", first["meta"]["task_card"])


if __name__ == "__main__":
    unittest.main()
