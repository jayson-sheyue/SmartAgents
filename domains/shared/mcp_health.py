# -*- coding: utf-8 -*-
"""MCP endpoint health check (shared by agent entrypoints)."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from domains.shared.runtime_mode import normalize_mcp_url


def probe_mcp_endpoint(url: str, *, label: str = "MCP") -> dict[str, Any]:
    """探测 MCP Streamable HTTP 端点；不抛异常，返回结构化结果。

    注意：不能对 ``/mcp`` 发裸 GET（会 406）。应发带正确 Accept 的 initialize POST。
    """
    mcp_url = normalize_mcp_url(url)
    parsed = urlparse(mcp_url)
    if not parsed.scheme or not parsed.netloc:
        return {
            "ok": False,
            "label": label,
            "url": mcp_url,
            "error": "INVALID_URL",
            "message": f"{label} URL 非法: {mcp_url}",
        }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smart-agents-probe", "version": "0"},
        },
    }
    try:
        with httpx.Client(timeout=8.0, trust_env=False, follow_redirects=True) as client:
            resp = client.post(mcp_url, headers=headers, json=payload)
        # 404 Session not found / 406 Accept 都说明「连得上但协议不对」——对业务仍算不可用
        if resp.status_code == 404:
            return {
                "ok": False,
                "label": label,
                "url": mcp_url,
                "error": "SESSION_ERROR",
                "message": (
                    f"{label} 返回 HTTP 404（多为 Streamable HTTP 会话失效/"
                    "有状态多实例问题，并非 VPC 网络不通）"
                ),
                "status_code": 404,
                "body_preview": (resp.text or "")[:180],
            }
        if resp.status_code < 200 or resp.status_code >= 400:
            return {
                "ok": False,
                "label": label,
                "url": mcp_url,
                "error": "HTTP_ERROR",
                "message": f"{label} 状态异常: HTTP {resp.status_code}",
                "status_code": resp.status_code,
                "body_preview": (resp.text or "")[:180],
            }
        return {
            "ok": True,
            "label": label,
            "url": mcp_url,
            "status_code": resp.status_code,
            "message": f"{label} 可达",
        }
    except Exception as exc:
        return {
            "ok": False,
            "label": label,
            "url": mcp_url,
            "error": "UNREACHABLE",
            "message": f"{label} 端点不可达: {exc}",
        }


def assert_mcp_reachable(url: str, *, label: str = "MCP") -> None:
    result = probe_mcp_endpoint(url, label=label)
    if result.get("ok"):
        return
    msg = result.get("message") or f"{label} 不可达"
    if result.get("error") == "UNREACHABLE":
        raise RuntimeError(
            f"{msg}\n请先启动对应 mcp_server（例如 python mcp_server/etsy_mcp.py --http）"
        )
    raise RuntimeError(msg)
