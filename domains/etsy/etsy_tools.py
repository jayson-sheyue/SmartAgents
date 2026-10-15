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
import json
import sys
import time
import uuid
import subprocess
import traceback
from datetime import datetime
from typing import Any

import pandas as pd
import requests
from smart_agents.env_runtime import load_runtime_env

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_runtime_env(default_env_path=os.path.join(PROJECT_ROOT, ".env"))

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
JOBS_ROOT = os.path.join(os.path.expanduser("~"), "Documents", "EtsyData", "jobs")
JOB_NOTIFICATIONS_PATH = os.path.join(JOBS_ROOT, "scene_job_notifications.jsonl")
_JOB_THREADS: dict[str, Any] = {}


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


def _ensure_jobs_root() -> str:
    os.makedirs(JOBS_ROOT, exist_ok=True)
    return JOBS_ROOT


def _job_file(job_id: str) -> str:
    return os.path.join(_ensure_jobs_root(), f"{job_id}.json")


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _write_job(record: dict[str, Any]) -> None:
    path = _job_file(record["job_id"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)


def _read_job(job_id: str) -> dict[str, Any] | None:
    path = _job_file(job_id)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _job_result_preview(result: dict[str, Any]) -> dict[str, Any]:
    data = result.get("data") or {}
    imgs = data.get("images") or []
    paths = [i.get("local_path") for i in imgs if i.get("local_path")]
    gcs_uris = [i.get("gcs_uri") for i in imgs if i.get("gcs_uri")]
    return {
        "ok": bool(result.get("ok")),
        "error": result.get("error"),
        "image_count": len(imgs),
        "local_paths": paths[:10],
        "gcs_uris": gcs_uris[:10],
        "manifest": data.get("manifest"),
    }


def _append_job_notification(record: dict[str, Any]) -> None:
    _ensure_jobs_root()
    payload = {
        "job_id": record.get("job_id"),
        "status": record.get("status"),
        "created_at": record.get("created_at"),
        "finished_at": record.get("finished_at"),
        "updated_at": _utc_now(),
        "result": record.get("result"),
    }
    with open(JOB_NOTIFICATIONS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


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
    """写入评论 Excel：默认上传 GCS；仅当显式传入 excel_path 时写本地（调试用）。"""
    tool = "etsy_write_reviews_excel"

    if not reviews:
        return _tool_err(tool, "ETSY_NO_REVIEWS_FOUND", "没有可写入的评论")

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

    # 云路径：整表上传 GCS（不做本地增量合并）
    if not excel_path:
        try:
            from domains.shared.artifact_store import write_dataframe_excel_to_gcs

            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            artifact = write_dataframe_excel_to_gcs(
                incoming_df,
                filename=f"etsy_reviews_{listing_id}_{stamp}.xlsx",
                sheet_name=sheet_name,
                subdomain="etsy/reviews",
            )
        except ValueError as exc:
            return _tool_err(tool, "GCS_BUCKET_MISSING", str(exc))
        except Exception as exc:
            return _tool_err(tool, "WRITE_FAILED", str(exc))
        return _tool_ok(
            tool,
            {
                "rows_written": len(incoming_df),
                "rows_deduplicated": 0,
                "total_rows": len(incoming_df),
                "gcs_uri": artifact.get("gcs_uri"),
                "signed_url": artifact.get("signed_url"),
            },
            meta={
                "sheet_name": sheet_name,
                "deduplicate": deduplicate,
                "gcs_uri": artifact.get("gcs_uri"),
            },
        )

    try:
        path = _resolve_excel_path(excel_path)
    except ValueError as exc:
        return _tool_err(tool, "PATH_NOT_ALLOWED", str(exc))

    os.makedirs(os.path.dirname(path), exist_ok=True)
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


def _parse_listing_image_record(img: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(img, dict):
        return None
    url = (
        img.get("url_fullxfull")
        or img.get("url_570xN")
        or img.get("url_75x75")
        or ""
    )
    if not url:
        return None
    rank_raw = img.get("rank")
    try:
        rank = int(rank_raw) if rank_raw is not None else 0
    except (TypeError, ValueError):
        rank = 0
    return {
        "listing_image_id": str(img.get("listing_image_id") or ""),
        "url": str(url).strip(),
        "rank": rank,
        "full_width": img.get("full_width"),
        "full_height": img.get("full_height"),
    }


def _fetch_listing_images_normalized(listing_id: str) -> tuple[list[dict[str, Any]], dict | None]:
    body, err = _etsy_request("GET", f"/listings/{listing_id}/images")
    if err:
        return [], err
    results = body.get("results") if isinstance(body, dict) else None
    if not isinstance(results, list):
        return [], None
    images = [
        parsed
        for raw in results
        if (parsed := _parse_listing_image_record(raw)) is not None
    ]
    images.sort(key=lambda x: (x.get("rank") or 0, x.get("listing_image_id") or ""))
    return images, None


def _normalize_listing_context(body: dict[str, Any], listing_id: str) -> dict[str, Any]:
    tags_raw = body.get("tags") or []
    if isinstance(tags_raw, str):
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(t).strip() for t in tags_raw if str(t).strip()]
    else:
        tags = []

    images, _ = _fetch_listing_images_normalized(listing_id)

    listing_url = f"https://www.etsy.com/listing/{listing_id}"
    return {
        "platform": "etsy",
        "listing_id": str(body.get("listing_id") or listing_id),
        "listing_url": listing_url,
        "shop_id": str(body.get("shop_id") or ""),
        "title": (body.get("title") or "").strip(),
        "description": (body.get("description") or "").strip(),
        "state": (body.get("state") or "").strip(),
        "tags": tags,
        "price": body.get("price"),
        "currency_code": body.get("currency_code") or "",
        "quantity": body.get("quantity"),
        "existing_images": images,
        "existing_image_count": len(images),
        "main_image": images[0] if images else None,
    }


def tool_etsy_fetch_listing_images(listing_id: str) -> dict:
    """拉取 listing 全部附图；按 rank 排序，main_image 为主图（rank 最小）。"""
    tool = "etsy_fetch_listing_images"
    listing_id = (listing_id or "").strip()
    if not listing_id.isdigit():
        return _tool_err(tool, "INVALID_INPUT", "listing_id 必须是数字")

    cred = tool_etsy_check_credentials()
    if not cred.get("ok"):
        return _tool_err(tool, cred["error"]["code"], cred["error"]["message"])

    images, err = _fetch_listing_images_normalized(listing_id)
    if err:
        err["tool"] = tool
        return err

    return _tool_ok(
        tool,
        {
            "listing_id": listing_id,
            "count": len(images),
            "images": images,
            "main_image": images[0] if images else None,
        },
        meta={"api_base": ETSY_API_BASE},
    )


def tool_etsy_get_listing(listing_id: str, *, listing_url: str | None = None) -> dict:
    """读取 Etsy listing 元数据（标题、描述、标签、现有附图 URL）。"""
    tool = "etsy_get_listing"
    listing_id = (listing_id or "").strip()
    if not listing_id.isdigit():
        return _tool_err(tool, "INVALID_INPUT", "listing_id 必须是数字")

    cred = tool_etsy_check_credentials()
    if not cred.get("ok"):
        return _tool_err(tool, cred["error"]["code"], cred["error"]["message"])

    body, err = _etsy_request("GET", f"/listings/{listing_id}")
    if err:
        err["tool"] = tool
        return err

    if not isinstance(body, dict):
        return _tool_err(tool, "ETSY_API_ERROR", "listing 响应格式异常")

    data = _normalize_listing_context(body, listing_id)
    if listing_url:
        data["listing_url"] = listing_url
    return _tool_ok(tool, data, meta={"api_base": ETSY_API_BASE})


def tool_etsy_summarize_reviews_for_prompt(
    listing_id: str,
    *,
    listing_url: str | None = None,
    limit: int = 25,
    max_pages: int = 2,
    min_rating: int = 4,
) -> dict:
    """从评论中提炼生图关键词（无评论时返回空列表，不报错）。"""
    tool = "etsy_summarize_reviews_for_prompt"
    fetch = tool_etsy_fetch_listing_reviews(
        listing_id,
        listing_url=listing_url,
        limit=limit,
        max_pages=max_pages,
    )
    if not fetch.get("ok"):
        code = fetch["error"]["code"]
        if code == "ETSY_NO_REVIEWS_FOUND":
            return _tool_ok(
                tool,
                {
                    "listing_id": listing_id,
                    "keywords": [],
                    "sample_phrases": [],
                    "review_count_used": 0,
                },
                meta={"note": "no_reviews"},
            )
        return _tool_err(
            tool,
            fetch["error"]["code"],
            fetch["error"]["message"],
            retryable=fetch["error"].get("retryable", False),
        )

    reviews = fetch["data"].get("reviews") or []
    texts: list[str] = []
    for r in reviews:
        try:
            rating = int(r.get("rating") or 0)
        except (TypeError, ValueError):
            rating = 0
        if rating < min_rating:
            continue
        text = (r.get("review_text") or "").strip()
        if text:
            texts.append(text)

    # 简单关键词：英文/中文词片段 + 高频 2-gram（PoC 足够）
    word_freq: dict[str, int] = {}
    for text in texts:
        for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", text.lower()):
            if len(token) < 2 or token.isdigit():
                continue
            word_freq[token] = word_freq.get(token, 0) + 1

    keywords = [w for w, _ in sorted(word_freq.items(), key=lambda x: (-x[1], x[0]))[:12]]
    sample_phrases = [t[:120] for t in texts[:3]]

    return _tool_ok(
        tool,
        {
            "listing_id": listing_id,
            "keywords": keywords,
            "sample_phrases": sample_phrases,
            "review_count_used": len(texts),
        },
        meta={"min_rating": min_rating},
    )


def tool_etsy_generate_listing_assets(
    listing_url_or_id: str,
    *,
    count: int = 1,
    style: str = "clean nordic e-commerce lifestyle product scene",
    image_roles: list[str] | None = None,
    use_reviews: bool = True,
    upload_to_gcs: bool = True,
    excel_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    一步到位：拉 listing 上下文 →（可选）评论关键词 → 生图 → 校验 → manifest Excel。
  不上传 Etsy listing（MVP）；产出 GCS URI + Excel 清单。
    """
    tool = "etsy_generate_listing_assets"
    listing_id = extract_listing_id(listing_url_or_id)
    if not listing_id:
        return _tool_err(tool, "INVALID_INPUT", "无法解析 listing_id")

    listing_url = listing_url_or_id if listing_url_or_id.startswith("http") else None
    ctx = tool_etsy_get_listing(listing_id, listing_url=listing_url)
    if not ctx.get("ok"):
        return _tool_err(
            tool,
            ctx["error"]["code"],
            ctx["error"]["message"],
            data=ctx.get("data"),
        )

    listing = ctx["data"]
    keywords: list[str] = []
    if use_reviews:
        summ = tool_etsy_summarize_reviews_for_prompt(
            listing_id, listing_url=listing.get("listing_url")
        )
        if summ.get("ok"):
            keywords = summ["data"].get("keywords") or []

    from domains.etsy.image_tools import (  # noqa: WPS433 — 避免循环 import
        build_listing_image_prompt,
        image_env_config,
        tool_check_image_config,
        tool_export_image_manifest_excel,
        tool_generate_listing_image,
    )

    if not dry_run:
        cfg_check = tool_check_image_config(require_gcs_bucket=upload_to_gcs)
        if not cfg_check.get("ok"):
            return _tool_err(
                tool,
                cfg_check["error"]["code"],
                cfg_check["error"]["message"],
                data=cfg_check.get("data"),
            )

    n = max(1, min(int(count or 1), 4))
    roles = image_roles or ["lifestyle", "detail", "in-context", "banner"][:n]
    while len(roles) < n:
        roles.append(f"variant_{len(roles)+1}")

    generated_rows: list[dict[str, Any]] = []
    images_out: list[dict[str, Any]] = []
    for i in range(n):
        role = roles[i]
        prompt = build_listing_image_prompt(
            title=listing.get("title") or f"listing {listing_id}",
            tags=listing.get("tags"),
            description=listing.get("description") or "",
            review_keywords=keywords,
            style=style,
            image_role=role,
        )
        gen = tool_generate_listing_image(
            prompt=prompt,
            listing_id=listing_id,
            shop_id=listing.get("shop_id") or "",
            image_role=role,
            upload_to_gcs=upload_to_gcs,
            dry_run=dry_run,
        )
        if not gen.get("ok"):
            return _tool_err(
                tool,
                gen["error"]["code"],
                gen["error"]["message"],
                data={"listing": listing, "partial_images": images_out},
                retryable=gen["error"].get("retryable", False),
            )
        images_out.append(gen["data"])
        generated_rows.append(
            {
                "platform": "etsy",
                "listing_id": listing_id,
                "shop_id": listing.get("shop_id") or "",
                "generation_mode": "text_to_image",
                "image_role": role,
                "prompt": prompt,
                "model": gen["data"].get("model"),
                "aspect_ratio": gen["data"].get("aspect_ratio"),
                "width_px": gen["data"].get("width_px"),
                "height_px": gen["data"].get("height_px"),
                "file_size_bytes": gen["data"].get("file_size_bytes"),
                "reference_listing_image_id": "",
                "reference_image_url": "",
                "gcs_uri": gen["data"].get("gcs_uri", ""),
                "local_path": gen["data"].get("local_path", ""),
                "spec_ok": gen["data"].get("spec_ok"),
                "spec_notes": gen["data"].get("spec_notes", ""),
            }
        )

    manifest = tool_export_image_manifest_excel(generated_rows, excel_path=excel_path)
    if not manifest.get("ok"):
        return _tool_err(
            tool,
            manifest["error"]["code"],
            manifest["error"]["message"],
            data={"listing": listing, "images": images_out},
        )

    return _tool_ok(
        tool,
        {
            "listing": listing,
            "review_keywords": keywords,
            "images": images_out,
            "manifest": manifest["data"],
            "note": "图片已落 GCS/本地；请卖家在 Etsy 后台手动上传附图（MVP 未接 OAuth 写回）。",
        },
        meta={"dry_run": dry_run, "count": n, "image_config": image_env_config()},
    )


MAX_SCENE_SWAP_LISTING_IMAGES = 10


def _scene_swap_jobs(
    listing: dict[str, Any],
    *,
    count: int,
    all_images: bool,
    image_roles: list[str] | None,
) -> list[dict[str, Any]]:
    """构建 scene-swap 任务：all_images/count=0 时按附图逐张参考。"""
    from domains.etsy.image_tools import image_role_for_listing_rank  # noqa: WPS433

    images = list(listing.get("existing_images") or [])
    if not images:
        main = listing.get("main_image")
        if main:
            images = [main]

    if all_images or count == 0:
        jobs: list[dict[str, Any]] = []
        for i, img in enumerate(images[:MAX_SCENE_SWAP_LISTING_IMAGES]):
            try:
                rank = int(img.get("rank") or i + 1)
            except (TypeError, ValueError):
                rank = i + 1
            jobs.append(
                {
                    "reference": img,
                    "image_role": image_role_for_listing_rank(rank, i),
                    "reference_rank": rank,
                }
            )
        return jobs

    main_image = listing.get("main_image") or (images[0] if images else None)
    if not main_image:
        return []

    n = max(1, min(int(count or 1), 4))
    roles = image_roles or ["lifestyle", "detail", "in-context", "banner"][:n]
    while len(roles) < n:
        roles.append(f"variant_{len(roles)+1}")
    try:
        rank = int(main_image.get("rank") or 1)
    except (TypeError, ValueError):
        rank = 1
    return [
        {
            "reference": main_image,
            "image_role": roles[i],
            "reference_rank": rank,
        }
        for i in range(n)
    ]


def tool_etsy_generate_listing_scene_variants(
    listing_url_or_id: str,
    *,
    count: int = 1,
    all_images: bool = False,
    preset_id: str | None = None,
    custom_scene: str | None = None,
    polish_with_llm: bool = True,
    style: str | None = None,
    infer_style: bool = False,
    image_roles: list[str] | None = None,
    upload_to_gcs: bool = True,
    save_local_copy: bool = False,
    excel_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    参考 listing 附图换场景（保持产品形态）— 同步完成，返回 GCS URI。
    - count=1..4：仅用主图参考，生成 count 张（不同 image_role）
    - all_images 或 count=0：按 listing 附图 rank 逐张下载参考并各生成 1 张
    - 风格优先级：custom_scene > preset_id > style > infer_style > default
    - Cloud Run 上必须 upload_to_gcs=True；本地副本默认关闭
    """
    tool = "etsy_generate_listing_scene_variants"
    # 云端强制 GCS
    if (os.getenv("K_SERVICE") or "").strip() or (os.getenv("MCP_ARTIFACT_GCS_BUCKET") or "").strip():
        upload_to_gcs = True
        save_local_copy = False
    listing_id = extract_listing_id(listing_url_or_id)
    if not listing_id:
        return _tool_err(tool, "INVALID_INPUT", "无法解析 listing_id")

    listing_url = listing_url_or_id if listing_url_or_id.startswith("http") else None
    ctx = tool_etsy_get_listing(listing_id, listing_url=listing_url)
    if not ctx.get("ok"):
        return _tool_err(
            tool,
            ctx["error"]["code"],
            ctx["error"]["message"],
            data=ctx.get("data"),
        )

    listing = ctx["data"]
    custom_scene_text = (custom_scene or "").strip()
    effective_polish_with_llm = bool(polish_with_llm and not custom_scene_text)
    per_listing = bool(all_images or count == 0)
    jobs = _scene_swap_jobs(
        listing,
        count=count,
        all_images=per_listing,
        image_roles=image_roles,
    )
    if not jobs:
        return _tool_err(
            tool,
            "LISTING_IMAGES_NOT_FOUND",
            "该 listing 没有可拉取的附图",
            data={"listing": listing},
        )

    from domains.etsy.image_tools import (  # noqa: WPS433
        build_scene_swap_prompt,
        image_env_config,
        tool_check_image_config,
        tool_download_image_url,
        tool_export_image_manifest_excel,
        tool_generate_scene_variant_image,
    )
    from domains.etsy.preset_tools import resolve_scene_for_generation  # noqa: WPS433

    if not dry_run:
        cfg_check = tool_check_image_config(require_gcs_bucket=upload_to_gcs)
        if not cfg_check.get("ok"):
            return _tool_err(
                tool,
                cfg_check["error"]["code"],
                cfg_check["error"]["message"],
                data={**cfg_check.get("data", {}), "jobs": len(jobs)},
            )

    generated_rows: list[dict[str, Any]] = []
    images_out: list[dict[str, Any]] = []
    scene_resolutions: list[dict[str, Any]] = []
    for job in jobs:
        ref = job["reference"]
        ref_url = ref.get("url") or ""
        ref_id = ref.get("listing_image_id") or ""
        role = job["image_role"]
        ref_rank = job.get("reference_rank")
        ref_bytes = b""
        ref_mime = "image/jpeg"

        if not ref_url:
            return _tool_err(
                tool,
                "REFERENCE_IMAGE_URL_MISSING",
                f"rank {ref_rank} 附图缺少 URL",
                data={"listing": listing, "partial_images": images_out},
            )

        if not dry_run:
            dl = tool_download_image_url(ref_url)
            if not dl.get("ok"):
                return _tool_err(
                    tool,
                    dl["error"]["code"],
                    dl["error"]["message"],
                    data={
                        "listing": listing,
                        "reference_rank": ref_rank,
                        "reference_image_url": ref_url,
                        "partial_images": images_out,
                    },
                    retryable=dl["error"].get("retryable", False),
                )
            ref_bytes = dl["data"]["image_bytes"]
            ref_mime = dl["data"].get("mime_type") or "image/jpeg"

        try:
            scene_text, scene_meta = resolve_scene_for_generation(
                listing=listing,
                reference_rank=ref_rank,
                image_role=role,
                preset_id=preset_id,
                custom_scene=custom_scene_text,
                style=style,
                infer_style=infer_style,
                polish_with_llm=effective_polish_with_llm,
                dry_run=dry_run,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg.startswith("PRESET_NOT_FOUND:"):
                pid = msg.split(":", 1)[1]
                return _tool_err(
                    tool,
                    "PRESET_NOT_FOUND",
                    f"未找到预设: {pid}",
                    data={"listing": listing, "partial_images": images_out},
                )
            return _tool_err(
                tool,
                "SCENE_RESOLVE_FAILED",
                msg,
                data={"listing": listing, "partial_images": images_out},
            )
        except RuntimeError as exc:
            return _tool_err(
                tool,
                "SCENE_RESOLVE_FAILED",
                str(exc),
                data={"listing": listing, "partial_images": images_out},
                retryable=True,
            )

        scene_resolutions.append(scene_meta)
        prompt = build_scene_swap_prompt(
            title=listing.get("title") or f"listing {listing_id}",
            style=scene_text,
            image_role=role,
            description=listing.get("description") or "",
        )
        max_retries = max(1, min(int(os.getenv("ETSY_IMAGE_JOB_RETRIES", "3")), 6))
        gen: dict[str, Any] = {}
        for attempt in range(1, max_retries + 1):
            gen = tool_generate_scene_variant_image(
                prompt=prompt,
                listing_id=listing_id,
                shop_id=listing.get("shop_id") or "",
                image_role=role,
                reference_image_bytes=ref_bytes,
                reference_mime_type=ref_mime,
                reference_listing_image_id=ref_id,
                reference_image_url=ref_url,
                reference_rank=ref_rank,
                upload_to_gcs=upload_to_gcs,
            save_local_copy=save_local_copy,
                dry_run=dry_run,
            )
            if gen.get("ok"):
                break
            if not gen.get("error", {}).get("retryable", False):
                break
            if attempt < max_retries:
                # 瞬时网络抖动（如 server disconnected）做指数退避重试
                time.sleep(min(2 ** (attempt - 1), 8))
        if not gen.get("ok"):
            return _tool_err(
                tool,
                gen["error"]["code"],
                gen["error"]["message"],
                data={
                    "listing": listing,
                    "reference_rank": ref_rank,
                    "reference_image_url": ref_url,
                    "partial_images": images_out,
                },
                retryable=gen["error"].get("retryable", False),
                meta={"retry_attempts": max_retries},
            )
        images_out.append({**gen["data"], "scene_resolution": scene_meta})
        generated_rows.append(
            {
                "platform": "etsy",
                "listing_id": listing_id,
                "shop_id": listing.get("shop_id") or "",
                "generation_mode": "scene_swap",
                "image_role": role,
                "prompt": prompt,
                "model": gen["data"].get("model"),
                "aspect_ratio": gen["data"].get("aspect_ratio"),
                "width_px": gen["data"].get("width_px"),
                "height_px": gen["data"].get("height_px"),
                "file_size_bytes": gen["data"].get("file_size_bytes"),
                "reference_listing_image_id": ref_id,
                "reference_rank": ref_rank,
                "reference_image_url": ref_url,
                "gcs_uri": gen["data"].get("gcs_uri", ""),
                "local_path": gen["data"].get("local_path", ""),
                "spec_ok": gen["data"].get("spec_ok"),
                "spec_notes": gen["data"].get("spec_notes", ""),
            }
        )

    manifest = tool_export_image_manifest_excel(generated_rows, excel_path=excel_path)
    if not manifest.get("ok"):
        return _tool_err(
            tool,
            manifest["error"]["code"],
            manifest["error"]["message"],
            data={"listing": listing, "images": images_out},
        )

    return _tool_ok(
        tool,
        {
            "listing": listing,
            "preset_id": preset_id,
            "custom_scene": custom_scene_text,
            "polish_with_llm": effective_polish_with_llm,
            "polish_requested": bool(polish_with_llm),
            "upload_to_gcs": upload_to_gcs,
            "save_local_copy": save_local_copy,
            "scene_resolutions": scene_resolutions,
            "per_listing_image": per_listing,
            "jobs": [
                {
                    "reference_rank": j.get("reference_rank"),
                    "reference_listing_image_id": (j["reference"] or {}).get(
                        "listing_image_id"
                    ),
                    "reference_image_url": (j["reference"] or {}).get("url"),
                    "image_role": j.get("image_role"),
                }
                for j in jobs
            ],
            "images": images_out,
            "manifest": manifest["data"],
            "note": "附图逐张或主图参考换场景；请卖家在 Etsy 后台手动上传（MVP 未接 OAuth 写回）。",
        },
        meta={
            "dry_run": dry_run,
            "count": len(jobs),
            "per_listing_image": per_listing,
            "preset_id": preset_id,
            "polish_with_llm": effective_polish_with_llm,
            "polish_requested": bool(polish_with_llm),
            "upload_to_gcs": upload_to_gcs,
            "save_local_copy": save_local_copy,
            "generation_mode": "scene_swap",
            "image_config": image_env_config(),
        },
    )


def _run_scene_job(job_id: str, params: dict[str, Any]) -> None:
    started = _utc_now()
    rec = _read_job(job_id) or {"job_id": job_id}
    rec.update({"status": "running", "started_at": started, "updated_at": started})
    _write_job(rec)
    try:
        result = tool_etsy_generate_listing_scene_variants(**params)
        finished = _utc_now()
        rec.update(
            {
                "status": "succeeded" if result.get("ok") else "failed",
                "finished_at": finished,
                "updated_at": finished,
                "result": _job_result_preview(result),
            }
        )
        _write_job(rec)
        _append_job_notification(rec)
    except Exception as exc:  # pragma: no cover
        finished = _utc_now()
        rec.update(
            {
                "status": "failed",
                "finished_at": finished,
                "updated_at": finished,
                "result": {
                    "ok": False,
                    "error": {
                        "code": "ASYNC_JOB_CRASHED",
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                },
            }
        )
        _write_job(rec)
        _append_job_notification(rec)
    finally:
        _JOB_THREADS.pop(job_id, None)


def tool_etsy_wait_scene_job(
    job_id: str,
    *,
    timeout_sec: int = 120,
    poll_interval_sec: int = 5,
    verbose: bool = False,
) -> dict:
    """阻塞轮询异步任务直到完成或超时。"""
    tool = "etsy_wait_scene_job"
    job_id = (job_id or "").strip()
    if not job_id:
        return _tool_err(tool, "INVALID_INPUT", "job_id 不能为空")
    timeout = max(5, min(int(timeout_sec or 120), 3600))
    interval = max(1, min(int(poll_interval_sec or 5), 30))
    deadline = time.time() + timeout
    last: dict[str, Any] | None = None
    while time.time() < deadline:
        rec = _read_job(job_id)
        if not rec:
            return _tool_err(tool, "JOB_NOT_FOUND", f"未找到任务: {job_id}")
        last = rec
        if verbose:
            print(
                f"[scene-job] {job_id} status={rec.get('status')} updated_at={rec.get('updated_at')}",
                flush=True,
            )
        if rec.get("status") in ("succeeded", "failed"):
            return _tool_ok(tool, rec, meta={"waited_sec": timeout - int(deadline - time.time())})
        time.sleep(interval)
    return _tool_err(
        tool,
        "JOB_WAIT_TIMEOUT",
        f"任务在 {timeout}s 内未完成",
        retryable=True,
        data=last or {"job_id": job_id, "status": "unknown"},
    )


def tool_etsy_submit_scene_variants_job(
    listing_url_or_id: str,
    *,
    count: int = 1,
    all_images: bool = False,
    preset_id: str | None = None,
    custom_scene: str | None = None,
    polish_with_llm: bool = False,
    style: str | None = None,
    infer_style: bool = False,
    image_roles: list[str] | None = None,
    upload_to_gcs: bool = True,
    save_local_copy: bool = True,
    excel_path: str | None = None,
    dry_run: bool = False,
) -> dict:
    """
    异步提交 scene-swap 生图任务：立即返回 job_id，后台执行。
    使用 tool_etsy_get_scene_job / tool_etsy_list_scene_jobs 查询进度。
    """
    tool = "etsy_submit_scene_variants_job"
    job_id = uuid.uuid4().hex
    created = _utc_now()
    params = {
        "listing_url_or_id": listing_url_or_id,
        "count": count,
        "all_images": all_images,
        "preset_id": preset_id,
        "custom_scene": custom_scene,
        "polish_with_llm": polish_with_llm,
        "style": style,
        "infer_style": infer_style,
        "image_roles": image_roles,
        "upload_to_gcs": upload_to_gcs,
        "save_local_copy": save_local_copy,
        "excel_path": excel_path,
        "dry_run": dry_run,
    }
    rec = {
        "job_id": job_id,
        "type": "scene_swap",
        "status": "queued",
        "created_at": created,
        "updated_at": created,
        "params": params,
    }
    _write_job(rec)
    worker_script = os.path.join(PROJECT_ROOT, "scripts", "run_etsy_scene_job_worker.py")
    if not os.path.isfile(worker_script):
        return _tool_err(
            tool,
            "WORKER_SCRIPT_MISSING",
            f"未找到异步 worker 脚本: {worker_script}",
            data={"job_id": job_id},
        )
    try:
        proc = subprocess.Popen(
            [sys.executable, worker_script, job_id],
            cwd=PROJECT_ROOT,
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        _JOB_THREADS[job_id] = proc
    except Exception as exc:
        failed = _read_job(job_id) or rec
        failed.update(
            {
                "status": "failed",
                "updated_at": _utc_now(),
                "finished_at": _utc_now(),
                "result": {
                    "ok": False,
                    "error": {
                        "code": "WORKER_START_FAILED",
                        "message": str(exc),
                    },
                },
            }
        )
        _write_job(failed)
        _append_job_notification(failed)
        return _tool_err(
            tool,
            "WORKER_START_FAILED",
            str(exc),
            retryable=True,
            data={"job_id": job_id},
        )
    return _tool_ok(
        tool,
        {
            "job_id": job_id,
            "status": "queued",
            "check_hint": "调用 etsy_get_scene_job(job_id) 查询进度",
        },
        meta={"jobs_root": JOBS_ROOT},
    )


def run_scene_job_worker(job_id: str) -> int:
    """
    供外部 worker 脚本调用：读取 job 记录并执行任务。
    返回进程退出码（0 成功提交执行；非 0 输入错误）。
    """
    rec = _read_job(job_id)
    if not rec:
        return 2
    params = (rec.get("params") or {}).copy()
    if not params:
        rec.update(
            {
                "status": "failed",
                "updated_at": _utc_now(),
                "finished_at": _utc_now(),
                "result": {
                    "ok": False,
                    "error": {"code": "JOB_PARAMS_MISSING", "message": "任务参数缺失"},
                },
            }
        )
        _write_job(rec)
        _append_job_notification(rec)
        return 3
    _run_scene_job(job_id, params)
    return 0


def tool_etsy_get_scene_job(job_id: str) -> dict:
    """查询异步 scene-swap 任务状态。"""
    tool = "etsy_get_scene_job"
    job_id = (job_id or "").strip()
    if not job_id:
        return _tool_err(tool, "INVALID_INPUT", "job_id 不能为空")
    rec = _read_job(job_id)
    if not rec:
        return _tool_err(tool, "JOB_NOT_FOUND", f"未找到任务: {job_id}")
    return _tool_ok(tool, rec)


def tool_etsy_list_scene_jobs(*, limit: int = 20, status: str = "") -> dict:
    """列出最近 scene-swap 异步任务。"""
    tool = "etsy_list_scene_jobs"
    root = _ensure_jobs_root()
    rows: list[dict[str, Any]] = []
    for name in os.listdir(root):
        if not name.endswith(".json"):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, encoding="utf-8") as f:
                rec = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        if status and rec.get("status") != status:
            continue
        rows.append(
            {
                "job_id": rec.get("job_id"),
                "status": rec.get("status"),
                "created_at": rec.get("created_at"),
                "updated_at": rec.get("updated_at"),
                "listing_url_or_id": (rec.get("params") or {}).get("listing_url_or_id"),
                "preset_id": (rec.get("params") or {}).get("preset_id"),
                "custom_scene": (rec.get("params") or {}).get("custom_scene"),
            }
        )
    rows.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    n = max(1, min(int(limit or 20), 200))
    return _tool_ok(tool, {"jobs": rows[:n], "count": len(rows[:n])}, meta={"jobs_root": root})


def tool_etsy_read_scene_notifications(*, limit: int = 20) -> dict:
    """读取最近任务完成通知（JSONL）。"""
    tool = "etsy_read_scene_notifications"
    n = max(1, min(int(limit or 20), 200))
    if not os.path.exists(JOB_NOTIFICATIONS_PATH):
        return _tool_ok(tool, {"notifications": [], "count": 0}, meta={"path": JOB_NOTIFICATIONS_PATH})
    rows: list[dict[str, Any]] = []
    with open(JOB_NOTIFICATIONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    rows = rows[-n:]
    return _tool_ok(
        tool,
        {"notifications": list(reversed(rows)), "count": len(rows)},
        meta={"path": JOB_NOTIFICATIONS_PATH},
    )
