# -*- coding: utf-8 -*-
"""
mcp_server/bilibili_mcp.py — B 站热门 API MCP（HTTP / Cloud Run）

本地调试: python mcp_server/bilibili_mcp.py --http
Cloud Run: 镜像入口同本文件，端口读 $PORT
"""

from __future__ import annotations

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

from domains.bilibili.registry import TOOL_IMPLEMENTATIONS
from domains.shared.mcp_bootstrap import register_tools
from domains.shared.runtime import load_runtime_env
from mcp_server.http_settings import (
    build_transport_security,
    configure_streamable_http_for_runtime,
    prefer_stateless_http,
    resolve_listen_port,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_runtime_env(default_env_path=os.path.join(PROJECT_ROOT, ".env"))

_STATELESS = prefer_stateless_http()
mcp = FastMCP(
    "Bilibili Hot Videos MCP Server",
    stateless_http=_STATELESS,
    json_response=_STATELESS,
)
register_tools(mcp, TOOL_IMPLEMENTATIONS)


def main() -> None:
    if "--http" not in sys.argv and not os.getenv("K_SERVICE"):
        print("用法: python mcp_server/bilibili_mcp.py --http", file=sys.stderr)
        sys.exit(2)

    port = resolve_listen_port(8002)
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    mcp.settings.transport_security = build_transport_security(
        host_var="BILIBILI_TUNNEL_HOST",
        url_var="BILIBILI_MCP_SERVER_URL",
    )
    configure_streamable_http_for_runtime(mcp)
    mode = (
        f"stateless={mcp.settings.stateless_http} json={mcp.settings.json_response}"
    )
    print(f"🚀 Bilibili MCP HTTP → http://0.0.0.0:{port}/mcp ({mode})")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
