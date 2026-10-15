# -*- coding: utf-8 -*-
"""MCP HTTP 服务公共配置（Cloud Run / 本地调试）。"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings

from mcp_server.tunnel_hosts import resolve_tunnel_host


def resolve_listen_port(default: int) -> int:
    raw = (os.getenv("PORT") or "").strip()
    if raw.isdigit():
        return int(raw)
    return default


def is_cloud_run() -> bool:
    return bool((os.getenv("K_SERVICE") or "").strip())


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def prefer_stateless_http() -> bool:
    """Cloud Run / 多实例必须用无状态会话，否则会出现 Session not found → 404。"""
    if _truthy(os.getenv("FASTMCP_STATELESS_HTTP")):
        return True
    if _truthy(os.getenv("MCP_STATELESS_HTTP")):
        return True
    return is_cloud_run()


def configure_streamable_http_for_runtime(mcp: object) -> None:
    """按运行环境调整 FastMCP Streamable HTTP（就地改 mcp.settings）。"""
    settings = getattr(mcp, "settings", None)
    if settings is None:
        return
    if prefer_stateless_http():
        # 每请求独立 transport，避免 Agent Engine 持有的 session id
        # 落到另一实例 / 冷启动后返回 404 Session not found。
        settings.stateless_http = True
        # JSON 响应比 SSE 更适合 Cloud Run 短请求，降低半开流与 GET /mcp 406。
        settings.json_response = True


def build_transport_security(
    *,
    host_var: str,
    url_var: str,
) -> TransportSecuritySettings:
    """Cloud Run 关闭 DNS-rebinding；本地仍白名单 localhost + 可选公网 Host。"""
    if is_cloud_run() or (os.getenv("MCP_DISABLE_DNS_REBINDING") or "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
    }:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
            allowed_hosts=["*"],
            allowed_origins=["*"],
        )

    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*"]
    host = resolve_tunnel_host(host_var=host_var, url_var=url_var)
    if host:
        allowed_hosts.extend([host, f"{host}:*"])
        allowed_origins.append(f"https://{host}")
        if host.endswith(".run.app"):
            allowed_origins.append(f"http://{host}")
    # 若 URL 是 *.run.app，也加入
    url = (os.getenv(url_var) or "").strip()
    if url:
        hn = urlparse(url).hostname or ""
        if hn and hn not in allowed_hosts:
            allowed_hosts.extend([hn, f"{hn}:*"])
            allowed_origins.append(f"https://{hn}")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )
