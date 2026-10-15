# -*- coding: utf-8 -*-
"""Feishu tool registry — manifest constants + lazy L1 implementations."""

from __future__ import annotations

from typing import Any, Callable

from domains.shared.manifest import DomainManifest

MANIFEST = DomainManifest.load("feishu")

AGENT_NAME = MANIFEST.agent_name
STANDALONE_NAME = MANIFEST.standalone_name
SKILL_IDS = MANIFEST.skills
MCP_TOOL_NAMES = MANIFEST.mcp_tools


def _load_tool_implementations() -> dict[str, Callable[..., dict[str, Any]]]:
    from domains.feishu.feishu_cli_tools import (
        tool_feishu_bitable_create,
        tool_feishu_bitable_enrich_tse_records,
        tool_feishu_bitable_field_list,
        tool_feishu_bitable_parse_url,
        tool_feishu_bitable_record_batch_create,
        tool_feishu_bitable_record_batch_update,
        tool_feishu_bitable_record_list,
        tool_feishu_bitable_record_upsert,
        tool_feishu_bitable_table_list,
        tool_feishu_bitable_write_tse_records,
        tool_feishu_calendar_agenda,
        tool_feishu_calendar_create,
        tool_feishu_calendar_freebusy,
        tool_feishu_cli_status,
        tool_feishu_contact_search_user,
        tool_feishu_doc_create_markdown,
        tool_feishu_doc_fetch,
        tool_feishu_doc_search,
        tool_feishu_im_chat_messages_list,
        tool_feishu_im_chat_search,
        tool_feishu_im_messages_search,
        tool_feishu_im_send_text,
        tool_feishu_sheet_read,
        tool_feishu_sheet_write_csv,
    )
    from domains.feishu.oauth_flow import (
        tool_feishu_oauth_complete,
        tool_feishu_oauth_start,
        tool_feishu_oauth_status,
    )
    from domains.feishu.scope_remediation import tool_feishu_app_scopes_remediate

    return {
        "feishu_cli_status": tool_feishu_cli_status,
        "feishu_oauth_status": tool_feishu_oauth_status,
        "feishu_oauth_start": tool_feishu_oauth_start,
        "feishu_oauth_complete": tool_feishu_oauth_complete,
        "feishu_app_scopes_remediate": tool_feishu_app_scopes_remediate,
        "feishu_calendar_agenda": tool_feishu_calendar_agenda,
        "feishu_calendar_create": tool_feishu_calendar_create,
        "feishu_calendar_freebusy": tool_feishu_calendar_freebusy,
        "feishu_contact_search_user": tool_feishu_contact_search_user,
        "feishu_im_chat_search": tool_feishu_im_chat_search,
        "feishu_im_send_text": tool_feishu_im_send_text,
        "feishu_im_chat_messages_list": tool_feishu_im_chat_messages_list,
        "feishu_im_messages_search": tool_feishu_im_messages_search,
        "feishu_doc_search": tool_feishu_doc_search,
        "feishu_doc_fetch": tool_feishu_doc_fetch,
        "feishu_doc_create_markdown": tool_feishu_doc_create_markdown,
        "feishu_sheet_read": tool_feishu_sheet_read,
        "feishu_sheet_write_csv": tool_feishu_sheet_write_csv,
        "feishu_bitable_create": tool_feishu_bitable_create,
        "feishu_bitable_enrich_tse_records": tool_feishu_bitable_enrich_tse_records,
        "feishu_bitable_write_tse_records": tool_feishu_bitable_write_tse_records,
        "feishu_bitable_field_list": tool_feishu_bitable_field_list,
        "feishu_bitable_table_list": tool_feishu_bitable_table_list,
        "feishu_bitable_parse_url": tool_feishu_bitable_parse_url,
        "feishu_bitable_record_batch_create": tool_feishu_bitable_record_batch_create,
        "feishu_bitable_record_batch_update": tool_feishu_bitable_record_batch_update,
        "feishu_bitable_record_list": tool_feishu_bitable_record_list,
        "feishu_bitable_record_upsert": tool_feishu_bitable_record_upsert,
    }


def __getattr__(name: str) -> Any:
    if name == "TOOL_IMPLEMENTATIONS":
        value = _load_tool_implementations()
        globals()["TOOL_IMPLEMENTATIONS"] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
