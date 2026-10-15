# -*- coding: utf-8 -*-
"""Feishu user OAuth Device Flow via lark-cli (per-user HOME + Firestore persist)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from domains.feishu import oauth_store
from domains.feishu.user_context import get_adk_user_id

_CLI_TIMEOUT_SEC = int((os.getenv("FEISHU_CLI_TIMEOUT_SEC") or "120").strip() or "120")
_DEVICE_AUTH_URL = (
    os.getenv("FEISHU_OAUTH_DEVICE_URL")
    or "https://accounts.feishu.cn/oauth/v1/device_authorization"
).strip()
_TOKEN_URL = (
    os.getenv("FEISHU_OAUTH_TOKEN_URL")
    or "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
).strip()

# Minimal default: only refresh. Feature scopes are requested per-task (least privilege).
_CORE_SCOPES = "offline_access"

# Capability → scopes (no kitchen-sink; avoid broad bitable:app / calendar:calendar)
SCOPE_BUNDLES: dict[str, tuple[str, ...]] = {
    "calendar_read": (
        "calendar:calendar:readonly",
        "calendar:calendar.event:read",
    ),
    "calendar_write": (
        "calendar:calendar.event:create",
        "calendar:calendar.event:update",
        "calendar:calendar.free_busy:read",
    ),
    "docs_read": (
        "docx:document:readonly",
        "search:docs:read",
    ),
    "docs_write": ("docx:document",),
    "sheets_read": ("sheets:spreadsheet:readonly",),
    "sheets_write": ("sheets:spreadsheet",),
    "contact": ("contact:user:search",),
    "im_chat": ("im:chat:read",),
    # Keyword / time-bounded message search (user-only +messages-search).
    # Feishu Search API requires ``search:message`` (not only im:message:readonly).
    "im_message_read": (
        "search:message",
        "im:message:readonly",
        "im:chat:read",
    ),
    # Create Base + table schema WITHOUT deleting the default table.
    # (lark-cli +base-create --fields replaces the initial table → needs base:table:delete)
    "bitable_create": (
        "base:app:create",
        "base:table:read",
        "base:table:create",
        "base:table:update",
        "base:field:read",
        "base:field:create",
    ),
    # Read fields / write records into an existing table
    # note: list/search 用 base:record:read；单条检索用 retrieve — 两者都要申请
    "bitable_write": (
        "base:table:read",
        "base:field:read",
        "base:record:read",
        "base:record:retrieve",
        "base:record:create",
        "base:record:update",
    ),
}

# MCP tool → capabilities for auto re-auth / least-privilege start
TOOL_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "feishu_calendar_agenda": ("calendar_read",),
    "feishu_calendar_freebusy": ("calendar_read", "calendar_write"),
    "feishu_calendar_create": ("calendar_write",),
    "feishu_doc_fetch": ("docs_read",),
    "feishu_doc_search": ("docs_read",),
    "feishu_doc_create_markdown": ("docs_write",),
    "feishu_sheet_read": ("sheets_read",),
    "feishu_sheet_write_csv": ("sheets_write",),
    "feishu_contact_search_user": ("contact",),
    "feishu_im_chat_search": ("im_chat",),
    "feishu_im_messages_search": ("im_message_read",),
    # as_user=true path of chat-messages-list (default for history summary)
    "feishu_im_chat_messages_list": ("im_message_read",),
    "feishu_bitable_create": ("bitable_create", "bitable_write"),
    "feishu_bitable_field_list": ("bitable_write",),
    "feishu_bitable_parse_url": ("bitable_write",),
    "feishu_bitable_record_list": ("bitable_write",),
    "feishu_bitable_enrich_tse_records": ("bitable_write", "contact"),
    "feishu_bitable_write_tse_records": ("bitable_write", "contact"),
    "feishu_bitable_record_batch_create": ("bitable_write",),
    "feishu_bitable_record_batch_update": ("bitable_write",),
    "feishu_bitable_record_upsert": ("bitable_write",),
}

# Back-compat env / callers that still pass a full scope string
_DEFAULT_SCOPES = _CORE_SCOPES


def _split_scopes(text: str) -> list[str]:
    parts: list[str] = []
    seen: set[str] = set()
    for p in (text or "").replace(",", " ").split():
        s = p.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        parts.append(s)
    return parts


def scopes_for_capabilities(capabilities: list[str] | tuple[str, ...] | str) -> str:
    """Resolve capability ids → space-separated scope string (+ offline_access)."""
    if isinstance(capabilities, str):
        caps = [c.strip() for c in capabilities.replace(",", " ").split() if c.strip()]
    else:
        caps = [str(c).strip() for c in (capabilities or []) if str(c).strip()]
    out: list[str] = []
    seen: set[str] = set()
    for s in _split_scopes(_CORE_SCOPES):
        seen.add(s)
        out.append(s)
    for cap in caps:
        for s in SCOPE_BUNDLES.get(cap, ()):
            if s not in seen:
                seen.add(s)
                out.append(s)
        # Unknown capability: treat as raw scope token if it looks like one
        if cap not in SCOPE_BUNDLES and ":" in cap and cap not in seen:
            seen.add(cap)
            out.append(cap)
    return " ".join(out)


def scopes_for_tool(tool_name: str) -> str:
    caps = TOOL_CAPABILITIES.get((tool_name or "").strip(), ())
    return scopes_for_capabilities(caps)


def merge_scopes(*chunks: str) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for s in _split_scopes(chunk):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return " ".join(out)


def resolve_oauth_scopes(
    *,
    scopes: str = "",
    capabilities: str = "",
    tool_name: str = "",
    user_id: str = "",
    merge_existing: bool = False,
) -> str:
    """Least-privilege scope string for Device Flow.

    Priority: explicit ``scopes`` → ``capabilities`` → ``tool_name`` bundles → core only.
    ``merge_existing`` defaults False so consent screens stay minimal; set True only when
    intentionally expanding while keeping prior grants.
    """
    _OVERBROAD = {"bitable:app", "calendar:calendar"}
    explicit = (scopes or "").strip()
    if explicit:
        requested = explicit
    elif (capabilities or "").strip():
        requested = scopes_for_capabilities(capabilities)
    elif (tool_name or "").strip():
        requested = scopes_for_tool(tool_name)
    else:
        requested = (
            os.getenv("FEISHU_OAUTH_DEFAULT_SCOPES") or _CORE_SCOPES
        ).strip()

    # Drop historically over-broad scopes from any source
    requested = " ".join(s for s in _split_scopes(requested) if s not in _OVERBROAD)

    existing = ""
    if merge_existing and (user_id or "").strip():
        try:
            stored = oauth_store.get_tokens(user_id)
            if stored:
                existing = " ".join(
                    s
                    for s in _split_scopes(str(stored.get("scope") or ""))
                    if s not in _OVERBROAD
                )
        except Exception:
            existing = ""
    return merge_scopes(_CORE_SCOPES, existing, requested)


_OAUTH_TOOL_HINTS: dict[str, dict[str, str]] = {
    "feishu_oauth_start": {
        "deliverable_hint": "oauth_setup",
        "phase_hint": "blocked",
        "next_action": "user_reply_authorized_then_oauth_complete",
    },
    "feishu_oauth_complete": {
        "deliverable_hint": "oauth_setup",
        "phase_hint": "done",
        "next_action": "resume_prior_goal",
    },
    "feishu_oauth_status": {
        "deliverable_hint": "oauth_setup",
        "phase_hint": "planned",
        "next_action": "feishu_oauth_start_if_needed",
    },
}


def _tool_ok(tool: str, data: dict, meta: dict | None = None) -> dict:
    data_m = dict(data or {})
    meta_m = dict(meta or {})
    for key, val in (_OAUTH_TOOL_HINTS.get(tool) or {}).items():
        data_m.setdefault(key, val)
        meta_m.setdefault(key, val)
    return {"ok": True, "tool": tool, "data": data_m, "error": None, "meta": meta_m}


def _tool_err(
    tool: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    data: dict | None = None,
    meta: dict | None = None,
) -> dict:
    data_m = dict(data or {})
    meta_m = dict(meta or {})
    for key, val in (_OAUTH_TOOL_HINTS.get(tool) or {}).items():
        data_m.setdefault(key, val)
        meta_m.setdefault(key, val)
    return {
        "ok": False,
        "tool": tool,
        "data": data_m,
        "error": {"code": code, "message": message, "retryable": retryable},
        "meta": meta_m,
    }


def _require_user_id(tool: str) -> tuple[Optional[str], Optional[dict]]:
    uid = get_adk_user_id()
    if not uid:
        return None, _tool_err(
            tool,
            "MISSING_USER_ID",
            "缺少 X-Adk-User-Id。请通过飞书/TSE 会话调用（ADK session.user_id），"
            "勿在无用户上下文下直接调个人 OAuth 工具。",
        )
    return uid, None


def _resolve_lark_cli() -> Optional[str]:
    explicit = (os.getenv("LARK_CLI_BIN") or "").strip()
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return explicit
    return shutil.which("lark-cli")


def _ensure_app_env() -> None:
    app_id = (os.getenv("LARKSUITE_CLI_APP_ID") or os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (
        os.getenv("LARKSUITE_CLI_APP_SECRET")
        or os.getenv("FEISHU_APP_SECRET")
        or os.getenv("FEISHU_APP_TOKEN")
        or ""
    ).strip()
    if app_id and not (os.getenv("LARKSUITE_CLI_APP_ID") or "").strip():
        os.environ["LARKSUITE_CLI_APP_ID"] = app_id
    if app_secret and not (os.getenv("LARKSUITE_CLI_APP_SECRET") or "").strip():
        os.environ["LARKSUITE_CLI_APP_SECRET"] = app_secret


def user_home_dir(user_id: str) -> Path:
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:24]
    root = Path(os.getenv("FEISHU_OAUTH_HOME_ROOT") or "/tmp/lark-oauth")
    path = root / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def _app_credentials() -> tuple[str, str]:
    app_id = (os.getenv("LARKSUITE_CLI_APP_ID") or os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (
        os.getenv("LARKSUITE_CLI_APP_SECRET")
        or os.getenv("FEISHU_APP_SECRET")
        or os.getenv("FEISHU_APP_TOKEN")
        or ""
    ).strip()
    return app_id, app_secret


def _seed_cli_config(home: Path) -> None:
    """Write app credentials under isolated HOME (auth cannot use env provider)."""
    app_id, app_secret = _app_credentials()
    if not app_id or not app_secret:
        return
    payload = {
        "appId": app_id,
        "appSecret": app_secret,
        "app_id": app_id,
        "app_secret": app_secret,
        "brand": "feishu",
    }
    raw = json.dumps(payload, indent=2)
    for rel in (
        ".lark-cli/config.json",
        ".config/lark-cli/config.json",
        ".larksuite/cli/config.json",
    ):
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")


def _cli_env(home: Path, *, for_auth: bool = False) -> dict[str, str]:
    _ensure_app_env()
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    # Avoid picking up a shared keychain; prefer files under HOME
    env.pop("LARKSUITE_CLI_USER_ACCESS_TOKEN", None)
    env.pop("LARKSUITE_CLI_TENANT_ACCESS_TOKEN", None)
    if for_auth:
        # When LARKSUITE_CLI_APP_* are in env, lark-cli treats them as an
        # "external credential provider" and **blocks the entire auth family**.
        # Seed local config under HOME instead, then strip env provider vars.
        _seed_cli_config(home)
        for key in (
            "LARKSUITE_CLI_APP_ID",
            "LARKSUITE_CLI_APP_SECRET",
            "LARK_APP_ID",
            "LARK_APP_SECRET",
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "FEISHU_APP_TOKEN",
        ):
            env.pop(key, None)
    return env


def _parse_json_blob(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    # greedy first {...}
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def _run_cli(
    home: Path,
    argv: list[str],
    *,
    timeout: int | None = None,
    json_output: bool = True,
) -> tuple[int, str, str, Optional[dict]]:
    cli = _resolve_lark_cli()
    if not cli:
        return 127, "", "lark-cli not found", None
    # `auth login` rejects global `--format json`; use `--json` (or none).
    cmd = [cli, *argv]
    is_auth = bool(argv and argv[0] == "auth")
    if json_output and is_auth and "--json" not in cmd and "--format" not in cmd:
        cmd.append("--json")
    elif json_output and not is_auth and "--format" not in cmd:
        cmd = [cli, "--format", "json", *argv]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout or _CLI_TIMEOUT_SEC,
            env=_cli_env(home, for_auth=is_auth),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timeout", None
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    payload = _parse_json_blob(stdout) or _parse_json_blob(stderr)
    return proc.returncode, stdout, stderr, payload


def _find_token_files(home: Path) -> list[Path]:
    hits: list[Path] = []
    for pattern in (
        "**/*.json",
        "**/credentials*",
        "**/*token*",
        "**/.lark-cli/**",
    ):
        hits.extend(p for p in home.glob(pattern) if p.is_file())
    # de-dupe
    seen = set()
    out = []
    for p in hits:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _extract_tokens_from_obj(obj: Any) -> Optional[dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    # Direct
    access = (
        obj.get("access_token")
        or obj.get("accessToken")
        or obj.get("user_access_token")
        or ""
    )
    refresh = obj.get("refresh_token") or obj.get("refreshToken") or ""
    if not access and isinstance(obj.get("data"), dict):
        return _extract_tokens_from_obj(obj["data"])
    if not access and isinstance(obj.get("token"), dict):
        return _extract_tokens_from_obj(obj["token"])
    if not str(access).strip():
        return None
    now = time.time()
    expires_at = obj.get("expires_at") or obj.get("expiresAt")
    if expires_at is None:
        expires_in = int(obj.get("expires_in") or obj.get("expiresIn") or 7200)
        expires_at = now + max(60, expires_in - 120)
    else:
        expires_at = float(expires_at)
        # ms vs sec heuristic
        if expires_at > 10_000_000_000:
            expires_at = expires_at / 1000.0
    refresh_expires_at = obj.get("refresh_expires_at") or obj.get("refreshExpiresAt") or 0
    if refresh_expires_at:
        refresh_expires_at = float(refresh_expires_at)
        if refresh_expires_at > 10_000_000_000:
            refresh_expires_at = refresh_expires_at / 1000.0
    return {
        "access_token": str(access).strip(),
        "refresh_token": str(refresh).strip(),
        "expires_at": float(expires_at),
        "refresh_expires_at": float(refresh_expires_at or 0),
        "scope": str(obj.get("scope") or "").strip(),
        "open_id": str(
            obj.get("open_id")
            or obj.get("userOpenId")
            or obj.get("user_open_id")
            or ""
        ).strip(),
        "app_id": str(obj.get("app_id") or obj.get("appId") or "").strip(),
    }


def _load_tokens_from_home(home: Path) -> Optional[dict[str, Any]]:
    for path in _find_token_files(home):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        # file may be a list of tokens or nested map
        candidates = [obj]
        if isinstance(obj, list):
            candidates = [x for x in obj if isinstance(x, dict)]
        elif isinstance(obj, dict):
            for v in obj.values():
                if isinstance(v, dict):
                    candidates.append(v)
                elif isinstance(v, list):
                    candidates.extend(x for x in v if isinstance(x, dict))
        for c in candidates:
            tok = _extract_tokens_from_obj(c)
            if tok:
                return tok
    return None


def _ensure_offline_scope(scope: str) -> str:
    parts = [p for p in (scope or "").split() if p]
    if "offline_access" not in parts:
        parts.append("offline_access")
    return " ".join(parts)


def _http_form(
    url: str,
    form: dict[str, str],
    *,
    basic_auth: tuple[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any], str]:
    body = urllib.parse.urlencode(form).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if basic_auth:
        token = base64.b64encode(
            f"{basic_auth[0]}:{basic_auth[1]}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = (exc.read() or b"{}").decode("utf-8", errors="replace")
        status = exc.code
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, {}, f"network error: {exc}"
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return status, {}, raw[:500]
    if not isinstance(payload, dict):
        return status, {}, raw[:500]
    return status, payload, ""


def _device_authorization_start(scope: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    app_id, app_secret = _app_credentials()
    if not app_id or not app_secret:
        return None, "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET"
    scope = _ensure_offline_scope(scope)
    status, data, net_err = _http_form(
        _DEVICE_AUTH_URL,
        {
            "client_id": app_id,
            "client_secret": app_secret,
            "scope": scope,
        },
    )
    if net_err:
        return None, net_err
    if status >= 400 or data.get("error"):
        msg = (
            str(data.get("error_description") or data.get("error") or data)
            or f"HTTP {status}"
        )
        return None, f"device_authorization 失败: {msg}"[:400]
    device_code = str(data.get("device_code") or "").strip()
    verification_url = str(
        data.get("verification_uri_complete")
        or data.get("verification_uri")
        or data.get("verification_url")
        or ""
    ).strip()
    if not device_code or not verification_url:
        return None, f"响应缺少 device_code/verification_uri: {list(data.keys())}"
    return {
        "device_code": device_code,
        "user_code": str(data.get("user_code") or ""),
        "verification_url": verification_url,
        "expires_in": int(data.get("expires_in") or 240),
        "interval": int(data.get("interval") or 5),
        "scope": scope,
        "app_id": app_id,
    }, None


def _device_code_poll_once(device_code: str) -> tuple[Optional[dict[str, Any]], Optional[str], Optional[str]]:
    """Returns (tokens, pending_or_error_code, message)."""
    app_id, app_secret = _app_credentials()
    if not app_id or not app_secret:
        return None, "CLI_NOT_READY", "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET"
    status, data, net_err = _http_form(
        _TOKEN_URL,
        {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": app_id,
            "client_secret": app_secret,
        },
    )
    if net_err:
        return None, "NETWORK", net_err
    # Nested data for some Feishu responses
    payload = data.get("data") if isinstance(data.get("data"), dict) else data
    err = str(payload.get("error") or data.get("error") or "").strip()
    access = str(payload.get("access_token") or "").strip()
    if access and not err:
        now = time.time()
        expires_in = int(payload.get("expires_in") or 7200)
        refresh_expires_in = int(payload.get("refresh_token_expires_in") or 0)
        return {
            "access_token": access,
            "refresh_token": str(payload.get("refresh_token") or "").strip(),
            "expires_at": now + max(60, expires_in - 120),
            "refresh_expires_at": (
                now + refresh_expires_in if refresh_expires_in else 0
            ),
            "scope": str(payload.get("scope") or "").strip(),
            "open_id": str(
                payload.get("open_id") or payload.get("user_id") or ""
            ).strip(),
            "app_id": app_id,
        }, None, None
    if err in {"authorization_pending", "slow_down"}:
        return None, err, str(payload.get("error_description") or err)
    if status >= 400 or err:
        return (
            None,
            err or "token_error",
            str(payload.get("error_description") or payload.get("msg") or data)[:400],
        )
    return None, "token_error", f"unexpected token response keys={list(payload.keys())}"


def begin_user_oauth(
    user_id: str,
    scopes: str = "",
    *,
    capabilities: str = "",
    tool_name: str = "",
    merge_existing: bool = True,
) -> tuple[Optional[dict], Optional[str]]:
    """Start Device Flow for ``user_id``; persist pending; return public fields or error.

    Scope selection follows least privilege via ``resolve_oauth_scopes``.
    """
    uid = (user_id or "").strip()
    if not uid:
        return None, "缺少 user_id"
    _ensure_app_env()
    app_id, app_secret = _app_credentials()
    if not app_id or not app_secret:
        return None, "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET"

    # Task-specific auth: do not merge old kitchen-sink grants onto the consent screen
    if capabilities or tool_name or scopes:
        merge = merge_existing
    else:
        merge = False

    scope = resolve_oauth_scopes(
        scopes=scopes,
        capabilities=capabilities,
        tool_name=tool_name,
        user_id=uid,
        merge_existing=merge,
    )
    started, serr = _device_authorization_start(scope)
    if not started:
        return None, serr or "device_authorization 失败"

    try:
        oauth_store.put_pending(
            uid,
            {
                "device_code": started["device_code"],
                "verification_url": started["verification_url"],
                "scope": started["scope"],
                "interval": started.get("interval") or 5,
                "expires_in": started.get("expires_in") or 240,
                "started_at": time.time(),
                "flow": "http_device",
            },
        )
    except Exception as exc:
        return None, f"写入 pending 失败: {exc}"

    return {
        "user_id": uid,
        "verification_url": started["verification_url"],
        "device_code": started["device_code"],
        "user_code": started.get("user_code") or "",
        "scope": started["scope"],
        "requested_scopes": scope,
        "expires_in": started.get("expires_in"),
        "instructions": (
            "请把 verification_url **原样放进单独代码块**发给用户（三个反引号包住整段 URL，"
            "禁止 Markdown 链接）。用户点开飞书授权页确认即可，无需进开发者后台；"
            "结束后本轮；用户回复「已授权」后再 feishu_oauth_complete。"
            "本次仅申请当前任务所需权限（最小权限），不会一次申请全部能力。"
        ),
    }, None


def tool_feishu_oauth_status() -> dict:
    """查看当前会话用户是否已完成飞书用户 OAuth（不含 token 原文）。"""
    tool = "feishu_oauth_status"
    uid, err = _require_user_id(tool)
    if err:
        return err
    try:
        status = oauth_store.oauth_status_public(uid)
    except Exception as exc:
        return _tool_err(tool, "STORE_ERROR", f"读取 OAuth 状态失败: {exc}", retryable=True)
    return _tool_ok(tool, {"user_id": uid, **status})


def tool_feishu_oauth_start(scopes: str = "", capabilities: str = "") -> dict:
    """发起用户 OAuth Device Flow（按 capabilities / scopes 最小权限申请）。

    capabilities 示例：``bitable_create,bitable_write`` / ``calendar_read`` /
    ``docs_read`` / ``contact`` / ``im_chat``（逗号或空格分隔）。
    未指定时仅申请 offline_access；已有令牌的 scope 会自动合并保留。
    """
    tool = "feishu_oauth_start"
    uid, err = _require_user_id(tool)
    if err:
        return err
    data, serr = begin_user_oauth(uid, scopes=scopes, capabilities=capabilities)
    if not data:
        return _tool_err(tool, "OAUTH_START_FAILED", serr or "发起授权失败")
    return _tool_ok(tool, data)


def tool_feishu_oauth_complete(device_code: str = "") -> dict:
    """用户浏览器授权完成后，轮询换取并持久化用户令牌。"""
    tool = "feishu_oauth_complete"
    uid, err = _require_user_id(tool)
    if err:
        return err
    pending = None
    try:
        pending = oauth_store.get_pending(uid)
    except Exception as exc:
        return _tool_err(tool, "STORE_ERROR", f"读取 pending 失败: {exc}", retryable=True)

    code = (device_code or "").strip() or str((pending or {}).get("device_code") or "").strip()
    if not code:
        return _tool_err(
            tool,
            "NO_PENDING_OAUTH",
            "没有 pending device_code。请先 feishu_oauth_start。",
        )

    interval = max(2, int((pending or {}).get("interval") or 5))
    # User already confirmed; poll up to ~90s
    deadline = time.time() + 90
    last_msg = ""
    while time.time() < deadline:
        tokens, pend_err, msg = _device_code_poll_once(code)
        if tokens:
            app_id = (os.getenv("LARKSUITE_CLI_APP_ID") or os.getenv("FEISHU_APP_ID") or "").strip()
            if not tokens.get("app_id"):
                tokens["app_id"] = app_id
            try:
                oauth_store.put_tokens(uid, tokens)
                oauth_store.delete_pending(uid)
            except Exception as exc:
                return _tool_err(
                    tool, "STORE_ERROR", f"持久化 token 失败: {exc}", retryable=True
                )
            return _tool_ok(
                tool,
                {
                    "user_id": uid,
                    "authorized": True,
                    "open_id": tokens.get("open_id") or "",
                    "scope": tokens.get("scope") or "",
                    "expires_at": tokens.get("expires_at"),
                    "hint": "授权成功。之后日历/文档/表格读工具将以用户身份（--as user）调用。",
                },
            )
        if pend_err in {"authorization_pending", "slow_down"}:
            last_msg = msg or pend_err
            if pend_err == "slow_down":
                interval = min(interval + 5, 30)
            time.sleep(interval)
            continue
        return _tool_err(
            tool,
            "OAUTH_COMPLETE_FAILED",
            msg or pend_err or "换取 token 失败",
            retryable=pend_err in {"NETWORK", "authorization_pending"},
        )

    return _tool_err(
        tool,
        "OAUTH_COMPLETE_FAILED",
        "等待授权超时。请确认已在浏览器点完同意，然后再次调用 feishu_oauth_complete。"
        + (f" last={last_msg}" if last_msg else ""),
        retryable=True,
    )
