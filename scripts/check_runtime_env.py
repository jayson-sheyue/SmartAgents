#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime env checks. Launch scripts call this after load_env."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _fail(msg: str) -> int:
    print(f"❌ {msg}")
    return 1


def _ok(msg: str) -> None:
    print(f"✅ {msg}")


def _warn(msg: str) -> None:
    print(f"⚠️  {msg}")


def _looks_like_placeholder(value: str) -> bool:
    v = value.strip().lower()
    return not v or v.startswith("your-") or v in {"changeme", "todo", "xxx"}


def bootstrap_env() -> int:
    """Load .env then env/local.env (required)."""
    root_env = _REPO_ROOT / ".env"
    local_env = _REPO_ROOT / "env" / "local.env"

    if not root_env.is_file():
        return _fail("缺少根 .env，请：cp .env.example .env")
    if not local_env.is_file():
        return _fail("缺少 env/local.env，请：cp env/local.env.example env/local.env")

    from dotenv import load_dotenv

    load_dotenv(root_env, override=False)
    load_dotenv(local_env, override=True)
    print(f"📄 base: {root_env}")
    print(f"📄 local: {local_env}")
    return 0


def _check_mcp_url(name: str, url: str, *, local_hint: str = "") -> int:
    if not url:
        return _fail(f"{name} 未设置（请部署 Cloud Run MCP 后写入 .env）")
    if not url.endswith("/mcp"):
        return _fail(f"{name} 必须以 /mcp 结尾，当前: {url}")
    if "127.0.0.1" in url or "localhost" in url:
        return _fail(
            f"{name} 不能是本地地址（当前: {url}）。"
            "请使用 Cloud Run URL，例如 https://xxx.run.app/mcp"
        )
    _ok(f"{name}={url}")
    return 0


def _check_gcp() -> int:
    gcp = (os.getenv("GCP_PROJECT_ID") or "").strip()
    if not gcp:
        return _fail("GCP_PROJECT_ID 未设置（填根 .env）")
    if _looks_like_placeholder(gcp):
        return _fail("GCP_PROJECT_ID 仍是占位符，请编辑根 .env")
    _ok(f"GCP_PROJECT_ID={gcp}")
    return 0


def _check_dual_mcp() -> int:
    bilibili = (
        os.getenv("SMART_AGENTS_BILIBILI_MCP_SERVER_URL")
        or os.getenv("BILIBILI_MCP_SERVER_URL")
        or ""
    ).strip()
    etsy = (
        os.getenv("SMART_AGENTS_ETSY_MCP_SERVER_URL")
        or os.getenv("ETSY_MCP_SERVER_URL")
        or ""
    ).strip()
    feishu = (
        os.getenv("SMART_AGENTS_FEISHU_MCP_SERVER_URL")
        or os.getenv("FEISHU_MCP_SERVER_URL")
        or ""
    ).strip()
    if not bilibili:
        return _fail("BILIBILI_MCP_SERVER_URL 未设置")
    if not etsy:
        return _fail("ETSY_MCP_SERVER_URL 未设置")
    if not feishu:
        return _fail("FEISHU_MCP_SERVER_URL 未设置")
    if _check_mcp_url("BILIBILI_MCP_SERVER_URL", bilibili):
        return 1
    if _check_mcp_url("ETSY_MCP_SERVER_URL", etsy):
        return 1
    if _check_mcp_url("FEISHU_MCP_SERVER_URL", feishu):
        return 1
    _ok("runtime=cloud_run_mcp（Bilibili + Etsy + Feishu）")
    return 0


def check_etsy_agent() -> int:
    if _check_gcp():
        return 1
    url = (os.getenv("ETSY_MCP_SERVER_URL") or "").strip()
    if _check_mcp_url("ETSY_MCP_SERVER_URL", url):
        return 1
    if not (os.getenv("ETSY_KEYSTRING") or "").strip():
        _warn("ETSY_KEYSTRING 未在 .env 配置（Etsy MCP 工具会失败）")
    else:
        _ok("ETSY_KEYSTRING 已配置")
    _ok("etsy_agent 环境检查通过")
    return 0


def _check_vertex_reachable() -> int:
    """Lightweight Vertex ping (async path, same as adk run)."""
    vertex_proxy = ""
    try:
        import asyncio

        from google.genai import Client

        from smart_agents.vertex import LOCATION, PROJECT_ID, _VERTEX_HTTPX_ASYNC, _VERTEX_PROXY

        vertex_proxy = _VERTEX_PROXY or ""

        async def _ping() -> None:
            client = Client(
                vertexai=True,
                project=PROJECT_ID,
                location=LOCATION,
                http_options={"httpx_async_client": _VERTEX_HTTPX_ASYNC},
            )
            resp = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents="ping",
            )
            if not (resp.text or "").strip():
                raise RuntimeError("empty Vertex response")

        asyncio.run(asyncio.wait_for(_ping(), timeout=25.0))
    except Exception as exc:
        hint = (
            "Vertex 连不通（adk run 会在对话时 httpx.ConnectError）。"
            "请在 env/local.env 设置 VERTEX_HTTP_PROXY=http://127.0.0.1:7890（按你的代理端口改），"
            "并确认代理/VPN 已开启后重试。"
        )
        if vertex_proxy:
            return _fail(f"{hint} 当前 VERTEX_HTTP_PROXY={vertex_proxy!r}；错误: {exc}")
        return _fail(f"{hint} 错误: {exc}")
    label = f"VERTEX_HTTP_PROXY={vertex_proxy}" if vertex_proxy else "直连"
    _ok(f"Vertex 可达（{label}）")
    return 0


def _check_bilibili_mcp_tools() -> int:
    url = (os.getenv("BILIBILI_MCP_SERVER_URL") or "").strip()
    if _check_mcp_url("BILIBILI_MCP_SERVER_URL", url):
        return 1
    try:
        import asyncio

        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        required = {"fetch_hot_videos", "export_hot_videos_excel"}
        forbidden = {"get_up_list", "fetch_fans_data", "write_excel"}

        async def _list() -> set[str]:
            async with streamablehttp_client(url) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    return {t.name for t in tools.tools}

        names = asyncio.run(asyncio.wait_for(_list(), timeout=30.0))
        missing = required - names
        if missing:
            return _fail(f"Bilibili MCP 缺少工具 {sorted(missing)}")
        leftover = forbidden & names
        if leftover:
            return _fail(f"Bilibili MCP 仍暴露已废弃 RPA 工具 {sorted(leftover)}")
        _ok(f"Bilibili MCP 热点工具 OK: {', '.join(sorted(required))}")
    except Exception as exc:
        return _fail(f"无法连接 Bilibili MCP ({url}): {exc}")
    return 0


def check_bilibili_agent() -> int:
    if _check_gcp():
        return 1
    if _check_bilibili_mcp_tools():
        return 1
    if _check_vertex_reachable():
        return 1
    _ok("bilibili_agent 环境检查通过")
    return 0


def _check_code_execution() -> int:
    enabled = (os.getenv("CODE_EXECUTION_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not enabled:
        return 0

    loc = (os.getenv("CODE_EXEC_LOCATION") or os.getenv("GCP_LOCATION") or "us-central1").strip()
    if loc != "us-central1":
        _warn(
            f"Code Execution 沙箱仅支持 us-central1，当前 CODE_EXEC_LOCATION/GCP_LOCATION={loc}"
        )

    sandbox = (os.getenv("CODE_EXEC_SANDBOX_RESOURCE_NAME") or "").strip()
    engine_resource = (os.getenv("CODE_EXEC_AGENT_ENGINE_RESOURCE_NAME") or "").strip()
    engine_id = (os.getenv("SMART_AGENTS_ENGINE_ID") or "").strip()

    if sandbox:
        _ok(f"CODE_EXEC_SANDBOX_RESOURCE_NAME 已配置")
    elif engine_resource:
        _ok(f"CODE_EXEC_AGENT_ENGINE_RESOURCE_NAME 已配置")
    elif _looks_like_placeholder(engine_id):
        return _fail(
            "CODE_EXECUTION_ENABLED=true 但 SMART_AGENTS_ENGINE_ID 未配置（或仍是占位符）"
        )
    else:
        _ok(f"Code Execution 将使用 SMART_AGENTS_ENGINE_ID={engine_id} @ {loc}")

    try:
        from google.cloud import iam_credentials_v1  # noqa: F401
    except ImportError:
        return _fail(
            "Code Execution 缺少依赖：pip install 'google-cloud-aiplatform[agent_engines]'"
        )
    _ok("agent_engines.sandboxes 依赖已就绪")
    return 0


def _check_gcp_data_mcp() -> int:
    enabled = (os.getenv("GCP_DATA_MCP_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    kc = (os.getenv("KC_MCP_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    fs = (os.getenv("FIRESTORE_MCP_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if not (enabled or kc or fs):
        return 0

    flags = []
    if enabled or kc:
        flags.append("KC")
    if enabled or fs:
        flags.append("Firestore")
    _ok(f"GCP Data MCP 已启用：{', '.join(flags)}（需 ADC + roles/mcp.toolUser）")

    db = (os.getenv("TSE_FIRESTORE_DATABASE") or "tse-jayson-database").strip()
    _ok(f"TSE Firestore 目标库：{db}")
    return 0


def check_smart_agents() -> int:
    if _check_gcp():
        return 1
    if _check_dual_mcp():
        return 1
    if _check_code_execution():
        return 1
    if _check_gcp_data_mcp():
        return 1
    _ok("smart_agents 环境检查通过")
    return 0


def check_feishu() -> int:
    if check_smart_agents():
        return 1
    app_id = (os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (
        os.getenv("FEISHU_APP_SECRET") or os.getenv("FEISHU_APP_TOKEN") or ""
    ).strip()
    if _looks_like_placeholder(app_id) or _looks_like_placeholder(app_secret):
        return _fail("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置或仍是占位符（填根 .env）")
    run_mode = (os.getenv("FEISHU_RUN_MODE") or "local").strip().lower()
    if run_mode != "local":
        return _fail(
            f"FEISHU_RUN_MODE={run_mode}；本地飞书须在 env/local.env 设 FEISHU_RUN_MODE=local"
        )
    _ok(f"FEISHU_RUN_MODE={run_mode}")
    _ok("feishu 环境检查通过")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check .env + env/local.env (launch scripts run this automatically)."
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=["etsy_agent", "bilibili_agent", "smart_agents", "feishu"],
    )
    args = parser.parse_args()

    if bootstrap_env():
        return 1

    if args.mode == "etsy_agent":
        return check_etsy_agent()
    if args.mode == "bilibili_agent":
        return check_bilibili_agent()
    if args.mode == "feishu":
        return check_feishu()
    return check_smart_agents()


if __name__ == "__main__":
    sys.exit(main())
