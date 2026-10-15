# -*- coding: utf-8 -*-
"""Request-scoped ADK user id for Feishu MCP (from X-Adk-User-Id)."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Optional

_adk_user_id: ContextVar[str] = ContextVar("feishu_adk_user_id", default="")


def set_adk_user_id(user_id: str) -> Any:
    return _adk_user_id.set((user_id or "").strip())


def reset_adk_user_id(token: Any) -> None:
    _adk_user_id.reset(token)


def get_adk_user_id() -> str:
    return (_adk_user_id.get() or "").strip()


def extract_adk_user_id_from_headers(headers: Any) -> str:
    if headers is None:
        return ""
    # Starlette Headers is case-insensitive
    try:
        uid = headers.get("x-adk-user-id") or headers.get("X-Adk-User-Id") or ""
    except Exception:
        uid = ""
    return str(uid or "").strip()


def extract_adk_user_id_from_ctx(ctx: Optional[Any]) -> str:
    if ctx is None:
        return ""
    try:
        req = ctx.request_context.request  # type: ignore[attr-defined]
        return extract_adk_user_id_from_headers(getattr(req, "headers", None))
    except Exception:
        return ""
