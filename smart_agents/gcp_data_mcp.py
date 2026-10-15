# -*- coding: utf-8 -*-
"""Google 托管 Remote MCP：Knowledge Catalog + Firestore（挂在小智调度员）。

Lab-00：kc_* / fs_* 为 P2/P1 探索兜底；业务正确性走 tse_tools（API 优先）。
"""

from __future__ import annotations

import os
from typing import Optional

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from domains.shared.optional_mcp import OptionalMcpToolset

from smart_agents.tse_store import (
    refresh_adc_token,
    tse_firestore_database,
    tse_firestore_project_id,
)
from smart_agents.tse_tools import (
    build_tse_tools,
    dispatcher_instruction_block,
    ask_tse_workspace,
    clear_tse_session_api_key,
    generate_tse_global_report,
    get_tse_customer,
    get_tse_customer_daily_reports,
    get_tse_customer_sales_stats,
    get_tse_overview,
    get_tse_sales_customer_reports,
    get_tse_share,
    get_tse_user_workspace,
    list_tse_api_keys,
    list_tse_customers,
    list_tse_items_for_user,
    list_tse_pending_shares,
    list_tse_shares,
    list_tse_tool_catalog,
    list_tse_users,
    lookup_tse_schema,
    map_tse_daily_reports_to_bitable,
    query_tse_daily_reports_by_date,
    render_tse_customer_sales_chart,
    search_tse_daily_reports,
    set_tse_session_api_key,
    tse_session_api_key_status,
)

_DEFAULT_KC_URL = "https://dataplex.googleapis.com/mcp"
_DEFAULT_FIRESTORE_URL = "https://firestore.googleapis.com/mcp"
_CLOUD_PLATFORM_SCOPE = ("https://www.googleapis.com/auth/cloud-platform",)

KC_MCP_TOOL_NAMES = (
    "search_entries",
    "lookup_context",
    "lookup_entry",
)

# Firestore MCP：仅只读（小智不得通过 fs_* 增删改文档）
FIRESTORE_MCP_READ_TOOL_NAMES = (
    "get_document",
    "list_documents",
    "list_collections",
    "list_databases",
    "get_database",
)

# 已禁用：add_document / update_document / delete_document
FIRESTORE_MCP_TOOL_NAMES = FIRESTORE_MCP_READ_TOOL_NAMES


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def kc_mcp_enabled() -> bool:
    if _env_bool("GCP_DATA_MCP_ENABLED", False):
        return True
    return _env_bool("KC_MCP_ENABLED", False)


def firestore_mcp_enabled() -> bool:
    if _env_bool("GCP_DATA_MCP_ENABLED", False):
        return True
    return _env_bool("FIRESTORE_MCP_ENABLED", False)


def data_mcp_enabled() -> bool:
    return kc_mcp_enabled() or firestore_mcp_enabled()


def tse_scenario_tools_enabled() -> bool:
    """确定性 TSE 场景工具：Firestore MCP 或已配置 TSE API 根地址即可启用（Lab-00）。"""
    if firestore_mcp_enabled():
        return True
    from smart_agents.tse_api_client import tse_api_base_url

    return bool(tse_api_base_url())


def kc_mcp_url() -> str:
    return (os.getenv("KC_MCP_URL") or _DEFAULT_KC_URL).strip()


def firestore_mcp_url() -> str:
    return (os.getenv("FIRESTORE_MCP_URL") or _DEFAULT_FIRESTORE_URL).strip()


def _gcp_mcp_auth_header_provider(_ctx: ReadonlyContext) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {refresh_adc_token()}"}
    project = (os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    if project:
        headers["X-Goog-User-Project"] = project
    return headers


def _remote_mcp_toolset(
    *,
    url: str,
    tool_filter: tuple[str, ...],
    tool_name_prefix: str,
) -> McpToolset:
    return OptionalMcpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=url,
            headers={
                "Accept": "text/event-stream, application/json",
                "Content-Type": "application/json",
            },
            timeout=60.0,
            sse_read_timeout=300.0,
        ),
        tool_filter=list(tool_filter),
        tool_name_prefix=tool_name_prefix,
        header_provider=_gcp_mcp_auth_header_provider,
    )


def build_kc_mcp_toolset() -> Optional[McpToolset]:
    if not kc_mcp_enabled():
        return None
    return _remote_mcp_toolset(
        url=kc_mcp_url(),
        tool_filter=KC_MCP_TOOL_NAMES,
        tool_name_prefix="kc_",
    )


def build_firestore_mcp_toolset() -> Optional[McpToolset]:
    if not firestore_mcp_enabled():
        return None
    return _remote_mcp_toolset(
        url=firestore_mcp_url(),
        tool_filter=FIRESTORE_MCP_TOOL_NAMES,
        tool_name_prefix="fs_",
    )


def build_data_mcp_toolsets() -> list[McpToolset]:
    toolsets: list[McpToolset] = []
    kc = build_kc_mcp_toolset()
    if kc is not None:
        toolsets.append(kc)
    fs = build_firestore_mcp_toolset()
    if fs is not None:
        toolsets.append(fs)
    return toolsets


__all__ = [
    "ask_tse_workspace",
    "build_data_mcp_toolsets",
    "build_kc_mcp_toolset",
    "build_firestore_mcp_toolset",
    "build_tse_tools",
    "clear_tse_session_api_key",
    "data_mcp_enabled",
    "dispatcher_instruction_block",
    "firestore_mcp_enabled",
    "firestore_mcp_url",
    "generate_tse_global_report",
    "get_tse_customer",
    "get_tse_customer_daily_reports",
    "get_tse_customer_sales_stats",
    "get_tse_overview",
    "get_tse_sales_customer_reports",
    "get_tse_share",
    "get_tse_user_workspace",
    "kc_mcp_enabled",
    "kc_mcp_url",
    "list_tse_api_keys",
    "list_tse_customers",
    "list_tse_items_for_user",
    "list_tse_pending_shares",
    "list_tse_shares",
    "list_tse_tool_catalog",
    "list_tse_users",
    "lookup_tse_schema",
    "map_tse_daily_reports_to_bitable",
    "query_tse_daily_reports_by_date",
    "render_tse_customer_sales_chart",
    "search_tse_daily_reports",
    "set_tse_session_api_key",
    "tse_firestore_database",
    "tse_firestore_project_id",
    "tse_scenario_tools_enabled",
    "tse_session_api_key_status",
]
