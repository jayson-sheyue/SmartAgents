# -*- coding: utf-8 -*-
"""Register Feishu MCP tools with request-scoped ADK user id injection."""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable

from mcp.server.fastmcp import Context, FastMCP

from domains.feishu.user_context import (
    extract_adk_user_id_from_ctx,
    reset_adk_user_id,
    set_adk_user_id,
)


def register_feishu_tools(mcp: FastMCP, implementations: dict[str, Callable[..., Any]]) -> None:
    for name, impl in implementations.items():
        mcp.tool(name=name)(_wrap_with_user_context(impl))


def _wrap_with_user_context(impl: Callable[..., Any]) -> Callable[..., Any]:
    sig = inspect.signature(impl)
    params = [
        inspect.Parameter(
            "ctx",
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Context,
        )
    ]
    for p in sig.parameters.values():
        if p.name == "ctx":
            continue
        params.append(p)
    new_sig = sig.replace(parameters=params)

    @functools.wraps(impl)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        ctx = kwargs.pop("ctx", None)
        if ctx is None and args and isinstance(args[0], Context):
            ctx = args[0]
            args = args[1:]
        uid = extract_adk_user_id_from_ctx(ctx)
        token = set_adk_user_id(uid)
        try:
            return impl(*args, **kwargs)
        finally:
            reset_adk_user_id(token)

    wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
    # FastMCP uses annotations for schema; keep Context out of JSON schema via annotation
    wrapper.__annotations__ = {
        **getattr(impl, "__annotations__", {}),
        "ctx": Context,
        "return": getattr(impl, "__annotations__", {}).get("return", dict),
    }
    return wrapper
