# -*- coding: utf-8 -*-
"""Remediate Feishu scope gaps: user consent vs admin/developer enablement.

Two user-facing paths (TSE opens ``action_url`` when present):

1. **User consent** — app already declared the scope; user must OAuth-approve
   (Device Flow ``verification_url`` from oauth_flow, not this module).

2. **App / tenant gap** — open Feishu's official scope page and/or call
   ``POST /application/v6/scopes/apply`` so the tenant admin gets an approval
   request for scopes the app has already declared but the tenant has not
   granted yet.

Native ``tt.applyTenantAppScope`` only works inside Feishu gadgets; browser
TSE uses the OpenAPI apply + ``open.feishu.cn/app/{id}/auth?q=…`` deep link.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

_SCOPES_LIST_URL = "https://open.feishu.cn/open-apis/application/v6/scopes"
_SCOPES_APPLY_URL = "https://open.feishu.cn/open-apis/application/v6/scopes/apply"


def _app_id() -> str:
    return (
        (os.getenv("FEISHU_APP_ID") or "").strip()
        or (os.getenv("LARKSUITE_CLI_APP_ID") or "").strip()
    )


def _normalize_scopes(scopes: list[Any] | tuple[Any, ...] | str | None) -> list[str]:
    if scopes is None:
        return []
    if isinstance(scopes, str):
        parts = scopes.replace(",", " ").split()
    else:
        parts = [str(s) for s in scopes]
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        s = p.strip().rstrip(",.;")
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def build_scope_enable_url(scopes: list[str] | None = None, *, app_id: str = "") -> str:
    """Official Feishu help link to batch-enable / review scopes on the app."""
    aid = (app_id or _app_id()).strip()
    if not aid:
        return "https://open.feishu.cn/app"
    base = f"https://open.feishu.cn/app/{aid}/auth"
    qs = _normalize_scopes(scopes)
    if not qs:
        return base
    # Feishu docs use q=<scope> with literal ':' ; keep commas between scopes
    q = ",".join(qs)
    return f"{base}?q={urllib.parse.quote(q, safe=':,_')}&op_from=openapi"


def _tenant_token() -> tuple[Optional[str], Optional[str]]:
    from domains.feishu.feishu_cli_tools import _mint_tenant_access_token

    return _mint_tenant_access_token()


def _http_json(
    method: str,
    url: str,
    *,
    token: str,
    body: dict | None = None,
    timeout: float = 20.0,
) -> tuple[Optional[dict], Optional[str]]:
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return None, f"HTTP {exc.code}: {raw[:300]}"
        if isinstance(payload, dict):
            return payload, None
        return None, f"HTTP {exc.code}: {raw[:300]}"
    except Exception as exc:
        return None, str(exc)[:300]
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return None, f"非 JSON 响应: {raw[:200]}"
    if not isinstance(payload, dict):
        return None, f"响应非对象: {type(payload)}"
    return payload, None


def list_tenant_scope_grants() -> tuple[dict[str, int], Optional[str]]:
    """Return map scope_name → grant_status (1 granted, 2 not granted)."""
    token, terr = _tenant_token()
    if not token:
        return {}, terr or "no tenant token"
    payload, err = _http_json("GET", _SCOPES_LIST_URL, token=token)
    if err:
        return {}, err
    assert payload is not None
    if int(payload.get("code") or -1) != 0:
        return {}, f"scopes list code={payload.get('code')} msg={payload.get('msg')!r}"
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    scopes = data.get("scopes") if isinstance(data.get("scopes"), list) else []
    out: dict[str, int] = {}
    for item in scopes:
        if not isinstance(item, dict):
            continue
        name = str(item.get("scope_name") or "").strip()
        if not name:
            continue
        try:
            out[name] = int(item.get("grant_status"))
        except (TypeError, ValueError):
            continue
    return out, None


def apply_scopes_to_admin() -> tuple[bool, str, dict[str, Any]]:
    """POST scopes/apply — notify tenant admin for undeclared-but-pending grants.

    Returns (ok, message, meta).
    """
    token, terr = _tenant_token()
    if not token:
        return False, terr or "no tenant token", {}
    payload, err = _http_json("POST", _SCOPES_APPLY_URL, token=token, body={})
    if err:
        return False, err, {}
    assert payload is not None
    code = int(payload.get("code") or -1)
    msg = str(payload.get("msg") or "")
    meta = {"api_code": code, "api_msg": msg}
    if code == 0:
        return True, "已向企业管理员提交应用权限审批申请", meta
    # Friendly map of known codes
    hints = {
        212001: "剩余未授权权限为高敏权限，无法通过接口申请，请管理员在后台处理",
        212002: "当前没有待管理员审批的权限（可能尚未在开放平台开通这些 scope）",
        212003: "本版本向管理员申请次数已达上限（≤10），请等待审批或发新版",
        212004: "已有进行中的申请，请勿重复提交",
    }
    return False, hints.get(code, f"scopes/apply 失败 code={code} msg={msg!r}"), meta


def remediate_app_scopes(missing_scopes: list[str] | str | None = None) -> dict[str, Any]:
    """Classify missing scopes and produce an actionable payload for the agent/TSE.

    ``action``:
      - ``admin_apply_submitted`` — POST apply succeeded
      - ``admin_apply_pending`` — scopes declared but not granted; apply failed/dup
      - ``enable_on_console`` — scopes not on app yet; open enable URL
      - ``unknown`` — could not list grants
    """
    needed = _normalize_scopes(missing_scopes)
    app_id = _app_id()
    enable_url = build_scope_enable_url(needed, app_id=app_id)
    grants, gerr = list_tenant_scope_grants()

    declared_ungranted = [
        s for s in needed if grants.get(s) == 2
    ] if needed else [s for s, st in grants.items() if st == 2]
    not_on_app = [s for s in needed if s not in grants] if needed else []
    already_ok = [s for s in needed if grants.get(s) == 1]

    out: dict[str, Any] = {
        "app_id": app_id or None,
        "missing_scopes": needed,
        "already_granted": already_ok,
        "declared_but_ungranted": declared_ungranted,
        "not_declared_on_app": not_on_app,
        "scope_enable_url": enable_url,
        "action_url": enable_url,
        "action_kind": "app_scope_enable",
        "grants_error": gerr,
    }

    # Prefer admin apply when Feishu already knows about ungranted declared scopes
    if declared_ungranted or (not needed and not gerr and any(st == 2 for st in grants.values())):
        ok, msg, meta = apply_scopes_to_admin()
        out["admin_apply"] = {"ok": ok, "message": msg, **meta}
        if ok:
            out["action"] = "admin_apply_submitted"
            out["action_kind"] = "admin_apply"
            # Still give console URL so user can track / publish if needed
            out["hint"] = (
                "已替您向企业管理员提交权限审批。管理员通过并完成应用发布后，"
                "请回复「权限已开通」再继续原操作。"
                f"也可打开权限页查看：{enable_url}"
            )
            return out
        out["action"] = "admin_apply_pending"
        out["action_kind"] = "admin_apply"
        out["hint"] = (
            f"{msg}。请打开权限页确认或联系管理员：{enable_url}"
        )
        return out

    if not_on_app or gerr or not grants:
        out["action"] = "enable_on_console"
        out["action_kind"] = "app_scope_enable"
        # Still try apply — no-op if empty, harmless
        ok, msg, meta = apply_scopes_to_admin()
        out["admin_apply"] = {"ok": ok, "message": msg, **meta}
        if ok:
            out["action"] = "admin_apply_submitted"
            out["action_kind"] = "admin_apply"
            out["hint"] = (
                "已向管理员提交审批；若仍缺接口权限，请再打开权限页开通并发布："
                f"{enable_url}"
            )
            return out
        out["hint"] = (
            "应用尚未在开放平台声明这些 API 权限。"
            "请点击下方链接开通（勾选 missing_scopes）→ 创建版本并提交管理员发布；"
            f"完成后回复「权限已开通」。链接：{enable_url}"
        )
        return out

    out["action"] = "unknown"
    out["hint"] = f"权限状态异常，请打开：{enable_url}"
    return out


def tool_feishu_app_scopes_remediate(scopes: str = "") -> dict[str, Any]:
    """向管理员申请 / 打开开通页，修复应用级 API 权限缺口（非个人 OAuth）。"""
    from domains.feishu.feishu_cli_tools import _tool_err, _tool_ok

    tool = "feishu_app_scopes_remediate"
    try:
        data = remediate_app_scopes(scopes)
    except Exception as exc:
        return _tool_err(tool, "REMEDIATE_FAILED", str(exc)[:300])
    return _tool_ok(
        tool,
        data,
        meta={"action": data.get("action"), "action_kind": data.get("action_kind")},
    )
