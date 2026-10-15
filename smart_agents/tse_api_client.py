# -*- coding: utf-8 -*-
"""TSE Smart Workspace 外部 REST API 客户端（/api/external/v1）。

鉴权：Header ``X-API-Key``。Key 优先来自 **ADK Session state**（用户本会话提供），
可选回落 ``TSE_API_KEY`` 环境变量（仅运维/本地）；``TSE_API_BASE_URL`` 仍由环境配置。
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests

_DEFAULT_TIMEOUT_S = 180

# ADK tool_context.state keys（仅会话内；禁止写入 Memory Bank）
SESSION_API_KEY = "tse_api_key"
SESSION_API_KEY_SET_AT = "tse_api_key_set_at"
SESSION_API_KEY_TARGET = "tse_api_key_target_email"


def tse_api_base_url() -> str:
    return (os.getenv("TSE_API_BASE_URL") or "").strip().rstrip("/")


def tse_api_key_from_env() -> str:
    return (os.getenv("TSE_API_KEY") or "").strip()


def mask_api_key(value: str, *, visible_tail: int = 4) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    if len(raw) <= visible_tail + 4:
        return "***"
    return raw[:6] + "…" + raw[-visible_tail:]


def _state_dict(tool_context: Any) -> Optional[dict[str, Any]]:
    if tool_context is None:
        return None
    state = getattr(tool_context, "state", None)
    if isinstance(state, dict):
        return state
    # ADK State 多为类 dict 接口
    if state is not None and hasattr(state, "get") and hasattr(state, "__setitem__"):
        return state  # type: ignore[return-value]
    return None


def get_session_api_key(tool_context: Any) -> str:
    state = _state_dict(tool_context)
    if state is None:
        return ""
    return str(state.get(SESSION_API_KEY) or "").strip()


def set_session_api_key(
    tool_context: Any,
    api_key: str,
    *,
    target_email: str = "",
) -> None:
    state = _state_dict(tool_context)
    if state is None:
        raise RuntimeError("tool_context.state 不可用，无法写入会话 Key")
    state[SESSION_API_KEY] = (api_key or "").strip()
    state[SESSION_API_KEY_SET_AT] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if target_email:
        state[SESSION_API_KEY_TARGET] = (target_email or "").strip().lower()
    elif SESSION_API_KEY_TARGET in state and not target_email:
        # keep existing target unless cleared
        pass


def clear_session_api_key(tool_context: Any) -> None:
    state = _state_dict(tool_context)
    if state is None:
        return
    for key in (SESSION_API_KEY, SESSION_API_KEY_SET_AT, SESSION_API_KEY_TARGET):
        if key in state:
            try:
                del state[key]
            except Exception:
                state[key] = ""


def resolve_tse_api_key(tool_context: Any = None) -> tuple[str, str]:
    """返回 ``(api_key, source)``，source 为 session | env | none。"""
    session_key = get_session_api_key(tool_context)
    if session_key:
        return session_key, "session"
    env_key = tse_api_key_from_env()
    if env_key:
        return env_key, "env"
    return "", "none"


def tse_api_status(tool_context: Any = None) -> dict[str, Any]:
    """探测 base URL + Key 来源（不发起网络请求；不回显完整 Key）。"""
    base = tse_api_base_url()
    key, source = resolve_tse_api_key(tool_context)
    state = _state_dict(tool_context)
    set_at = ""
    target = ""
    if state is not None:
        set_at = str(state.get(SESSION_API_KEY_SET_AT) or "")
        target = str(state.get(SESSION_API_KEY_TARGET) or "")
    ready = bool(base and key)
    return {
        "base_url": base or None,
        "base_url_configured": bool(base),
        "api_key_present": bool(key),
        "api_key_source": source,
        "api_key_masked": mask_api_key(key) if key else None,
        "session_key_set_at": set_at or None,
        "target_email": target or None,
        "ready_for_chat_or_report": ready,
        # Lab-00：list/get 与 chat/report 共用同一就绪条件
        "ready_for_scoped_reads": ready,
    }


def tse_api_ready_for_scoped_reads(tool_context: Any = None) -> bool:
    """是否可用 External API 做 Key 作用域只读（Lab-00 P0）。"""
    return bool(tse_api_status(tool_context).get("ready_for_scoped_reads"))


def need_tse_api_key_error(*, reason: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "NEED_TSE_API_KEY",
            "message": reason
            or (
                "当前会话没有可用的 TSE API Key。"
                "请请用户在【私聊】提供 Key，再调用 set_tse_session_api_key。"
            ),
        },
        "user_prompt": (
            "请在【私聊】发送您的 TSE API Key（TSE 工作台 → 系统设置 → API Key 管理）。"
            "群聊请勿粘贴。我只会写入本会话，不会存入长期记忆，也不会在回复中回显完整 Key。"
        ),
        "next_tool": "set_tse_session_api_key",
        "wait_user": True,
        "blocked_reason": "waiting_tse_api_key",
    }


def need_tse_api_base_url_error() -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "NEED_TSE_API_BASE_URL",
            "message": (
                "服务端未配置 TSE_API_BASE_URL。"
                "请运维在 Agent 环境变量中设置 TSE 应用根 URL 后 redeploy。"
            ),
        },
    }


def call_tse_external(
    method: str,
    path: str,
    *,
    json_body: Optional[dict[str, Any]] = None,
    timeout: int = _DEFAULT_TIMEOUT_S,
    api_key: str = "",
    tool_context: Any = None,
) -> dict[str, Any]:
    """调用 TSE 外部 API。成功时返回 ``{"ok": True, "data": ...}``。"""
    base = tse_api_base_url()
    if not base:
        return need_tse_api_base_url_error()

    key = (api_key or "").strip()
    source = "explicit"
    if not key:
        key, source = resolve_tse_api_key(tool_context)
    if not key:
        return need_tse_api_key_error()

    url_path = path if path.startswith("/") else f"/{path}"
    url = f"{base}{url_path}"
    headers = {
        "X-API-Key": key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    try:
        resp = requests.request(
            method.upper(),
            url,
            headers=headers,
            json=json_body,
            timeout=max(30, int(timeout or _DEFAULT_TIMEOUT_S)),
        )
    except requests.Timeout:
        return {
            "ok": False,
            "error": {
                "code": "TSE_API_TIMEOUT",
                "message": f"TSE API 超时（{timeout}s）：{method.upper()} {url_path}",
            },
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "error": {
                "code": "TSE_API_NETWORK",
                "message": f"TSE API 网络错误：{exc}",
            },
        }

    try:
        body = resp.json()
    except Exception:
        body = {"raw": (resp.text or "")[:800]}

    if resp.status_code in (401, 403):
        return {
            "ok": False,
            "error": {
                "code": "TSE_API_KEY_INVALID",
                "message": "TSE API Key 无效或已撤销，请重新 set_tse_session_api_key",
                "http_status": resp.status_code,
            },
            "next_tool": "set_tse_session_api_key",
            "api_key_source": source,
        }

    if resp.status_code >= 400:
        msg = ""
        if isinstance(body, dict):
            msg = str(body.get("message") or body.get("error") or "")
        return {
            "ok": False,
            "error": {
                "code": "TSE_API_HTTP_ERROR",
                "message": msg or f"HTTP {resp.status_code}",
                "http_status": resp.status_code,
                "path": url_path,
            },
        }

    if isinstance(body, dict) and body.get("status") == "error":
        return {
            "ok": False,
            "error": {
                "code": "TSE_API_STATUS_ERROR",
                "message": str(body.get("message") or "TSE API status=error"),
                "path": url_path,
            },
        }

    data = body.get("data") if isinstance(body, dict) and "data" in body else body
    return {
        "ok": True,
        "http_status": resp.status_code,
        "data": data,
        "api_key_source": source,
    }
