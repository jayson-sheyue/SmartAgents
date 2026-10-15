# -*- coding: utf-8 -*-
"""
mcp_server/feishu_mcp.py — 飞书 MCP（HTTP / Cloud Run，内嵌 lark-cli）

本地调试: python mcp_server/feishu_mcp.py --http
Cloud Run: 镜像入口同本文件，端口读 $PORT
"""

from __future__ import annotations

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

from domains.feishu.registry import TOOL_IMPLEMENTATIONS
from domains.feishu.mcp_register import register_feishu_tools
from domains.shared.runtime import load_runtime_env
from mcp_server.http_settings import (
    build_transport_security,
    configure_streamable_http_for_runtime,
    prefer_stateless_http,
    resolve_listen_port,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_runtime_env(default_env_path=os.path.join(PROJECT_ROOT, ".env"))

# Headless bot credentials for lark-cli
if (os.getenv("FEISHU_APP_ID") or "").strip() and not (
    os.getenv("LARKSUITE_CLI_APP_ID") or ""
).strip():
    os.environ["LARKSUITE_CLI_APP_ID"] = os.environ["FEISHU_APP_ID"].strip()
_secret = (
    os.getenv("FEISHU_APP_SECRET") or os.getenv("FEISHU_APP_TOKEN") or ""
).strip()
if _secret and not (os.getenv("LARKSUITE_CLI_APP_SECRET") or "").strip():
    os.environ["LARKSUITE_CLI_APP_SECRET"] = _secret

_STATELESS = prefer_stateless_http()
mcp = FastMCP(
    "Feishu Lark-CLI MCP Server",
    stateless_http=_STATELESS,
    json_response=_STATELESS,
)
register_feishu_tools(mcp, TOOL_IMPLEMENTATIONS)


def main() -> None:
    if "--http" not in sys.argv and not os.getenv("K_SERVICE"):
        print("用法: python mcp_server/feishu_mcp.py --http", file=sys.stderr)
        sys.exit(2)

    port = resolve_listen_port(8004)
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = port
    mcp.settings.transport_security = build_transport_security(
        host_var="FEISHU_TUNNEL_HOST",
        url_var="FEISHU_MCP_SERVER_URL",
    )
    configure_streamable_http_for_runtime(mcp)
    mode = (
        f"stateless={mcp.settings.stateless_http} json={mcp.settings.json_response}"
    )
    print(f"🚀 Feishu MCP HTTP → http://0.0.0.0:{port}/mcp ({mode})")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
