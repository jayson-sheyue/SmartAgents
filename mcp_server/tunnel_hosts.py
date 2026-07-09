# -*- coding: utf-8 -*-
"""Cloudflare Tunnel 等公网穿透的 MCP Host 白名单辅助。"""

from __future__ import annotations

import os
from urllib.parse import urlparse


def resolve_tunnel_host(*, host_var: str, url_var: str) -> str:
    """从 TUNNEL_HOST 或对应 HTTPS URL 解析 hostname（不含端口）。"""
    host = (os.getenv(host_var) or "").strip()
    if host:
        return host
    url = (os.getenv(url_var) or "").strip()
    if url:
        return urlparse(url).hostname or ""
    return ""
