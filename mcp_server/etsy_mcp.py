# -*- coding: utf-8 -*-
"""
mcp_server/etsy_mcp.py — Etsy 评论 MCP 工具服务器

stdio：Cursor / 本地调试（无需隧道）
HTTP：python mcp_server/etsy_mcp.py --http  →  :8003/mcp
      供 etsy_cloud_agent_mcp + Cloudflare Tunnel 调用；凭证与 Excel 留在本机 .env
"""

from __future__ import annotations

import os
import sys
from typing import Any, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_server.tunnel_hosts import resolve_tunnel_host
from etsy_agent.etsy_tools import (
    tool_etsy_check_credentials,
    tool_etsy_fetch_and_export_reviews,
    tool_etsy_fetch_listing_reviews,
    tool_etsy_write_reviews_excel,
)

load_dotenv()

ETSY_TUNNEL_HOST = resolve_tunnel_host(
    host_var="ETSY_TUNNEL_HOST",
    url_var="ETSY_MCP_SERVER_URL",
)

mcp = FastMCP("Etsy Review MCP Server")


@mcp.tool()
def etsy_check_credentials(probe: bool = True, probe_listing_id: str = "786582119") -> dict[str, Any]:
    """检查本机 .env 中的 Etsy API 凭证；probe 为 True 时真实请求 API。"""
    return tool_etsy_check_credentials(probe=probe, probe_listing_id=probe_listing_id)


@mcp.tool()
def etsy_fetch_listing_reviews(
    listing_id: str,
    listing_url: Optional[str] = None,
    limit: int = 25,
    max_pages: int = 3,
    min_created: Optional[int] = None,
    max_created: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """分页拉取 Etsy listing 评论（P0 envelope）。"""
    return tool_etsy_fetch_listing_reviews(
        listing_id,
        listing_url=listing_url,
        limit=limit,
        max_pages=max_pages,
        min_created=min_created,
        max_created=max_created,
        dry_run=dry_run,
    )


@mcp.tool()
def etsy_write_reviews_excel(
    listing_id: str,
    reviews: list[dict[str, Any]],
    listing_url: Optional[str] = None,
    excel_path: Optional[str] = None,
    sheet_name: str = "评论明细",
    deduplicate: bool = True,
) -> dict[str, Any]:
    """将评论列表写入本机 Excel（P0 envelope）。"""
    return tool_etsy_write_reviews_excel(
        listing_id,
        reviews,
        listing_url=listing_url,
        excel_path=excel_path,
        sheet_name=sheet_name,
        deduplicate=deduplicate,
    )


@mcp.tool()
def etsy_fetch_and_export_reviews(
    listing_url_or_id: str,
    limit: int = 25,
    max_pages: int = 3,
    min_created: Optional[int] = None,
    max_created: Optional[int] = None,
    excel_path: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """一步到位：拉取评论并写入本机 Excel（P0 envelope）。"""
    return tool_etsy_fetch_and_export_reviews(
        listing_url_or_id,
        limit=limit,
        max_pages=max_pages,
        min_created=min_created,
        max_created=max_created,
        excel_path=excel_path,
        dry_run=dry_run,
    )


if __name__ == "__main__":
    if "--http" in sys.argv:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = 8003
        allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
        allowed_origins = ["http://127.0.0.1:*", "http://localhost:*"]
        if ETSY_TUNNEL_HOST:
            allowed_hosts.extend([ETSY_TUNNEL_HOST, f"{ETSY_TUNNEL_HOST}:*"])
            allowed_origins.append(f"https://{ETSY_TUNNEL_HOST}")
            print(f"🌐 Etsy MCP 隧道 Host 白名单：{ETSY_TUNNEL_HOST}")
        else:
            print(
                "⚠️ 未配置 ETSY_TUNNEL_HOST（且无法从 ETSY_MCP_SERVER_URL 解析），"
                "云端经隧道访问将 421。请先 source .env 再启动，或更新 .env 后重启本进程。"
            )
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
        mcp.run(transport="streamable-http")
    else:
        mcp.run()
