# -*- coding: utf-8 -*-
"""Feishu L1 tools — whitelist wrappers around ``lark-cli`` (bot identity)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_YEAR_PREFIX_RE = re.compile(r"^(\d{4})")

_CLI_TIMEOUT_SEC = int((os.getenv("FEISHU_CLI_TIMEOUT_SEC") or "90").strip() or "90")
_MAX_TEXT_CHARS = 8000
_MAX_DOC_CHARS = 50000
_ID_RE = re.compile(r"^[A-Za-z0-9_.:\-/]+$")
_CHAT_OR_USER_RE = re.compile(r"^(oc_|ou_|on_)[A-Za-z0-9]+$")
_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
_token_cache: dict[str, Any] = {"token": "", "expires_at": 0.0}


# deliverable_hint / phase_hint / next_action — Task Card + TSE continue read these.
_TOOL_HINTS: dict[str, dict[str, str]] = {
    "feishu_bitable_create": {
        "deliverable_hint": "bitable_with_rows",
        "phase_hint": "created",
        "next_action": "feishu_bitable_record_batch_create",
    },
    "feishu_bitable_parse_url": {
        "deliverable_hint": "bitable_with_rows",
        "phase_hint": "in_progress",
        "next_action": "feishu_bitable_field_list_or_record_batch_create",
    },
    "feishu_bitable_table_list": {
        "deliverable_hint": "bitable_with_rows",
        "phase_hint": "in_progress",
        "next_action": "feishu_bitable_record_batch_create",
    },
    "feishu_bitable_field_list": {
        "deliverable_hint": "bitable_with_rows",
        "phase_hint": "in_progress",
        "next_action": "feishu_bitable_record_batch_create_or_write_tse",
    },
    "feishu_bitable_record_batch_create": {
        "deliverable_hint": "bitable_with_rows",
        "phase_hint": "done",
        "next_action": "report_url_to_user",
    },
    "feishu_bitable_write_tse_records": {
        "deliverable_hint": "bitable_with_rows",
        "phase_hint": "done",
        "next_action": "report_url_to_user",
    },
    "feishu_bitable_record_upsert": {
        "deliverable_hint": "bitable_with_rows",
        "phase_hint": "done",
        "next_action": "report_url_to_user",
    },
    "feishu_bitable_record_batch_update": {
        "deliverable_hint": "bitable_with_rows",
        "phase_hint": "done",
        "next_action": "report_url_to_user",
    },
    "feishu_doc_search": {
        "deliverable_hint": "doc_search_answer",
        "phase_hint": "searched",
        "next_action": "report_search_results_to_user",
    },
    "feishu_doc_fetch": {
        "deliverable_hint": "doc_fetch",
        "phase_hint": "done",
        "next_action": "report_doc_content_to_user",
    },
    "feishu_doc_create_markdown": {
        "deliverable_hint": "doc_created",
        "phase_hint": "done",
        "next_action": "report_url_to_user",
    },
    "feishu_calendar_create": {
        "deliverable_hint": "calendar_event",
        "phase_hint": "done",
        "next_action": "report_event_to_user",
    },
    "feishu_calendar_agenda": {
        "deliverable_hint": "calendar_agenda",
        "phase_hint": "done",
        "next_action": "report_agenda_to_user",
    },
    "feishu_calendar_freebusy": {
        "deliverable_hint": "calendar_agenda",
        "phase_hint": "done",
        "next_action": "report_freebusy_to_user",
    },
    "feishu_im_send_text": {
        "deliverable_hint": "im_message_sent",
        "phase_hint": "done",
        "next_action": "report_sent_to_user",
    },
    "feishu_contact_search_user": {
        "deliverable_hint": "contact_resolved",
        "phase_hint": "searched",
        "next_action": "confirm_then_send_or_invite",
    },
    "feishu_im_chat_search": {
        "deliverable_hint": "chat_resolved",
        "phase_hint": "searched",
        "next_action": "confirm_then_im_send_text",
    },
    "feishu_im_messages_search": {
        "deliverable_hint": "im_chat_topic_summary",
        "phase_hint": "searched",
        "next_action": "report_topic_hits_to_user",
    },
    "feishu_im_chat_messages_list": {
        "deliverable_hint": "im_chat_topic_summary",
        "phase_hint": "in_progress",
        "next_action": "paginate_or_report_messages",
    },
    "feishu_sheet_write_csv": {
        "deliverable_hint": "sheet_updated",
        "phase_hint": "done",
        "next_action": "report_sheet_to_user",
    },
    "feishu_sheet_read": {
        "deliverable_hint": "sheet_read",
        "phase_hint": "done",
        "next_action": "report_sheet_to_user",
    },
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
}


def _merge_tool_hints(tool: str, data: dict, meta: dict) -> tuple[dict, dict]:
    """Inject stable deliverable/phase/next_action without clobbering explicit values."""
    hints = _TOOL_HINTS.get(tool) or {}
    if not hints:
        return data, meta
    data_out = dict(data) if isinstance(data, dict) else {}
    meta_out = dict(meta) if isinstance(meta, dict) else {}
    for key in ("deliverable_hint", "phase_hint", "next_action"):
        if key not in data_out and hints.get(key):
            data_out[key] = hints[key]
        if key not in meta_out and hints.get(key):
            meta_out[key] = hints[key]
    return data_out, meta_out


def _tool_ok(tool: str, data: dict, meta: dict | None = None) -> dict:
    data_m, meta_m = _merge_tool_hints(tool, data or {}, meta or {})
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
    data_m, meta_m = _merge_tool_hints(tool, data or {}, meta or {})
    return {
        "ok": False,
        "tool": tool,
        "data": data_m,
        "error": {"code": code, "message": message, "retryable": retryable},
        "meta": meta_m,
    }


def _ensure_cli_credentials_env() -> None:
    """Map FEISHU_* → LARKSUITE_CLI_* for headless bot token minting."""
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


def _mint_tenant_access_token() -> tuple[Optional[str], Optional[str]]:
    """Exchange app credentials for tenant_access_token (Feishu OpenAPI).

    Newer lark-cli can mint from env itself; older builds need
    ``LARKSUITE_CLI_TENANT_ACCESS_TOKEN`` injected explicitly.
    """
    now = time.time()
    cached = str(_token_cache.get("token") or "")
    if cached and float(_token_cache.get("expires_at") or 0) > now + 60:
        return cached, None

    app_id = (os.getenv("LARKSUITE_CLI_APP_ID") or os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (
        os.getenv("LARKSUITE_CLI_APP_SECRET")
        or os.getenv("FEISHU_APP_SECRET")
        or os.getenv("FEISHU_APP_TOKEN")
        or ""
    ).strip()
    if not app_id or not app_secret:
        return None, "缺少 FEISHU_APP_ID / FEISHU_APP_SECRET"

    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        _TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            payload = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return None, f"tenant_access_token 请求失败: {exc}"

    if not isinstance(payload, dict):
        return None, f"tenant_access_token 响应非对象: {raw[:200]}"

    try:
        code = int(payload.get("code"))
    except (TypeError, ValueError):
        return None, f"tenant_access_token 响应 code 异常: {payload!r}"[:300]

    if code != 0:
        return None, (
            f"tenant_access_token 失败 code={code} "
            f"msg={payload.get('msg')!r}"
        )[:300]
    token = (payload.get("tenant_access_token") or "").strip()
    if not token:
        keys = ",".join(sorted(payload.keys()))
        return None, f"响应缺少 tenant_access_token（keys={keys}）"
    expire = int(payload.get("expire") or 7200)
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + max(60, expire - 120)
    os.environ["LARKSUITE_CLI_TENANT_ACCESS_TOKEN"] = token
    return token, None


def _resolve_lark_cli() -> Optional[str]:
    explicit = (os.getenv("LARK_CLI_BIN") or "").strip()
    if explicit and os.path.isfile(explicit) and os.access(explicit, os.X_OK):
        return explicit
    return shutil.which("lark-cli")


def _validate_token_like(value: str, *, field: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return f"{field} 不能为空"
    if len(text) > 512:
        return f"{field} 过长"
    # Allow URLs for doc/spreadsheet refs
    if text.startswith("http://") or text.startswith("https://"):
        if any(c in text for c in (" ", ";", "|", "`", "$(", "\n", "\r")):
            return f"{field} URL 含非法字符"
        return None
    if not _ID_RE.match(text):
        return f"{field} 格式不合法"
    return None


def _validate_chat_or_user(value: str, *, field: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return f"{field} 不能为空"
    if not _CHAT_OR_USER_RE.match(text):
        return f"{field} 须为 oc_/ou_/on_ 开头的飞书 ID"
    return None


def _run_lark_cli(
    argv: list[str],
    *,
    tool: str,
    json_format: bool = True,
    require_bot_token: bool = True,
    identity: str = "bot",
) -> dict[str, Any]:
    """Run a fixed argv list (caller builds whitelist). Prefer global ``--format json``.

    identity:
      - bot: mint tenant token (default)
      - user: require ADK user OAuth UAT via Firestore; inject LARKSUITE_CLI_USER_ACCESS_TOKEN
    """
    from domains.feishu.oauth_store import ensure_fresh_uat
    from domains.feishu.user_context import get_adk_user_id

    _ensure_cli_credentials_env()
    cli = _resolve_lark_cli()
    if not cli:
        return _tool_err(
            tool,
            "CLI_NOT_READY",
            "未找到 lark-cli 可执行文件。请在镜像中安装 @larksuite/cli，"
            "或设置 LARK_CLI_BIN。",
        )
    if not (os.getenv("LARKSUITE_CLI_APP_ID") or "").strip() or not (
        os.getenv("LARKSUITE_CLI_APP_SECRET") or ""
    ).strip():
        return _tool_err(
            tool,
            "CLI_NOT_READY",
            "缺少飞书应用凭证：请设置 FEISHU_APP_ID + FEISHU_APP_SECRET "
            "（或 LARKSUITE_CLI_APP_ID + LARKSUITE_CLI_APP_SECRET）。",
        )

    env = os.environ.copy()
    ident = (identity or "bot").strip().lower()
    if ident == "user":
        uid = get_adk_user_id()
        if not uid:
            return _tool_err(
                tool,
                "MISSING_USER_ID",
                "用户身份调用需要 X-Adk-User-Id（ADK session.user_id）。",
            )
        uat, uerr = ensure_fresh_uat(uid)
        if not uat:
            code = "NEED_USER_OAUTH" if (uerr == "NEED_USER_OAUTH" or not uerr) else "OAUTH_REFRESH_FAILED"
            return _tool_err(
                tool,
                code,
                (
                    "当前用户尚未完成飞书 OAuth，或令牌已失效。"
                    "请先 feishu_oauth_start → 把 verification_url 发给用户 → "
                    "用户授权后再 feishu_oauth_complete。"
                    + (f" detail={uerr}" if uerr and uerr != "NEED_USER_OAUTH" else "")
                ),
                data={"user_id": uid},
            )
        env["LARKSUITE_CLI_USER_ACCESS_TOKEN"] = uat
        # Prefer user token over any stale tenant token for this process env copy
        env.pop("LARKSUITE_CLI_TENANT_ACCESS_TOKEN", None)
        require_bot_token = False
    elif require_bot_token:
        token, terr = _mint_tenant_access_token()
        if not token:
            return _tool_err(
                tool,
                "CLI_NOT_READY",
                terr or "无法获取 tenant_access_token",
                retryable=True,
            )
        env["LARKSUITE_CLI_TENANT_ACCESS_TOKEN"] = token

    # Rewrite --as in argv if present; callers usually already set it
    final_argv = list(argv)
    if "--as" in final_argv:
        i = final_argv.index("--as")
        if i + 1 < len(final_argv):
            final_argv[i + 1] = "user" if ident == "user" else "bot"

    # Global flags before subcommand: `lark-cli --format json calendar +agenda …`
    cmd = [cli]
    if json_format and "--format" not in final_argv:
        cmd.extend(["--format", "json"])
    cmd.extend(final_argv)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_CLI_TIMEOUT_SEC,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _tool_err(
            tool,
            "CLI_TIMEOUT",
            f"lark-cli 超时（>{_CLI_TIMEOUT_SEC}s）：{' '.join(final_argv[:6])}",
            retryable=True,
        )
    except OSError as exc:
        return _tool_err(tool, "CLI_EXEC_FAILED", f"无法执行 lark-cli: {exc}")

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    payload: Any = None
    for blob in (stdout, stderr):
        if not blob:
            continue
        try:
            payload = json.loads(blob)
            break
        except json.JSONDecodeError:
            # Try last JSON object in SSE-ish / multi-line output
            for line in reversed(blob.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        payload = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            if payload is not None:
                break

    meta = {
        "argv": final_argv,
        "exit_code": proc.returncode,
        "cli": cli,
        "identity": ident,
    }

    if isinstance(payload, dict):
        if payload.get("ok") is True:
            return _tool_ok(
                tool,
                {
                    "identity": payload.get("identity") or ident,
                    "result": payload.get("data"),
                    "cli_meta": payload.get("meta"),
                },
                meta=meta,
            )
        err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        err_type = str(err.get("type") or "").strip().lower()
        err_subtype = str(err.get("subtype") or "").strip().lower()
        msg = str(
            err.get("message") or err.get("hint") or stderr or stdout or "lark-cli 失败"
        )[:500]
        missing = err.get("missing_scopes") or err.get("scopes") or []
        if isinstance(missing, str):
            missing = [missing]
        if not isinstance(missing, list):
            missing = []
        # Feishu often embeds scopes only in the message text
        if not missing:
            m = re.search(
                r"required scope\(s\):\s*([^\n→]+)",
                msg,
                flags=re.IGNORECASE,
            )
            if m:
                missing = [
                    p.strip().rstrip(",.;")
                    for p in re.split(r"[\s,]+", m.group(1))
                    if p.strip() and ":" in p
                ]
        code = str(err_subtype or err_type or "CLI_ERROR")
        data: dict[str, Any] = {"cli_error": err}
        if missing:
            data["missing_scopes"] = missing
        # Map auth failures to actionable codes for the agent
        if err_type in {"authorization", "auth"} or "scope" in err_subtype or "scope" in msg.lower():
            # Feishu often says "app has not applied" even for user-token calls when
            # the UAT simply lacks a fine-grained scope (e.g. base:record:read).
            # If we're on --as user and the gap is a user bitable-read scope, prefer
            # re-OAuth over sending the developer-console link.
            missing_l = {str(s).strip().lower() for s in missing}
            _USER_BITABLE_READ = {"base:record:read", "base:record:retrieve"}
            user_token_likely_stale = (
                ident == "user"
                and bool(missing_l & _USER_BITABLE_READ)
                and (
                    "has not applied" in msg.lower()
                    or "app_scope" in err_subtype
                    or "required scope" in msg.lower()
                )
            )
            # App-level: developer never enabled the API scope in 开放平台.
            is_app_scope = (
                not user_token_likely_stale
                and (
                    "app_scope" in err_subtype
                    or "app scope" in msg.lower()
                    or "has not applied" in msg.lower()
                    or ("未开通" in msg and "权限" in msg)
                    or ("未申请" in msg and ("权限" in msg or "scope" in msg.lower()))
                )
            )
            if user_token_likely_stale:
                code = "NEED_REAUTH"
                scope_list = ", ".join(sorted(missing_l & _USER_BITABLE_READ)) or ", ".join(
                    str(s) for s in missing
                )
                msg = (
                    f"{msg} → 当前用户令牌可能缺少 [{scope_list}]。"
                    "开放平台「用户身份」已开通时，请重新 feishu_oauth_start"
                    "(capabilities=bitable_write) 刷新授权（旧令牌不会自动带上新 scope）；"
                    "完成后回复「已授权」再重试。不要只点应用权限开通页。"
                )
                data["fix"] = (
                    "用户 OAuth 令牌缺 base:record:read/retrieve（控制台有 ≠ 令牌里有）。"
                    "重新个人授权即可；禁止误导用户去开应用身份。"
                )
                data["also_need_user_reauth"] = True
                try:
                    from domains.feishu.oauth_flow import begin_user_oauth
                    from domains.feishu.user_context import get_adk_user_id

                    uid = get_adk_user_id()
                    reauth, _rerr = (
                        begin_user_oauth(
                            uid,
                            capabilities="bitable_write",
                            merge_existing=False,
                        )
                        if uid
                        else (None, "no user")
                    )
                    if reauth and reauth.get("verification_url"):
                        data["verification_url"] = reauth["verification_url"]
                        data["action_url"] = reauth["verification_url"]
                        data["action_kind"] = "user_oauth"
                        data["user_code"] = reauth.get("user_code") or ""
                        data["reauth_started"] = True
                        data["instructions"] = reauth.get("instructions") or (
                            "把 verification_url 放进代码块发给用户；"
                            "用户授权后回复「已授权」。"
                        )
                        msg += f" verification_url={reauth['verification_url']}"
                except Exception as exc:
                    data["reauth_start_error"] = str(exc)[:200]
            elif is_app_scope:
                code = "MISSING_APP_SCOPE"
                app_id = (
                    (os.getenv("FEISHU_APP_ID") or "").strip()
                    or (os.getenv("LARKSUITE_CLI_APP_ID") or "").strip()
                )
                scope_list = ", ".join(str(s) for s in missing) if missing else "（见上方错误）"
                data["app_id"] = app_id or None
                # Open console + try admin apply (official scopes/apply)
                try:
                    from domains.feishu.scope_remediation import remediate_app_scopes

                    rem = remediate_app_scopes(missing)
                    data.update(
                        {
                            "remediation": rem,
                            "scope_enable_url": rem.get("scope_enable_url"),
                            "action_url": rem.get("action_url"),
                            "action_kind": rem.get("action_kind") or "app_scope_enable",
                            "admin_apply": rem.get("admin_apply"),
                            "developer_console_url": rem.get("scope_enable_url"),
                        }
                    )
                    hint = rem.get("hint") or ""
                except Exception as exc:
                    from domains.feishu.scope_remediation import build_scope_enable_url

                    enable_url = build_scope_enable_url(missing, app_id=app_id)
                    data["scope_enable_url"] = enable_url
                    data["action_url"] = enable_url
                    data["action_kind"] = "app_scope_enable"
                    data["developer_console_url"] = enable_url
                    data["remediation_error"] = str(exc)[:200]
                    hint = (
                        f"请打开权限开通页勾选并发布 [{scope_list}]：{enable_url}"
                    )
                data["fix"] = (
                    "应用级权限缺口（不是个人 OAuth）。"
                    "把 action_url / scope_enable_url 放进代码块请用户点开："
                    "开通缺失 scope → 提交管理员发布；"
                    "若 admin_apply.ok=true 说明已自动向管理员提交审批。"
                    "禁止再发个人授权页；禁止用云文档冒充多维表格。"
                    "用户回复「权限已开通」后重试原工具。"
                )
                msg = (
                    f"{msg} → MISSING_APP_SCOPE [{scope_list}]。{hint}"
                )
            else:
                code = "NEED_REAUTH"
                missing_scopes_str = ", ".join(str(s) for s in missing) if missing else ""
                msg = (
                    msg
                    + " → 请点击下方授权链接，在飞书授权页确认权限即可（无需进开发者后台）；"
                    "完成后回复「已授权」。不要改用云文档冒充多维表格。"
                )
                if missing_scopes_str:
                    msg += f" 本次将申请：[{missing_scopes_str}]。"
                # Auto-start Device Flow only for user-token / user-scope gaps.
                # Prefer scopes parsed from the API error (e.g. search:message) so
                # consent matches the real gap; fall back to tool capability bundle.
                if ident == "user":
                    try:
                        from domains.feishu.oauth_flow import begin_user_oauth
                        from domains.feishu.user_context import get_adk_user_id

                        uid = get_adk_user_id()
                        scope_arg = " ".join(str(s).strip() for s in missing if str(s).strip())
                        reauth, _rerr = (
                            begin_user_oauth(
                                uid,
                                scopes=scope_arg,
                                tool_name=tool if not scope_arg else "",
                                merge_existing=True,
                            )
                            if uid
                            else (None, "no user")
                        )
                        if reauth and reauth.get("verification_url"):
                            data["verification_url"] = reauth["verification_url"]
                            data["action_url"] = reauth["verification_url"]
                            data["action_kind"] = "user_oauth"
                            data["user_code"] = reauth.get("user_code") or ""
                            data["requested_scopes"] = reauth.get("requested_scopes") or scope_arg
                            data["reauth_started"] = True
                            data["instructions"] = reauth.get("instructions") or (
                                "把 verification_url 放进代码块发给用户；"
                                "用户回复已授权后 feishu_oauth_complete。"
                            )
                    except Exception as exc:
                        data["reauth_started"] = False
                        data["reauth_error"] = str(exc)[:200]
        return _tool_err(
            tool,
            code,
            msg,
            retryable=False,
            data=data,
            meta=meta,
        )

    if proc.returncode != 0:
        return _tool_err(
            tool,
            "CLI_ERROR",
            (stderr or stdout or f"exit={proc.returncode}")[:500],
            meta=meta,
        )
    return _tool_ok(
        tool,
        {"raw_stdout": stdout[:4000], "raw_stderr": stderr[:1000], "identity": ident},
        meta=meta,
    )


def _require_user_for_read(tool: str) -> tuple[str, Optional[dict]]:
    """Calendar/doc/sheet reads require user OAuth (plan: no silent bot fallback)."""
    from domains.feishu.oauth_store import get_tokens
    from domains.feishu.user_context import get_adk_user_id

    uid = get_adk_user_id()
    if not uid:
        return "", _tool_err(
            tool,
            "MISSING_USER_ID",
            "缺少 X-Adk-User-Id。个人日历/文档/表格需在飞书或 TSE 会话中调用。",
        )
    if not get_tokens(uid):
        return uid, _tool_err(
            tool,
            "NEED_USER_OAUTH",
            "当前用户尚未授权飞书个人权限。请先 feishu_oauth_start，"
            "把 verification_url 原样发给用户；用户浏览器授权后调用 feishu_oauth_complete。",
            data={"user_id": uid},
        )
    return uid, None


def _write_identity() -> str:
    """Writes: prefer user when OAuth present, else bot."""
    from domains.feishu.oauth_store import get_tokens
    from domains.feishu.user_context import get_adk_user_id

    uid = get_adk_user_id()
    if uid and get_tokens(uid):
        return "user"
    return "bot"


def tool_feishu_cli_status() -> dict:
    """检查 lark-cli 是否可用，以及应用凭证是否已注入。"""
    tool = "feishu_cli_status"
    _ensure_cli_credentials_env()
    cli = _resolve_lark_cli()
    has_id = bool((os.getenv("LARKSUITE_CLI_APP_ID") or "").strip())
    has_secret = bool((os.getenv("LARKSUITE_CLI_APP_SECRET") or "").strip())
    if not cli:
        return _tool_err(tool, "CLI_NOT_READY", "lark-cli 未安装")
    if not has_id or not has_secret:
        return _tool_err(tool, "CLI_NOT_READY", "应用凭证未配置")
    token, terr = _mint_tenant_access_token()
    if not token:
        return _tool_err(tool, "CLI_NOT_READY", terr or "tenant_access_token 失败")
    # Prefer version probe over `auth status` (blocked under env credential provider).
    probe = _run_lark_cli(
        ["--version"],
        tool=tool,
        json_format=False,
        require_bot_token=False,
    )
    return _tool_ok(
        tool,
        {
            "cli": cli,
            "credentials": True,
            "tenant_token": True,
            "cli_probe": probe.get("data") if probe.get("ok") else probe.get("error"),
        },
        meta=probe.get("meta") or {},
    )


def _agenda_query_window(start: str, end: str) -> tuple[str, str, dict] | tuple[None, None, dict]:
    """Resolve agenda range in Asia/Shanghai; reject stale LLM years."""
    today = datetime.now(_SHANGHAI).date()
    meta: dict[str, Any] = {
        "timezone": "Asia/Shanghai",
        "server_today": today.isoformat(),
    }
    s = (start or "").strip()
    e = (end or "").strip()
    for label, val in (("start", s), ("end", e)):
        if not val:
            continue
        m = _YEAR_PREFIX_RE.match(val)
        if m and int(m.group(1)) < today.year:
            meta["stale_field"] = label
            meta["stale_value"] = val
            return None, None, meta
    if not s:
        s = f"{today.isoformat()}T00:00:00+08:00"
        meta["start_defaulted"] = True
    if not e:
        nxt = today + timedelta(days=1)
        e = f"{nxt.isoformat()}T00:00:00+08:00"
        meta["end_defaulted"] = True
    meta["queried_start"] = s
    meta["queried_end"] = e
    return s, e, meta


def _reject_stale_year(tool: str, *values: str) -> Optional[dict]:
    today = datetime.now(_SHANGHAI).date()
    for val in values:
        text = (val or "").strip()
        if not text:
            continue
        m = _YEAR_PREFIX_RE.match(text)
        if m and int(m.group(1)) < today.year:
            return _tool_err(
                tool,
                "STALE_DATE",
                (
                    f"日期年份过旧（{text}），疑似模型臆测。"
                    f"今天是 {today.isoformat()}（Asia/Shanghai）。"
                ),
                data={"server_today": today.isoformat(), "stale_value": text},
            )
    return None


def _parse_attendee_ids(raw: str, *, tool: str) -> tuple[Optional[str], Optional[dict]]:
    text = (raw or "").strip()
    if not text:
        return "", None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if len(parts) > 50:
        return None, _tool_err(tool, "INVALID_ARGUMENT", "attendee_ids 最多 50 个")
    for p in parts:
        if not (p.startswith("ou_") or p.startswith("oc_") or p.startswith("omm_")):
            return None, _tool_err(
                tool,
                "INVALID_ARGUMENT",
                f"attendee_ids 项须为 ou_/oc_/omm_ 前缀，非法项: {p}",
            )
        verr = _validate_chat_or_user(p, field="attendee_id") if p.startswith(("ou_", "oc_")) else None
        if verr:
            # omm_ rooms: allow token-like
            if p.startswith("omm_"):
                if not _ID_RE.match(p):
                    return None, _tool_err(tool, "INVALID_ARGUMENT", f"会议室 id 不合法: {p}")
            else:
                return None, _tool_err(tool, "INVALID_ARGUMENT", verr)
    return ",".join(parts), None


def _ensure_shanghai_offset(iso_text: str) -> str:
    """If datetime lacks offset, append +08:00."""
    text = (iso_text or "").strip()
    if not text:
        return text
    if re.search(r"(Z|[+-]\d{2}:?\d{2})$", text, re.I):
        return text
    # date-only or local datetime
    if "T" in text:
        return f"{text}+08:00"
    return text


def _im_time_bound(iso_or_date: str, *, end_of_day: bool = False) -> str:
    """Normalize IM ``--start``/``--end`` to ISO 8601 with Asia/Shanghai offset.

    Accepts ``YYYY-MM-DD`` or full ISO; date-only becomes start/end of that day.
    """
    text = (iso_or_date or "").strip()
    if not text:
        return text
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        suffix = "T23:59:59+08:00" if end_of_day else "T00:00:00+08:00"
        return f"{text}{suffix}"
    return _ensure_shanghai_offset(text)


def _validate_page_token(token: str) -> str | None:
    tok = (token or "").strip()
    if not tok:
        return None
    if len(tok) > 512 or any(c in tok for c in (" ", ";", "|", "`", "\n")):
        return "page_token 格式不合法"
    return None


def tool_feishu_calendar_agenda(
    start: str = "",
    end: str = "",
    calendar_id: str = "primary",
) -> dict:
    """查看当前用户日程（需用户 OAuth）。默认上海时区「今天」。"""
    tool = "feishu_calendar_agenda"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    cal = (calendar_id or "primary").strip() or "primary"
    verr = _validate_token_like(cal, field="calendar_id")
    if verr and cal != "primary":
        return _tool_err(tool, "INVALID_ARGUMENT", verr)

    resolved_start, resolved_end, window = _agenda_query_window(start, end)
    if resolved_start is None:
        return _tool_err(
            tool,
            "STALE_DATE",
            (
                f"日期年份过旧（{window.get('stale_value')}），疑似模型臆测。"
                f"今天是 {window.get('server_today')}（Asia/Shanghai）；"
                "查「今天」请将 start/end 留空。"
            ),
            data=window,
        )

    argv = [
        "calendar",
        "+agenda",
        "--as",
        "user",
        "--calendar-id",
        cal,
        "--start",
        resolved_start,
        "--end",
        resolved_end,
    ]
    out = _run_lark_cli(argv, tool=tool, identity="user")
    if isinstance(out.get("data"), dict):
        out["data"].update(
            {
                "queried_start": window["queried_start"],
                "queried_end": window["queried_end"],
                "timezone": window["timezone"],
                "server_today": window["server_today"],
            }
        )
    return out


def tool_feishu_calendar_create(
    summary: str,
    start: str,
    end: str,
    attendee_ids: str = "",
    description: str = "",
    calendar_id: str = "primary",
) -> dict:
    """创建日程并可邀请参会人（需用户 OAuth；写操作）。

    start/end 用 ISO 8601（建议带 +08:00）。参会人先 ``feishu_contact_search_user`` 解析为 ou_。
    """
    tool = "feishu_calendar_create"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    title = (summary or "").strip()
    if not title:
        return _tool_err(tool, "INVALID_ARGUMENT", "summary（标题）不能为空")
    if len(title) > 200:
        return _tool_err(tool, "INVALID_ARGUMENT", "summary 超过 200 字符")
    s = _ensure_shanghai_offset((start or "").strip())
    e = _ensure_shanghai_offset((end or "").strip())
    if not s or not e:
        return _tool_err(tool, "INVALID_ARGUMENT", "start 与 end 均为必填（ISO 8601）")
    stale = _reject_stale_year(tool, s, e)
    if stale:
        return stale
    desc = (description or "").strip()
    if len(desc) > _MAX_TEXT_CHARS:
        return _tool_err(tool, "INVALID_ARGUMENT", f"description 超过 {_MAX_TEXT_CHARS} 字符")
    cal = (calendar_id or "primary").strip() or "primary"
    verr = _validate_token_like(cal, field="calendar_id")
    if verr and cal != "primary":
        return _tool_err(tool, "INVALID_ARGUMENT", verr)
    attendees, aerr = _parse_attendee_ids(attendee_ids, tool=tool)
    if aerr:
        return aerr

    argv = [
        "calendar",
        "+create",
        "--as",
        "user",
        "--calendar-id",
        cal,
        "--summary",
        title,
        "--start",
        s,
        "--end",
        e,
    ]
    if desc:
        argv.extend(["--description", desc])
    if attendees:
        argv.extend(["--attendee-ids", attendees])
    return _run_lark_cli(argv, tool=tool, identity="user")


def tool_feishu_calendar_freebusy(
    start: str = "",
    end: str = "",
    user_id: str = "",
) -> dict:
    """查询主日历忙闲（需用户 OAuth）。user_id 为空查自己；可传 ou_ 查他人忙闲（无标题）。"""
    tool = "feishu_calendar_freebusy"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    s = _ensure_shanghai_offset((start or "").strip())
    e = _ensure_shanghai_offset((end or "").strip())
    resolved_start, resolved_end, window = _agenda_query_window(s, e)
    if resolved_start is None:
        return _tool_err(
            tool,
            "STALE_DATE",
            (
                f"日期年份过旧（{window.get('stale_value')}），疑似模型臆测。"
                f"今天是 {window.get('server_today')}（Asia/Shanghai）。"
            ),
            data=window,
        )
    uid = (user_id or "").strip()
    if uid:
        verr = _validate_chat_or_user(uid, field="user_id")
        if verr or not uid.startswith("ou_"):
            return _tool_err(tool, "INVALID_ARGUMENT", "user_id 须为 ou_ 开头的 open_id")
    argv = [
        "calendar",
        "+freebusy",
        "--as",
        "user",
        "--start",
        resolved_start,
        "--end",
        resolved_end,
    ]
    if uid:
        argv.extend(["--user-id", uid])
    out = _run_lark_cli(argv, tool=tool, identity="user")
    if isinstance(out.get("data"), dict):
        out["data"].update(
            {
                "queried_start": window["queried_start"],
                "queried_end": window["queried_end"],
                "timezone": window["timezone"],
                "server_today": window["server_today"],
                "target_user_id": uid or "me",
            }
        )
    return out


def tool_feishu_contact_search_user(
    query: str = "",
    page_size: int = 20,
    has_chatted: bool = False,
) -> dict:
    """按姓名/邮箱搜索同事，解析 open_id（需用户 OAuth；仅 user）。

    发消息前若只有姓名：先搜 → 多候选请用户确认 → 再 ``feishu_im_send_text(user_id=ou_…)``。
    """
    tool = "feishu_contact_search_user"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    q = (query or "").strip()
    if not q:
        return _tool_err(tool, "INVALID_ARGUMENT", "query 不能为空（姓名 / 邮箱 / 手机号）")
    # Feishu limits ~50 runes; keep a safe byte/char bound
    if len(q) > 50:
        return _tool_err(tool, "INVALID_ARGUMENT", "query 超过 50 字符")
    size = max(1, min(int(page_size or 20), 30))
    argv = [
        "contact",
        "+search-user",
        "--as",
        "user",
        "--query",
        q,
        "--page-size",
        str(size),
    ]
    if has_chatted:
        argv.append("--has-chatted")
    return _run_lark_cli(argv, tool=tool, identity="user")


def tool_feishu_im_chat_search(
    query: str = "",
    member_ids: str = "",
    page_size: int = 20,
    page_token: str = "",
) -> dict:
    """搜索可见群聊（需用户 OAuth）。按群名/成员名关键词，或按成员 open_id 过滤。

    至少提供 ``query`` 或 ``member_ids`` 其一。发群消息前用本工具解析 ``chat_id``，
    再 ``feishu_im_send_text(chat_id=oc_…)``（发送仍为 Bot，Bot 须在群内）。
    """
    tool = "feishu_im_chat_search"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    q = (query or "").strip()
    mids = (member_ids or "").strip()
    if not q and not mids:
        return _tool_err(
            tool,
            "INVALID_ARGUMENT",
            "请提供 query（群名/成员名关键词）或 member_ids（ou_… 逗号分隔）至少其一",
        )
    if len(q) > 64:
        return _tool_err(tool, "INVALID_ARGUMENT", "query 超过 64 字符")
    if mids:
        parts = [p.strip() for p in mids.split(",") if p.strip()]
        if not parts:
            return _tool_err(tool, "INVALID_ARGUMENT", "member_ids 为空")
        if len(parts) > 50:
            return _tool_err(tool, "INVALID_ARGUMENT", "member_ids 最多 50 个")
        for p in parts:
            verr = _validate_chat_or_user(p, field="member_id")
            if verr or not p.startswith("ou_"):
                return _tool_err(
                    tool,
                    "INVALID_ARGUMENT",
                    f"member_ids 须为 ou_ 开头的 open_id，非法项: {p}",
                )
        mids = ",".join(parts)
    size = max(1, min(int(page_size or 20), 100))
    argv = [
        "im",
        "+chat-search",
        "--as",
        "user",
        "--page-size",
        str(size),
    ]
    if q:
        argv.extend(["--query", q])
    if mids:
        argv.extend(["--member-ids", mids])
    tok = (page_token or "").strip()
    if tok:
        if len(tok) > 512 or any(c in tok for c in (" ", ";", "|", "`", "\n")):
            return _tool_err(tool, "INVALID_ARGUMENT", "page_token 格式不合法")
        argv.extend(["--page-token", tok])
    return _run_lark_cli(argv, tool=tool, identity="user")


def tool_feishu_im_send_text(
    text: str,
    chat_id: str = "",
    user_id: str = "",
) -> dict:
    """以 Bot 身份发送文本消息（需 chat_id 或 user_id 其一）。"""
    tool = "feishu_im_send_text"
    body = (text or "").strip()
    if not body:
        return _tool_err(tool, "INVALID_ARGUMENT", "text 不能为空")
    if len(body) > _MAX_TEXT_CHARS:
        return _tool_err(
            tool,
            "INVALID_ARGUMENT",
            f"text 超过 {_MAX_TEXT_CHARS} 字符限制",
        )
    cid = (chat_id or "").strip()
    uid = (user_id or "").strip()
    if bool(cid) == bool(uid):
        return _tool_err(
            tool,
            "INVALID_ARGUMENT",
            "请只提供 chat_id 或 user_id 其中之一",
        )
    if cid:
        err = _validate_chat_or_user(cid, field="chat_id")
        if err:
            return _tool_err(tool, "INVALID_ARGUMENT", err)
        target_flag, target_val = "--chat-id", cid
    else:
        err = _validate_chat_or_user(uid, field="user_id")
        if err:
            return _tool_err(tool, "INVALID_ARGUMENT", err)
        target_flag, target_val = "--user-id", uid

    argv = [
        "im",
        "+messages-send",
        "--as",
        "bot",
        target_flag,
        target_val,
        "--text",
        body,
    ]
    return _run_lark_cli(argv, tool=tool, identity="bot")


def _is_meta_im_search_query(query: str) -> bool:
    """True when query is not a real keyword (e.g. 聊天记录 / 最近3天要点)."""
    q = (query or "").strip()
    if not q:
        return True
    low = q.lower()
    if low in {"*", "all", "message", "messages", "chat", "history"}:
        return True
    # Strip time/quantity words then meta words; leftover must be a real topic token
    rest = re.sub(
        r"(\d+|最近|近|今天|今日|本周|本月|天|日|周|月|年|的|里|中|内|全部|所有|一下)",
        "",
        q,
    )
    for m in (
        "聊天记录",
        "聊天",
        "消息记录",
        "消息",
        "记录",
        "要点",
        "总结",
        "汇总",
        "讨论",
        "内容",
        "历史",
        "群聊",
    ):
        rest = rest.replace(m, "")
    rest = re.sub(r"[\W_]+", "", rest, flags=re.UNICODE)
    return len(rest) < 2


def _im_payload_message_count(data: Any) -> Optional[int]:
    """Best-effort count of messages in a list/search payload; None if unknown."""
    if not isinstance(data, dict):
        return None
    for key in ("messages", "items", "results", "list"):
        v = data.get(key)
        if isinstance(v, list):
            return len(v)
    result = data.get("result")
    if isinstance(result, list):
        return len(result)
    if isinstance(result, dict):
        return _im_payload_message_count(result)
    # Nested under data from _tool_ok wrapper shape {identity, result}
    inner = data.get("data")
    if isinstance(inner, dict):
        return _im_payload_message_count(inner)
    return None


def tool_feishu_im_chat_messages_list(
    chat_id: str,
    page_size: int = 50,
    page_token: str = "",
    start: str = "",
    end: str = "",
    order: str = "desc",
    as_user: bool = True,
) -> dict:
    """列出某会话时间窗内的消息（支持翻页）。

    **「最近 N 天聊天记录 / 总结要点」无明确关键词时必须用本工具**，不要用
    ``feishu_im_messages_search``。默认 ``as_user=true``（用户 OAuth，可见性
    与用户一致）；Bot 不在群内时也请用 user。若返回 ``has_more``/``page_token``
    且仍在时间窗内，须继续翻页，禁止只看第一页就宣称「没有」。
    """
    tool = "feishu_im_chat_messages_list"
    err = _validate_chat_or_user(chat_id, field="chat_id")
    if err:
        return _tool_err(tool, "INVALID_ARGUMENT", err)
    use_user = bool(as_user)
    if use_user:
        _uid, uerr = _require_user_for_read(tool)
        if uerr:
            return uerr
    size = max(1, min(int(page_size or 50), 50))
    ord_raw = (order or "desc").strip().lower() or "desc"
    if ord_raw not in ("asc", "desc"):
        return _tool_err(tool, "INVALID_ARGUMENT", "order 须为 asc 或 desc")
    tok_err = _validate_page_token(page_token)
    if tok_err:
        return _tool_err(tool, "INVALID_ARGUMENT", tok_err)
    start_b = _im_time_bound(start, end_of_day=False)
    end_b = _im_time_bound(end, end_of_day=True)
    ident = "user" if use_user else "bot"
    argv = [
        "im",
        "+chat-messages-list",
        "--as",
        ident,
        "--chat-id",
        chat_id.strip(),
        "--page-size",
        str(size),
        "--order",
        ord_raw,
    ]
    if start_b:
        argv.extend(["--start", start_b])
    if end_b:
        argv.extend(["--end", end_b])
    tok = (page_token or "").strip()
    if tok:
        argv.extend(["--page-token", tok])
    out = _run_lark_cli(argv, tool=tool, identity=ident)
    if isinstance(out.get("data"), dict):
        data = out["data"]
        data.setdefault("chat_id", chat_id.strip())
        data.setdefault("identity", ident)
        if start_b:
            data.setdefault("queried_start", start_b)
        if end_b:
            data.setdefault("queried_end", end_b)
        data.setdefault(
            "server_today",
            datetime.now(_SHANGHAI).date().isoformat(),
        )
        data.setdefault(
            "next_action_hint",
            "若 has_more/page_token 且仍在时间窗内，继续传 page_token 翻页后再汇总；"
            "禁止单页 0 条就断言整段时间为空。",
        )
        n = _im_payload_message_count(data)
        if n is not None:
            data["message_count"] = n
    return out


def tool_feishu_im_messages_search(
    query: str,
    chat_id: str = "",
    start: str = "",
    end: str = "",
    page_size: int = 20,
    page_token: str = "",
    page_all: bool = False,
    page_limit: int = 20,
) -> dict:
    """按关键词搜索聊天记录（需用户 OAuth；user-only）。

    仅当用户给了**明确主题词**（如 BQCA）时使用。``query`` 只放检索词，
    不要塞「总结一下」「聊天记录」「最近3天」。无关键词、只要近 N 天全量要点
    → 改用 ``feishu_im_chat_messages_list``。长区间优先 ``page_all=true``。
    """
    tool = "feishu_im_messages_search"
    q = (query or "").strip()
    if not q:
        return _tool_err(
            tool,
            "USE_MESSAGES_LIST",
            "无关键词时不要用 messages_search。"
            "请改用 feishu_im_chat_messages_list(chat_id, start, end, page_size=50, as_user=true) "
            "并按 page_token 翻页后汇总。",
        )
    if len(q) > 200:
        return _tool_err(tool, "INVALID_ARGUMENT", "query 超过 200 字符")
    if _is_meta_im_search_query(q):
        return _tool_err(
            tool,
            "USE_MESSAGES_LIST",
            f"query={q!r} 不是有效主题词（像「聊天记录/要点/最近N天」）。"
            "用户要的是时间段内全量聊天总结时，必须用 "
            "feishu_im_chat_messages_list(chat_id, start, end, as_user=true) 翻页拉取，"
            "禁止把这类词当作 search query。",
        )
    # Soft guard: agent often dumps the whole user ask into query
    junk = ("总结", "汇总", "帮我", "告诉我", "都有哪些", "需要做的")
    if len(q) > 40 and any(j in q for j in junk):
        return _tool_err(
            tool,
            "INVALID_ARGUMENT",
            "query 应只含检索关键词（如 BQCA），不要把「总结/帮我找」整句塞进 query",
        )
    _uid, err = _require_user_for_read(tool)
    if err:
        return err

    cid_raw = (chat_id or "").strip()
    chat_ids = ""
    if cid_raw:
        parts = [p.strip() for p in cid_raw.split(",") if p.strip()]
        if not parts:
            return _tool_err(tool, "INVALID_ARGUMENT", "chat_id 为空")
        if len(parts) > 20:
            return _tool_err(tool, "INVALID_ARGUMENT", "chat_id 最多 20 个")
        for p in parts:
            verr = _validate_chat_or_user(p, field="chat_id")
            if verr or not p.startswith("oc_"):
                return _tool_err(
                    tool,
                    "INVALID_ARGUMENT",
                    f"chat_id 须为 oc_ 开头的群/会话 ID，非法项: {p}",
                )
        chat_ids = ",".join(parts)

    size = max(1, min(int(page_size or 20), 50))
    tok_err = _validate_page_token(page_token)
    if tok_err:
        return _tool_err(tool, "INVALID_ARGUMENT", tok_err)
    limit = max(1, min(int(page_limit or 20), 40))
    start_b = _im_time_bound(start, end_of_day=False)
    end_b = _im_time_bound(end, end_of_day=True)

    argv = [
        "im",
        "+messages-search",
        "--as",
        "user",
        "--query",
        q,
        "--page-size",
        str(size),
    ]
    if chat_ids:
        argv.extend(["--chat-id", chat_ids])
    if start_b:
        argv.extend(["--start", start_b])
    if end_b:
        argv.extend(["--end", end_b])
    tok = (page_token or "").strip()
    if tok:
        argv.extend(["--page-token", tok])
    if page_all:
        argv.append("--page-all")
        argv.extend(["--page-limit", str(limit)])

    out = _run_lark_cli(argv, tool=tool, identity="user")
    if isinstance(out.get("data"), dict):
        data = out["data"]
        data.setdefault("query", q)
        if chat_ids:
            data.setdefault("chat_id", chat_ids)
        if start_b:
            data.setdefault("queried_start", start_b)
        if end_b:
            data.setdefault("queried_end", end_b)
        data.setdefault(
            "server_today",
            datetime.now(_SHANGHAI).date().isoformat(),
        )
        n = _im_payload_message_count(data)
        if n is not None:
            data["message_count"] = n
        if n == 0:
            data["empty_hint"] = (
                "关键词 0 命中 ≠ 群里无消息。若用户要的是「近 N 天聊天要点」而非某主题，"
                "请改用 feishu_im_chat_messages_list(chat_id, start, end, as_user=true) 翻页汇总。"
            )
            data["next_action"] = "feishu_im_chat_messages_list"
    return out


def _strip_html_highlight(text: str) -> str:
    return re.sub(r"</?h>", "", text or "").strip()


def _normalize_doc_search_items(raw: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Flatten Feishu docs/+search payload into agent-friendly ``items`` with urls.

    Accepts CLI shapes: ``{res_units:[…]}``, ``{results:[…]}``, or a bare list.
    Each item: title, url, doc_token, entity_type, summary (links from tool only).
    """
    meta: dict[str, Any] = {"total": 0, "has_more": False, "page_token": ""}
    units: list[Any] = []
    if isinstance(raw, list):
        units = raw
    elif isinstance(raw, dict):
        meta["total"] = raw.get("total") or 0
        meta["has_more"] = bool(raw.get("has_more"))
        meta["page_token"] = str(raw.get("page_token") or "").strip()
        for key in ("res_units", "results", "items", "docs"):
            cand = raw.get(key)
            if isinstance(cand, list):
                units = cand
                break
    items: list[dict[str, Any]] = []
    for unit in units:
        if not isinstance(unit, dict):
            continue
        result_meta = unit.get("result_meta")
        if not isinstance(result_meta, dict):
            result_meta = {}
        title = _strip_html_highlight(
            str(
                unit.get("title")
                or unit.get("title_highlighted")
                or result_meta.get("title")
                or ""
            )
        )
        url = str(
            unit.get("url")
            or result_meta.get("url")
            or unit.get("docs_url")
            or ""
        ).strip()
        token = str(
            unit.get("token")
            or unit.get("doc_token")
            or result_meta.get("token")
            or ""
        ).strip()
        entity = str(
            unit.get("entity_type")
            or result_meta.get("doc_types")
            or unit.get("type")
            or ""
        ).strip()
        summary = _strip_html_highlight(
            str(
                unit.get("summary")
                or unit.get("summary_highlighted")
                or result_meta.get("summary")
                or ""
            )
        )
        if not (title or url or token):
            continue
        items.append(
            {
                "title": title or "(无标题)",
                "url": url,
                "doc_token": token,
                "entity_type": entity,
                "summary": summary[:500] if summary else "",
                "url_from_tool": bool(url),
            }
        )
    if not meta["total"]:
        meta["total"] = len(items)
    return items, meta


def tool_feishu_doc_search(
    query: str = "",
    page_size: int = 15,
    page_token: str = "",
    filter_json: str = "",
) -> dict:
    """按关键词搜索云文档/知识库/表格（需用户 OAuth；仅 user）。

    query 须走 ``--query``（不要当位置参数）。留空则接近「最近浏览」。
    标题优先可用 ``intitle:日报`` 等语法。

    成功时 ``data.items`` 为扁平列表（title/url/doc_token）；**链接必须来自 items[].url**，
    禁止模型臆造飞书 URL。0 命中时 count=0，应如实告知用户。
    """
    tool = "feishu_doc_search"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    q = (query or "").strip()
    if len(q) > 200:
        return _tool_err(tool, "INVALID_ARGUMENT", "query 超过 200 字符")
    size = max(1, min(int(page_size or 15), 20))
    filt = (filter_json or "").strip()
    if filt:
        try:
            parsed = json.loads(filt)
        except json.JSONDecodeError:
            return _tool_err(tool, "INVALID_ARGUMENT", "filter_json 须为合法 JSON 对象")
        if not isinstance(parsed, dict):
            return _tool_err(tool, "INVALID_ARGUMENT", "filter_json 须为 JSON 对象")
    argv = [
        "docs",
        "+search",
        "--as",
        "user",
        "--page-size",
        str(size),
    ]
    # Always pass --query explicitly (even empty) so CLI never treats keyword as positional.
    argv.extend(["--query", q])
    tok = (page_token or "").strip()
    if tok:
        if len(tok) > 512 or any(c in tok for c in (" ", ";", "|", "`", "\n")):
            return _tool_err(tool, "INVALID_ARGUMENT", "page_token 格式不合法")
        argv.extend(["--page-token", tok])
    if filt:
        argv.extend(["--filter", filt])
    env = _run_lark_cli(argv, tool=tool, identity="user")
    if not isinstance(env, dict) or not env.get("ok"):
        return env
    data = env.get("data") if isinstance(env.get("data"), dict) else {}
    raw_result = data.get("result")
    items, page_meta = _normalize_doc_search_items(raw_result)
    # Also accept already-flat payloads
    if not items and isinstance(data.get("items"), list):
        items, page_meta = _normalize_doc_search_items({"items": data["items"], **page_meta})
    data_out = {
        **data,
        "query": q,
        "items": items,
        "count": len(items),
        "total": page_meta.get("total", len(items)),
        "has_more": page_meta.get("has_more", False),
        "page_token": page_meta.get("page_token") or "",
        "links_from_tool_only": True,
        "empty": len(items) == 0,
        "hint": (
            "向用户列出 title + url（仅用 items[].url）；0 命中则如实说未找到，禁止编造链接。"
            if items
            else "无命中：如实告知用户飞书云文档未找到，禁止编造链接或改走多维表格。"
        ),
    }
    meta = env.get("meta") if isinstance(env.get("meta"), dict) else {}
    return _tool_ok(tool, data_out, meta=meta)


def tool_feishu_doc_fetch(doc: str, doc_format: str = "markdown") -> dict:
    """读取云文档（需用户 OAuth，读用户有权访问的文档）。"""
    tool = "feishu_doc_fetch"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    verr = _validate_token_like(doc, field="doc")
    if verr:
        return _tool_err(tool, "INVALID_ARGUMENT", verr)
    fmt = (doc_format or "markdown").strip().lower()
    if fmt not in {"markdown", "xml", "im-markdown"}:
        return _tool_err(tool, "INVALID_ARGUMENT", "doc_format 仅支持 markdown/xml/im-markdown")
    argv = [
        "docs",
        "+fetch",
        "--as",
        "user",
        "--doc",
        doc.strip(),
        "--doc-format",
        fmt,
    ]
    return _run_lark_cli(argv, tool=tool, identity="user")


def tool_feishu_doc_create_markdown(content: str, title: str = "") -> dict:
    """用 Markdown 创建云文档（有用户 OAuth 则用 user，否则 bot）。"""
    tool = "feishu_doc_create_markdown"
    body = (content or "").strip()
    if not body:
        return _tool_err(tool, "INVALID_ARGUMENT", "content 不能为空")
    if len(body) > _MAX_DOC_CHARS:
        return _tool_err(
            tool,
            "INVALID_ARGUMENT",
            f"content 超过 {_MAX_DOC_CHARS} 字符限制",
        )
    # Prefer wrapping title if provided and content has no title tag
    payload = body
    t = (title or "").strip()
    if t and "<title>" not in body.lower():
        payload = f"<title>{t}</title>\n{body}"
    ident = _write_identity()
    argv = [
        "docs",
        "+create",
        "--as",
        ident,
        "--doc-format",
        "markdown",
        "--content",
        payload,
    ]
    return _run_lark_cli(argv, tool=tool, identity=ident)


def tool_feishu_sheet_read(spreadsheet: str, range_a1: str = "") -> dict:
    """读取电子表格 CSV 范围（需用户 OAuth）。"""
    tool = "feishu_sheet_read"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    verr = _validate_token_like(spreadsheet, field="spreadsheet")
    if verr:
        return _tool_err(tool, "INVALID_ARGUMENT", verr)
    argv = [
        "sheets",
        "+csv-get",
        "--as",
        "user",
        "--spreadsheet",
        spreadsheet.strip(),
    ]
    rng = (range_a1 or "").strip()
    if rng:
        if not re.match(r"^[A-Za-z0-9_:!]+$", rng):
            return _tool_err(tool, "INVALID_ARGUMENT", "range_a1 格式不合法")
        argv.extend(["--range", rng])
    return _run_lark_cli(argv, tool=tool, identity="user")


def tool_feishu_sheet_write_csv(
    spreadsheet: str,
    csv_text: str,
    start_cell: str = "A1",
) -> dict:
    """向电子表格写入 CSV 文本（有用户 OAuth 则用 user，否则 bot）。"""
    tool = "feishu_sheet_write_csv"
    err = _validate_token_like(spreadsheet, field="spreadsheet")
    if err:
        return _tool_err(tool, "INVALID_ARGUMENT", err)
    body = (csv_text or "").strip("\n")
    if not body:
        return _tool_err(tool, "INVALID_ARGUMENT", "csv_text 不能为空")
    if len(body) > _MAX_DOC_CHARS:
        return _tool_err(tool, "INVALID_ARGUMENT", "csv_text 过大")
    cell = (start_cell or "A1").strip() or "A1"
    if not re.match(r"^[A-Za-z]+\d+$", cell):
        return _tool_err(tool, "INVALID_ARGUMENT", "start_cell 须如 A1")
    ident = _write_identity()
    argv = [
        "sheets",
        "+csv-put",
        "--as",
        ident,
        "--spreadsheet",
        spreadsheet.strip(),
        "--start-cell",
        cell,
        "--values",
        body,
    ]
    return _run_lark_cli(argv, tool=tool, identity=ident)


def _sanitize_bitable_create_fields(parsed: list[Any]) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Strip OpenAPI-only keys (e.g. ``property``) that ``+table-create`` rejects."""
    allowed = {"name", "type", "options", "description", "style", "formatter"}
    out: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            return [], "fields_json 每项须为对象"
        name = item.get("name")
        typ = item.get("type")
        if not name or not typ:
            return [], "每个字段须含 type 与 name（如 text/number）"
        clean: dict[str, Any] = {"name": str(name).strip(), "type": str(typ).strip()}
        if not clean["name"] or not clean["type"]:
            return [], "字段 name/type 不能为空"
        for key in allowed:
            if key in ("name", "type"):
                continue
            if key in item and item[key] is not None:
                clean[key] = item[key]
        # Common mistake: pass field_list dump with property/tableId
        out.append(clean)
    return out, None


def _coerce_create_records_payload(raw: Any) -> tuple[list[dict[str, Any]], Optional[str]]:
    """Accept common agent shapes → list of field maps for create_records."""
    payload = raw

    if isinstance(payload, list):
        if not payload:
            return [], "create_records 为空"
        rows: list[dict[str, Any]] = []
        for x in payload:
            if isinstance(x, dict):
                if set(x.keys()) <= {"ok", "tool", "error", "meta"}:
                    continue
                rows.append(x)
            elif isinstance(x, str) and x.strip():
                rows.append({"名称": x.strip()})
        if not rows:
            return [], "数组中没有可用的记录对象"
        if len(rows) > 200:
            return [], "单次最多 200 条记录"
        return rows, None

    if not isinstance(payload, dict):
        return [], 'records_json 须为 {"create_records":[...]} 或字段对象数组'

    for key in ("create_records", "records", "items", "rows"):
        cand = payload.get(key)
        if isinstance(cand, list):
            return _coerce_create_records_payload(cand)

    for wrap in ("data", "result", "output", "response"):
        nested = payload.get(wrap)
        if isinstance(nested, (dict, list)):
            rows, err = _coerce_create_records_payload(nested)
            if not err:
                return rows, None

    fields = payload.get("fields")
    rows = payload.get("rows")
    if isinstance(fields, list) and isinstance(rows, list) and fields and rows:
        if len(rows) > 200:
            return [], "单次最多 200 条记录"
        create_records = []
        for row in rows:
            if not isinstance(row, list) or len(row) != len(fields):
                return [], "rows 每行长度须与 fields 一致"
            create_records.append({str(fields[i]): row[i] for i in range(len(fields))})
        return create_records, None

    meta_only = {"ok", "tool", "error", "meta", "message", "code", "hint", "summary"}
    if payload and not (set(payload.keys()) <= meta_only):
        # Avoid treating whole TSE query envelopes as one row
        if any(k in payload for k in ("reports", "items", "customers", "results")):
            for k in ("reports", "items", "customers", "results"):
                if isinstance(payload.get(k), list):
                    return _coerce_create_records_payload(payload[k])
            return [], (
                "看起来像 TSE 查询原始结果，不是 bitable create_records。"
                "请先整理成 "
                '{"create_records":[{"客户简称":"…","优先级":"P1"},…]}'
            )
        return [payload], None
    return [], 'records_json 须为 {"create_records":[...]} 或字段对象数组'


def _normalize_bitable_batch_json(raw: str, *, tool: str) -> tuple[Optional[str], Optional[dict]]:
    """Normalize to create_records / update_records shapes expected by current lark-cli."""
    text = (raw or "").strip()
    if not text:
        return None, _tool_err(tool, "INVALID_ARGUMENT", "records_json 不能为空")
    if len(text) > _MAX_DOC_CHARS:
        return None, _tool_err(tool, "INVALID_ARGUMENT", "records_json 过大")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None, _tool_err(tool, "INVALID_ARGUMENT", "records_json 须为合法 JSON")

    if isinstance(payload, dict) and "update_records" in payload and "create_records" not in payload:
        mapping = payload.get("update_records")
        if not isinstance(mapping, dict) or not mapping:
            return None, _tool_err(tool, "INVALID_ARGUMENT", "update_records 须为非空对象")
        if len(mapping) > 200:
            return None, _tool_err(tool, "INVALID_ARGUMENT", "单次最多 200 条记录")
        return json.dumps(payload, ensure_ascii=False), None

    rows, err = _coerce_create_records_payload(payload)
    if err:
        return None, _tool_err(
            tool,
            "INVALID_ARGUMENT",
            f"{err}。示例："
            '{"create_records":[{"客户简称":"Acme","优先级":"P1"}]}',
        )
    return json.dumps({"create_records": rows}, ensure_ascii=False), None


def _dig_first(obj: Any, keys: tuple[str, ...]) -> Any:
    """Breadth-ish first match for key names in nested dict/list structures."""
    if isinstance(obj, dict):
        for k in keys:
            if k in obj and obj[k] not in (None, ""):
                return obj[k]
        for v in obj.values():
            found = _dig_first(v, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _dig_first(item, keys)
            if found not in (None, ""):
                return found
    return None


def _extract_bitable_create_coords(payload: Any) -> dict[str, str]:
    """Best-effort extract base_token / table_id / url from lark-cli create results."""
    base_token = _dig_first(
        payload,
        ("base_token", "app_token", "baseToken", "appToken"),
    )
    table_id = _dig_first(
        payload,
        ("table_id", "default_table_id", "tableId", "defaultTableId"),
    )
    url = _dig_first(payload, ("url", "link", "base_url", "share_url", "shareUrl"))
    out: dict[str, str] = {}
    if isinstance(base_token, str) and base_token.strip():
        out["base_token"] = base_token.strip()
    if isinstance(table_id, str) and table_id.strip():
        out["table_id"] = table_id.strip()
    if isinstance(url, str) and url.strip():
        out["url"] = url.strip()
    return out


def _feishu_base_web_origin() -> str:
    """Tenant web origin for Base links (e.g. https://your-tenant.feishu.cn)."""
    raw = (
        os.getenv("FEISHU_BASE_WEB_ORIGIN")
        or os.getenv("FEISHU_WEB_ORIGIN")
        or ""
    ).strip().rstrip("/")
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return "https://feishu.cn"


def _canonical_bitable_url(
    base_token: str,
    *,
    table_id: str = "",
    url_hint: str = "",
) -> str:
    """Prefer CLI-provided URL; otherwise build ``{origin}/base/{token}?table=…``."""
    hint = (url_hint or "").strip()
    bt = (base_token or "").strip()
    tid = (table_id or "").strip()
    if hint.startswith("http://") or hint.startswith("https://"):
        # Ensure table query when we know it and hint lacks it
        if tid and "table=" not in hint and "/base/" in hint:
            sep = "&" if "?" in hint else "?"
            return f"{hint}{sep}table={tid}"
        return hint
    if not bt:
        return ""
    origin = _feishu_base_web_origin()
    # If hint is a host-less path
    if hint.startswith("/base/"):
        url = f"{origin}{hint}"
    else:
        url = f"{origin}/base/{bt}"
    if tid and "table=" not in url:
        url = f"{url}?table={tid}"
    return url


def _verify_base_exists(base_token: str, *, tool: str) -> tuple[bool, dict[str, Any]]:
    """``+base-get`` to ensure token is a real Base (not wiki/hallucinated)."""
    bt = (base_token or "").strip()
    if not bt:
        return False, {"error": "empty base_token"}
    got = _run_lark_cli(
        [
            "base",
            "+base-get",
            "--as",
            "user",
            "--base-token",
            bt,
        ],
        tool=tool,
        identity="user",
    )
    if got.get("ok"):
        payload = got.get("data") if isinstance(got.get("data"), dict) else got.get("data")
        coords = _extract_bitable_create_coords(payload)
        return True, {"base_get": payload, "coords": coords}
    return False, {
        "error": got.get("error"),
        "data": got.get("data"),
    }


def _extract_tables_from_list_payload(payload: Any) -> list[dict[str, str]]:
    """Normalize ``+table-list`` payload into ``[{table_id, name}, ...]``."""
    root = payload
    if isinstance(payload, dict):
        for key in ("tables", "items", "result", "data"):
            nested = payload.get(key)
            if isinstance(nested, list):
                root = nested
                break
            if isinstance(nested, dict):
                for k2 in ("tables", "items"):
                    if isinstance(nested.get(k2), list):
                        root = nested[k2]
                        break
    if not isinstance(root, list):
        return []
    out: list[dict[str, str]] = []
    for item in root:
        if not isinstance(item, dict):
            continue
        tid = _dig_first(item, ("table_id", "tableId", "id"))
        name = _dig_first(item, ("name", "table_name", "tableName"))
        entry: dict[str, str] = {}
        if isinstance(tid, str) and tid.strip():
            entry["table_id"] = tid.strip()
        if isinstance(name, str) and name.strip():
            entry["name"] = name.strip()
        if entry.get("table_id"):
            out.append(entry)
    return out


def _resolve_table_id_via_list(
    base_token: str,
    *,
    preferred_name: str = "",
    tool: str,
) -> tuple[str, list[dict[str, str]], dict[str, Any]]:
    """Call ``+table-list`` to recover table_id when create/parse omitted it."""
    bt = (base_token or "").strip()
    if not bt:
        return "", [], {}
    listed = _run_lark_cli(
        [
            "base",
            "+table-list",
            "--as",
            "user",
            "--base-token",
            bt,
            "--limit",
            "100",
        ],
        tool=tool,
        identity="user",
    )
    meta = listed.get("meta") if isinstance(listed.get("meta"), dict) else {}
    if not listed.get("ok"):
        return "", [], {"table_list_error": listed.get("error"), "meta": meta}
    payload = listed.get("data") if isinstance(listed.get("data"), dict) else listed.get("data")
    tables = _extract_tables_from_list_payload(payload)
    if not tables:
        # Sometimes CLI nests under data.result
        tables = _extract_tables_from_list_payload(listed)
    preferred = (preferred_name or "").strip()
    if preferred:
        for t in tables:
            if t.get("name") == preferred:
                return t["table_id"], tables, {"resolved_via": "table_list_name"}
    if tables:
        return tables[0]["table_id"], tables, {"resolved_via": "table_list_first"}
    return "", tables, {"resolved_via": "table_list_empty"}


def tool_feishu_bitable_create(
    name: str,
    table_name: str = "数据表",
    fields_json: str = "",
) -> dict:
    """新建多维表格 Base（需用户 OAuth）。强烈建议带 table_name + fields_json。

    实现刻意避免 ``+base-create --fields``（会替换默认表，触发 ``base:table:delete``）。
    流程：先建空 Base → 再用 ``+table-create`` 建目标表与字段。

    fields_json 为字段数组，例如：
    ``[{"type":"text","name":"指标"},{"type":"text","name":"数值"}]``
    """
    tool = "feishu_bitable_create"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    title = (name or "").strip()
    if not title:
        return _tool_err(tool, "INVALID_ARGUMENT", "name（多维表格名称）不能为空")
    if len(title) > 100:
        return _tool_err(tool, "INVALID_ARGUMENT", "name 超过 100 字符")
    tname = (table_name or "数据表").strip() or "数据表"
    if len(tname) > 100:
        return _tool_err(tool, "INVALID_ARGUMENT", "table_name 超过 100 字符")

    fields: list[Any] = []
    fj = (fields_json or "").strip()
    if fj:
        try:
            parsed = json.loads(fj)
        except json.JSONDecodeError:
            return _tool_err(tool, "INVALID_ARGUMENT", "fields_json 须为合法 JSON 数组")
        if not isinstance(parsed, list) or not parsed:
            return _tool_err(tool, "INVALID_ARGUMENT", "fields_json 须为非空数组")
        if len(parsed) > 50:
            return _tool_err(tool, "INVALID_ARGUMENT", "fields 最多 50 个")
        fields, ferr = _sanitize_bitable_create_fields(parsed)
        if ferr:
            return _tool_err(
                tool,
                "INVALID_ARGUMENT",
                f"{ferr}。建表 fields 只需 name/type/options，"
                "不要传 field_list 的 property（会报 Unrecognized key 'property'）",
            )

    # 1) Create Base with platform default table — no --fields / --table-name
    #    (those paths replace the initial table and require base:table:delete).
    created = _run_lark_cli(
        [
            "base",
            "+base-create",
            "--as",
            "user",
            "--name",
            title,
            "--time-zone",
            "Asia/Shanghai",
        ],
        tool=tool,
        identity="user",
    )
    if not created.get("ok"):
        return created

    create_data = created.get("data") if isinstance(created.get("data"), dict) else {}
    coords = _extract_bitable_create_coords(create_data)
    base_token = coords.get("base_token") or ""
    default_table_id = coords.get("table_id") or ""
    base_url = coords.get("url") or ""
    if not base_token:
        return _tool_err(
            tool,
            "CREATE_PARSE_FAILED",
            "已创建 Base，但未解析到 base_token；请根据 cli 原始结果手工取 token。",
            data={"create": create_data},
            meta=created.get("meta") if isinstance(created.get("meta"), dict) else {},
        )

    working_table_id = default_table_id
    table_create_data: Any = None

    if fields:
        # 2) Add a dedicated table with the requested schema (create-only scopes).
        table_res = _run_lark_cli(
            [
                "base",
                "+table-create",
                "--as",
                "user",
                "--base-token",
                base_token,
                "--name",
                tname,
                "--fields",
                json.dumps(fields, ensure_ascii=False),
            ],
            tool=tool,
            identity="user",
        )
        if not table_res.get("ok"):
            # Base already exists — surface both so agent can continue or tell user.
            err_data = table_res.get("data") if isinstance(table_res.get("data"), dict) else {}
            err_data = {
                **err_data,
                "base_token": base_token,
                "default_table_id": default_table_id,
                "url": base_url,
                "partial": "base_created_table_failed",
            }
            table_res["data"] = err_data
            return table_res
        table_create_data = (
            table_res.get("data") if isinstance(table_res.get("data"), dict) else {}
        )
        tcoords = _extract_bitable_create_coords(table_create_data)
        if tcoords.get("table_id"):
            working_table_id = tcoords["table_id"]
    elif tname and default_table_id:
        # No custom fields: just rename the default table when requested.
        renamed = _run_lark_cli(
            [
                "base",
                "+table-update",
                "--as",
                "user",
                "--base-token",
                base_token,
                "--table-id",
                default_table_id,
                "--name",
                tname,
            ],
            tool=tool,
            identity="user",
        )
        if not renamed.get("ok"):
            # Non-fatal for rename; still return the created base.
            table_create_data = {
                "rename_warning": renamed.get("error") or renamed.get("data")
            }
        else:
            table_create_data = renamed.get("data")

    list_meta: dict[str, Any] = {}
    tables_snapshot: list[dict[str, str]] = []
    if not working_table_id:
        recovered, tables_snapshot, list_meta = _resolve_table_id_via_list(
            base_token, preferred_name=tname, tool=tool
        )
        if recovered:
            working_table_id = recovered

    if not working_table_id:
        return _tool_err(
            tool,
            "CREATE_MISSING_TABLE_ID",
            "Base 已创建，但未能解析 table_id。请立刻调用 "
            "feishu_bitable_table_list(base_token=…) 取表，禁止让用户去浏览器找 table=。",
            data={
                "base_token": base_token,
                "default_table_id": default_table_id,
                "table_name": tname,
                "url": _canonical_bitable_url(base_token, url_hint=base_url),
                "tables": tables_snapshot,
                "create": create_data.get("result")
                if isinstance(create_data, dict)
                else create_data,
                "table": table_create_data,
                "list_meta": list_meta,
            },
            meta={"avoided_scope": "base:table:delete", **list_meta},
            retryable=True,
        )

    # Verify Base is openable; reject hallucinated / wrong-tenant tokens early.
    ok_base, verify_meta = _verify_base_exists(base_token, tool=tool)
    if not ok_base:
        return _tool_err(
            tool,
            "CREATE_UNVERIFIED",
            "CLI 声称已创建，但 base-get 无法打开该 Base（token 可能错误或无权限）。"
            "禁止向用户编造 /base/ 链接；请重试 create 或检查 OAuth。",
            data={
                "base_token": base_token,
                "table_id": working_table_id,
                "create": create_data.get("result")
                if isinstance(create_data, dict)
                else create_data,
                "verify": verify_meta,
            },
            meta={"avoided_scope": "base:table:delete"},
            retryable=True,
        )
    vcoords = verify_meta.get("coords") if isinstance(verify_meta.get("coords"), dict) else {}
    if vcoords.get("url"):
        base_url = vcoords["url"]
    final_url = _canonical_bitable_url(
        base_token, table_id=working_table_id, url_hint=base_url
    )
    if not final_url:
        return _tool_err(
            tool,
            "CREATE_MISSING_URL",
            "Base 已创建且可验证，但未能生成打开链接。请设置 FEISHU_BASE_WEB_ORIGIN"
            "（如 https://your-tenant.feishu.cn）后重试，禁止臆造域名。",
            data={
                "base_token": base_token,
                "table_id": working_table_id,
                "verify": verify_meta,
            },
            retryable=True,
        )

    return _tool_ok(
        tool,
        {
            "base_token": base_token,
            "table_id": working_table_id,
            "default_table_id": default_table_id,
            "table_name": tname,
            "url": final_url,
            "fields": fields,
            "tables": tables_snapshot,
            "create": create_data.get("result") if isinstance(create_data, dict) else create_data,
            "table": table_create_data,
            "url_verified": True,
            "next_action": "feishu_bitable_record_batch_create",
            "note": (
                "已用「空 Base + table-create」路径创建，不申请 base:table:delete。"
                "打开链接请只用返回的 url 字段（已 base-get 校验），禁止拼接臆造域名。"
                "下一步必须用返回的 base_token + table_id 调用 "
                "feishu_bitable_record_batch_create（或先 field_list）；"
                "禁止只交回调度员、禁止让用户找 table=。"
                if fields
                else (
                    "已创建空 Base（默认表已按需重命名）。"
                    "打开链接请只用返回的 url 字段（已 base-get 校验）。"
                    "下一步必须用返回的 base_token + table_id 写入记录；"
                    "禁止只交回调度员、禁止让用户找 table=。"
                )
            ),
        },
        meta={"avoided_scope": "base:table:delete", **list_meta, "url_verified": True},
    )


def tool_feishu_bitable_field_list(
    base_token: str,
    table_id: str,
) -> dict:
    """列出多维表格某数据表的字段（需用户 OAuth；写记录前先调用）。"""
    tool = "feishu_bitable_field_list"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    bt = (base_token or "").strip()
    tid = (table_id or "").strip()
    for field, val in (("base_token", bt), ("table_id", tid)):
        verr = _validate_token_like(val, field=field)
        if verr:
            return _tool_err(tool, "INVALID_ARGUMENT", verr)
    argv = [
        "base",
        "+field-list",
        "--as",
        "user",
        "--base-token",
        bt,
        "--table-id",
        tid,
        "--limit",
        "100",
    ]
    return _run_lark_cli(argv, tool=tool, identity="user")


def tool_feishu_bitable_table_list(base_token: str) -> dict:
    """列出 Base 下全部数据表（需用户 OAuth）。丢失 table_id 时的自愈入口。

    禁止让用户去浏览器复制 ``table=tbl…``；优先用本工具取 id。
    """
    tool = "feishu_bitable_table_list"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    bt = (base_token or "").strip()
    verr = _validate_token_like(bt, field="base_token")
    if verr:
        return _tool_err(tool, "INVALID_ARGUMENT", verr)
    listed = _run_lark_cli(
        [
            "base",
            "+table-list",
            "--as",
            "user",
            "--base-token",
            bt,
            "--limit",
            "100",
        ],
        tool=tool,
        identity="user",
    )
    if not listed.get("ok"):
        return listed
    payload = listed.get("data") if isinstance(listed.get("data"), dict) else listed.get("data")
    tables = _extract_tables_from_list_payload(payload)
    if not tables:
        tables = _extract_tables_from_list_payload(listed)
    preferred = tables[0]["table_id"] if tables else ""
    return _tool_ok(
        tool,
        {
            "base_token": bt,
            "tables": tables,
            "table_id": preferred or None,
            "count": len(tables),
            "hint": (
                "写记录请用返回的 table_id（多表时按 name 选择）；"
                "禁止臆造 ID，禁止让用户去浏览器找 table=。"
            ),
            "next_action": "feishu_bitable_record_batch_create"
            if preferred
            else "confirm_which_table",
        },
        meta=listed.get("meta") if isinstance(listed.get("meta"), dict) else {},
    )


def tool_feishu_bitable_record_batch_create(
    base_token: str,
    table_id: str,
    records_json: str,
) -> dict:
    """批量写入多维表格记录（需用户 OAuth）。

    records_json 推荐：``{"create_records":[{"字段名":"值"}, ...]}``；
    也接受对象数组，或 legacy ``{"fields":[...],"rows":[[...]]}``。
    """
    tool = "feishu_bitable_record_batch_create"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    bt = (base_token or "").strip()
    tid = (table_id or "").strip()
    for field, val in (("base_token", bt), ("table_id", tid)):
        verr = _validate_token_like(val, field=field)
        if verr:
            return _tool_err(tool, "INVALID_ARGUMENT", verr)
    body, berr = _normalize_bitable_batch_json(records_json, tool=tool)
    if berr:
        return berr
    if body and "update_records" in body and "create_records" not in body:
        return _tool_err(
            tool,
            "INVALID_ARGUMENT",
            "批量创建请用 create_records；更新请用 feishu_bitable_record_batch_update",
        )
    argv = [
        "base",
        "+record-batch-create",
        "--as",
        "user",
        "--base-token",
        bt,
        "--table-id",
        tid,
        "--json",
        body or "",
    ]
    return _run_lark_cli(argv, tool=tool, identity="user")


def tool_feishu_bitable_record_batch_update(
    base_token: str,
    table_id: str,
    records_json: str,
) -> dict:
    """批量更新多维表格记录（需用户 OAuth）。

    records_json：``{"update_records":{"recXXX":{"字段":"值"}, ...}}``
    """
    tool = "feishu_bitable_record_batch_update"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    bt = (base_token or "").strip()
    tid = (table_id or "").strip()
    for field, val in (("base_token", bt), ("table_id", tid)):
        verr = _validate_token_like(val, field=field)
        if verr:
            return _tool_err(tool, "INVALID_ARGUMENT", verr)
    body, berr = _normalize_bitable_batch_json(records_json, tool=tool)
    if berr:
        return berr
    if not body or "update_records" not in body:
        return _tool_err(
            tool,
            "INVALID_ARGUMENT",
            'records_json 须为 {"update_records":{"rec_id":{...}}}',
        )
    argv = [
        "base",
        "+record-batch-update",
        "--as",
        "user",
        "--base-token",
        bt,
        "--table-id",
        tid,
        "--json",
        body,
    ]
    return _run_lark_cli(argv, tool=tool, identity="user")


def tool_feishu_bitable_record_upsert(
    base_token: str,
    table_id: str,
    fields_json: str,
    record_id: str = "",
) -> dict:
    """创建或更新单条多维表格记录（需用户 OAuth）。带 record_id 则更新。"""
    tool = "feishu_bitable_record_upsert"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    bt = (base_token or "").strip()
    tid = (table_id or "").strip()
    for field, val in (("base_token", bt), ("table_id", tid)):
        verr = _validate_token_like(val, field=field)
        if verr:
            return _tool_err(tool, "INVALID_ARGUMENT", verr)
    fj = (fields_json or "").strip()
    if not fj:
        return _tool_err(tool, "INVALID_ARGUMENT", "fields_json 不能为空")
    try:
        fields = json.loads(fj)
    except json.JSONDecodeError:
        return _tool_err(tool, "INVALID_ARGUMENT", "fields_json 须为合法 JSON 对象")
    if not isinstance(fields, dict) or not fields:
        return _tool_err(tool, "INVALID_ARGUMENT", "fields_json 须为非空字段对象")
    argv = [
        "base",
        "+record-upsert",
        "--as",
        "user",
        "--base-token",
        bt,
        "--table-id",
        tid,
        "--json",
        json.dumps(fields, ensure_ascii=False),
    ]
    rid = (record_id or "").strip()
    if rid:
        verr = _validate_token_like(rid, field="record_id")
        if verr:
            return _tool_err(tool, "INVALID_ARGUMENT", verr)
        argv.extend(["--record-id", rid])
    return _run_lark_cli(argv, tool=tool, identity="user")


def _cli_data_payload(result: dict[str, Any]) -> Any:
    """Unwrap _run_lark_cli success envelope to inner data blob."""
    if not isinstance(result, dict):
        return None
    data = result.get("data")
    if not isinstance(data, dict):
        return data
    for key in ("data", "result", "output"):
        inner = data.get(key)
        if isinstance(inner, (dict, list)):
            return inner
    return data


def _iter_records_from_list_payload(payload: Any) -> list[dict[str, Any]]:
    items: list[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("items", "records", "data", "list"):
            val = payload.get(key)
            if isinstance(val, list):
                items = val
                break
            if isinstance(val, dict):
                for key2 in ("items", "records", "list"):
                    if isinstance(val.get(key2), list):
                        items = val[key2]
                        break
            if items:
                break
    return [item for item in items if isinstance(item, dict)]


def _record_id_of(item: dict[str, Any]) -> str:
    for key in ("record_id", "id", "recordId"):
        val = item.get(key)
        if isinstance(val, str) and val.strip().startswith("rec"):
            return val.strip()
    return ""


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_cell_text(x) for x in value]
        return " ".join(p for p in parts if p).strip()
    if isinstance(value, dict):
        for key in ("text", "name", "value", "title"):
            if key in value:
                t = _cell_text(value.get(key))
                if t:
                    return t
        return ""
    return str(value).strip()


def _fields_map_of_record(item: dict[str, Any]) -> dict[str, Any]:
    fields = item.get("fields")
    if isinstance(fields, dict):
        return fields
    skip = {"record_id", "id", "recordId", "created_time", "last_modified_time"}
    return {k: v for k, v in item.items() if k not in skip}


def _pick_primary_text_field(fields: list[dict[str, Any]]) -> Optional[str]:
    preferred = ("客户简称", "客户名称", "客户名", "名称", "姓名", "标题", "Title", "Name")
    textish: list[str] = []
    for item in fields:
        name = str(
            item.get("field_name") or item.get("name") or item.get("title") or ""
        ).strip()
        if not name:
            continue
        ftype = str(item.get("type") or item.get("ui_type") or "").strip().lower()
        ui = str(item.get("ui_type") or "").strip().lower()
        if ftype in {"1", "text", "multiline"} or ui in {"text", "barcode", "phone", "url"}:
            textish.append(name)
        elif "text" in ftype or "text" in ui:
            textish.append(name)
    for pref in preferred:
        if pref in textish:
            return pref
    return textish[0] if textish else None


def _normalize_name_key(text: str) -> str:
    return "".join(str(text or "").strip().lower().split())


def _extract_open_ids_from_contact(payload: Any) -> list[dict[str, str]]:
    """Return [{open_id, name, email}, ...] from contact search payload."""
    users: list[Any] = []
    if isinstance(payload, list):
        users = payload
    elif isinstance(payload, dict):
        for key in ("users", "items", "data", "result"):
            val = payload.get(key)
            if isinstance(val, list):
                users = val
                break
            if isinstance(val, dict):
                for key2 in ("users", "items", "list"):
                    if isinstance(val.get(key2), list):
                        users = val[key2]
                        break
            if users:
                break
        if not users and ("open_id" in payload or "user_id" in payload):
            users = [payload]

    out: list[dict[str, str]] = []
    for u in users:
        if not isinstance(u, dict):
            continue
        nested = u.get("user") if isinstance(u.get("user"), dict) else {}
        oid = str(
            u.get("open_id")
            or u.get("user_id")
            or u.get("id")
            or nested.get("open_id")
            or nested.get("user_id")
            or nested.get("id")
            or ""
        ).strip()
        name = str(
            u.get("name")
            or u.get("display_name")
            or nested.get("name")
            or nested.get("display_name")
            or ""
        ).strip()
        email = str(
            u.get("email")
            or u.get("enterprise_email")
            or nested.get("email")
            or nested.get("enterprise_email")
            or ""
        ).strip()
        if oid.startswith("ou_"):
            out.append({"open_id": oid, "name": name, "email": email.lower()})
    return out


def _parse_fields_items(fields_json: str) -> tuple[list[dict[str, Any]], Optional[str]]:
    raw = (fields_json or "").strip()
    if not raw:
        return [], "fields_json 不能为空"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [], "fields_json 须为合法 JSON"
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
    out = [x for x in items if isinstance(x, dict)]
    if not out:
        return [], "未能从 fields_json 解析出字段列表"
    return out, None


def _field_type_code(item: dict[str, Any]) -> str:
    """Normalize field type from OpenAPI numeric codes or lark-cli string types.

    lark-cli ``+field-list`` often returns ``type: "link"`` / ``style.type: "link"``
    instead of legacy bitable codes 18/21.
    """
    candidates: list[Any] = [
        item.get("type"),
        item.get("field_type"),
        item.get("fieldType"),
    ]
    style = item.get("style") if isinstance(item.get("style"), dict) else {}
    candidates.append(style.get("type"))
    for raw in candidates:
        if raw is None:
            continue
        if isinstance(raw, float):
            raw = int(raw)
        s = str(raw).strip()
        if not s:
            continue
        if s.endswith(".0") and s[:-2].isdigit():
            s = s[:-2]
        return s
    return ""


def _field_id(item: dict[str, Any]) -> str:
    for key in ("field_id", "fieldId", "id"):
        val = item.get(key)
        if isinstance(val, str) and val.strip().startswith("fld"):
            return val.strip()
    return ""


def _field_name(item: dict[str, Any]) -> str:
    return str(
        item.get("field_name") or item.get("name") or item.get("title") or ""
    ).strip()


def _is_link_type_code(
    code: str,
    ui: str,
    name: str,
    item: Optional[dict[str, Any]] = None,
) -> bool:
    """Detect SingleLink(18) / DuplexLink(21) / CLI type ``link``.

    Official CellValue: ``[{"id":"<record_id>"}]`` (see lark-base-cell-value.md §2.7).
    """
    c = (code or "").strip().lower()
    if c in {"18", "21", "link"}:
        return True
    u = (ui or "").strip().lower()
    if u in {"singlelink", "duplexlink", "link"} or "link" in u:
        return True
    blob = f"{c} {u} {name}".lower()
    if any(
        k in blob
        for k in (
            "singlelink",
            "duplexlink",
            "单向关联",
            "双向关联",
            "关联字段",
        )
    ):
        return True
    # Common CRM column names that are almost always link fields
    if name.strip() in {"客户简称", "客户名称", "关联客户", "客户"}:
        if item is not None and _linked_table_id_from_field(item):
            return True
        # Still treat as link candidate so enrich hard-fails if tableId missing
        if c not in {"1", "text", "2", "number", "3", "select", "11", "user"}:
            return True
    if item is not None and _linked_table_id_from_field(item):
        return True
    return False


def _is_person_type_code(code: str, ui: str, name: str) -> bool:
    c = (code or "").strip().lower()
    if c in {"11"}:
        return True
    if c in {"1001", "1003"}:
        return False
    blob = f"{c} {ui}".lower()
    if any(k in blob for k in ("user", "person", "personnel")):
        return True
    return "参与人" in name or name in {"内部参与人"}


def _linked_table_id_from_field(item: dict[str, Any]) -> Optional[str]:
    prop = item.get("property") if isinstance(item.get("property"), dict) else {}
    for key in (
        "table_id",
        "tableId",
        "link_table_id",
        "linkTableId",
        "linked_table_id",
        "linkedTableId",
        "base_table_id",
        "baseTableId",
    ):
        val = prop.get(key)
        if isinstance(val, str) and val.strip().startswith("tbl"):
            return val.strip()
    # Dig any tbl* string nested in property
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


def tool_feishu_bitable_parse_url(url: str) -> dict:
    """从飞书多维表格链接解析 base_token / table_id / view_id（禁止臆造 ID）。

    优先 ``lark-cli base +url-resolve``；失败则从 URL 路径/query 正则提取。
    """
    tool = "feishu_bitable_parse_url"
    raw = (url or "").strip()
    if not raw:
        return _tool_err(tool, "INVALID_ARGUMENT", "url 不能为空")
    if not raw.startswith(("http://", "https://")):
        return _tool_err(tool, "INVALID_ARGUMENT", "url 须为 https://…/base/… 链接")

    # Local parse first (deterministic; avoids hallucinated tokens)
    base_token = ""
    table_id = ""
    view_id = ""
    m = re.search(r"/base/([A-Za-z0-9]+)", raw)
    if m:
        base_token = m.group(1)
    qm = re.search(r"[?&]table=(tbl[A-Za-z0-9]+)", raw)
    if qm:
        table_id = qm.group(1)
    vm = re.search(r"[?&]view=(vew[A-Za-z0-9]+)", raw)
    if vm:
        view_id = vm.group(1)

    cli_out: dict[str, Any] = {}
    _uid, err = _require_user_for_read(tool)
    if not err:
        argv = [
            "base",
            "+url-resolve",
            "--as",
            "user",
            "--url",
            raw,
        ]
        resolved = _run_lark_cli(argv, tool=tool, identity="user")
        if resolved.get("ok"):
            payload = _cli_data_payload(resolved)
            coords = _extract_bitable_create_coords(payload)
            if coords.get("base_token"):
                base_token = coords["base_token"]
            if coords.get("table_id"):
                table_id = coords["table_id"]
            dig_view = _dig_first(payload, ("view_id", "viewId", "default_view_id"))
            if isinstance(dig_view, str) and dig_view.strip().startswith("vew"):
                view_id = dig_view.strip()
            cli_out = {"cli_ok": True, "coords": coords}
        else:
            cli_out = {"cli_ok": False, "cli_error": resolved.get("error")}

    if not base_token:
        return _tool_err(
            tool,
            "PARSE_FAILED",
            "无法从 URL 解析 base_token；请确认链接形如 https://…/base/<token>?table=tbl…",
            data={"url": raw, **cli_out},
        )

    list_meta: dict[str, Any] = {}
    tables: list[dict[str, str]] = []
    if not table_id:
        recovered, tables, list_meta = _resolve_table_id_via_list(
            base_token, tool=tool
        )
        if recovered:
            table_id = recovered

    if not table_id:
        return _tool_err(
            tool,
            "MISSING_TABLE_ID",
            "链接只有 Base、没有 table_id，且 table-list 未能解析。"
            "请再调 feishu_bitable_table_list；禁止让用户去浏览器找 table=。",
            data={
                "url": raw,
                "base_token": base_token,
                "view_id": view_id or None,
                "tables": tables,
                **cli_out,
                **list_meta,
            },
            retryable=True,
        )

    return _tool_ok(
        tool,
        {
            "url": raw,
            "base_token": base_token,
            "table_id": table_id,
            "view_id": view_id or None,
            "tables": tables,
            "hint": (
                "后续所有 feishu_bitable_* 必须用这里的 base_token/table_id；"
                "禁止使用会话记忆里其它 Base 的旧 ID；"
                "禁止让用户去浏览器复制 table=。"
            ),
            "next_action": "feishu_bitable_field_list_or_record_batch_create",
            **cli_out,
            **list_meta,
        },
    )


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _extract_record_id_any(payload: Any) -> str:
    rid = str(_dig_first(payload, ("record_id", "recordId")) or "").strip()
    if rid.startswith("rec"):
        return rid
    # Avoid matching unrelated "id" fields that aren't record ids
    if isinstance(payload, dict):
        for key in ("record_id", "recordId", "id"):
            val = payload.get(key)
            if isinstance(val, str) and val.startswith("rec"):
                return val
        for v in payload.values():
            found = _extract_record_id_any(v)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _extract_record_id_any(item)
            if found:
                return found
    return ""


def tool_feishu_bitable_record_list(
    base_token: str,
    table_id: str,
    limit: int = 100,
    offset: int = 0,
    filter_json: str = "",
) -> dict:
    """列出多维表格记录（需用户 OAuth；关联字段解析前先查关联表）。"""
    tool = "feishu_bitable_record_list"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    bt = (base_token or "").strip()
    tid = (table_id or "").strip()
    for field, val in (("base_token", bt), ("table_id", tid)):
        verr = _validate_token_like(val, field=field)
        if verr:
            return _tool_err(tool, "INVALID_ARGUMENT", verr)
    lim = max(1, min(int(limit or 100), 200))
    off = max(0, int(offset or 0))
    argv = [
        "base",
        "+record-list",
        "--as",
        "user",
        "--base-token",
        bt,
        "--table-id",
        tid,
        "--limit",
        str(lim),
        "--offset",
        str(off),
    ]
    fj = (filter_json or "").strip()
    if fj:
        try:
            json.loads(fj)
        except json.JSONDecodeError:
            return _tool_err(tool, "INVALID_ARGUMENT", "filter_json 须为合法 JSON")
        argv.extend(["--filter-json", fj])
    return _run_lark_cli(argv, tool=tool, identity="user")


def _items_from_field_list_payload(payload: Any) -> list[dict[str, Any]]:
    items: list[Any] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("items", "fields", "data", "result", "list"):
            val = payload.get(key)
            if isinstance(val, list):
                items = val
                break
            if isinstance(val, dict):
                for key2 in ("items", "fields", "list"):
                    if isinstance(val.get(key2), list):
                        items = val[key2]
                        break
            if items:
                break
    return [x for x in items if isinstance(x, dict)]


def _refresh_table_fields(
    base_token: str,
    table_id: str,
    fields_json_fallback: str = "",
) -> tuple[list[dict[str, Any]], Optional[str], str]:
    """Always prefer live field_list so type/tableId are not lost in agent handoff.

    Returns (items, error_message, source) where source is "api"|"fallback".
    """
    fl = tool_feishu_bitable_field_list(base_token=base_token, table_id=table_id)
    if fl.get("ok"):
        items = _items_from_field_list_payload(_cli_data_payload(fl))
        if items:
            return items, None, "api"
        # ok but empty — keep trying fallback
    items, err = _parse_fields_items(fields_json_fallback)
    if err:
        # Prefer the live API error if present
        if not fl.get("ok"):
            api_err = fl.get("error") if isinstance(fl.get("error"), dict) else {}
            return [], str(api_err.get("message") or err), "api_error"
        return [], err, "fallback"
    return items, None, "fallback"


def _link_cell_value(record_id: str) -> list[dict[str, str]]:
    """lark-cli CellValue for link/DuplexLink: [{{"id":"rec…"}}]."""
    return [{"id": record_id}]


def _cell_has_link_value(val: Any) -> bool:
    if isinstance(val, list) and val:
        first = val[0]
        if isinstance(first, dict) and str(first.get("id") or "").startswith("rec"):
            return True
        if isinstance(first, str) and first.startswith("rec"):
            return True
    if isinstance(val, dict):
        ids = val.get("link_record_ids")
        if isinstance(ids, list) and ids:
            return True
    return False


def tool_feishu_bitable_enrich_tse_records(
    base_token: str,
    table_id: str,
    fields_json: str,
    records_json: str,
    enrichment_hints_json: str = "",
    create_missing_links: bool = True,
) -> dict:
    """把 TSE map 结果补全关联/人员字段，便于 batch_create。

    - **客户简称（单向/双向关联）**：在关联表按名称匹配 ``record_id``；找不到时可自动创建一行
    - **内部参与人（人员）**：用 ``sales_name`` / ``owner`` 邮箱 ``contact +search-user`` 解析 ``open_id``
    - 系统只读字段（创建人等）不会写入

    返回 ``records_json``（已 enrich）可直接交给 ``feishu_bitable_record_batch_create``。
    """
    tool = "feishu_bitable_enrich_tse_records"
    _uid, err = _require_user_for_read(tool)
    if err:
        return err
    bt = (base_token or "").strip()
    tid = (table_id or "").strip()
    for field, val in (("base_token", bt), ("table_id", tid)):
        verr = _validate_token_like(val, field=field)
        if verr:
            return _tool_err(tool, "INVALID_ARGUMENT", verr)

    create_missing_links = _coerce_bool(create_missing_links, True)

    # Do NOT trust agent-passed fields_json alone — handoffs often drop type/tableId.
    field_items, ferr, fields_source = _refresh_table_fields(bt, tid, fields_json)
    if ferr:
        return _tool_err(tool, "INVALID_ARGUMENT", ferr)

    rj = (records_json or "").strip()
    if not rj:
        return _tool_err(tool, "INVALID_ARGUMENT", "records_json 不能为空")
    try:
        rparsed = json.loads(rj)
    except json.JSONDecodeError:
        return _tool_err(tool, "INVALID_ARGUMENT", "records_json 须为合法 JSON")

    create_records, cerr = _coerce_create_records_payload(rparsed)
    if cerr:
        return _tool_err(
            tool,
            "INVALID_ARGUMENT",
            f"{cerr}。若是「新建空表 + 写入客户名单」，请改用 "
            "feishu_bitable_record_batch_create，不要把原始 TSE 查询结果塞进 write_tse。"
            ' 正确示例：{"create_records":[{"客户简称":"Acme","优先级":"P1"}]}',
        )

    hints: list[dict[str, Any]] = []
    hj = (enrichment_hints_json or "").strip()
    if hj:
        try:
            hparsed = json.loads(hj)
        except json.JSONDecodeError:
            return _tool_err(tool, "INVALID_ARGUMENT", "enrichment_hints_json 须为合法 JSON")
        if isinstance(hparsed, dict) and isinstance(hparsed.get("enrichment_hints"), list):
            hints = [x for x in hparsed["enrichment_hints"] if isinstance(x, dict)]
        elif isinstance(hparsed, list):
            hints = [x for x in hparsed if isinstance(x, dict)]

    while len(hints) < len(create_records):
        hints.append({})

    link_fields: list[dict[str, Any]] = []
    person_fields: list[dict[str, Any]] = []
    for item in field_items:
        name = _field_name(item)
        if not name:
            continue
        code = _field_type_code(item)
        ui = str(
            item.get("ui_type") or item.get("uiType") or ""
        ).strip().lower()
        if code in {"1001", "1002", "1003", "1004", "23"}:
            continue
        if _is_link_type_code(code, ui, name, item):
            link_fields.append(
                {
                    "name": name,
                    "field_id": _field_id(item),
                    "linked_table_id": _linked_table_id_from_field(item),
                    "type_code": code,
                    "ui_type": ui,
                    "raw": item,
                }
            )
        elif _is_person_type_code(code, ui, name):
            person_fields.append({"name": name, "raw": item})

    resolutions: dict[str, Any] = {
        "links": {},
        "persons": {},
        "created_link_records": [],
        "unresolved": [],
        "fields_source": fields_source,
        "detected_link_fields": [
            {
                "name": lf["name"],
                "field_id": lf.get("field_id"),
                "linked_table_id": lf.get("linked_table_id"),
                "type_code": lf.get("type_code"),
                "ui_type": lf.get("ui_type"),
            }
            for lf in link_fields
        ],
    }

    # Ensure each hint has customer_name (row-embedded __tse_* / 沟通对象 fallback)
    for i, hint in enumerate(hints):
        row = create_records[i] if i < len(create_records) else {}
        if not str(hint.get("customer_name") or "").strip():
            embedded = row.get("__tse_customer_name")
            if isinstance(embedded, str) and embedded.strip():
                hint["customer_name"] = embedded.strip()
            else:
                for key in ("沟通对象", "客户简称", "客户名称", "客户名"):
                    val = row.get(key)
                    if isinstance(val, str) and val.strip():
                        hint["customer_name"] = val.strip()
                        break
        if not str(hint.get("sales_name") or "").strip():
            emb = row.get("__tse_sales_name")
            if isinstance(emb, str) and emb.strip():
                hint["sales_name"] = emb.strip()
        if not str(hint.get("owner") or "").strip():
            emb = row.get("__tse_owner")
            if isinstance(emb, str) and emb.strip():
                hint["owner"] = emb.strip()

    for lf in link_fields:
        linked_tid = lf.get("linked_table_id")
        if not linked_tid:
            resolutions["unresolved"].append(
                {
                    "field": lf["name"],
                    "reason": "missing_linked_table_id",
                    "hint": "fields_json 里关联字段 property 需含 tableId/table_id；请重跑 field_list 后 enrich",
                }
            )
            continue

        fl_res = tool_feishu_bitable_field_list(base_token=bt, table_id=linked_tid)
        if not fl_res.get("ok"):
            return fl_res
        linked_fields_raw = _cli_data_payload(fl_res)
        linked_items: list[dict[str, Any]] = []
        if isinstance(linked_fields_raw, list):
            linked_items = [x for x in linked_fields_raw if isinstance(x, dict)]
        elif isinstance(linked_fields_raw, dict):
            for key in ("items", "fields"):
                if isinstance(linked_fields_raw.get(key), list):
                    linked_items = [
                        x for x in linked_fields_raw[key] if isinstance(x, dict)
                    ]
                    break
        primary = _pick_primary_text_field(linked_items) or "名称"
        primary_candidates: list[str] = []
        for cand in (
            primary,
            "客户简称",
            "客户名称",
            "客户名",
            "名称",
            "姓名",
            "公司名称",
            "Title",
            "Name",
        ):
            if cand and cand not in primary_candidates:
                primary_candidates.append(cand)

        def _lookup_name(catalog: dict[str, str], cname: str) -> str:
            key = _normalize_name_key(cname)
            if key in catalog:
                return catalog[key]
            for k, rid in catalog.items():
                if key and k and (key in k or k in key):
                    return rid
            return ""

        name_to_rec: dict[str, str] = {}
        offset = 0
        while offset < 1000:
            list_res = tool_feishu_bitable_record_list(
                base_token=bt,
                table_id=linked_tid,
                limit=200,
                offset=offset,
            )
            if not list_res.get("ok"):
                return list_res
            rows = _iter_records_from_list_payload(_cli_data_payload(list_res))
            if not rows:
                break
            for row in rows:
                rid = _record_id_of(row)
                if not rid:
                    rid = str(
                        _dig_first(row, ("record_id", "id", "recordId")) or ""
                    ).strip()
                if not rid.startswith("rec"):
                    continue
                fmap = _fields_map_of_record(row)
                label = _cell_text(fmap.get(primary))
                if not label:
                    for v in fmap.values():
                        label = _cell_text(v)
                        if label:
                            break
                key = _normalize_name_key(label)
                if key and key not in name_to_rec:
                    name_to_rec[key] = rid
            if len(rows) < 200:
                break
            offset += 200

        def _search_linked(cname: str) -> Optional[str]:
            q = (cname or "").strip()
            if not q:
                return None
            for search_field in primary_candidates[:4]:
                argv = [
                    "base",
                    "+record-search",
                    "--as",
                    "user",
                    "--base-token",
                    bt,
                    "--table-id",
                    linked_tid,
                    "--keyword",
                    q[:50],
                    "--search-field",
                    search_field,
                    "--limit",
                    "10",
                ]
                search_res = _run_lark_cli(argv, tool=tool, identity="user")
                if not search_res.get("ok"):
                    continue
                for row in _iter_records_from_list_payload(_cli_data_payload(search_res)):
                    rid = _record_id_of(row) or str(
                        _dig_first(row, ("record_id", "id", "recordId")) or ""
                    ).strip()
                    if not rid.startswith("rec"):
                        continue
                    fmap = _fields_map_of_record(row)
                    label = (
                        _cell_text(fmap.get(search_field))
                        or _cell_text(fmap.get(primary))
                        or _cell_text(next(iter(fmap.values()), None))
                    )
                    if _normalize_name_key(label) == _normalize_name_key(q):
                        return rid
                    if q in (label or "") or (label or "") in q:
                        return rid
                    return rid
            return None

        field_map: dict[str, str] = {}
        seen_names: set[str] = set()
        for hint in hints:
            cname = str(hint.get("customer_name") or "").strip()
            if not cname or cname in seen_names:
                continue
            seen_names.add(cname)
            key = _normalize_name_key(cname)
            rid = _lookup_name(name_to_rec, cname)
            if not rid:
                rid = _search_linked(cname) or ""
                if rid:
                    name_to_rec[key] = rid
            if not rid and create_missing_links:
                create_res: dict[str, Any] = {"ok": False}
                used_primary = primary
                for pf_name in primary_candidates:
                    used_primary = pf_name
                    create_res = tool_feishu_bitable_record_batch_create(
                        base_token=bt,
                        table_id=linked_tid,
                        records_json=json.dumps(
                            {"create_records": [{pf_name: cname}]},
                            ensure_ascii=False,
                        ),
                    )
                    if create_res.get("ok"):
                        break
                    create_res = tool_feishu_bitable_record_upsert(
                        base_token=bt,
                        table_id=linked_tid,
                        fields_json=json.dumps({pf_name: cname}, ensure_ascii=False),
                    )
                    if create_res.get("ok"):
                        break
                if create_res.get("ok"):
                    created_payload = _cli_data_payload(create_res)
                    rid = _extract_record_id_any(created_payload)
                    if not rid.startswith("rec"):
                        rid = _search_linked(cname) or ""
                    if not rid.startswith("rec"):
                        filt = json.dumps(
                            {
                                "logic": "and",
                                "conditions": [[used_primary, "==", cname]],
                            },
                            ensure_ascii=False,
                        )
                        list_res = tool_feishu_bitable_record_list(
                            base_token=bt,
                            table_id=linked_tid,
                            limit=5,
                            filter_json=filt,
                        )
                        if list_res.get("ok"):
                            for row in _iter_records_from_list_payload(
                                _cli_data_payload(list_res)
                            ):
                                cand = _record_id_of(row) or _extract_record_id_any(row)
                                if cand.startswith("rec"):
                                    rid = cand
                                    break
                    if rid.startswith("rec"):
                        name_to_rec[key] = rid
                        resolutions["created_link_records"].append(
                            {
                                "table_id": linked_tid,
                                "name": cname,
                                "record_id": rid,
                                "primary_field": used_primary,
                            }
                        )
                    else:
                        resolutions["unresolved"].append(
                            {
                                "field": lf["name"],
                                "customer_name": cname,
                                "reason": "created_but_no_record_id",
                                "hint": (
                                    f"已尝试在关联表 {linked_tid} 创建「{cname}」，"
                                    "但未拿到 record_id；请检查关联表主键是否为 "
                                    f"「{used_primary}」"
                                ),
                                "create_payload_keys": (
                                    list(created_payload.keys())
                                    if isinstance(created_payload, dict)
                                    else type(created_payload).__name__
                                ),
                            }
                        )
                else:
                    resolutions["unresolved"].append(
                        {
                            "field": lf["name"],
                            "customer_name": cname,
                            "reason": "create_failed",
                            "linked_table_id": linked_tid,
                            "primary_field": used_primary,
                            "primary_candidates_tried": primary_candidates,
                            "error": (create_res.get("error") or {}),
                        }
                    )
            elif not rid:
                resolutions["unresolved"].append(
                    {
                        "field": lf["name"],
                        "customer_name": cname,
                        "reason": "no_match_in_linked_table",
                        "catalog_size": len(name_to_rec),
                    }
                )
            if rid:
                field_map[cname] = rid
        resolutions["links"][lf["name"]] = {
            "linked_table_id": linked_tid,
            "primary_field": primary,
            "catalog_size": len(name_to_rec),
            "matched": dict(field_map),
            "matched_count": len(field_map),
        }

    person_cache: dict[str, Optional[str]] = {}

    def _resolve_person(query: str) -> Optional[str]:
        q = (query or "").strip()
        if not q:
            return None
        if q in person_cache:
            return person_cache[q]
        search = tool_feishu_contact_search_user(query=q, page_size=10)
        if not search.get("ok"):
            person_cache[q] = None
            resolutions["unresolved"].append(
                {
                    "field": "内部参与人",
                    "query": q,
                    "reason": "contact_search_failed",
                    "error": search.get("error") or {},
                }
            )
            return None
        candidates = _extract_open_ids_from_contact(_cli_data_payload(search))
        oid: Optional[str] = None
        if len(candidates) == 1:
            oid = candidates[0]["open_id"]
        elif len(candidates) > 1:
            q_l = q.lower()
            for c in candidates:
                if c.get("email") == q_l or c.get("name") == q:
                    oid = c["open_id"]
                    break
            if not oid:
                resolutions["unresolved"].append(
                    {
                        "field": "内部参与人",
                        "query": q,
                        "reason": "ambiguous_contact",
                        "candidates": candidates[:5],
                    }
                )
        else:
            resolutions["unresolved"].append(
                {
                    "field": "内部参与人",
                    "query": q,
                    "reason": "contact_not_found",
                }
            )
        person_cache[q] = oid
        return oid

    for pf in person_fields:
        matched_persons: dict[str, str] = {}
        for hint in hints:
            sales = str(hint.get("sales_name") or "").strip()
            owner = str(hint.get("owner") or "").strip()
            oid = None
            used = ""
            if sales:
                oid = _resolve_person(sales)
                used = sales
            if not oid and owner:
                oid = _resolve_person(owner)
                used = owner
            if oid and used:
                matched_persons[used] = oid
        resolutions["persons"][pf["name"]] = matched_persons

    _HINT_KEYS = ("__tse_customer_name", "__tse_sales_name", "__tse_owner")
    enriched: list[dict[str, Any]] = []
    for idx, row in enumerate(create_records):
        out_row = {k: v for k, v in row.items() if k not in _HINT_KEYS}
        hint = hints[idx] if idx < len(hints) else {}
        cname = str(hint.get("customer_name") or "").strip()
        if not cname:
            for key in ("沟通对象", "客户简称", "客户名称", "__tse_customer_name"):
                val = row.get(key)
                if isinstance(val, str) and val.strip():
                    cname = val.strip()
                    break
        sales = str(hint.get("sales_name") or "").strip() or str(
            row.get("__tse_sales_name") or ""
        ).strip()
        owner = str(hint.get("owner") or "").strip() or str(
            row.get("__tse_owner") or ""
        ).strip()

        for lf in link_fields:
            fname = lf["name"]
            fid = str(lf.get("field_id") or "").strip()
            # Drop any plain-text placeholder left by map (link CellValue must be [{id}])
            for key in (fname, fid):
                if key and key in out_row and not _cell_has_link_value(out_row.get(key)):
                    out_row.pop(key, None)
            matched = (resolutions["links"].get(fname) or {}).get("matched") or {}
            rid = matched.get(cname)
            if not rid and cname:
                nkey = _normalize_name_key(cname)
                for k, v in matched.items():
                    kk = _normalize_name_key(k)
                    if kk == nkey or (nkey and kk and (nkey in kk or kk in nkey)):
                        rid = v
                        break
            if rid:
                # Prefer field_id key (stable); official CellValue = [{"id":"rec…"}]
                write_key = fid or fname
                out_row[write_key] = _link_cell_value(rid)
                if write_key != fname and fname in out_row:
                    out_row.pop(fname, None)

        for pf in person_fields:
            fname = pf["name"]
            matched = resolutions["persons"].get(fname) or {}
            oid = matched.get(sales) or matched.get(owner)
            if not oid and sales:
                oid = person_cache.get(sales)
            if not oid and owner:
                oid = person_cache.get(owner)
            if oid:
                out_row[fname] = [{"id": oid}]

        enriched.append(out_row)

    records_out = {"create_records": enriched}
    unresolved = resolutions.get("unresolved") or []
    link_unresolved = [
        u for u in unresolved
        if isinstance(u, dict) and (
            "customer_name" in u
            or str(u.get("reason") or "").startswith("missing_linked")
            or str(u.get("reason") or "") in {
                "no_match_in_linked_table",
                "created_but_no_record_id",
                "create_failed",
            }
        )
    ]
    rows_needing_link = 0
    rows_with_link = 0
    missing_link_details: list[dict[str, Any]] = []
    for idx, row in enumerate(enriched):
        hint = hints[idx] if idx < len(hints) else {}
        cname = str(hint.get("customer_name") or "").strip()
        if not cname:
            continue
        if not link_fields:
            missing_link_details.append(
                {
                    "row_index": idx,
                    "customer_name": cname,
                    "link_fields": [],
                    "reason": "no_link_field_detected",
                }
            )
            continue
        rows_needing_link += 1
        has = False
        for lf in link_fields:
            fname = lf["name"]
            fid = str(lf.get("field_id") or "").strip()
            if _cell_has_link_value(row.get(fname)) or (
                fid and _cell_has_link_value(row.get(fid))
            ):
                has = True
                break
        if has:
            rows_with_link += 1
        else:
            missing_link_details.append(
                {
                    "row_index": idx,
                    "customer_name": cname,
                    "link_fields": [lf["name"] for lf in link_fields],
                }
            )

    payload = {
        "base_token": bt,
        "table_id": tid,
        "create_record_count": len(enriched),
        "link_fields": [lf["name"] for lf in link_fields],
        "fields_source": fields_source,
        "link_rows_needed": rows_needing_link,
        "link_rows_filled": rows_with_link,
        "unresolved_count": len(unresolved),
        "resolutions": resolutions,
        "records_json": json.dumps(records_out, ensure_ascii=False),
        "create_records": enriched,
    }

    has_customer = any(
        str((hints[i] if i < len(hints) else {}).get("customer_name") or "").strip()
        for i in range(len(enriched))
    )
    if has_customer and not link_fields:
        payload["missing_links"] = missing_link_details
        payload["hint"] = (
            "表里应有「客户简称」等关联字段，但 field_list 未识别出 link/DuplexLink。"
            f"fields_source={fields_source}；请检查字段 type/ui_type/property.tableId。"
        )
        return _tool_err(
            tool,
            "LINK_FIELD_NOT_DETECTED",
            "未识别到双向/单向关联字段，拒绝写入以免客户简称留空。",
            data=payload,
        )

    if missing_link_details and (link_fields or has_customer):
        payload["missing_links"] = missing_link_details
        payload["hint"] = (
            "客户简称等关联字段仍未解析，禁止谎称已写入。"
            "请看 resolutions.unresolved / missing_links / detected_link_fields；"
            "常见原因：缺 base:record:read、关联表主键不匹配、创建失败。"
        )
        return _tool_err(
            tool,
            "LINK_FIELDS_UNRESOLVED",
            (
                f"有 {len(missing_link_details)} 行客户简称未关联成功；"
                "未写入主表。请根据 resolutions 排查后重试。"
            ),
            data=payload,
        )

    payload["hint"] = (
        "关联/人员已就绪（lark-cli link CellValue=[{id:rec…}]）。"
        "推荐 feishu_bitable_write_tse_records 一步写入。"
    )
    return _tool_ok(tool, payload)


def tool_feishu_bitable_write_tse_records(
    base_token: str,
    table_id: str,
    fields_json: str,
    records_json: str,
    enrichment_hints_json: str = "",
    create_missing_links: bool = True,
) -> dict:
    """TSE 映射结果 → enrich 关联/人员 → 写入主表（一步完成，避免用错 records_json）。"""
    tool = "feishu_bitable_write_tse_records"
    enrich = tool_feishu_bitable_enrich_tse_records(
        base_token=base_token,
        table_id=table_id,
        fields_json=fields_json,
        records_json=records_json,
        enrichment_hints_json=enrichment_hints_json,
        create_missing_links=create_missing_links,
    )
    if not enrich.get("ok"):
        # Preserve enrich error code/data; retarget tool name for tracing
        out = dict(enrich)
        out["tool"] = tool
        if isinstance(out.get("data"), dict):
            out["data"] = {**out["data"], "stage": "enrich"}
        return out
    data = enrich.get("data") if isinstance(enrich.get("data"), dict) else {}
    rj = str(data.get("records_json") or "").strip()
    if not rj:
        return _tool_err(
            tool,
            "EMPTY_ENRICHED_RECORDS",
            "enrich 成功但未返回 records_json",
            data={"stage": "enrich", "enrich": data},
        )
    create = tool_feishu_bitable_record_batch_create(
        base_token=base_token,
        table_id=table_id,
        records_json=rj,
    )
    if not create.get("ok"):
        out = dict(create)
        out["tool"] = tool
        if isinstance(out.get("data"), dict):
            out["data"] = {
                **out["data"],
                "stage": "batch_create",
                "enrich_resolutions": data.get("resolutions"),
                "link_rows_filled": data.get("link_rows_filled"),
            }
        else:
            out["data"] = {
                "stage": "batch_create",
                "enrich_resolutions": data.get("resolutions"),
            }
        return out
    create_data = create.get("data") if isinstance(create.get("data"), dict) else {}

    # Verify link cells actually landed (CLI may silently ignore bad link cells).
    link_names = [str(x) for x in (data.get("link_fields") or []) if x]
    detected = (
        (data.get("resolutions") or {}).get("detected_link_fields")
        if isinstance(data.get("resolutions"), dict)
        else None
    )
    link_field_ids: list[str] = []
    if isinstance(detected, list):
        for d in detected:
            if isinstance(d, dict):
                fid = str(d.get("field_id") or "").strip()
                if fid.startswith("fld"):
                    link_field_ids.append(fid)

    verify: dict[str, Any] = {"checked": False}
    repair: dict[str, Any] = {"attempted": False}

    def _collect_created_ids(blob: Any) -> list[str]:
        found: list[str] = []
        if not blob:
            return found
        rid = _extract_record_id_any(blob)
        if rid.startswith("rec"):
            found.append(rid)
        if isinstance(blob, dict):
            for key in ("record_id_list", "record_ids", "records"):
                vals = blob.get(key)
                if isinstance(vals, list):
                    for x in vals:
                        if isinstance(x, str) and x.strip().startswith("rec"):
                            found.append(x.strip())
                        elif isinstance(x, dict):
                            r2 = _record_id_of(x) or _extract_record_id_any(x)
                            if r2.startswith("rec"):
                                found.append(r2)
        # unique
        seen: set[str] = set()
        out: list[str] = []
        for x in found:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def _read_link_empties(record_ids: list[str]) -> list[dict[str, str]]:
        empties: list[dict[str, str]] = []
        if not record_ids or not link_names:
            return empties
        argv = [
            "base",
            "+record-get",
            "--as",
            "user",
            "--base-token",
            base_token.strip(),
            "--table-id",
            table_id.strip(),
            "--format",
            "json",
        ]
        for rid in record_ids[:20]:
            argv.extend(["--record-id", rid])
        # Prefer real field ids; field *names* as --field-id can break the get
        for fid in link_field_ids[:5]:
            argv.extend(["--field-id", fid])
        got = _run_lark_cli(argv, tool=tool, identity="user")
        if not got.get("ok"):
            # Fallback: list without field filter
            argv2 = [
                "base",
                "+record-get",
                "--as",
                "user",
                "--base-token",
                base_token.strip(),
                "--table-id",
                table_id.strip(),
                "--format",
                "json",
            ]
            for rid in record_ids[:20]:
                argv2.extend(["--record-id", rid])
            got = _run_lark_cli(argv2, tool=tool, identity="user")
        if not got.get("ok"):
            return empties
        payload = _cli_data_payload(got)
        rows = _iter_records_from_list_payload(payload)
        if not rows and isinstance(payload, dict):
            rows = [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            fmap = _fields_map_of_record(row)
            rid = _record_id_of(row) or _extract_record_id_any(row)
            for fn in link_names:
                val = fmap.get(fn)
                if not _cell_has_link_value(val):
                    # also try field_id keys
                    for fid in link_field_ids:
                        if _cell_has_link_value(fmap.get(fid)):
                            val = fmap.get(fid)
                            break
                if not _cell_has_link_value(val):
                    empties.append({"record_id": rid, "field": fn})
        return empties

    if link_names and data.get("link_rows_filled"):
        uniq_ids = _collect_created_ids(create_data)
        if not uniq_ids:
            uniq_ids = _collect_created_ids(_cli_data_payload(create))
        verify = {
            "checked": True,
            "record_ids": uniq_ids[:20],
            "empty_link_fields": [],
        }
        if uniq_ids:
            empties = _read_link_empties(uniq_ids)
            verify["empty_link_fields"] = empties
            if empties:
                # Repair: PATCH each row with official link CellValue via upsert
                repair = {"attempted": True, "results": []}
                try:
                    written_rows = json.loads(rj).get("create_records") or []
                except Exception:
                    written_rows = []
                # Build field→link value from the enriched payload we tried to write
                link_patches: list[dict[str, Any]] = []
                if isinstance(written_rows, list) and written_rows:
                    for i, rid in enumerate(uniq_ids):
                        if i >= len(written_rows):
                            break
                        row = written_rows[i] if isinstance(written_rows[i], dict) else {}
                        patch: dict[str, Any] = {}
                        for fn in link_names:
                            if _cell_has_link_value(row.get(fn)):
                                patch[fn] = row[fn]
                        for fid in link_field_ids:
                            if _cell_has_link_value(row.get(fid)):
                                patch[fid] = row[fid]
                        if patch:
                            link_patches.append({"record_id": rid, "fields": patch})
                for item in link_patches:
                    rid = item["record_id"]
                    fields = item["fields"]
                    up = tool_feishu_bitable_record_upsert(
                        base_token=base_token,
                        table_id=table_id,
                        fields_json=json.dumps(fields, ensure_ascii=False),
                        record_id=rid,
                    )
                    repair["results"].append(
                        {
                            "record_id": rid,
                            "ok": bool(up.get("ok")),
                            "error": up.get("error") if not up.get("ok") else None,
                            "fields_keys": list(fields.keys()),
                        }
                    )
                # Re-verify
                empties2 = _read_link_empties(uniq_ids)
                verify["empty_link_fields_after_repair"] = empties2
                if empties2:
                    return _tool_err(
                        tool,
                        "LINK_WRITE_NOT_PERSISTED",
                        (
                            "写入后回读「客户简称」等关联字段仍为空；"
                            "已按官方 CellValue [{id:rec…}] 尝试 upsert 修复仍失败。"
                            "请检查关联表权限与字段类型。"
                        ),
                        data={
                            "stage": "verify",
                            "verify": verify,
                            "repair": repair,
                            "enrich_resolutions": data.get("resolutions"),
                            "batch_create": create_data,
                            "records_json_written": rj,
                        },
                    )
                verify["repaired"] = True

    return _tool_ok(
        tool,
        {
            "stage": "done",
            "base_token": base_token,
            "table_id": table_id,
            "create_record_count": data.get("create_record_count"),
            "link_rows_filled": data.get("link_rows_filled"),
            "link_fields": link_names,
            "created_link_records": (data.get("resolutions") or {}).get(
                "created_link_records"
            ),
            "resolutions": data.get("resolutions"),
            "batch_create": create_data,
            "verify": verify,
            "repair": repair,
            "hint": "已 enrich 并写入主表；回读校验关联字段非空。",
        },
    )
