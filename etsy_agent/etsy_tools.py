# -*- coding: utf-8 -*-
"""
etsy_agent/etsy_tools.py — Etsy Open API v3 工具层（L1）

直接调用官方 REST API。
返回标准 envelope 格式（ok / tool / data / error / meta）。

接口文档：https://developer.etsy.com/documentation/
评论接口：GET /v3/application/listings/{listing_id}/reviews
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any

import pandas as pd
import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

ETSY_API_BASE = "https://openapi.etsy.com/v3/application"
DEFAULT_EXPORT_PATH = os.path.join(
    os.path.expanduser("~"), "Documents", "EtsyData", "etsy_reviews.xlsx"
)
ALLOWED_EXCEL_ROOTS = [
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Documents", "EtsyData"),
]

REVIEW_COLUMNS = [
    "platform",
    "listing_id",
    "listing_url",
    "review_id",
    "shop_id",
    "rating",
    "review_text",
    "language",
    "buyer_user_id",
    "created_timestamp",
    "updated_timestamp",
    "image_url",
    "scraped_at",
]

_SESSION = requests.Session()
_SESSION.trust_env = False


def _tool_ok(tool: str, data: dict, meta: dict | None = None) -> dict:
    return {"ok": True, "tool": tool, "data": data, "error": None, "meta": meta or {}}


def _tool_err(
    tool: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    data: dict | None = None,
    meta: dict | None = None,
) -> dict:
    return {
        "ok": False,
        "tool": tool,
        "data": data or {},
        "error": {"code": code, "message": message, "retryable": retryable},
        "meta": meta or {},
    }


def _strip_env(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    return text


def get_etsy_api_key() -> tuple[str | None, str]:
    """读取 x-api-key 值（格式 keystring:shared_secret）。"""
    combined = _strip_env(os.getenv("ETSY_API_KEY"))
    if combined and ":" in combined:
        ks, sec = combined.split(":", 1)
        ks, sec = _strip_env(ks), _strip_env(sec)
        if ks and sec:
            return f"{ks}:{sec}", "ETSY_API_KEY"

    ks = _strip_env(os.getenv("ETSY_KEYSTRING"))
    sec = _strip_env(os.getenv("ETSY_SHARED_SECRET"))
    if ks and sec:
        return f"{ks}:{sec}", "ETSY_KEYSTRING+ETSY_SHARED_SECRET"
    return None, ""


def extract_listing_id(listing_url_or_id: str) -> str:
    raw = (listing_url_or_id or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        return raw
    m = re.search(r"/listing/(\d+)", raw)
    return m.group(1) if m else ""


def _resolve_excel_path(excel_path: str | None) -> str:
    raw = excel_path or DEFAULT_EXPORT_PATH
    path = os.path.abspath(os.path.expanduser(raw))
    for root in ALLOWED_EXCEL_ROOTS:
        allowed = os.path.abspath(root)
        if path == allowed or path.startswith(allowed + os.sep):
            return path
    raise ValueError(f"excel_path 不在允许目录内: {path}")


def tool_etsy_check_credentials(*, probe: bool = False, probe_listing_id: str = "786582119") -> dict:
    tool = "etsy_check_credentials"
    api_key, source = get_etsy_api_key()
    if not api_key:
        return _tool_err(
            tool,
            "ETSY_API_KEY_MISSING",
            "请在 .env 配置 ETSY_KEYSTRING + ETSY_SHARED_SECRET（或 ETSY_API_KEY=key:secret）",
            retryable=False,
        )

    parts = api_key.split(":", 1)
    masked = parts[0][:6] + "..." + (parts[1][-4:] if len(parts) > 1 else "")
    data = {"configured": True, "source": source, "masked_key": masked, "api_verified": False}

    if not probe:
        return _tool_ok(tool, data, meta={"api_base": ETSY_API_BASE})

    body, err = _etsy_request("GET", f"/listings/{probe_listing_id}/reviews", params={"limit": 1})
    if err:
        err["tool"] = tool
        err["data"] = {**data, "api_verified": False}
        return err

    data["api_verified"] = True
    data["probe_listing_id"] = probe_listing_id
    data["probe_count"] = body.get("count") if isinstance(body, dict) else None
    return _tool_ok(tool, data, meta={"api_base": ETSY_API_BASE})


def _etsy_request(method: str, path: str, *, params: dict | None = None) -> tuple[dict | None, dict | None]:
    api_key, _ = get_etsy_api_key()
    if not api_key:
        return None, _tool_err("etsy_request", "ETSY_API_KEY_MISSING", "未配置 Etsy API Key", retryable=False)

    url = f"{ETSY_API_BASE}{path}"
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    try:
        resp = _SESSION.request(method, url, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        return None, _tool_err("etsy_request", "ETSY_NETWORK_ERROR", str(exc), retryable=True, meta={"url": url})

    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {"raw": resp.text[:500]}

    if resp.status_code in (401, 403):
        text = str(body).lower()
        if "not active" in text or "not found" in text:
            return None, _tool_err(
                "etsy_request",
                "ETSY_API_KEY_PENDING",
                "API Key 尚未激活或 Secret 不正确；请确认 Etsy 后台状态为 Personal Access。",
                retryable=True,
                meta={"status_code": resp.status_code, "url": url, "raw": body},
            )
        return None, _tool_err(
            "etsy_request",
            "ETSY_AUTH_FAILED",
            f"认证失败 HTTP {resp.status_code}: {body}",
            retryable=False,
            meta={"status_code": resp.status_code, "url": url},
        )
    if resp.status_code == 404:
        return None, _tool_err(
            "etsy_request",
            "ETSY_NOT_FOUND",
            f"资源不存在 HTTP 404: {body}",
            retryable=False,
            meta={"status_code": resp.status_code, "url": url},
        )
    if not resp.ok:
        return None, _tool_err(
            "etsy_request",
            "ETSY_API_ERROR",
            f"HTTP {resp.status_code}: {body}",
            retryable=resp.status_code >= 500,
            meta={"status_code": resp.status_code, "url": url},
        )
    return body, None


def _normalize_review_row(raw: dict[str, Any], listing_id: str, listing_url: str) -> dict[str, Any]:
    return {
        "platform": "etsy",
        "listing_id": str(raw.get("listing_id") or listing_id),
        "listing_url": listing_url,
        "review_id": str(raw.get("review_id") or raw.get("transaction_id") or ""),
        "shop_id": str(raw.get("shop_id") or ""),
        "rating": raw.get("rating"),
        "review_text": (raw.get("review") or raw.get("review_text") or "").strip(),
        "language": (raw.get("language") or "").strip(),
        "buyer_user_id": str(raw.get("buyer_user_id") or ""),
        "created_timestamp": raw.get("created_timestamp") or raw.get("create_timestamp"),
        "updated_timestamp": raw.get("updated_timestamp") or raw.get("update_timestamp"),
        "image_url": (raw.get("image_url_fullxfull") or raw.get("image_url") or "").strip(),
    }


def tool_etsy_fetch_listing_reviews(
    listing_id: str,
    *,
    listing_url: str | None = None,
    limit: int = 25,
    max_pages: int = 5,
    min_created: int | None = None,
    max_created: int | None = None,
    dry_run: bool = False,
) -> dict:
    tool = "etsy_fetch_listing_reviews"
    listing_id = (listing_id or "").strip()
    if not listing_id.isdigit():
        return _tool_err(tool, "INVALID_INPUT", "listing_id 必须是数字")

    cred = tool_etsy_check_credentials()
    if not cred.get("ok"):
        return _tool_err(tool, cred["error"]["code"], cred["error"]["message"])

    if dry_run:
        return _tool_ok(
            tool,
            {"listing_id": listing_id, "status": "dry_run", "reviews": [], "count": 0},
            meta={"dry_run": True},
        )

    started = time.perf_counter()
    page_limit = max(1, min(int(limit or 25), 100))
    max_pages = max(1, int(max_pages or 1))
    offset = 0
    all_raw: list[dict[str, Any]] = []
    listing_url = listing_url or f"https://www.etsy.com/listing/{listing_id}"
    last_body: dict | None = None

    for _ in range(max_pages):
        params: dict[str, Any] = {"limit": page_limit, "offset": offset}
        if min_created is not None:
            params["min_created"] = min_created
        if max_created is not None:
            params["max_created"] = max_created

        body, err = _etsy_request("GET", f"/listings/{listing_id}/reviews", params=params)
        if err:
            err["tool"] = tool
            err.setdefault("meta", {})
            err["meta"]["duration_ms"] = int((time.perf_counter() - started) * 1000)
            return err

        last_body = body if isinstance(body, dict) else {}
        rows = last_body.get("results") or []
        if not isinstance(rows, list):
            rows = []
        all_raw.extend(rows)
        if len(rows) < page_limit:
            break
        offset += page_limit

    reviews = [_normalize_review_row(r, listing_id, listing_url) for r in all_raw]
    duration_ms = int((time.perf_counter() - started) * 1000)

    if not reviews:
        return _tool_err(
            tool,
            "ETSY_NO_REVIEWS_FOUND",
            "未返回评论（listing 无评论或 ID 不正确）",
            retryable=False,
            data={"listing_id": listing_id, "count": 0},
            meta={"duration_ms": duration_ms},
        )

    return _tool_ok(
        tool,
        {
            "platform": "etsy",
            "listing_id": listing_id,
            "listing_url": listing_url,
            "reviews": reviews,
            "count": len(reviews),
        },
        meta={
            "duration_ms": duration_ms,
            "limit": page_limit,
            "max_pages": max_pages,
            "api_count": last_body.get("count") if last_body else None,
        },
    )


def tool_etsy_write_reviews_excel(
    listing_id: str,
    reviews: list[dict[str, Any]],
    *,
    listing_url: str | None = None,
    excel_path: str | None = None,
    sheet_name: str = "评论明细",
    deduplicate: bool = True,
) -> dict:
    tool = "etsy_write_reviews_excel"
    try:
        path = _resolve_excel_path(excel_path)
    except ValueError as exc:
        return _tool_err(tool, "PATH_NOT_ALLOWED", str(exc))

    if not reviews:
        return _tool_err(tool, "ETSY_NO_REVIEWS_FOUND", "没有可写入的评论")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    listing_url = listing_url or f"https://www.etsy.com/listing/{listing_id}"
    scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    for i, r in enumerate(reviews):
        row = dict(r)
        row.setdefault("platform", "etsy")
        row.setdefault("listing_id", listing_id)
        row.setdefault("listing_url", listing_url)
        row.setdefault("review_id", f"row_{i+1}")
        row["scraped_at"] = scraped_at
        rows.append({col: row.get(col, "") for col in REVIEW_COLUMNS})

    incoming_df = pd.DataFrame(rows, columns=REVIEW_COLUMNS)
    if os.path.exists(path):
        try:
            existing_df = pd.read_excel(path, sheet_name=sheet_name)
        except Exception:
            existing_df = pd.DataFrame(columns=REVIEW_COLUMNS)
    else:
        existing_df = pd.DataFrame(columns=REVIEW_COLUMNS)

    merged = pd.concat([existing_df, incoming_df], ignore_index=True)
    before = len(merged)
    if deduplicate:
        merged = merged.drop_duplicates(
            subset=["platform", "listing_id", "review_id", "review_text"], keep="last"
        )

    try:
        merged.to_excel(path, sheet_name=sheet_name, index=False)
    except Exception as exc:
        return _tool_err(tool, "WRITE_FAILED", str(exc), data={"excel_path": path})

    return _tool_ok(
        tool,
        {
            "rows_written": len(incoming_df),
            "rows_deduplicated": before - len(merged),
            "total_rows": len(merged),
            "excel_path": path,
        },
        meta={"sheet_name": sheet_name, "deduplicate": deduplicate},
    )


def tool_etsy_fetch_and_export_reviews(
    listing_url_or_id: str,
    *,
    limit: int = 25,
    max_pages: int = 5,
    min_created: int | None = None,
    max_created: int | None = None,
    excel_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    """一步到位：拉取评论 + 写入 Excel。"""
    tool = "etsy_fetch_and_export_reviews"
    listing_id = extract_listing_id(listing_url_or_id)
    if not listing_id:
        return _tool_err(tool, "INVALID_INPUT", "无法解析 listing_id")

    listing_url = listing_url_or_id if listing_url_or_id.startswith("http") else None
    fetch = tool_etsy_fetch_listing_reviews(
        listing_id,
        listing_url=listing_url,
        limit=limit,
        max_pages=max_pages,
        min_created=min_created,
        max_created=max_created,
        dry_run=dry_run,
    )
    if not fetch.get("ok"):
        return _tool_err(
            tool,
            fetch["error"]["code"],
            fetch["error"]["message"],
            retryable=fetch["error"].get("retryable", False),
            data=fetch.get("data"),
            meta={"fetch_meta": fetch.get("meta", {})},
        )
    if dry_run:
        return _tool_ok(tool, {"status": "dry_run", **fetch["data"]}, meta={"fetch_meta": fetch.get("meta", {})})

    write = tool_etsy_write_reviews_excel(
        listing_id,
        fetch["data"]["reviews"],
        listing_url=fetch["data"].get("listing_url"),
        excel_path=excel_path,
    )
    if not write.get("ok"):
        return _tool_err(
            tool,
            write["error"]["code"],
            write["error"]["message"],
            data={"fetch": fetch["data"]},
            meta={"fetch_meta": fetch.get("meta", {}), "write_meta": write.get("meta", {})},
        )

    return _tool_ok(
        tool,
        {
            "fetch": {
                "listing_id": listing_id,
                "listing_url": fetch["data"].get("listing_url"),
                "count": fetch["data"]["count"],
            },
            "write": write["data"],
        },
        meta={"fetch_meta": fetch.get("meta", {}), "write_meta": write.get("meta", {})},
    )
