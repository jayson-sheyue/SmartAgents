# -*- coding: utf-8 -*-
"""TSE 登录身份 ↔ ADK session.state 贯通与数据访问强制 scope。

TSE App 在 create_session / streamQuery 时写入：
  - ``tse_user_email``: Google 登录邮箱（小写）
  - ``tse_auth_source``: ``tse_app``

工具层读取后，对客户/跟进类 Firestore 兜底路径强制 ``owner == tse_user_email``，
禁止模型靠自然语言越权扫描他人数据。Playground / 无身份会话保持旧行为。
"""

from __future__ import annotations

from typing import Any, Optional

TSE_USER_EMAIL_KEY = "tse_user_email"
TSE_AUTH_SOURCE_KEY = "tse_auth_source"
TSE_AUTH_SOURCE_APP = "tse_app"


def _state_mapping(obj: Any) -> Any:
    if obj is None:
        return None
    state = getattr(obj, "state", None)
    if state is None and hasattr(obj, "session"):
        session = getattr(obj, "session", None)
        state = getattr(session, "state", None) if session is not None else None
    if state is None:
        return None
    if hasattr(state, "get") and (
        hasattr(state, "__setitem__") or isinstance(state, dict)
    ):
        return state
    return None


def resolve_tse_principal(ctx_or_tool: Any = None) -> dict[str, Any]:
    """从 ToolContext / ReadonlyContext 解析当前 TSE 主体。"""
    state = _state_mapping(ctx_or_tool)
    email = ""
    source = ""
    if state is not None:
        email = str(state.get(TSE_USER_EMAIL_KEY) or "").strip().lower()
        source = str(state.get(TSE_AUTH_SOURCE_KEY) or "").strip().lower()
    scoped = bool(email) and source == TSE_AUTH_SOURCE_APP
    return {
        "email": email,
        "source": source or None,
        "scoped": scoped,
    }


def format_principal_instruction_block(ctx_or_tool: Any = None) -> str:
    """注入调度员 instruction：让模型知道对面是谁。"""
    p = resolve_tse_principal(ctx_or_tool)
    if not p.get("scoped"):
        return (
            "\n\n【TSE 用户身份】当前会话未绑定 TSE App 登录用户"
            "（Playground / 本地调试）。客户跟进数据无自动 ACL；"
            "开放语义仍可能需要 `set_tse_session_api_key`。"
        )
    email = p["email"]
    return (
        f"\n\n【TSE 用户身份 — 强制】当前登录用户是 **{email}**（来源 tse_app）。\n"
        f"- 查询/分析/写飞书摘要时，默认只处理 **该用户可见** 的客户跟进"
        f"（owner={email} 或已共享给该用户）。\n"
        f"- **禁止**改查其他同事的私密跟进；工具层会拒绝越权 owner / 无权限 item_id。\n"
        f"- 对用户说话时可称呼其邮箱本地部分，但不要泄露他人数据。"
    )


def cross_user_forbidden(principal_email: str, requested: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "CROSS_USER_FORBIDDEN",
            "message": (
                f"当前会话绑定用户 {principal_email}，"
                f"不能查询他人（{requested}）的客户跟进。"
                "请只分析本人数据，或请对方在 TSE 中分享条目后再查。"
            ),
        },
        "wait_user": False,
        "principal_email": principal_email,
        "requested_owner": requested,
    }


def enforce_owner_scope(
    tool_context: Any = None,
    requested_owner_email: str = "",
) -> tuple[str, Optional[dict[str, Any]]]:
    """返回 ``(effective_owner_filter, error_or_None)``。

    - TSE App 绑定身份：强制 effective = 本人邮箱；若请求他人 → CROSS_USER_FORBIDDEN
    - 未绑定：effective = 请求值（可空，表示不强制过滤，旧行为）

    列表/检索更推荐 ``enforce_data_scope``（含 viewers 共享可见）。
    """
    owner_filter, _access, err = enforce_data_scope(
        tool_context, requested_owner_email=requested_owner_email
    )
    if err:
        return owner_filter, err
    p = resolve_tse_principal(tool_context)
    if p.get("scoped") and not owner_filter:
        # 仅 owner 过滤的旧接口：无 viewers 字段时退化为本人 owner
        return str(p["email"]), None
    return owner_filter, None


def enforce_data_scope(
    tool_context: Any = None,
    *,
    requested_owner_email: str = "",
    requested_user_email: str = "",
) -> tuple[str, str, Optional[dict[str, Any]]]:
    """返回 ``(owner_filter, access_email, error_or_None)``。

    - ``access_email`` 非空时：行必须对改邮箱可见（owner 或 viewers）
    - 请求他人 owner/user → CROSS_USER_FORBIDDEN
    - Playground：access_email 为空，仅应用请求的 owner_filter
    """
    p = resolve_tse_principal(tool_context)
    requested_owner = (requested_owner_email or "").strip().lower()
    requested_user = (requested_user_email or "").strip().lower()
    if not p.get("scoped"):
        return requested_owner, "", None
    email = str(p["email"])
    if requested_owner and requested_owner != email:
        return email, email, cross_user_forbidden(email, requested_owner)
    if requested_user and requested_user != email:
        return email, email, cross_user_forbidden(email, requested_user)
    return requested_owner, email, None


def row_visible_to(owner: str, viewers: Any, access_email: str) -> bool:
    """owner 本人或 viewers 中含 access_email 则可见。"""
    email = (access_email or "").strip().lower()
    if not email:
        return True
    if (owner or "").strip().lower() == email:
        return True
    if isinstance(viewers, str):
        viewers = [viewers]
    for v in viewers or []:
        if str(v or "").strip().lower() == email:
            return True
    return False


def assert_item_access(
    tool_context: Any = None,
    *,
    owner: str = "",
    viewers: Any = None,
    item_id: str = "",
) -> Optional[dict[str, Any]]:
    """单条客户：scoped 会话下非本人/非共享则拒绝。"""
    p = resolve_tse_principal(tool_context)
    if not p.get("scoped"):
        return None
    email = str(p["email"])
    if row_visible_to(owner, viewers, email):
        return None
    return {
        "ok": False,
        "error": {
            "code": "ITEM_ACCESS_DENIED",
            "message": (
                f"客户条目 {item_id or '(unknown)'} 不属于当前用户 {email}，"
                "且未共享给你。无法读取。"
            ),
        },
        "principal_email": email,
        "item_id": item_id or None,
        "owner": (owner or "").strip().lower() or None,
    }


def deny_unscoped_global(tool_context: Any = None, *, tool: str = "") -> Optional[dict[str, Any]]:
    """全库总览类工具在 TSE App 会话中禁止无过滤扫描。"""
    p = resolve_tse_principal(tool_context)
    if not p.get("scoped"):
        return None
    return {
        "ok": False,
        "error": {
            "code": "SCOPED_SESSION_NO_GLOBAL_SCAN",
            "message": (
                f"当前为 TSE App 登录会话（{p['email']}），"
                f"工具 {tool or '该工具'} 的全库扫描已禁用。"
                "请改用 list_tse_customers / query_tse_daily_reports_by_date"
                "（已自动限定为本人可见数据）。"
            ),
        },
        "principal_email": p["email"],
    }
