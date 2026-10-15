# -*- coding: utf-8 -*-
"""TSE 确定性工具集（对齐 KC-checklist.md 常见场景）。"""

from __future__ import annotations

import json
import random
import re
from typing import Any, Callable, Optional
from urllib.parse import quote

from smart_agents.chart_labels import to_chart_label
from smart_agents.tse_api_client import (
    call_tse_external,
    clear_session_api_key,
    mask_api_key,
    need_tse_api_key_error,
    set_session_api_key,
    tse_api_base_url,
    tse_api_ready_for_scoped_reads,
    tse_api_status,
)
from smart_agents.tse_identity import (
    assert_item_access,
    cross_user_forbidden,
    enforce_data_scope,
    resolve_tse_principal,
    row_visible_to,
)
from smart_agents.tse_store import (
    customer_item_type_filter,
    field_string,
    field_string_array,
    filter_reports_by_date,
    get_document,
    is_customer_row,
    list_collection_rows,
    mask_secret,
    meta_block,
    mcp_call,
    normalize_report_date,
    parent_path,
    parse_daily_reports,
    parse_map_value,
    row_item_type,
    strict_customer_item_type,
    truncate_text,
)

# path: api_only | hybrid | firestore | session | local — Lab-00 标注
TSE_TOOL_CATALOG: list[dict[str, str]] = [
    {"intent": "不确定用哪个工具 / 字段什么意思", "tool": "list_tse_tool_catalog", "path": "local", "notes": "先查目录"},
    {"intent": "术语、schema、日报在哪", "tool": "lookup_tse_schema", "path": "local", "notes": "内嵌 Glossary；KC 可选"},
    {"intent": "TSE 总览（用户数/客户数/销售分布）", "tool": "get_tse_overview", "path": "firestore", "notes": "跨租户；API 无对等"},
    {"intent": "有多少 TSE 用户", "tool": "list_tse_users", "path": "firestore", "notes": "tse_workspaces"},
    {"intent": "某用户的 Prompt / UI 配置", "tool": "get_tse_user_workspace", "path": "hybrid", "notes": "Key 主体走 API /settings"},
    {"intent": "某用户可见的客户/知识（侧边栏）", "tool": "list_tse_items_for_user", "path": "hybrid", "notes": "Key 主体走 API /customers"},
    {"intent": "客户名单（可按销售/owner 过滤）", "tool": "list_tse_customers", "path": "hybrid", "notes": "有 Key 优先 API"},
    {"intent": "单客户详情（背景/元数据）", "tool": "get_tse_customer", "path": "hybrid", "notes": "有 Key 优先 API"},
    {"intent": "单客户全部/部分日报", "tool": "get_tse_customer_daily_reports", "path": "hybrid", "notes": "有 Key 优先 API"},
    {"intent": "按时间段查日报（跨客户/按销售）", "tool": "query_tse_daily_reports_by_date", "path": "firestore", "notes": "API 无日期查询"},
    {
        "intent": "是否提到/使用某产品（关键词证据）",
        "tool": "search_tse_daily_reports",
        "path": "firestore",
        "notes": "关键词+snippet；禁止抽样后猜",
    },
    {
        "intent": "绑定本会话 TSE API Key（私聊提供）",
        "tool": "set_tse_session_api_key",
        "path": "api_only",
        "notes": "写入 Session；禁止回显/写入 Memory",
    },
    {
        "intent": "查看/清除本会话 TSE API Key",
        "tool": "tse_session_api_key_status / clear_tse_session_api_key",
        "path": "session",
        "notes": "",
    },
    {
        "intent": "开放语义问答（全量上下文+信源）",
        "tool": "ask_tse_workspace",
        "path": "api_only",
        "notes": "TSE /chat；需会话 Key 或 env 回落",
    },
    {
        "intent": "生成全局工作大盘/总览汇报",
        "tool": "generate_tse_global_report",
        "path": "api_only",
        "notes": "TSE /global_report；仅总览，非定向问答",
    },
    {
        "intent": "按多维表格字段映射 TSE 日报（先 field_list）",
        "tool": "map_tse_daily_reports_to_bitable",
        "path": "hybrid",
        "notes": "输出 create_records",
    },
    {
        "intent": "某销售的客户 + 随机日报",
        "tool": "get_tse_sales_customer_reports",
        "path": "firestore",
        "notes": "仅名单浏览；禁止用于产品/关键词判断",
    },
    {"intent": "客户数量统计 / owner×销售分布", "tool": "get_tse_customer_sales_stats", "path": "firestore", "notes": ""},
    {"intent": "客户分布堆叠图", "tool": "render_tse_customer_sales_chart", "path": "firestore", "notes": "需 Code Execution"},
    {"intent": "待我审批的分享", "tool": "list_tse_pending_shares", "path": "firestore", "notes": "API 未暴露 shares"},
    {"intent": "我发起的分享/审批记录", "tool": "list_tse_shares", "path": "firestore", "notes": "API 未暴露 shares"},
    {"intent": "单条分享详情", "tool": "get_tse_share", "path": "firestore", "notes": "API 未暴露 shares"},
    {"intent": "某用户的 API Key 列表", "tool": "list_tse_api_keys", "path": "hybrid", "notes": "Key 脱敏；列表≠会话绑定"},
]

# 常见产品别名：查询词会扩展为 OR 匹配（大小写不敏感）
_KEYWORD_ALIASES: dict[str, tuple[str, ...]] = {
    "bq": ("bigquery", "bq", "大查询"),
    "bigquery": ("bigquery", "bq", "大查询"),
    "大查询": ("bigquery", "bq", "大查询"),
    "gke": ("gke", "google kubernetes engine", "kubernetes engine"),
    "gcs": ("gcs", "cloud storage", "google cloud storage"),
    "vertex": ("vertex ai", "vertex", "gemini"),
}

_TSE_SCHEMA_GUIDE = """
【TSE 术语】用户=tse_workspaces；客户/知识=global_customers；日报=daily_reports[] 内嵌字段；
shares=协作审批；api_keys=外部鉴权（敏感）。v1 customers 子集合已废弃。
【Lab-00 优先级】业务：TSE API + 确定性工具 > Firestore MCP 兜底 > KC（可选元数据）。
禁止用裸 fs_*/kc_* 回答客户/日报业务问题；禁止把 BigQuery/KC 当业务真相源。
【原则】先 list_tse_tool_catalog / lookup_tse_schema，再调场景工具；禁止反问「数据存在哪」。
"""


def list_tse_tool_catalog() -> dict[str, Any]:
    """返回 TSE 常见场景 → 确定性工具对照表（对齐 Lab-00 / KC-checklist）。"""
    return {
        "ok": True,
        **meta_block(),
        "priority": "API/工具 > Firestore MCP > KC",
        "catalog": TSE_TOOL_CATALOG,
        "schema_guide_summary": _TSE_SCHEMA_GUIDE.strip(),
        "docs": "docs/tse_data_access.md",
    }


def lookup_tse_schema(topic: str = "") -> dict[str, Any]:
    """返回 TSE 术语与集合说明（内嵌 Glossary；KC 仅可选补充）。"""
    topic_key = (topic or "").strip().lower()
    hints: dict[str, str] = {
        "user": "TSE 用户=tse_workspaces；list_tse_users / get_tse_user_workspace",
        "customer": "TSE 客户=global_customers；list_tse_customers（有 Key 优先 API）",
        "knowledge": "已下线：旧 item_type=knowledge 不再读取；技术文档用 search_tse_knowledge / rag_search",
        "日报": "daily_reports[]；按时间段用 query_tse_daily_reports_by_date 或 get_tse_customer_daily_reports",
        "daily_reports": "fields: date, raw_draft, ai_generated_content；日期建议 YYYY-MM-DD",
        "时间段": "query_tse_daily_reports_by_date(date_from, date_to, sales_name?=…)",
        "关键词": "是否提到/使用某产品 → search_tse_daily_reports(keyword, sales_name?=…)",
        "语义": "开放语义问答 → ask_tse_workspace；关键词证据 → search_tse_daily_reports",
        "大盘": "全局工作大盘总览 → generate_tse_global_report(start_date, end_date)；非定向问答",
        "分享": "shares（仅 Firestore 工具）；list_tse_pending_shares / list_tse_shares",
        "prompt": "get_tse_user_workspace（Key 主体可走 API /settings）",
        "api_key": "list_tse_api_keys（脱敏；Key 主体可走 API）",
        "sales": "sales_name 过滤；list_tse_customers(sales_name=...)",
        "路径": "P0 API+工具 / P1 Firestore MCP / P2 KC 可选 / P3 BigQuery 仅审计",
    }
    return {
        "ok": True,
        **meta_block(),
        "topic": topic_key or "(all)",
        "focused_hint": hints.get(topic_key, ""),
        "kc_query_hint": (
            "可选：KC 搜「TSE Smart Workspace」「global_customers」（元数据，非业务查询）"
            if topic_key in {"日报", "daily_reports", "report", "路径", "kc"}
            else ""
        ),
        "schema_guide": _TSE_SCHEMA_GUIDE.strip(),
        "tool_catalog": "list_tse_tool_catalog",
        "priority": "API/工具 > Firestore MCP > KC",
    }


def _customer_row_from_api_doc(doc: dict[str, Any]) -> dict[str, Any]:
    """把 External API 客户文档压成 list 行形状。"""
    viewers = doc.get("viewers") or []
    if not isinstance(viewers, list):
        viewers = []
    item_type = str(doc.get("item_type") or "customer").strip() or "customer"
    return {
        "id": str(doc.get("id") or "").strip(),
        "name": str(doc.get("name") or "").strip(),
        "owner": str(doc.get("owner") or "").strip(),
        "sales_name": str(doc.get("sales_name") or "").strip(),
        "item_type": item_type,
        "viewers": [str(v).strip().lower() for v in viewers if str(v).strip()],
        "created_at": str(doc.get("created_at") or "").strip(),
    }


def _api_list_customers_payload(
    tool_context: Any = None,
) -> tuple[Optional[list[dict[str, Any]]], Optional[dict[str, Any]]]:
    """成功返回 (rows, None)；失败返回 (None, error_dict 或 None 表示未就绪)。"""
    if not tse_api_ready_for_scoped_reads(tool_context):
        return None, None
    result = call_tse_external(
        "GET",
        "/api/external/v1/customers",
        tool_context=tool_context,
        timeout=120,
    )
    if not result.get("ok"):
        return None, result
    data = result.get("data")
    if not isinstance(data, list):
        return None, {
            "ok": False,
            "error": {
                "code": "TSE_API_UNEXPECTED_SHAPE",
                "message": "GET /customers 未返回 list",
            },
        }
    rows = [_customer_row_from_api_doc(d) for d in data if isinstance(d, dict)]
    return rows, None


def _list_global_items(
    *,
    knowledge_only: bool,
    include_knowledge: bool,
    limit: int,
    sales_name: str = "",
    owner_email: str = "",
    viewer_email: str = "",
) -> dict[str, Any]:
    sales_filter = (sales_name or "").strip()
    owner_filter = (owner_email or "").strip().lower()
    viewer_filter = (viewer_email or "").strip().lower()
    unlimited = limit <= 0
    effective_limit = 20000 if unlimited else min(limit, 20000)

    rows: list[dict[str, Any]] = []
    scanned = 0
    item_type_counts: dict[str, int] = {}
    page_token = ""
    pages_fetched = 0

    while True:
        page_size = 300 if unlimited else min(300, effective_limit - len(rows) or 300)
        args: dict[str, Any] = {
            "parent": parent_path(),
            "collectionId": "global_customers",
            "pageSize": page_size,
            "mask": {
                "fieldPaths": ["name", "owner", "sales_name", "item_type", "viewers", "created_at"],
            },
        }
        if page_token:
            args["pageToken"] = page_token
        page = mcp_call("list_documents", args)
        pages_fetched += 1
        for doc in page.get("documents") or []:
            scanned += 1
            fields = doc.get("fields") or {}
            item_type = row_item_type(fields)
            bucket = item_type or "(empty)"
            item_type_counts[bucket] = item_type_counts.get(bucket, 0) + 1

            # 旧版 item_type=knowledge 已下线；TSE 工具只读客户条目
            if knowledge_only:
                continue
            if not is_customer_row(item_type, include_knowledge=False):
                continue

            owner = field_string(fields, "owner").lower()
            viewers = [v.lower() for v in field_string_array(fields, "viewers")]
            sales = field_string(fields, "sales_name")
            if sales_filter and sales != sales_filter:
                continue
            if owner_filter and owner != owner_filter:
                continue
            if viewer_filter and viewer_filter != owner and viewer_filter not in viewers:
                continue

            full_name = str(doc.get("name") or "")
            doc_id = full_name.rsplit("/", 1)[-1] if "/" in full_name else full_name
            rows.append(
                {
                    "id": doc_id,
                    "name": field_string(fields, "name"),
                    "owner": field_string(fields, "owner"),
                    "sales_name": sales,
                    "item_type": item_type,
                    "viewers": viewers,
                    "created_at": field_string(fields, "created_at"),
                }
            )
            if not unlimited and len(rows) >= effective_limit:
                break
        if not unlimited and len(rows) >= effective_limit:
            break
        page_token = str(page.get("nextPageToken") or "")
        if not page_token:
            break

    filter_mode = (
        "knowledge_only"
        if knowledge_only
        else (
            "all_documents"
            if include_knowledge
            else (
                f"strict:{customer_item_type_filter()}"
                if strict_customer_item_type()
                else "exclude_knowledge_include_empty_item_type"
            )
        )
    )
    return {
        **meta_block(),
        "collection": "global_customers",
        "customer_filter_mode": filter_mode,
        "pages_fetched": pages_fetched,
        "scanned_documents": scanned,
        "item_type_counts": item_type_counts,
        "returned_count": len(rows),
        "truncated": (not unlimited) and len(rows) >= effective_limit,
        "rows": rows,
    }


def list_tse_users(limit: int = 5000, tool_context: Any = None) -> dict[str, Any]:
    """列出 TSE 用户（tse_workspaces），不是客户。"""
    principal = resolve_tse_principal(tool_context)
    if principal.get("scoped"):
        email = str(principal["email"])
        return {
            "ok": True,
            "entity": "tse_user",
            "collection": "tse_workspaces",
            "access_path": "scoped_self",
            "note": "TSE App 会话禁止枚举全部用户，仅返回当前登录者",
            **meta_block(),
            "scanned_documents": 1,
            "returned_count": 1,
            "truncated": False,
            "user_count": 1,
            "users": [{"email": email, "display_name": ""}],
            "principal_email": email,
        }
    listed = list_collection_rows("tse_workspaces", field_paths=["email", "display_name"], limit=limit)
    users = [
        {
            "email": (row.get("email") or row.get("id") or "").strip(),
            "display_name": (row.get("display_name") or "").strip(),
        }
        for row in listed["rows"]
    ]
    return {
        "ok": True,
        "entity": "tse_user",
        "collection": "tse_workspaces",
        **meta_block(),
        **listed,
        "user_count": len(users),
        "users": users,
    }


def get_tse_user_workspace(user_email: str, tool_context: Any = None) -> dict[str, Any]:
    """读取用户工作区配置（Prompt/UI）；脱敏飞书凭据。Key 主体优先 External API。"""
    email = (user_email or "").strip().lower()
    if not email:
        return {"ok": False, "error": {"code": "MISSING_EMAIL", "message": "user_email 不能为空"}}
    _owner, _access, scope_err = enforce_data_scope(
        tool_context, requested_user_email=email
    )
    if scope_err:
        return scope_err

    api_status = tse_api_status(tool_context)
    key_email = str(api_status.get("target_email") or "").strip().lower()
    if tse_api_ready_for_scoped_reads(tool_context) and (not key_email or key_email == email):
        result = call_tse_external(
            "GET",
            "/api/external/v1/settings",
            tool_context=tool_context,
            timeout=60,
        )
        if result.get("ok"):
            settings = result.get("data") if isinstance(result.get("data"), dict) else {}
            safe: dict[str, Any] = {
                "snapshot_prefix": settings.get("snapshot_prefix"),
                "auto_server_backup": settings.get("auto_server_backup"),
                "ui_preferences": settings.get("ui_preferences"),
                "prompts": settings.get("prompts"),
            }
            if settings.get("feishu_app_id"):
                safe["feishu_app_id"] = mask_secret(str(settings["feishu_app_id"]))
            return {
                "ok": True,
                "entity": "tse_user_workspace",
                "user_email": key_email or email,
                "access_path": "tse_api",
                "note": "系统内置 Prompt 在代码 SYSTEM_PROMPTS，运行时合并。",
                **meta_block(),
                "settings": safe,
            }

    doc = get_document("tse_workspaces", email, field_paths=["settings"])
    settings = parse_map_value((doc.get("fields") or {}).get("settings") or {})
    safe = {
        "snapshot_prefix": settings.get("snapshot_prefix"),
        "auto_server_backup": settings.get("auto_server_backup"),
        "ui_preferences": settings.get("ui_preferences"),
        "prompts": settings.get("prompts"),
    }
    if settings.get("feishu_app_id"):
        safe["feishu_app_id"] = mask_secret(str(settings["feishu_app_id"]))
    return {
        "ok": True,
        "entity": "tse_user_workspace",
        "user_email": email,
        "access_path": "firestore_mcp",
        "note": "系统内置 Prompt 在代码 SYSTEM_PROMPTS，运行时合并。",
        **meta_block(),
        "settings": safe,
    }


def list_tse_items_for_user(
    user_email: str,
    item_kind: str = "all",
    limit: int = 5000,
    tool_context: Any = None,
) -> dict[str, Any]:
    """某 TSE 用户可见条目（owner 或 viewers），对齐 App 侧边栏。"""
    email = (user_email or "").strip().lower()
    if not email:
        return {"ok": False, "error": {"code": "MISSING_EMAIL", "message": "user_email 不能为空"}}
    _owner, access_email, scope_err = enforce_data_scope(
        tool_context, requested_user_email=email
    )
    if scope_err:
        return scope_err
    if access_email:
        email = access_email
    kind = (item_kind or "all").strip().lower()
    knowledge_only = kind in {"knowledge", "知识"}
    customers_only = kind in {"customer", "customers", "客户"}

    api_status = tse_api_status(tool_context)
    key_email = str(api_status.get("target_email") or "").strip().lower()
    if (
        not knowledge_only
        and tse_api_ready_for_scoped_reads(tool_context)
        and (not key_email or key_email == email)
    ):
        rows, api_err = _api_list_customers_payload(tool_context)
        if rows is not None:
            if customers_only:
                rows = [r for r in rows if is_customer_row(r.get("item_type"), include_knowledge=False)]
            elif knowledge_only:
                rows = []
            if access_email:
                rows = [
                    r
                    for r in rows
                    if row_visible_to(
                        str(r.get("owner") or ""),
                        r.get("viewers") or [],
                        access_email,
                    )
                ]
            unlimited = limit <= 0
            effective_limit = 20000 if unlimited else min(limit, 20000)
            truncated = (not unlimited) and len(rows) > effective_limit
            picked = rows if unlimited else rows[:effective_limit]
            return {
                "ok": True,
                "entity": "tse_visible_items",
                "user_email": key_email or email,
                "item_kind": kind,
                "access_path": "tse_api",
                "note": "External API Key 作用域（owner∪viewers）",
                **meta_block(),
                "collection": "global_customers",
                "returned_count": len(picked),
                "truncated": truncated,
                "rows": picked,
                "principal_email": access_email or None,
            }

    base = _list_global_items(
        knowledge_only=knowledge_only,
        include_knowledge=not customers_only,
        limit=limit,
        viewer_email=email,
    )
    return {
        "ok": True,
        "entity": "tse_visible_items",
        "user_email": email,
        "item_kind": kind,
        "access_path": "firestore_mcp",
        "note": "owner==email OR viewers contains email",
        **base,
        "principal_email": access_email or None,
    }


def list_tse_customers(
    include_knowledge: bool = False,
    limit: int = 5000,
    sales_name: str = "",
    owner_email: str = "",
    tool_context: Any = None,
) -> dict[str, Any]:
    """列出 TSE 客户（global_customers），支持 sales_name / owner 过滤。有 Key 优先 API。"""
    owner_filter, access_email, scope_err = enforce_data_scope(
        tool_context, requested_owner_email=owner_email
    )
    if scope_err:
        return scope_err
    sales_filter = (sales_name or "").strip()

    rows, _api_err = _api_list_customers_payload(tool_context)
    if rows is not None:
        filtered: list[dict[str, Any]] = []
        for row in rows:
            item_type = row.get("item_type")
            if not include_knowledge and not is_customer_row(item_type, include_knowledge=False):
                continue
            if sales_filter and (row.get("sales_name") or "") != sales_filter:
                continue
            if owner_filter and (row.get("owner") or "").lower() != owner_filter:
                continue
            if access_email and not row_visible_to(
                str(row.get("owner") or ""),
                row.get("viewers") or [],
                access_email,
            ):
                continue
            filtered.append(row)
        unlimited = limit <= 0
        effective_limit = 20000 if unlimited else min(limit, 20000)
        truncated = (not unlimited) and len(filtered) > effective_limit
        picked = filtered if unlimited else filtered[:effective_limit]
        return {
            "ok": True,
            "entity": "tse_customer",
            "include_knowledge": include_knowledge,
            "sales_name_filter": sales_filter or None,
            "owner_email_filter": owner_filter or None,
            "access_path": "tse_api",
            **meta_block(),
            "collection": "global_customers",
            "returned_count": len(picked),
            "truncated": truncated,
            "rows": picked,
            "principal_email": access_email or None,
        }

    base = _list_global_items(
        knowledge_only=False,
        include_knowledge=include_knowledge,
        limit=limit,
        sales_name=sales_name,
        owner_email=owner_filter,
        viewer_email=access_email if not owner_filter else "",
    )
    return {
        "ok": True,
        "entity": "tse_customer",
        "include_knowledge": include_knowledge,
        "sales_name_filter": sales_filter or None,
        "owner_email_filter": owner_filter or None,
        "access_path": "firestore_mcp",
        **base,
        "principal_email": access_email or None,
    }


def get_tse_customer(
    item_id: str,
    include_background: bool = True,
    tool_context: Any = None,
) -> dict[str, Any]:
    """单客户条目元数据（不含 daily_reports 全文）。旧 knowledge 条目不再返回。"""
    cid = (item_id or "").strip()
    if not cid:
        return {"ok": False, "error": {"code": "MISSING_ITEM_ID", "message": "item_id 不能为空"}}

    if tse_api_ready_for_scoped_reads(tool_context):
        result = call_tse_external(
            "GET",
            f"/api/external/v1/customers/{quote(cid, safe='')}",
            tool_context=tool_context,
            timeout=60,
        )
        if result.get("ok") and isinstance(result.get("data"), dict):
            doc = result["data"]
            item_type = str(doc.get("item_type") or "").strip()
            if item_type.lower() == "knowledge":
                return {
                    "ok": False,
                    "error": {
                        "code": "LEGACY_KNOWLEDGE_RETIRED",
                        "message": "旧版知识沉淀条目已下线；技术文档请用 search_tse_knowledge / rag_search",
                    },
                    "access_path": "tse_api",
                    **meta_block(),
                }
            denied = assert_item_access(
                tool_context,
                owner=str(doc.get("owner") or ""),
                viewers=doc.get("viewers") or [],
                item_id=cid,
            )
            if denied:
                return denied
            bg = str(doc.get("background") or "") if include_background else ""
            return {
                "ok": True,
                "entity": "tse_customer_detail",
                "access_path": "tse_api",
                **meta_block(),
                "item": {
                    "id": str(doc.get("id") or cid),
                    "name": str(doc.get("name") or ""),
                    "owner": str(doc.get("owner") or ""),
                    "sales_name": str(doc.get("sales_name") or ""),
                    "item_type": item_type or "customer",
                    "created_at": str(doc.get("created_at") or ""),
                    "background": truncate_text(bg, 2000) if bg else "",
                },
            }

    paths = ["id", "name", "owner", "sales_name", "item_type", "viewers", "created_at"]
    if include_background:
        paths.append("background")
    doc = get_document("global_customers", cid, field_paths=paths)
    fields = doc.get("fields") or {}
    item_type = row_item_type(fields)
    if (item_type or "").strip().lower() == "knowledge":
        return {
            "ok": False,
            "error": {
                "code": "LEGACY_KNOWLEDGE_RETIRED",
                "message": "旧版知识沉淀条目已下线；技术文档请用 search_tse_knowledge / rag_search",
            },
            "access_path": "firestore_mcp",
            **meta_block(),
        }
    owner = field_string(fields, "owner")
    viewers = field_string_array(fields, "viewers")
    denied = assert_item_access(
        tool_context, owner=owner, viewers=viewers, item_id=cid
    )
    if denied:
        return denied
    bg = field_string(fields, "background")
    return {
        "ok": True,
        "entity": "tse_customer_detail",
        "access_path": "firestore_mcp",
        **meta_block(),
        "item": {
            "id": cid,
            "name": field_string(fields, "name"),
            "owner": owner,
            "sales_name": field_string(fields, "sales_name"),
            "item_type": item_type,
            "created_at": field_string(fields, "created_at"),
            "background": truncate_text(bg, 2000) if bg else "",
        },
    }


def get_tse_customer_daily_reports(
    item_id: str,
    limit: int = 20,
    latest_first: bool = True,
    date_from: str = "",
    date_to: str = "",
    tool_context: Any = None,
) -> dict[str, Any]:
    """读取单客户内嵌 daily_reports[]，可选按日期闭区间过滤。

    ``date_from`` / ``date_to`` 建议 ``YYYY-MM-DD``；只填一端则另一端开放。
    """
    cid = (item_id or "").strip()
    if not cid:
        return {"ok": False, "error": {"code": "MISSING_ITEM_ID", "message": "item_id 不能为空"}}
    # ACL gate before any report body is returned
    meta = get_tse_customer(cid, include_background=False, tool_context=tool_context)
    if not meta.get("ok"):
        return meta
    start = normalize_report_date(date_from)
    end = normalize_report_date(date_to)
    if (date_from or "").strip() and not start:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_DATE_FROM",
                "message": "date_from 无法解析，请用 YYYY-MM-DD",
            },
        }
    if (date_to or "").strip() and not end:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_DATE_TO",
                "message": "date_to 无法解析，请用 YYYY-MM-DD",
            },
        }
    if start and end and start > end:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_DATE_RANGE",
                "message": f"date_from({start}) 不能晚于 date_to({end})",
            },
        }

    customer_name = ""
    sales_name = ""
    reports: list[dict[str, Any]] = []
    access_path = "firestore_mcp"

    if tse_api_ready_for_scoped_reads(tool_context):
        enc = quote(cid, safe="")
        result = call_tse_external(
            "GET",
            f"/api/external/v1/customers/{enc}/daily_reports",
            tool_context=tool_context,
            timeout=120,
        )
        if result.get("ok"):
            access_path = "tse_api"
            raw = result.get("data")
            if isinstance(raw, list):
                for r in raw:
                    if not isinstance(r, dict):
                        continue
                    reports.append(
                        {
                            "date": str(r.get("date") or ""),
                            "raw_draft": str(r.get("raw_draft") or ""),
                            "ai_generated_content": str(r.get("ai_generated_content") or ""),
                        }
                    )
            detail = call_tse_external(
                "GET",
                f"/api/external/v1/customers/{enc}",
                tool_context=tool_context,
                timeout=60,
            )
            if detail.get("ok") and isinstance(detail.get("data"), dict):
                customer_name = str(detail["data"].get("name") or "")
                sales_name = str(detail["data"].get("sales_name") or "")
        else:
            access_path = "firestore_mcp"

    if access_path == "firestore_mcp":
        doc = get_document(
            "global_customers",
            cid,
            field_paths=["name", "sales_name", "daily_reports"],
        )
        fields = doc.get("fields") or {}
        customer_name = field_string(fields, "name")
        sales_name = field_string(fields, "sales_name")
        reports = parse_daily_reports(fields)

    total_before = len(reports)
    reports = filter_reports_by_date(reports, date_from=start, date_to=end)
    if latest_first:
        reports.sort(key=lambda r: normalize_report_date(r.get("date") or "") or "", reverse=True)
    else:
        reports.sort(key=lambda r: normalize_report_date(r.get("date") or "") or "")
    cap = max(1, min(int(limit or 20), 100))
    picked = reports[:cap]
    for rep in picked:
        rep["raw_draft"] = truncate_text(rep.get("raw_draft") or "")
        rep["ai_generated_content"] = truncate_text(rep.get("ai_generated_content") or "")
    return {
        "ok": True,
        "entity": "tse_daily_reports",
        "access_path": access_path,
        **meta_block(),
        "item_id": cid,
        "customer_name": customer_name,
        "sales_name": sales_name,
        "date_from": start or None,
        "date_to": end or None,
        "total_reports": total_before,
        "matched_reports": len(reports),
        "returned_count": len(picked),
        "truncated": len(reports) > len(picked),
        "reports": picked,
    }


def query_tse_daily_reports_by_date(
    date_from: str = "",
    date_to: str = "",
    sales_name: str = "",
    owner_email: str = "",
    item_id: str = "",
    limit_reports: int = 50,
    limit_customers: int = 500,
    include_text: bool = True,
    tool_context: Any = None,
) -> dict[str, Any]:
    """按日期闭区间查询日报（可跨客户），在服务端过滤后再返回。

    适用：「查某时间段 TSE 数据并提炼」——避免先拉全量再让模型筛。
    至少提供 ``date_from`` 或 ``date_to`` 之一（建议 ``YYYY-MM-DD``）。
    可选 ``sales_name`` / ``owner_email`` / ``item_id`` 缩小范围。
    """
    owner_filter, access_email, scope_err = enforce_data_scope(
        tool_context, requested_owner_email=owner_email
    )
    if scope_err:
        return scope_err
    start = normalize_report_date(date_from)
    end = normalize_report_date(date_to)
    if not start and not end:
        return {
            "ok": False,
            "error": {
                "code": "MISSING_DATE_RANGE",
                "message": "请至少提供 date_from 或 date_to（YYYY-MM-DD）",
            },
        }
    if (date_from or "").strip() and not start:
        return {
            "ok": False,
            "error": {"code": "INVALID_DATE_FROM", "message": "date_from 无法解析，请用 YYYY-MM-DD"},
        }
    if (date_to or "").strip() and not end:
        return {
            "ok": False,
            "error": {"code": "INVALID_DATE_TO", "message": "date_to 无法解析，请用 YYYY-MM-DD"},
        }
    if start and end and start > end:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_DATE_RANGE",
                "message": f"date_from({start}) 不能晚于 date_to({end})",
            },
        }

    cid = (item_id or "").strip()
    sales_filter = (sales_name or "").strip()
    report_cap = max(1, min(int(limit_reports or 50), 200))
    customer_cap = max(1, min(int(limit_customers or 500), 2000))

    # Single-customer fast path
    if cid:
        one = get_tse_customer_daily_reports(
            cid,
            limit=report_cap,
            latest_first=True,
            date_from=start,
            date_to=end,
            tool_context=tool_context,
        )
        if not one.get("ok"):
            return one
        hits = [
            {
                "item_id": cid,
                "customer_name": one.get("customer_name") or "",
                "sales_name": one.get("sales_name") or "",
                **rep,
            }
            for rep in (one.get("reports") or [])
        ]
        return {
            "ok": True,
            "entity": "tse_daily_reports_by_date",
            **meta_block(),
            "date_from": start or None,
            "date_to": end or None,
            "filters": {
                "item_id": cid,
                "sales_name": sales_filter or None,
                "owner_email": owner_filter or None,
            },
            "customers_scanned": 1,
            "customers_with_matches": 1 if hits else 0,
            "matched_reports": one.get("matched_reports") or len(hits),
            "returned_count": len(hits),
            "truncated": bool(one.get("truncated")),
            "reports": hits,
            "principal_email": access_email or None,
            "hint": "单客户路径；提炼时优先用 returned reports，勿再全量拉取。",
        }

    matched: list[dict[str, Any]] = []
    customers_scanned = 0
    customers_with_matches = 0
    total_matched = 0
    truncated = False
    page_token = ""
    pages_fetched = 0

    while True:
        if customers_scanned >= customer_cap or len(matched) >= report_cap:
            truncated = True
            break
        page_size = min(100, customer_cap - customers_scanned)
        args: dict[str, Any] = {
            "parent": parent_path(),
            "collectionId": "global_customers",
            "pageSize": page_size,
            "mask": {
                "fieldPaths": [
                    "name",
                    "owner",
                    "sales_name",
                    "item_type",
                    "viewers",
                    "daily_reports",
                ],
            },
        }
        if page_token:
            args["pageToken"] = page_token
        page = mcp_call("list_documents", args)
        pages_fetched += 1
        docs = page.get("documents") or []
        if not docs:
            break
        stop = False
        for doc in docs:
            if customers_scanned >= customer_cap or len(matched) >= report_cap:
                truncated = True
                stop = True
                break
            fields = doc.get("fields") or {}
            item_type = row_item_type(fields)
            if not is_customer_row(item_type, include_knowledge=False):
                continue
            sales = field_string(fields, "sales_name")
            owner = field_string(fields, "owner").lower()
            viewers = [v.lower() for v in field_string_array(fields, "viewers")]
            if sales_filter and sales != sales_filter:
                continue
            if owner_filter and owner != owner_filter:
                continue
            if access_email and not row_visible_to(owner, viewers, access_email):
                continue

            customers_scanned += 1
            full_name = str(doc.get("name") or "")
            doc_id = full_name.rsplit("/", 1)[-1] if "/" in full_name else full_name
            reports = filter_reports_by_date(
                parse_daily_reports(fields),
                date_from=start,
                date_to=end,
            )
            if not reports:
                continue
            customers_with_matches += 1
            total_matched += len(reports)
            reports.sort(
                key=lambda r: normalize_report_date(r.get("date") or "") or "",
                reverse=True,
            )
            for rep in reports:
                if len(matched) >= report_cap:
                    truncated = True
                    stop = True
                    break
                row = {
                    "item_id": doc_id,
                    "customer_name": field_string(fields, "name"),
                    "sales_name": sales,
                    "owner": owner,
                    "id": rep.get("id") or "",
                    "date": rep.get("date") or "",
                    "created_at": rep.get("created_at") or "",
                }
                if include_text:
                    row["raw_draft"] = truncate_text(rep.get("raw_draft") or "")
                    row["ai_generated_content"] = truncate_text(
                        rep.get("ai_generated_content") or ""
                    )
                matched.append(row)
            if stop:
                break

        if stop:
            break
        page_token = str(page.get("nextPageToken") or "")
        if not page_token:
            break

    matched.sort(
        key=lambda r: (
            normalize_report_date(r.get("date") or "") or "",
            r.get("customer_name") or "",
        ),
        reverse=True,
    )
    return {
        "ok": True,
        "entity": "tse_daily_reports_by_date",
        **meta_block(),
        "date_from": start or None,
        "date_to": end or None,
        "filters": {
            "item_id": None,
            "sales_name": sales_filter or None,
            "owner_email": owner_filter or None,
        },
        "pages_fetched": pages_fetched,
        "customers_scanned": customers_scanned,
        "customers_with_matches": customers_with_matches,
        "matched_reports": total_matched,
        "returned_count": len(matched),
        "truncated": truncated or total_matched > len(matched),
        "reports": matched,
        "principal_email": access_email or None,
        "hint": (
            "已在服务端按日期过滤。若 truncated=true，缩小销售/客户范围或收紧日期后再查；"
            "提炼时直接使用 reports，勿再对全库无过滤拉取。"
        ),
    }


def _bitable_field_meta(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one field_list item → name / type / ui_type / property."""
    name = str(
        item.get("field_name")
        or item.get("name")
        or item.get("title")
        or ""
    ).strip()
    raw_type = item.get("type")
    if raw_type is None:
        raw_type = item.get("field_type")
    type_str = str(raw_type if raw_type is not None else "").strip()
    ui = str(item.get("ui_type") or item.get("uiType") or type_str).strip()
    prop = item.get("property") if isinstance(item.get("property"), dict) else {}
    return {
        "name": name,
        "type": type_str.lower(),
        "type_code": type_str,
        "ui_type": ui.lower(),
        "property": prop,
        "raw": item,
    }


# Feishu Bitable field types (numeric)
_BITABLE_READONLY_TYPES = frozenset({"23", "1001", "1002", "1003"})
_BITABLE_LINK_TYPES = frozenset({"18", "21", "link"})
_BITABLE_PERSON_TYPES = frozenset({"11"})


def _is_readonly_field(meta: dict[str, Any]) -> bool:
    code = str(meta.get("type_code") or meta.get("type") or "").strip()
    if code in _BITABLE_READONLY_TYPES:
        return True
    blob = f"{meta.get('ui_type','')} {meta.get('name','')}".lower()
    return any(
        k in blob
        for k in (
            "createdtime",
            "createduser",
            "modifiedtime",
            "modifieduser",
            "autonumber",
            "创建时间",
            "创建人",
            "修改时间",
            "修改人",
        )
    )


def _is_link_field(meta: dict[str, Any]) -> bool:
    code = str(meta.get("type_code") or meta.get("type") or "").strip()
    if code in _BITABLE_LINK_TYPES:
        return True
    blob = f"{code} {meta.get('ui_type','')}".lower()
    return any(k in blob for k in ("singlelink", "duplexlink", "link", "关联"))


def _linked_table_id(meta: dict[str, Any]) -> Optional[str]:
    prop = meta.get("property") if isinstance(meta.get("property"), dict) else {}
    for key in (
        "table_id",
        "tableId",
        "link_table_id",
        "linkTableId",
        "linked_table_id",
        "linkedTableId",
    ):
        val = prop.get(key)
        if isinstance(val, str) and val.strip().startswith("tbl"):
            return val.strip()
    def _dig_tbl(obj: Any) -> Optional[str]:
        if isinstance(obj, str) and obj.strip().startswith("tbl"):
            return obj.strip()
        if isinstance(obj, dict):
            for v in obj.values():
                found = _dig_tbl(v)
                if found:
                    return found
        if isinstance(obj, list):
            for v in obj:
                found = _dig_tbl(v)
                if found:
                    return found
        return None
    return _dig_tbl(prop)


def _parse_bitable_fields_schema(fields_json: str) -> tuple[list[dict[str, Any]], Optional[dict]]:
    raw = (fields_json or "").strip()
    if not raw:
        return [], {
            "ok": False,
            "error": {
                "code": "MISSING_FIELDS_JSON",
                "message": "fields_json 不能为空：请先让小飞 feishu_bitable_field_list，再把字段列表传入",
            },
        }
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [], {
            "ok": False,
            "error": {"code": "INVALID_FIELDS_JSON", "message": "fields_json 须为合法 JSON"},
        }

    items: list[Any] = []
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(parsed, dict):
        for key in ("fields", "items", "data", "result"):
            val = parsed.get(key)
            if isinstance(val, list):
                items = val
                break
            if isinstance(val, dict):
                for key2 in ("fields", "items", "list"):
                    if isinstance(val.get(key2), list):
                        items = val[key2]
                        break
            if items:
                break
        if not items and all(isinstance(v, dict) for v in parsed.values()):
            # Maybe {field_id: {...}} map
            items = list(parsed.values())

    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        meta = _bitable_field_meta(item)
        if meta["name"]:
            out.append(meta)
    if not out:
        return [], {
            "ok": False,
            "error": {
                "code": "EMPTY_FIELD_SCHEMA",
                "message": "未能从 fields_json 解析出字段名；请传入 feishu_bitable_field_list 的原始 fields 数组",
            },
        }
    return out, None


def _is_date_field(meta: dict[str, Any]) -> bool:
    # Feishu bitable: type 5 = DateTime；23/1002 = created/modified time (readonly)
    raw_type = str(meta.get("type_code") or meta.get("type") or "").strip()
    if raw_type == "5":
        return True
    if raw_type in _BITABLE_READONLY_TYPES:
        return False
    blob = f"{meta.get('name','')} {raw_type} {meta.get('ui_type','')}".lower()
    return any(
        k in blob
        for k in ("date", "datetime", "时间", "日期", "跟进日期")
    ) and not _is_readonly_field(meta)


def _is_person_field(meta: dict[str, Any]) -> bool:
    if _is_readonly_field(meta):
        return False
    raw_type = str(meta.get("type_code") or meta.get("type") or "").strip()
    if raw_type in _BITABLE_PERSON_TYPES:
        return True
    blob = f"{raw_type} {meta.get('ui_type','')}".lower()
    name = meta.get("name") or ""
    if any(k in blob for k in ("user", "person", "personnel", "联系人")):
        return True
    if "参与人" in name or name in {"内部参与人"}:
        return True
    return False


def _date_to_feishu_ms(date_value: str) -> Optional[int]:
    """YYYY-MM-DD → Asia/Shanghai midnight epoch ms (Feishu datetime)."""
    day = normalize_report_date(date_value)
    if not day:
        return None
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


_SECTION_STOP = re.compile(
    r"\n(?=(?:#{1,3}\s+|[-*•]\s+)?(?:下一步|跟进计划|跟进记录|工作摘要|沟通对象|"
    r"风险|问题|背景|结论|建议|待办|Action|Next\s*steps?)\b)",
    re.IGNORECASE,
)


def _report_body(report: dict[str, Any], *, limit: int = 4000) -> str:
    body = (
        str(report.get("ai_generated_content") or "").strip()
        or str(report.get("raw_draft") or "").strip()
    )
    return truncate_text(body, limit)


def _extract_section_from_text(body: str, *headers: str) -> Optional[str]:
    """从日报正文按小标题/关键词二次提取段落（非 Firestore 结构化字段）。"""
    text = (body or "").strip()
    if not text or not headers:
        return None
    normalized = text.replace("\r\n", "\n")
    for header in headers:
        h = (header or "").strip()
        if not h:
            continue
        # Header with optional colon on same line, then rest of section
        m = re.search(
            rf"(?im)^[＃#*\-•\s]*{re.escape(h)}\s*[：:]?[ \t]*(.*)$",
            normalized,
        )
        if not m:
            # Inline form: 「下一步：xxx」 mid-paragraph
            m2 = re.search(
                rf"(?is){re.escape(h)}\s*[：:]\s*(.+?)(?=\n\n|\n[＃#]|$)",
                normalized,
            )
            if not m2:
                continue
            chunk = (m2.group(1) or "").strip()
        else:
            first = (m.group(1) or "").strip()
            rest = normalized[m.end() :].lstrip("\n")
            # Cut at next known section header
            parts = _SECTION_STOP.split(rest, maxsplit=1)
            following = (parts[0] if parts else rest).strip()
            if first and following:
                chunk = f"{first}\n{following}".strip()
            else:
                chunk = first or following
        chunk = re.sub(r"\n{3,}", "\n\n", chunk).strip(" -\n\t")
        if chunk:
            return truncate_text(chunk, 800)
    return None


def _extract_next_step(body: str) -> Optional[str]:
    found = _extract_section_from_text(
        body,
        "下一步跟进计划",
        "下一步计划",
        "下一步跟进",
        "跟进计划",
        "下一步",
        "后续计划",
        "待办",
        "Action items",
        "Action Items",
        "Next steps",
        "Next Steps",
        "Next step",
    )
    if found:
        return found
    # Soft: last sentence containing 下周/后续/建议跟进
    for line in reversed([ln.strip() for ln in (body or "").splitlines() if ln.strip()]):
        if any(k in line for k in ("下一步", "跟进计划", "后续", "下周", "建议跟进", "待办")):
            if len(line) >= 6:
                return truncate_text(line, 800)
    return None


def _pick_tse_value_for_field(
    field_name: str,
    *,
    meta: dict[str, Any],
    is_date: bool,
    is_person: bool,
    is_link: bool,
    is_readonly: bool,
    report: dict[str, Any],
) -> tuple[Any, str]:
    """Return (value_or_None, source_tag)."""
    if is_readonly:
        return None, "skipped_readonly_system_field"
    if is_link:
        return None, "skipped_link_field_needs_record_id"
    if is_person:
        return None, "skipped_person_field_needs_open_id"

    name = (field_name or "").strip()
    customer = str(report.get("customer_name") or report.get("name") or "").strip()
    sales = str(report.get("sales_name") or "").strip()
    date_raw = str(report.get("date") or "").strip()
    body = _report_body(report)

    if is_date or any(k in name for k in ("日期", "时间")):
        ms = _date_to_feishu_ms(date_raw)
        if ms is not None:
            return ms, "date→ms"
        return date_raw or None, "date_raw"

    # Prefer exact / strong name matches
    if any(k in name for k in ("客户简称", "客户名称", "客户名")) or name in {"客户"}:
        return customer or None, "customer_name"
    if any(k in name for k in ("沟通对象", "联系对象", "对方")):
        return customer or None, "customer_name_as_contact"
    if any(k in name for k in ("跟进人", "销售", "负责人")):
        return sales or None, "sales_name"
    if any(k in name for k in ("下一步", "跟进计划")):
        nxt = _extract_next_step(body)
        if nxt:
            return nxt, "extracted_next_step_from_report"
        return None, "no_next_step_in_report_text"
    if any(k in name for k in ("跟进记录", "工作摘要", "摘要", "日报", "工作记录")) or name in {
        "记录"
    }:
        return (truncate_text(body, 1500) or None), "report_body"
    if "邮箱" in name or "email" in name.lower():
        return None, "no_email_in_tse_daily"

    # Secondary extraction: treat unmatched text field name as a section header in body
    ui = str(meta.get("ui_type") or "")
    type_code = str(meta.get("type_code") or meta.get("type") or "")
    if type_code in {"1", "text"} or "text" in ui:
        section = _extract_section_from_text(body, name)
        if section:
            return section, "extracted_section_from_report"

    # Soft fallbacks by keyword
    lower = name.lower()
    if "customer" in lower or "client" in lower:
        return customer or None, "customer_name"
    if "sales" in lower or "owner" in lower:
        return sales or None, "sales_name"
    if "plan" in lower or "next" in lower:
        nxt = _extract_next_step(body)
        if nxt:
            return nxt, "extracted_next_step_from_report"
    if "summary" in lower or "note" in lower or "content" in lower or "desc" in lower:
        return (truncate_text(body, 1500) or None), "report_body"
    return None, "unmapped"


def map_tse_daily_reports_to_bitable(
    fields_json: str,
    reports_json: str = "",
    date_from: str = "",
    date_to: str = "",
    sales_name: str = "",
    owner_email: str = "",
    limit_reports: int = 50,
    tool_context: Any = None,
) -> dict[str, Any]:
    """按多维表格字段 schema 映射 TSE 日报 → ``create_records``。

    **必须先有** ``feishu_bitable_field_list`` 的字段列表（``fields_json``），
    再映射；禁止先按臆造列名提炼再写入。

    数据来源二选一：
    - ``reports_json``：已有 ``query_tse_daily_reports_by_date`` 的 reports 数组；或
    - ``date_from``/``date_to``：本工具内再查询。
    """
    fields, ferr = _parse_bitable_fields_schema(fields_json)
    if ferr:
        return ferr

    reports: list[dict[str, Any]] = []
    source = "reports_json"
    rj = (reports_json or "").strip()
    if rj:
        try:
            parsed = json.loads(rj)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": {"code": "INVALID_REPORTS_JSON", "message": "reports_json 须为合法 JSON"},
            }
        if isinstance(parsed, dict) and isinstance(parsed.get("reports"), list):
            reports = [r for r in parsed["reports"] if isinstance(r, dict)]
        elif isinstance(parsed, list):
            reports = [r for r in parsed if isinstance(r, dict)]
        else:
            return {
                "ok": False,
                "error": {
                    "code": "INVALID_REPORTS_JSON",
                    "message": "reports_json 须为数组，或含 reports 数组的对象",
                },
            }
    else:
        source = "query_tse_daily_reports_by_date"
        queried = query_tse_daily_reports_by_date(
            date_from=date_from,
            date_to=date_to,
            sales_name=sales_name,
            owner_email=owner_email,
            limit_reports=limit_reports,
            include_text=True,
            tool_context=tool_context,
        )
        if not queried.get("ok"):
            return queried
        reports = [r for r in (queried.get("reports") or []) if isinstance(r, dict)]

    create_records: list[dict[str, Any]] = []
    enrichment_hints: list[dict[str, str]] = []
    mapping_legend: dict[str, str] = {}
    skipped_fields: list[str] = []
    writable_field_names: list[str] = []
    unsupported_fields: list[dict[str, Any]] = []
    field_flags: list[dict[str, Any]] = []

    for meta in fields:
        fname = meta["name"]
        readonly = _is_readonly_field(meta)
        link = _is_link_field(meta)
        person = _is_person_field(meta)
        date_f = _is_date_field(meta)
        flags = {
            "meta": meta,
            "is_readonly": readonly,
            "is_link": link,
            "is_person": person,
            "is_date": date_f,
        }
        field_flags.append(flags)

        sample = reports[0] if reports else {}
        _val, tag = _pick_tse_value_for_field(
            fname,
            meta=meta,
            is_date=date_f,
            is_person=person,
            is_link=link,
            is_readonly=readonly,
            report=sample if sample else {},
        )
        mapping_legend[fname] = tag

        if tag.startswith("skipped"):
            skipped_fields.append(f"{fname} ({tag})")
            reason = tag.removeprefix("skipped_")
            entry: dict[str, Any] = {
                "name": fname,
                "type_code": meta.get("type_code"),
                "ui_type": meta.get("ui_type"),
                "reason": reason,
            }
            if link:
                lt = _linked_table_id(meta)
                if lt:
                    entry["linked_table_id"] = lt
            unsupported_fields.append(entry)
        elif tag in {"no_next_step_in_report_text", "no_email_in_tse_daily", "unmapped"}:
            skipped_fields.append(f"{fname} ({tag})")
        else:
            writable_field_names.append(fname)

    for report in reports:
        row: dict[str, Any] = {}
        for flags in field_flags:
            meta = flags["meta"]
            fname = meta["name"]
            val, _tag = _pick_tse_value_for_field(
                fname,
                meta=meta,
                is_date=flags["is_date"],
                is_person=flags["is_person"],
                is_link=flags["is_link"],
                is_readonly=flags["is_readonly"],
                report=report,
            )
            if val is None or val == "":
                continue
            row[fname] = val
        if row:
            # Embed hints into the row so enrich still works even if agent
            # forgets to pass enrichment_hints_json (stripped before write).
            cust = str(
                report.get("customer_name") or report.get("name") or ""
            ).strip()
            sales = str(report.get("sales_name") or "").strip()
            owner = str(report.get("owner") or "").strip()
            if cust:
                row["__tse_customer_name"] = cust
            if sales:
                row["__tse_sales_name"] = sales
            if owner:
                row["__tse_owner"] = owner
            create_records.append(row)
            enrichment_hints.append(
                {
                    "customer_name": cust,
                    "sales_name": sales,
                    "owner": owner,
                }
            )

    return {
        "ok": True,
        "entity": "tse_bitable_mapped_records",
        **meta_block(),
        "source": source,
        "field_names": [f["name"] for f in fields],
        "writable_field_names": writable_field_names,
        "unsupported_fields": unsupported_fields,
        "mapping_legend": mapping_legend,
        "skipped_or_empty_fields": skipped_fields,
        "input_report_count": len(reports),
        "create_record_count": len(create_records),
        "enrichment_hints": enrichment_hints,
        "records_json": json.dumps(
            {"create_records": create_records},
            ensure_ascii=False,
        ),
        "create_records": create_records,
        "hint": (
            "把 records_json + fields_json 交给小飞 "
            "`feishu_bitable_write_tse_records`（推荐：enrich+写入一步完成）；"
            "或 `enrich_tse_records` 再 `record_batch_create`。"
            "records_json 内嵌 __tse_customer_name 等 hint（enrich 会剥离）；"
            "文本列会从日报正文二次抽取；关联/人员由 enrich 解析。"
        ),
    }


def get_tse_overview(tool_context: Any = None) -> dict[str, Any]:
    """TSE 总览：用户数、客户数、术语对照。"""
    users = list_tse_users(limit=0, tool_context=tool_context)
    customers = list_tse_customers(
        include_knowledge=False, limit=0, tool_context=tool_context
    )
    if not customers.get("ok", True) and customers.get("ok") is False:
        return customers
    stats = get_tse_customer_sales_stats(
        include_knowledge=False, limit=0, tool_context=tool_context
    )
    principal = resolve_tse_principal(tool_context)
    if principal.get("scoped"):
        return {
            "ok": True,
            **meta_block(),
            "scoped": True,
            "principal_email": principal["email"],
            "terminology": {
                "tse_user": "tse_workspaces = 登录用户配置",
                "tse_customer": "global_customers 非 knowledge",
                "daily_reports": "global_customers 内嵌数组",
            },
            "counts": {
                "tse_users": users.get("user_count"),
                "global_customers_scanned": customers.get("returned_count"),
                "customers_excluding_knowledge": customers.get("returned_count"),
                "customer_owners": (stats.get("summary") or {}).get("owners"),
                "sales_people": (stats.get("summary") or {}).get("sales_people"),
                "item_type_counts": customers.get("item_type_counts") or {},
            },
            "users": users.get("users") or [],
            "by_owner": stats.get("by_owner") or [],
            "by_sales_name": stats.get("by_sales_name") or [],
            "tool_catalog": "list_tse_tool_catalog",
            "note": "TSE App 会话仅汇总当前用户可见客户，不做全库扫描",
        }
    all_docs = list_collection_rows("global_customers", field_paths=["item_type"], limit=0)
    item_type_counts: dict[str, int] = {}
    for row in all_docs["rows"]:
        bucket = (row.get("item_type") or "").strip() or "(empty)"
        item_type_counts[bucket] = item_type_counts.get(bucket, 0) + 1
    return {
        "ok": True,
        **meta_block(),
        "terminology": {
            "tse_user": "tse_workspaces = 登录用户配置",
            "tse_customer": "global_customers 非 knowledge",
            "daily_reports": "global_customers 内嵌数组",
        },
        "counts": {
            "tse_users": users["user_count"],
            "global_customers_scanned": all_docs["scanned_documents"],
            "customers_excluding_knowledge": customers["returned_count"],
            "customer_owners": stats["summary"]["owners"],
            "sales_people": stats["summary"]["sales_people"],
            "item_type_counts": item_type_counts,
        },
        "users": users["users"],
        "by_owner": stats["by_owner"],
        "by_sales_name": stats["by_sales_name"],
        "tool_catalog": "list_tse_tool_catalog",
    }


def get_tse_customer_sales_stats(
    include_knowledge: bool = False,
    limit: int = 5000,
    tool_context: Any = None,
) -> dict[str, Any]:
    """按 owner / sales_name 聚合客户统计。"""
    base = list_tse_customers(
        include_knowledge=include_knowledge, limit=limit, tool_context=tool_context
    )
    if not base.get("ok", True) and base.get("ok") is False:
        return base
    rows = base.get("rows") or []
    by_owner: dict[str, int] = {}
    by_sales: dict[str, int] = {}
    by_owner_sales: dict[str, dict[str, int]] = {}
    for row in rows:
        owner = (row.get("owner") or "").strip() or "(unknown_owner)"
        sales = (row.get("sales_name") or "").strip() or "(unknown_sales)"
        by_owner[owner] = by_owner.get(owner, 0) + 1
        by_sales[sales] = by_sales.get(sales, 0) + 1
        by_owner_sales.setdefault(owner, {})[sales] = by_owner_sales[owner].get(sales, 0) + 1

    owner_sales_rows = [
        {"owner": o, "sales_name": s, "customer_count": by_owner_sales[o][s]}
        for o in sorted(by_owner_sales)
        for s in sorted(by_owner_sales[o])
    ]
    sales_ranked = sorted(by_sales.items(), key=lambda kv: (-kv[1], kv[0]))
    sales_alias_map = {n: f"Sales{i + 1:02d}" for i, (n, _) in enumerate(sales_ranked)}
    sales_alias_legend = [
        {
            "sales_alias": sales_alias_map[name],
            "sales_name": name,
            "sales_label_en": to_chart_label(name),
            "customer_count": count,
        }
        for name, count in sales_ranked
    ]
    by_owner_sales_alias = [
        {
            "owner": r["owner"],
            "sales_alias": sales_alias_map[r["sales_name"]],
            "sales_name": r["sales_name"],
            "sales_label_en": to_chart_label(r["sales_name"]),
            "customer_count": r["customer_count"],
        }
        for r in owner_sales_rows
    ]
    return {
        "ok": True,
        **base,
        "summary": {
            "total_customers": len(rows),
            "owners": len(by_owner),
            "sales_people": len(by_sales),
        },
        "by_owner": [{"owner": o, "customer_count": by_owner[o]} for o in sorted(by_owner)],
        "by_sales_name": [
            {"sales_name": s, "customer_count": by_sales[s]} for s in sorted(by_sales)
        ],
        "by_owner_sales": owner_sales_rows,
        "chart_safe": {
            "by_owner_sales_alias": by_owner_sales_alias,
            "sales_alias_map": sales_alias_map,
            "sales_alias_legend": sales_alias_legend,
        },
    }


def get_tse_sales_customer_reports(
    sales_name: str,
    sample_reports_per_customer: int = 1,
    include_knowledge: bool = False,
    limit_customers: int = 200,
    tool_context: Any = None,
) -> dict[str, Any]:
    """按销售名列客户，并为每位客户随机抽取 daily_reports。"""
    sales = (sales_name or "").strip()
    if not sales:
        return {"ok": False, "error": {"code": "MISSING_SALES_NAME", "message": "sales_name 不能为空"}}
    per_customer = max(1, min(int(sample_reports_per_customer or 1), 5))
    cap = max(1, min(int(limit_customers or 200), 500))
    base = list_tse_customers(
        include_knowledge=include_knowledge,
        limit=0,
        sales_name=sales,
        tool_context=tool_context,
    )
    if not base.get("ok", True) and base.get("ok") is False:
        return base
    customer_rows = (base.get("rows") or [])[:cap]
    if not customer_rows:
        return {
            "ok": True,
            "sales_name": sales,
            "customer_count": 0,
            "customers": [],
            **meta_block(),
        }
    customers_out: list[dict[str, Any]] = []
    for row in customer_rows:
        doc_id = row["id"]
        doc = get_document(
            "global_customers",
            doc_id,
            field_paths=["name", "sales_name", "owner", "daily_reports"],
        )
        fields = doc.get("fields") or {}
        reports = parse_daily_reports(fields)
        picked = random.sample(reports, k=min(per_customer, len(reports))) if reports else []
        sampled = [
            {
                "id": rep.get("id") or "",
                "date": rep.get("date") or "",
                "raw_draft": truncate_text(rep.get("raw_draft") or ""),
                "ai_generated_content": truncate_text(rep.get("ai_generated_content") or ""),
                "created_at": rep.get("created_at") or "",
            }
            for rep in picked
        ]
        customers_out.append(
            {
                "id": doc_id,
                "name": row.get("name") or field_string(fields, "name"),
                "owner": row.get("owner") or field_string(fields, "owner"),
                "sales_name": sales,
                "daily_report_count": len(reports),
                "sampled_reports": sampled,
            }
        )
    return {
        "ok": True,
        "entity": "tse_customer_daily_reports",
        **meta_block(),
        "sales_name": sales,
        "customer_count": len(customers_out),
        "customers": customers_out,
        "warning": (
            "本工具仅随机抽样日报，不适合「是否提到/使用某产品」类问题；"
            "请改用 search_tse_daily_reports 或 ask_tse_workspace。"
        ),
    }


def _expand_search_keywords(keyword: str) -> list[str]:
    """把用户输入拆成查询词，并按别名表扩展（去重保序）。"""
    raw = (keyword or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,，|;/\s]+", raw) if p.strip()]
    if not parts:
        parts = [raw]
    out: list[str] = []
    seen: set[str] = set()
    for part in parts:
        candidates = _KEYWORD_ALIASES.get(part.lower(), (part,))
        for cand in candidates:
            key = cand.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(cand)
    return out


def _extract_keyword_snippet(text: str, needle: str, *, radius: int = 120) -> str:
    raw = text or ""
    if not raw or not needle:
        return truncate_text(raw, 240)
    lower = raw.lower()
    idx = lower.find(needle.lower())
    if idx < 0:
        return truncate_text(raw, 240)
    start = max(0, idx - radius)
    end = min(len(raw), idx + len(needle) + radius)
    snippet = raw[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(raw):
        snippet = snippet + "…"
    return snippet


def search_tse_daily_reports(
    keyword: str,
    sales_name: str = "",
    owner_email: str = "",
    date_from: str = "",
    date_to: str = "",
    limit_hits: int = 30,
    limit_customers: int = 500,
    include_knowledge: bool = False,
    tool_context: Any = None,
) -> dict[str, Any]:
    """服务端关键词检索日报正文，返回命中客户 + 原文 snippet。

    适用：「某销售客户有没有提到/用过 BigQuery」——禁止用随机抽样再让模型猜。
    ``keyword`` 支持空格/逗号分隔多词（OR）；常见别名（如 BQ→BigQuery）自动扩展。
    """
    owner_filter, access_email, scope_err = enforce_data_scope(
        tool_context, requested_owner_email=owner_email
    )
    if scope_err:
        return scope_err
    needles = _expand_search_keywords(keyword)
    if not needles:
        return {
            "ok": False,
            "error": {"code": "MISSING_KEYWORD", "message": "keyword 不能为空"},
        }

    start = normalize_report_date(date_from)
    end = normalize_report_date(date_to)
    if (date_from or "").strip() and not start:
        return {
            "ok": False,
            "error": {"code": "INVALID_DATE_FROM", "message": "date_from 无法解析，请用 YYYY-MM-DD"},
        }
    if (date_to or "").strip() and not end:
        return {
            "ok": False,
            "error": {"code": "INVALID_DATE_TO", "message": "date_to 无法解析，请用 YYYY-MM-DD"},
        }
    if start and end and start > end:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_DATE_RANGE",
                "message": f"date_from({start}) 不能晚于 date_to({end})",
            },
        }

    sales_filter = (sales_name or "").strip()
    hit_cap = max(1, min(int(limit_hits or 30), 100))
    customer_cap = max(1, min(int(limit_customers or 500), 2000))

    hits: list[dict[str, Any]] = []
    customers_scanned = 0
    customers_with_hits = 0
    truncated = False
    page_token = ""
    pages_fetched = 0
    customer_names: list[str] = []
    seen_customers: set[str] = set()

    while True:
        if customers_scanned >= customer_cap or len(hits) >= hit_cap:
            truncated = True
            break
        page_size = min(100, max(1, customer_cap - customers_scanned))
        args: dict[str, Any] = {
            "parent": parent_path(),
            "collectionId": "global_customers",
            "pageSize": page_size,
            "mask": {
                "fieldPaths": [
                    "name",
                    "owner",
                    "sales_name",
                    "item_type",
                    "viewers",
                    "daily_reports",
                ],
            },
        }
        if page_token:
            args["pageToken"] = page_token
        page = mcp_call("list_documents", args)
        pages_fetched += 1
        docs = page.get("documents") or []
        if not docs:
            break

        stop = False
        for doc in docs:
            if customers_scanned >= customer_cap or len(hits) >= hit_cap:
                truncated = True
                stop = True
                break
            fields = doc.get("fields") or {}
            item_type = row_item_type(fields)
            if not is_customer_row(item_type, include_knowledge=include_knowledge):
                continue
            sales = field_string(fields, "sales_name")
            owner = field_string(fields, "owner").lower()
            viewers = [v.lower() for v in field_string_array(fields, "viewers")]
            if sales_filter and sales != sales_filter:
                continue
            if owner_filter and owner != owner_filter:
                continue
            if access_email and not row_visible_to(owner, viewers, access_email):
                continue

            customers_scanned += 1
            full_name = str(doc.get("name") or "")
            doc_id = full_name.rsplit("/", 1)[-1] if "/" in full_name else full_name
            cname = field_string(fields, "name")
            reports = filter_reports_by_date(
                parse_daily_reports(fields),
                date_from=start,
                date_to=end,
            )
            customer_hit = False
            for rep in reports:
                if len(hits) >= hit_cap:
                    truncated = True
                    stop = True
                    break
                ai_text = rep.get("ai_generated_content") or ""
                draft_text = rep.get("raw_draft") or ""
                haystacks = (
                    ("ai_generated_content", ai_text),
                    ("raw_draft", draft_text),
                )
                matched_kw = ""
                matched_field = ""
                matched_text = ""
                for field_name, text in haystacks:
                    if not text:
                        continue
                    lower_text = text.lower()
                    for needle in needles:
                        if needle.lower() in lower_text:
                            matched_kw = needle
                            matched_field = field_name
                            matched_text = text
                            break
                    if matched_kw:
                        break
                if not matched_kw:
                    continue
                customer_hit = True
                hits.append(
                    {
                        "item_id": doc_id,
                        "customer_name": cname,
                        "sales_name": sales,
                        "owner": owner,
                        "report_id": rep.get("id") or "",
                        "date": rep.get("date") or "",
                        "matched_keyword": matched_kw,
                        "matched_field": matched_field,
                        "snippet": _extract_keyword_snippet(matched_text, matched_kw),
                    }
                )
                if doc_id not in seen_customers:
                    seen_customers.add(doc_id)
                    customer_names.append(cname)
            if customer_hit:
                customers_with_hits += 1
            if stop:
                break

        if stop:
            break
        page_token = str(page.get("nextPageToken") or "")
        if not page_token:
            break

    hits.sort(
        key=lambda r: (
            normalize_report_date(r.get("date") or "") or "",
            r.get("customer_name") or "",
        ),
        reverse=True,
    )
    return {
        "ok": True,
        "entity": "tse_daily_report_keyword_hits",
        **meta_block(),
        "keyword": (keyword or "").strip(),
        "keywords_expanded": needles,
        "filters": {
            "sales_name": sales_filter or None,
            "owner_email": owner_filter or None,
            "date_from": start or None,
            "date_to": end or None,
            "include_knowledge": include_knowledge,
        },
        "pages_fetched": pages_fetched,
        "customers_scanned": customers_scanned,
        "customers_with_hits": customers_with_hits,
        "hit_count": len(hits),
        "truncated": truncated,
        "customer_names_in_hits": customer_names,
        "hits": hits,
        "principal_email": access_email or None,
        "grounding_rules": [
            "只能引用 customer_names_in_hits / hits 中的客户名，禁止编造名单外客户",
            "每条结论须带：客户名 + 日期 + snippet 原文摘录",
            "命中仅表示日报正文出现关键词，不等于客户已在生产使用该产品；证据不足须如实说明",
            "hit_count=0 时明确说检索范围内未发现，禁止用训练知识补客户",
        ],
    }


def set_tse_session_api_key(
    api_key: str,
    verify: bool = True,
    tool_context: Any = None,
) -> dict[str, Any]:
    """将用户提供的 TSE API Key 写入**当前 ADK Session**（非 Memory Bank）。

    用户在私聊中给出 Key 后调用本工具；禁止在回复中回显完整 Key，禁止写入长期记忆。
    ``verify=true``（默认）时会请求 ``/system/status`` 校验 Key。
    """
    key = (api_key or "").strip()
    # 允许用户消息里夹杂说明文字时，尽量抽出 sk_tse_… 形态
    if key and "sk_tse_" in key and not key.startswith("sk_tse_"):
        m = re.search(r"sk_tse_[A-Za-z0-9_\-]+", key)
        if m:
            key = m.group(0)
    if not key:
        return {
            "ok": False,
            "error": {"code": "MISSING_API_KEY", "message": "api_key 不能为空"},
        }
    if not tse_api_base_url():
        return {
            "ok": False,
            "error": {
                "code": "NEED_TSE_API_BASE_URL",
                "message": "服务端未配置 TSE_API_BASE_URL，无法校验/调用 TSE API",
            },
        }

    target_email = ""
    if verify:
        probe = call_tse_external(
            "GET",
            "/api/external/v1/system/status",
            api_key=key,
            timeout=60,
        )
        if not probe.get("ok"):
            err = probe.get("error") or {}
            return {
                "ok": False,
                "error": {
                    "code": err.get("code") or "TSE_API_KEY_VERIFY_FAILED",
                    "message": err.get("message") or "Key 校验失败",
                },
                "api_key_masked": mask_api_key(key),
                "hint": "请确认 Key 未撤销，且来自正确的 TSE 工作台",
            }
        data = probe.get("data") or {}
        if isinstance(data, dict):
            target_email = str(
                data.get("target_email") or data.get("email") or ""
            ).strip()

    try:
        set_session_api_key(tool_context, key, target_email=target_email)
    except RuntimeError as exc:
        return {
            "ok": False,
            "error": {"code": "SESSION_STATE_UNAVAILABLE", "message": str(exc)},
        }

    status = tse_api_status(tool_context)
    return {
        "ok": True,
        "entity": "tse_session_api_key",
        "stored": True,
        "verified": bool(verify),
        "api_key_masked": status.get("api_key_masked"),
        "target_email": status.get("target_email"),
        "session_key_set_at": status.get("session_key_set_at"),
        "grounding_rules": [
            "禁止在对用户回复中输出完整 api_key",
            "禁止把 Key 写入 Memory Bank / load_memory 相关内容",
            "群聊场景提醒用户改私聊；本 Key 仅本会话有效",
        ],
    }


def clear_tse_session_api_key(tool_context: Any) -> dict[str, Any]:
    """清除当前 Session 中的 TSE API Key。"""
    clear_session_api_key(tool_context)
    return {
        "ok": True,
        "entity": "tse_session_api_key",
        "cleared": True,
        "api": tse_api_status(tool_context),
    }


def tse_session_api_key_status(tool_context: Any) -> dict[str, Any]:
    """查看本会话是否已绑定 TSE API Key（仅脱敏信息）。"""
    status = tse_api_status(tool_context)
    return {
        "ok": True,
        "entity": "tse_session_api_key_status",
        **status,
        "hint": (
            None
            if status.get("ready_for_chat_or_report")
            else "未就绪：缺 base_url 或会话 Key；开放语义请先 set_tse_session_api_key，"
            "或改用 search_tse_daily_reports"
        ),
    }


def ask_tse_workspace(
    question: str,
    history_json: str = "",
    tool_context: Any = None,
) -> dict[str, Any]:
    """调用 TSE 外部 API ``POST /chat``：全量历史注入 + 强制信源的开放语义问答。

    适用：风险梳理、跨客户进展、需要全量上下文的分析。
    精确关键词证据优先 ``search_tse_daily_reports``；名单/数量仍用确定性 list/get 工具。
    需要本会话已 ``set_tse_session_api_key``（或运维配置了可选 env 回落 Key）。
    """
    q = (question or "").strip()
    if not q:
        return {
            "ok": False,
            "error": {"code": "MISSING_QUESTION", "message": "question 不能为空"},
        }

    status = tse_api_status(tool_context)
    if not status.get("base_url_configured"):
        return {
            "ok": False,
            "entity": "tse_workspace_chat",
            "api": status,
            "error": {
                "code": "NEED_TSE_API_BASE_URL",
                "message": "服务端未配置 TSE_API_BASE_URL",
            },
        }
    if not status.get("api_key_present"):
        return {
            **need_tse_api_key_error(),
            "entity": "tse_workspace_chat",
            "api": status,
            "wait_user": True,
            "blocked_reason": "waiting_tse_api_key",
            "fallback_hint": (
                "禁止自动改用 search_tse_daily_reports / 空分析写飞书表来绕过。"
                "必须：把 user_prompt 发给用户 → 等 Key → set_tse_session_api_key → 重试 ask_tse_workspace。"
                "task_card_upsert(status=blocked, blocked_reason=waiting_tse_api_key)，然后结束本轮。"
            ),
        }

    messages: list[dict[str, str]] = []
    raw_hist = (history_json or "").strip()
    if raw_hist:
        try:
            parsed = json.loads(raw_hist)
            if isinstance(parsed, list):
                for item in parsed:
                    if not isinstance(item, dict):
                        continue
                    role = str(item.get("role") or "").strip().lower()
                    content = str(item.get("content") or "").strip()
                    if role in {"user", "assistant"} and content:
                        messages.append({"role": role, "content": content})
        except json.JSONDecodeError:
            return {
                "ok": False,
                "error": {
                    "code": "INVALID_HISTORY_JSON",
                    "message": "history_json 必须是 JSON 数组，元素含 role/content",
                },
            }
    messages.append({"role": "user", "content": q})

    result = call_tse_external(
        "POST",
        "/api/external/v1/chat",
        json_body={"messages": messages},
        timeout=240,
        tool_context=tool_context,
    )
    status = tse_api_status(tool_context)
    if not result.get("ok"):
        out = {
            **result,
            "entity": "tse_workspace_chat",
            "api": status,
            "fallback_hint": (
                "失败时可改用 search_tse_daily_reports；"
                "若 Key 无效请重新 set_tse_session_api_key。"
            ),
        }
        return out

    data = result.get("data") or {}
    reply = ""
    if isinstance(data, dict):
        reply = str(data.get("reply") or "")
    return {
        "ok": True,
        "entity": "tse_workspace_chat",
        **meta_block(),
        "api": {
            "api_key_source": status.get("api_key_source"),
            "api_key_masked": status.get("api_key_masked"),
            "target_email": status.get("target_email"),
            "base_url": status.get("base_url"),
        },
        "question": q,
        "reply": reply,
        "grounding_rules": [
            "向用户转述时保留 reply 中的【参考信源】；禁止另造客户名或日期",
            "若 reply 声明无可考证/不知道，如实告知用户，勿用训练知识补全",
            "数据范围跟随当前会话 Key 绑定邮箱的可见客户（含只读共享）",
            "禁止回显完整 API Key",
        ],
    }


def generate_tse_global_report(
    start_date: str,
    end_date: str,
    prompt_name: str = "",
    tool_context: Any = None,
) -> dict[str, Any]:
    """调用 TSE 外部 API ``POST /global_report`` 生成全局工作大盘（总览汇报）。

    仅用于「出一份全局大盘/工作总览」；定向语义问答请用 ask_tse_workspace，
    关键词证据请用 search_tse_daily_reports。
    """
    start = normalize_report_date(start_date)
    end = normalize_report_date(end_date)
    if not start or not end:
        return {
            "ok": False,
            "error": {
                "code": "MISSING_DATE_RANGE",
                "message": "start_date / end_date 必填，格式 YYYY-MM-DD",
            },
        }
    if start > end:
        return {
            "ok": False,
            "error": {
                "code": "INVALID_DATE_RANGE",
                "message": f"start_date({start}) 不能晚于 end_date({end})",
            },
        }

    status = tse_api_status(tool_context)
    if not status.get("base_url_configured"):
        return {
            "ok": False,
            "entity": "tse_global_report",
            "api": status,
            "error": {
                "code": "NEED_TSE_API_BASE_URL",
                "message": "服务端未配置 TSE_API_BASE_URL",
            },
        }
    if not status.get("api_key_present"):
        return {
            **need_tse_api_key_error(),
            "entity": "tse_global_report",
            "api": status,
            "fallback_hint": (
                "也可用 query_tse_daily_reports_by_date 拉时段日报后归纳；"
                "或 search_tse_daily_reports 做关键词证据。"
            ),
        }

    body: dict[str, Any] = {"startDate": start, "endDate": end}
    pname = (prompt_name or "").strip()
    if pname:
        body["usePromptName"] = pname

    result = call_tse_external(
        "POST",
        "/api/external/v1/global_report",
        json_body=body,
        timeout=300,
        tool_context=tool_context,
    )
    status = tse_api_status(tool_context)
    if not result.get("ok"):
        return {
            **result,
            "entity": "tse_global_report",
            "api": status,
            "fallback_hint": (
                "失败时可改用 query_tse_daily_reports_by_date / search_tse_daily_reports；"
                "Key 无效请重新 set_tse_session_api_key。"
            ),
        }

    data = result.get("data") or {}
    report = ""
    if isinstance(data, dict):
        report = str(data.get("generated_report") or "")
    return {
        "ok": True,
        "entity": "tse_global_report",
        **meta_block(),
        "api": {
            "api_key_source": status.get("api_key_source"),
            "api_key_masked": status.get("api_key_masked"),
            "target_email": status.get("target_email"),
            "base_url": status.get("base_url"),
        },
        "start_date": start,
        "end_date": end,
        "prompt_name": pname or None,
        "generated_report": report,
        "grounding_rules": [
            "原样转述大盘结论；禁止添加报告中不存在的客户或产品断言",
            "本工具只适合总览汇报，不适合回答「某销售某客户有没有用 X」",
            "禁止回显完整 API Key",
        ],
    }


def _filter_shares(
  rows: list[dict[str, Any]],
  *,
  recipient_email: str = "",
  sender_email: str = "",
  status: str = "",
) -> list[dict[str, Any]]:
    recipient = (recipient_email or "").strip().lower()
    sender = (sender_email or "").strip().lower()
    status_filter = (status or "").strip().lower()
    out: list[dict[str, Any]] = []
    for row in rows:
        if recipient and (row.get("recipient_email") or "").lower() != recipient:
            continue
        if sender and (row.get("sender_email") or "").lower() != sender:
            continue
        if status_filter and (row.get("status") or "").lower() != status_filter:
            continue
        out.append(row)
    return out


def list_tse_pending_shares(
    recipient_email: str, limit: int = 200, tool_context: Any = None
) -> dict[str, Any]:
    """待审批分享（recipient_email + status=pending）。"""
    email = (recipient_email or "").strip().lower()
    if not email:
        return {"ok": False, "error": {"code": "MISSING_EMAIL", "message": "recipient_email 不能为空"}}
    _owner, access_email, scope_err = enforce_data_scope(
        tool_context, requested_user_email=email
    )
    if scope_err:
        return scope_err
    if access_email:
        email = access_email
    listed = list_collection_rows(
        "shares",
        field_paths=[
            "sender_email",
            "recipient_email",
            "status",
            "share_type",
            "timestamp",
            "customers_bundle",
        ],
        limit=0,
    )
    rows = _filter_shares(listed["rows"], recipient_email=email, status="pending")[:limit]
    return {
        "ok": True,
        "entity": "tse_pending_shares",
        **meta_block(),
        "recipient_email": email,
        "pending_count": len(rows),
        "shares": rows,
        "principal_email": access_email or None,
    }


def list_tse_shares(
    sender_email: str = "",
    recipient_email: str = "",
    status: str = "",
    limit: int = 200,
    tool_context: Any = None,
) -> dict[str, Any]:
    """分享/审批记录列表（按 sender 或 recipient 过滤）。"""
    sender = (sender_email or "").strip().lower()
    recipient = (recipient_email or "").strip().lower()
    principal = resolve_tse_principal(tool_context)
    if principal.get("scoped"):
        email = str(principal["email"])
        if sender and sender != email:
            return cross_user_forbidden(email, sender)
        if recipient and recipient != email:
            return cross_user_forbidden(email, recipient)
        # 未指定方向时：只返回与本人相关的分享
        if not sender and not recipient:
            listed = list_collection_rows(
                "shares",
                field_paths=[
                    "sender_email",
                    "recipient_email",
                    "status",
                    "share_type",
                    "timestamp",
                ],
                limit=0,
            )
            related = [
                r
                for r in listed["rows"]
                if (r.get("sender_email") or "").lower() == email
                or (r.get("recipient_email") or "").lower() == email
            ]
            if status:
                related = [
                    r
                    for r in related
                    if (r.get("status") or "").lower() == status.strip().lower()
                ]
            rows = related[: max(1, min(limit, 500))]
            return {
                "ok": True,
                "entity": "tse_shares",
                **meta_block(),
                "returned_count": len(rows),
                "shares": rows,
                "principal_email": email,
            }
    listed = list_collection_rows(
        "shares",
        field_paths=[
            "sender_email",
            "recipient_email",
            "status",
            "share_type",
            "timestamp",
        ],
        limit=0,
    )
    rows = _filter_shares(
        listed["rows"],
        sender_email=sender,
        recipient_email=recipient,
        status=status,
    )[: max(1, min(limit, 500))]
    return {
        "ok": True,
        "entity": "tse_shares",
        **meta_block(),
        "returned_count": len(rows),
        "shares": rows,
    }


def get_tse_share(share_id: str) -> dict[str, Any]:
    """单条分享审批详情。"""
    sid = (share_id or "").strip()
    if not sid:
        return {"ok": False, "error": {"code": "MISSING_SHARE_ID", "message": "share_id 不能为空"}}
    doc = get_document(
        "shares",
        sid,
        field_paths=[
            "sender_email",
            "recipient_email",
            "status",
            "share_type",
            "timestamp",
            "customers_bundle",
        ],
    )
    fields = doc.get("fields") or {}
    return {
        "ok": True,
        "entity": "tse_share_detail",
        **meta_block(),
        "share": {
            "id": sid,
            "sender_email": field_string(fields, "sender_email"),
            "recipient_email": field_string(fields, "recipient_email"),
            "status": field_string(fields, "status"),
            "share_type": field_string(fields, "share_type"),
            "timestamp": field_string(fields, "timestamp"),
        },
    }


def list_tse_api_keys(
    target_email: str,
    limit: int = 50,
    tool_context: Any = None,
) -> dict[str, Any]:
    """列出某用户代理的 API Key（Document ID 脱敏）。Key 主体优先 External API。"""
    email = (target_email or "").strip().lower()
    if not email:
        return {"ok": False, "error": {"code": "MISSING_EMAIL", "message": "target_email 不能为空"}}

    api_status = tse_api_status(tool_context)
    key_email = str(api_status.get("target_email") or "").strip().lower()
    if tse_api_ready_for_scoped_reads(tool_context) and (not key_email or key_email == email):
        result = call_tse_external(
            "GET",
            "/api/external/v1/api_keys",
            tool_context=tool_context,
            timeout=60,
        )
        if result.get("ok") and isinstance(result.get("data"), list):
            rows: list[dict[str, str]] = []
            for item in result["data"]:
                if not isinstance(item, dict):
                    continue
                raw_key = str(item.get("key") or item.get("id") or "")
                rows.append(
                    {
                        "key_id_masked": mask_api_key(raw_key) if raw_key else "",
                        "name": str(item.get("name") or ""),
                        "created_at": str(item.get("created_at") or ""),
                        "target_email": key_email or email,
                    }
                )
                if len(rows) >= limit:
                    break
            return {
                "ok": True,
                "entity": "tse_api_keys",
                "access_path": "tse_api",
                **meta_block(),
                "target_email": key_email or email,
                "key_count": len(rows),
                "keys": rows,
                "note": "完整 Key 禁止在回复中输出。",
            }

    listed = list_collection_rows("api_keys", field_paths=["target_email", "name", "created_at"], limit=0)
    rows = []
    for row in listed["rows"]:
        if (row.get("target_email") or "").lower() != email:
            continue
        rows.append(
            {
                "key_id_masked": mask_secret(row.get("id") or ""),
                "name": row.get("name") or "",
                "created_at": row.get("created_at") or "",
                "target_email": email,
            }
        )
        if len(rows) >= limit:
            break
    return {
        "ok": True,
        "entity": "tse_api_keys",
        "access_path": "firestore_mcp",
        **meta_block(),
        "target_email": email,
        "key_count": len(rows),
        "keys": rows,
        "note": "完整 Key 禁止在回复中输出。",
    }


async def render_tse_customer_sales_chart(tool_context: Any) -> dict[str, Any]:
    """用真实统计生成 owner×sales 堆叠图。"""
    from smart_agents.code_exec import code_exec_enabled, run_code

    if not code_exec_enabled():
        return {
            "ok": False,
            "error": {"code": "CODE_EXEC_DISABLED", "message": "需要 CODE_EXECUTION_ENABLED"},
        }
    stats = get_tse_customer_sales_stats(include_knowledge=False, limit=0)
    chart = stats.get("chart_safe") or {}
    rows = chart.get("by_owner_sales_alias") or []
    if not rows:
        return {"ok": False, "error": {"code": "NO_DATA", "message": "无客户数据"}}
    legend_rows = chart.get("sales_alias_legend") or []
    code = f"""import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
rows = {json.dumps(rows, ensure_ascii=False)}
legend_rows = {json.dumps(legend_rows, ensure_ascii=False)}
df = pd.DataFrame(rows)
owners = list(df.groupby("owner")["customer_count"].sum().sort_values(ascending=False).index)
sales_aliases = [r["sales_alias"] for r in legend_rows]
alias_labels = {{r["sales_alias"]: f"{{r['sales_alias']}} | {{r['sales_label_en']}} ({{int(r['customer_count'])}})" for r in legend_rows}}
fig, ax = plt.subplots(figsize=(max(10, len(owners)*2.8), 7))
bottom = np.zeros(len(owners))
colors = plt.cm.tab20(np.linspace(0, 1, max(len(sales_aliases), 1)))
for idx, alias in enumerate(sales_aliases):
    vals = [int(df[(df["owner"]==o)&(df["sales_alias"]==alias)]["customer_count"].sum()) for o in owners]
    ax.bar(owners, vals, bottom=bottom, label=alias_labels.get(alias, alias), color=colors[idx % len(colors)])
    bottom += np.array(vals, dtype=float)
ax.set_title("TSE Customer Distribution by Owner and Sales")
ax.set_ylabel("Number of Customers")
plt.xticks(rotation=30, ha="right")
ax.legend(fontsize=7, bbox_to_anchor=(1.02, 1))
plt.tight_layout()
plt.savefig("tse_customer_sales_chart.png", dpi=150)
print("total", int(df["customer_count"].sum()))
"""
    result = await run_code(code, tool_context)
    return {
        "ok": bool(result.get("ok")),
        "tool": "render_tse_customer_sales_chart",
        "data": {"stats_summary": stats.get("summary"), "sales_alias_legend": legend_rows, **(result.get("data") or {})},
        "error": result.get("error"),
    }


def build_tse_tools(*, include_chart: bool = True) -> list[Callable[..., Any]]:
    """注册到 Dispatcher 的 TSE 确定性工具列表。"""
    tools: list[Callable[..., Any]] = [
        list_tse_tool_catalog,
        lookup_tse_schema,
        get_tse_overview,
        list_tse_users,
        get_tse_user_workspace,
        list_tse_items_for_user,
        list_tse_customers,
        get_tse_customer,
        get_tse_customer_daily_reports,
        query_tse_daily_reports_by_date,
        search_tse_daily_reports,
        set_tse_session_api_key,
        clear_tse_session_api_key,
        tse_session_api_key_status,
        ask_tse_workspace,
        generate_tse_global_report,
        map_tse_daily_reports_to_bitable,
        get_tse_sales_customer_reports,
        get_tse_customer_sales_stats,
        list_tse_pending_shares,
        list_tse_shares,
        get_tse_share,
        list_tse_api_keys,
    ]
    if include_chart:
        tools.append(render_tse_customer_sales_chart)
    return tools


def dispatcher_instruction_block() -> str:
    catalog_lines = "\n".join(
        f"  - [{row.get('path', '?')}] {row['intent']} → `{row['tool']}`"
        for row in TSE_TOOL_CATALOG
    )
    meta = meta_block()
    api = tse_api_status()
    base = api.get("base_url") or "(未配置 TSE_API_BASE_URL)"
    return f"""

【TSE 数据访问（Lab-00）】
- **优先级**：`API + 确定性工具 > Firestore MCP 兜底 > Knowledge Catalog（可选）`；BigQuery 仅审计（未启用）
- 项目 `{meta["project_id"]}`；库 `{meta["database"]}`；TSE API：`{base}`
- **会话 API Key**：私聊 → `set_tse_session_api_key`。禁止写入 Memory；禁止回显完整 Key；群聊改私聊。
- 若返回 `NEED_TSE_API_KEY`：把 `user_prompt` 发给用户 → `task_card_upsert(status=blocked, blocked_reason=waiting_tse_api_key)` → **结束本轮等用户**；
  Key 后立刻 `set_tse_session_api_key` → 重试。**禁止**用 search_tse 绕过写飞书表。
- **业务必须先** `list_tse_tool_catalog`，再调场景工具；**禁止**用裸 `fs_*` / `kc_*` 回答客户/日报问题
- 术语不清 → `lookup_tse_schema`（内嵌 Glossary）；`kc_*` 仅元数据发现，非默认依赖
- 有会话 Key 时：名单/详情/单客户日报/本人 settings/api_keys **优先走 External API**（工具返回 `access_path=tse_api`）
- **指定时间段跨客户日报** → `query_tse_daily_reports_by_date`（Firestore 兜底；API 尚无对等）
- **关键词证据** → `search_tse_daily_reports`（无需 Key）；禁止随机抽样后猜
- **开放语义** → `ask_tse_workspace`；**大盘总览** → `generate_tse_global_report`（均需 Key）
- **写入已有多维表格** → 先 `feishu_bitable_field_list`，再 `map_tse_daily_reports_to_bitable`
- `fs_*`（只读）仅排障/探 schema；`shares` / 跨租户总览 / 关键词扫描仍用下方 Firestore 标注工具

【TSE 场景工具目录】（括号内为 path）
{catalog_lines}

【强约束 / Grounding】
- 日报 = global_customers.daily_reports[]；销售名单浏览 → get_tse_sales_customer_reports（禁止语义判断）
- 关键词证据 → search_tse_daily_reports；开放语义 → ask_tse_workspace；大盘 → generate_tse_global_report
- **客户名只能来自工具返回**；引用须 **客户名 + 日期 + snippet**；0 命中如实说未发现
- 「日报提到 X」≠「已在生产使用 X」
- 「本月」用【当前日期】的 month_start～month_end，禁止默认 2024
- 技术知识库 → search_tse_knowledge / rag_search（不读 Firestore knowledge）
- api_keys 脱敏；**Firestore 只读**：禁止 fs 写；修改须在 TSE App
"""
