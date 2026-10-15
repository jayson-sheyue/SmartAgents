# -*- coding: utf-8 -*-
"""TSE Firestore 只读访问层（MCP get/list，供 tse_tools 使用）。"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

import google.auth
import requests
from google.auth.transport.requests import Request

_DEFAULT_FIRESTORE_URL = "https://firestore.googleapis.com/mcp"
_CLOUD_PLATFORM_SCOPE = ("https://www.googleapis.com/auth/cloud-platform",)

_MAX_REPORT_TEXT_CHARS = 4000


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def tse_firestore_project_id() -> str:
    return (
        (os.getenv("TSE_FIRESTORE_PROJECT_ID") or "").strip()
        or (os.getenv("GCP_PROJECT_ID") or "").strip()
        or (os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()
    )


def tse_firestore_database() -> str:
    return (os.getenv("TSE_FIRESTORE_DATABASE") or "tse-jayson-database").strip()


def firestore_mcp_url() -> str:
    return (os.getenv("FIRESTORE_MCP_URL") or _DEFAULT_FIRESTORE_URL).strip()


def customer_item_type_filter() -> str:
    return (os.getenv("TSE_CUSTOMER_ITEM_TYPE") or "customer").strip()


def strict_customer_item_type() -> bool:
    return _env_bool("TSE_CUSTOMER_STRICT_ITEM_TYPE", False)


@lru_cache(maxsize=1)
def _adc_credentials():
    credentials, _ = google.auth.default(scopes=list(_CLOUD_PLATFORM_SCOPE))
    return credentials


def refresh_adc_token() -> str:
    credentials = _adc_credentials()
    if not credentials.valid:
        credentials.refresh(Request())
    token = credentials.token
    if not token:
        raise RuntimeError(
            "无法获取 GCP ADC access token；请运行 gcloud auth application-default login"
        )
    return token


def parent_path() -> str:
    project = tse_firestore_project_id()
    if not project:
        raise RuntimeError("TSE_FIRESTORE_PROJECT_ID / GCP_PROJECT_ID 未设置")
    return f"projects/{project}/databases/{tse_firestore_database()}/documents"


def mcp_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {refresh_adc_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    resp = requests.post(firestore_mcp_url(), headers=headers, json=payload, timeout=120)
    if resp.status_code != 200:
        raise RuntimeError(f"Firestore MCP HTTP {resp.status_code}: {resp.text[:800]}")
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"Firestore MCP error: {body['error']}")
    content = ((body.get("result") or {}).get("content") or [])
    if not content or not content[0].get("text"):
        return {}
    return json.loads(content[0]["text"])


def field_string(fields: dict[str, Any], name: str) -> str:
    value = fields.get(name) or {}
    return str(value.get("stringValue") or "")


def field_string_array(fields: dict[str, Any], name: str) -> list[str]:
    raw = fields.get(name) or {}
    values = (raw.get("arrayValue") or {}).get("values") or []
    out: list[str] = []
    for item in values:
        s = str(item.get("stringValue") or "").strip()
        if s:
            out.append(s)
    return out


def row_item_type(fields: dict[str, Any]) -> str:
    return field_string(fields, "item_type").strip()


def is_customer_row(item_type: str, *, include_knowledge: bool) -> bool:
    if include_knowledge:
        return True
    it = (item_type or "").strip().lower()
    if it == "knowledge":
        return False
    if strict_customer_item_type():
        return it == customer_item_type_filter().lower()
    return True


def is_knowledge_row(item_type: str) -> bool:
    return (item_type or "").strip().lower() == "knowledge"


def truncate_text(text: str, limit: int = _MAX_REPORT_TEXT_CHARS) -> str:
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "…(truncated)"


def normalize_report_date(value: str) -> str:
    """Normalize TSE report date to ``YYYY-MM-DD`` for lexicographic compare.

    Accepts ``YYYY-MM-DD``, ``YYYY/MM/DD``, and ISO datetimes (``YYYY-MM-DDTHH:MM…``).
    Returns empty string when unparseable.
    """
    raw = (value or "").strip()
    if not raw:
        return ""
    # ISO / datetime prefix
    if len(raw) >= 10 and raw[4] in "-/" and raw[7] in "-/":
        y, m, d = raw[0:4], raw[5:7], raw[8:10]
        if y.isdigit() and m.isdigit() and d.isdigit():
            return f"{y}-{m}-{d}"
    # Compact YYYYMMDD
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        y, m, d = digits[0:4], digits[4:6], digits[6:8]
        if 1 <= int(m) <= 12 and 1 <= int(d) <= 31:
            return f"{y}-{m}-{d}"
    return ""


def report_in_date_range(
    date_value: str,
    *,
    date_from: str = "",
    date_to: str = "",
) -> bool:
    """Inclusive date filter. Empty bound = open side. Unparseable dates excluded when any bound set."""
    start = normalize_report_date(date_from)
    end = normalize_report_date(date_to)
    if not start and not end:
        return True
    day = normalize_report_date(date_value)
    if not day:
        return False
    if start and day < start:
        return False
    if end and day > end:
        return False
    return True


def filter_reports_by_date(
    reports: list[dict[str, Any]],
    *,
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    if not (date_from or "").strip() and not (date_to or "").strip():
        return list(reports)
    return [
        r
        for r in reports
        if report_in_date_range(
            str(r.get("date") or ""),
            date_from=date_from,
            date_to=date_to,
        )
    ]


def parse_daily_reports(fields: dict[str, Any]) -> list[dict[str, str]]:
    raw = fields.get("daily_reports") or {}
    values = (raw.get("arrayValue") or {}).get("values") or []
    reports: list[dict[str, str]] = []
    for item in values:
        mf = (item.get("mapValue") or {}).get("fields") or {}
        reports.append(
            {
                "id": field_string(mf, "id"),
                "date": field_string(mf, "date"),
                "raw_draft": field_string(mf, "raw_draft"),
                "ai_generated_content": field_string(mf, "ai_generated_content"),
                "created_at": field_string(mf, "created_at"),
            }
        )
    return reports


def parse_map_value(field: dict[str, Any]) -> dict[str, Any]:
    """浅层解析 Firestore mapValue（仅 string/bool 子字段）。"""
    mf = (field or {}).get("mapValue", {}).get("fields") or {}
    out: dict[str, Any] = {}
    for key, value in mf.items():
        if "stringValue" in value:
            out[key] = value["stringValue"]
        elif "booleanValue" in value:
            out[key] = value["booleanValue"]
        elif "mapValue" in value:
            out[key] = parse_map_value(value)
        elif "arrayValue" in value:
            vals = (value.get("arrayValue") or {}).get("values") or []
            items: list[Any] = []
            for v in vals:
                if "stringValue" in v:
                    items.append(v["stringValue"])
                elif "mapValue" in v:
                    items.append(parse_map_value(v))
            out[key] = items
    return out


def mask_secret(value: str, *, visible_tail: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= visible_tail + 3:
        return "***"
    return raw[:7] + "…" + raw[-visible_tail:]


def get_document(
    collection_id: str,
    doc_id: str,
    *,
    field_paths: list[str],
) -> dict[str, Any]:
    return mcp_call(
        "get_document",
        {
            "name": f"{parent_path()}/{collection_id}/{doc_id}",
            "mask": {"fieldPaths": field_paths},
        },
    )


def list_collection_rows(
    collection_id: str,
    *,
    field_paths: list[str],
    limit: int = 5000,
) -> dict[str, Any]:
    unlimited = limit <= 0
    effective_limit = 20000 if unlimited else min(limit, 20000)
    rows: list[dict[str, Any]] = []
    scanned = 0
    page_token = ""
    pages_fetched = 0
    while True:
        page_size = 300 if unlimited else min(300, effective_limit - len(rows) or 300)
        args: dict[str, Any] = {
            "parent": parent_path(),
            "collectionId": collection_id,
            "pageSize": page_size,
            "mask": {"fieldPaths": field_paths},
        }
        if page_token:
            args["pageToken"] = page_token
        page = mcp_call("list_documents", args)
        pages_fetched += 1
        for doc in page.get("documents") or []:
            scanned += 1
            fields = doc.get("fields") or {}
            full_name = str(doc.get("name") or "")
            did = full_name.rsplit("/", 1)[-1] if "/" in full_name else full_name
            row: dict[str, Any] = {"id": did, "_fields": fields}
            for path in field_paths:
                if path == "viewers":
                    row[path] = field_string_array(fields, path)
                else:
                    row[path] = field_string(fields, path)
            rows.append(row)
            if not unlimited and len(rows) >= effective_limit:
                break
        if not unlimited and len(rows) >= effective_limit:
            break
        page_token = str(page.get("nextPageToken") or "")
        if not page_token:
            break
    return {
        "scanned_documents": scanned,
        "pages_fetched": pages_fetched,
        "returned_count": len(rows),
        "truncated": (not unlimited) and len(rows) >= effective_limit,
        "rows": rows,
    }


def meta_block() -> dict[str, str]:
    return {
        "project_id": tse_firestore_project_id(),
        "database": tse_firestore_database(),
    }
