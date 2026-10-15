# -*- coding: utf-8 -*-
"""Per-user Feishu OAuth token store (Firestore, not TSE business DB)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any, Optional

_REFRESH_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
_USER_ID_SAFE = re.compile(r"[^A-Za-z0-9_.\-]+")


def _project_id() -> str:
    return (os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT") or "").strip()


def _collection(kind: str = "tokens") -> str:
    if kind == "pending":
        return (
            os.getenv("FEISHU_OAUTH_PENDING_COLLECTION") or "feishu_oauth_pending"
        ).strip()
    return (
        os.getenv("FEISHU_OAUTH_FIRESTORE_COLLECTION") or "feishu_user_oauth"
    ).strip()


def _doc_id(user_id: str) -> str:
    raw = (user_id or "").strip()
    if not raw:
        raise ValueError("user_id 为空")
    # Firestore doc ids: avoid slashes; keep readable when possible
    safe = _USER_ID_SAFE.sub("_", raw)
    if len(safe) > 1400:
        safe = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return safe


def _client():
    from google.cloud import firestore

    project = _project_id()
    if not project:
        raise RuntimeError("未设置 GCP_PROJECT_ID，无法读写飞书用户 OAuth Firestore")
    return firestore.Client(project=project)


def get_tokens(user_id: str) -> Optional[dict[str, Any]]:
    """Return stored token payload or None."""
    try:
        doc = _client().collection(_collection()).document(_doc_id(user_id)).get()
    except Exception:
        return None
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    if not (data.get("access_token") or "").strip():
        return None
    return data


def put_tokens(user_id: str, payload: dict[str, Any]) -> None:
    body = {
        "access_token": (payload.get("access_token") or "").strip(),
        "refresh_token": (payload.get("refresh_token") or "").strip(),
        "expires_at": float(payload.get("expires_at") or 0),
        "refresh_expires_at": float(payload.get("refresh_expires_at") or 0),
        "scope": (payload.get("scope") or "").strip(),
        "open_id": (payload.get("open_id") or "").strip(),
        "app_id": (payload.get("app_id") or "").strip(),
        "updated_at": time.time(),
        "user_id": (user_id or "").strip(),
    }
    if not body["access_token"]:
        raise ValueError("access_token 不能为空")
    _client().collection(_collection()).document(_doc_id(user_id)).set(body, merge=True)


def delete_tokens(user_id: str) -> None:
    _client().collection(_collection()).document(_doc_id(user_id)).delete()


def put_pending(user_id: str, payload: dict[str, Any]) -> None:
    body = dict(payload)
    body["user_id"] = (user_id or "").strip()
    body["updated_at"] = time.time()
    _client().collection(_collection("pending")).document(_doc_id(user_id)).set(body)


def get_pending(user_id: str) -> Optional[dict[str, Any]]:
    try:
        doc = (
            _client()
            .collection(_collection("pending"))
            .document(_doc_id(user_id))
            .get()
        )
    except Exception:
        return None
    if not doc.exists:
        return None
    return doc.to_dict() or {}


def delete_pending(user_id: str) -> None:
    _client().collection(_collection("pending")).document(_doc_id(user_id)).delete()


def _app_credentials() -> tuple[str, str]:
    app_id = (os.getenv("LARKSUITE_CLI_APP_ID") or os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (
        os.getenv("LARKSUITE_CLI_APP_SECRET")
        or os.getenv("FEISHU_APP_SECRET")
        or os.getenv("FEISHU_APP_TOKEN")
        or ""
    ).strip()
    return app_id, app_secret


def _refresh_uat(refresh_token: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    app_id, app_secret = _app_credentials()
    if not app_id or not app_secret:
        return None, "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET"
    body = json.dumps(
        {
            "grant_type": "refresh_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "refresh_token": refresh_token,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        _REFRESH_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"refresh_token 请求失败: {exc}"

    # v2 may nest under data
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    code = payload.get("code")
    if code is not None and int(code) != 0:
        return None, f"refresh 失败 code={code} msg={payload.get('msg')!r}"[:300]

    access = (data.get("access_token") or "").strip()
    if not access:
        return None, f"refresh 响应缺少 access_token: {list(data.keys())}"
    now = time.time()
    expires_in = int(data.get("expires_in") or 7200)
    refresh_expires_in = int(data.get("refresh_token_expires_in") or 0)
    return {
        "access_token": access,
        "refresh_token": (data.get("refresh_token") or refresh_token).strip(),
        "expires_at": now + max(60, expires_in - 120),
        "refresh_expires_at": (
            now + refresh_expires_in if refresh_expires_in else 0
        ),
        "scope": (data.get("scope") or "").strip(),
        "open_id": (data.get("open_id") or data.get("user_id") or "").strip(),
        "app_id": app_id,
    }, None


def ensure_fresh_uat(user_id: str) -> tuple[Optional[str], Optional[str]]:
    """Return a valid user access token, refreshing if needed."""
    stored = get_tokens(user_id)
    if not stored:
        return None, "NEED_USER_OAUTH"
    now = time.time()
    access = (stored.get("access_token") or "").strip()
    expires_at = float(stored.get("expires_at") or 0)
    if access and expires_at > now + 60:
        return access, None
    refresh = (stored.get("refresh_token") or "").strip()
    if not refresh:
        return None, "NEED_USER_OAUTH"
    fresh, err = _refresh_uat(refresh)
    if not fresh:
        return None, err or "NEED_USER_OAUTH"
    # preserve prior open_id/scope if refresh omits them
    if not fresh.get("open_id"):
        fresh["open_id"] = stored.get("open_id") or ""
    if not fresh.get("scope"):
        fresh["scope"] = stored.get("scope") or ""
    put_tokens(user_id, fresh)
    return fresh["access_token"], None


def oauth_status_public(user_id: str) -> dict[str, Any]:
    """Safe status for agents (no raw tokens)."""
    _BITABLE_SCOPES = (
        "base:app:create",
        "base:record:create",
        "base:record:read",
        "base:record:retrieve",
        "base:table:create",
        "base:field:read",
    )
    stored = get_tokens(user_id)
    if not stored:
        return {
            "authorized": False,
            "hint": "请先调用 feishu_oauth_start，把 verification_url 发给用户授权，"
            "用户完成后调用 feishu_oauth_complete。",
        }
    now = time.time()
    expires_at = float(stored.get("expires_at") or 0)
    scope = (stored.get("scope") or "").strip()
    scope_parts = {p.strip() for p in scope.replace(",", " ").split() if p.strip()}
    has_bitable = bool(scope_parts & set(_BITABLE_SCOPES))
    out: dict[str, Any] = {
        "authorized": True,
        "open_id": stored.get("open_id") or "",
        "scope": scope,
        "expires_at": expires_at,
        "expired": bool(expires_at and expires_at <= now),
        "has_refresh_token": bool((stored.get("refresh_token") or "").strip()),
        "has_bitable_scopes": has_bitable if scope_parts else None,
    }
    if scope_parts and not has_bitable:
        out["hint"] = (
            "已授权，但令牌中未见多维表格相关 scope（base:app:create / bitable:app 等）。"
            "若要新建/写入多维表格：先确认开放平台已开通并发布对应权限，"
            "再 feishu_oauth_start → 用户重新授权 → feishu_oauth_complete。"
        )
    return out
