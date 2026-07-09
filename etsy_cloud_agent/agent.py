# -*- coding: utf-8 -*-
"""
etsy_cloud_agent/agent.py — Etsy REST + Skill Agent（ADK）

调用链：
  adk run → load_skill('etsy-review') + REST *_from_node
  → BILIBILI_REST_SERVER_URL/api/etsy_* → local_node/server.py → etsy_tools.py
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Any, Optional

import httpx
import requests
from dotenv import load_dotenv
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import Agent
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import Client

load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
SKILL_ID = "etsy-review"

if not PROJECT_ID:
    raise RuntimeError("请在 .env 中设置 GCP_PROJECT_ID")


def _pick_vertex_proxy_url() -> Optional[str]:
    for key in ("VERTEX_HTTP_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return None


def _isolate_global_proxy_env(vertex_proxy: Optional[str]) -> None:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)
    if vertex_proxy:
        os.environ["VERTEX_HTTP_PROXY"] = vertex_proxy
    no_proxy = os.getenv("NO_PROXY") or os.getenv("no_proxy") or ""
    parts = {p.strip() for p in no_proxy.split(",") if p.strip()}
    parts.update({"127.0.0.1", "localhost", ".local"})
    os.environ["NO_PROXY"] = ",".join(sorted(parts))


_VERTEX_PROXY = _pick_vertex_proxy_url()
_isolate_global_proxy_env(_VERTEX_PROXY)

_vertex_httpx_kwargs: dict = {"trust_env": False, "follow_redirects": True}
if _VERTEX_PROXY:
    _vertex_httpx_kwargs["proxy"] = _VERTEX_PROXY

_VERTEX_HTTPX_ASYNC = httpx.AsyncClient(**_vertex_httpx_kwargs)
_VERTEX_HTTPX_SYNC = httpx.Client(**_vertex_httpx_kwargs)
_REST_SESSION = requests.Session()
_REST_SESSION.trust_env = False

ETSY_REST_SERVER_URL = os.getenv("ETSY_REST_SERVER_URL", "http://127.0.0.1:8001").rstrip("/")
SKILL_RESOURCE_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/skills/{SKILL_ID}"

if _VERTEX_PROXY:
    print(f"🔐 Vertex 网络：经代理 {_VERTEX_PROXY}")
else:
    print("🔐 Vertex 网络：直连")
print(f"🌐 Etsy REST 节点：{ETSY_REST_SERVER_URL}")


class VertexGemini(Gemini):
    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION,
            http_options={
                "httpx_async_client": _VERTEX_HTTPX_ASYNC,
                "httpx_client": _VERTEX_HTTPX_SYNC,
                "client_args": {
                    "trust_env": False,
                    **({"proxy": _VERTEX_PROXY} if _VERTEX_PROXY else {}),
                },
            },
        )


vertex_model = VertexGemini(model="gemini-2.5-pro")


def _resolve_skill_dir() -> Path:
    candidates = [
        Path(__file__).parent / "skills" / SKILL_ID,
        Path(__file__).resolve().parent.parent / "skills" / SKILL_ID,
    ]
    for path in candidates:
        if (path / "SKILL.md").is_file():
            return path
    raise FileNotFoundError(f"未找到 skills/{SKILL_ID}/SKILL.md")


def _envelope_from_response(response: requests.Response, tool: str) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {
            "ok": False,
            "tool": tool,
            "data": {},
            "error": {
                "code": "INVALID_RESPONSE",
                "message": f"非 JSON 响应 HTTP {response.status_code}",
                "retryable": True,
            },
            "meta": {"status_code": response.status_code},
        }
    if response.ok and isinstance(body, dict) and "ok" in body:
        return body
    if isinstance(body, dict) and isinstance(body.get("detail"), dict) and "ok" in body["detail"]:
        return body["detail"]
    return {
        "ok": False,
        "tool": tool,
        "data": {},
        "error": {
            "code": "HTTP_ERROR",
            "message": str(body)[:500],
            "retryable": response.status_code >= 500,
        },
        "meta": {"status_code": response.status_code, "url": response.url},
    }


def _network_error_envelope(tool: str, exc: Exception, url: str) -> dict:
    return {
        "ok": False,
        "tool": tool,
        "data": {},
        "error": {"code": "NETWORK_ERROR", "message": str(exc), "retryable": True},
        "meta": {"url": url},
    }


def etsy_check_credentials_from_node(probe: bool = True, probe_listing_id: str = "786582119") -> dict[str, Any]:
    """REST：检查本机节点上的 Etsy API 凭证。"""
    tool = "etsy_check_credentials"
    url = f"{ETSY_REST_SERVER_URL}/api/etsy_check_credentials"
    try:
        resp = _REST_SESSION.get(
            url,
            params={"probe": probe, "probe_listing_id": probe_listing_id},
            timeout=60,
        )
        return _envelope_from_response(resp, tool)
    except requests.RequestException as exc:
        return _network_error_envelope(tool, exc, url)


def etsy_fetch_listing_reviews_from_node(
    listing_id: str,
    listing_url: Optional[str] = None,
    limit: int = 25,
    max_pages: int = 3,
    min_created: Optional[int] = None,
    max_created: Optional[int] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """REST：拉取 Etsy listing 评论。"""
    tool = "etsy_fetch_listing_reviews"
    url = f"{ETSY_REST_SERVER_URL}/api/etsy_fetch_listing_reviews"
    payload = {
        "listing_id": listing_id,
        "listing_url": listing_url,
        "limit": limit,
        "max_pages": max_pages,
        "min_created": min_created,
        "max_created": max_created,
        "dry_run": dry_run,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        resp = _REST_SESSION.post(url, json=payload, timeout=180)
        return _envelope_from_response(resp, tool)
    except requests.RequestException as exc:
        return _network_error_envelope(tool, exc, url)


def etsy_write_reviews_excel_from_node(
    listing_id: str,
    reviews: list[dict[str, Any]],
    listing_url: Optional[str] = None,
    excel_path: Optional[str] = None,
    sheet_name: str = "评论明细",
    deduplicate: bool = True,
) -> dict[str, Any]:
    """REST：将评论写入本机 Excel。"""
    tool = "etsy_write_reviews_excel"
    url = f"{ETSY_REST_SERVER_URL}/api/etsy_write_reviews_excel"
    payload = {
        "listing_id": listing_id,
        "reviews": reviews,
        "listing_url": listing_url,
        "excel_path": excel_path,
        "sheet_name": sheet_name,
        "deduplicate": deduplicate,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        resp = _REST_SESSION.post(url, json=payload, timeout=120)
        return _envelope_from_response(resp, tool)
    except requests.RequestException as exc:
        return _network_error_envelope(tool, exc, url)


def etsy_fetch_and_export_reviews_from_node(
    listing_url_or_id: str,
    limit: int = 25,
    max_pages: int = 3,
    min_created: Optional[int] = None,
    max_created: Optional[int] = None,
    excel_path: Optional[str] = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """REST：拉取评论并导出到本机 Excel（推荐）。"""
    tool = "etsy_fetch_and_export_reviews"
    url = f"{ETSY_REST_SERVER_URL}/api/etsy_fetch_and_export_reviews"
    payload = {
        "listing_url_or_id": listing_url_or_id,
        "limit": limit,
        "max_pages": max_pages,
        "min_created": min_created,
        "max_created": max_created,
        "excel_path": excel_path,
        "dry_run": dry_run,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        resp = _REST_SESSION.post(url, json=payload, timeout=300)
        return _envelope_from_response(resp, tool)
    except requests.RequestException as exc:
        return _network_error_envelope(tool, exc, url)


_rest_tools = [
    etsy_check_credentials_from_node,
    etsy_fetch_listing_reviews_from_node,
    etsy_write_reviews_excel_from_node,
    etsy_fetch_and_export_reviews_from_node,
]

etsy_skill = load_skill_from_dir(_resolve_skill_dir())
gcp_skill_registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)

skill_toolset = SkillToolset(
    skills=[etsy_skill],
    registry=gcp_skill_registry,
    additional_tools=[*_rest_tools, PreloadMemoryTool()],
)


async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


system_instruction = f"""
你是 Etsy 商品评论数据采集 Agent，通过 **REST** 调用本地节点（{ETSY_REST_SERVER_URL}）。

【Skill 工作流 — 必须先加载】
处理 Etsy 评论、listing、Excel 导出时：
1. 调用 `load_skill`，skill_name 设为 `{SKILL_ID}`
2. 严格按技能 instructions 执行
3. 使用 REST 工具（*_from_node）完成实际操作

【工具返回 — P0 envelope】先检查 ok，再读 data 或 error.code。

【执行要点】
1. 建议先 etsy_check_credentials_from_node(probe=true)
2. 多数场景用 etsy_fetch_and_export_reviews_from_node 一步完成
3. excel_path 须在 Desktop 或 ~/Documents/EtsyData
4. HTTP 404 常见原因：Cloudflare Tunnel 未启动或 ETSY_REST_SERVER_URL 过期；非 Etsy 凭证问题

GCP Skill：{SKILL_RESOURCE_NAME}
任务结束汇报条数、Excel 路径或失败原因。
"""

print("🛍️ 正在初始化 Etsy REST + Skill Agent...")

root_agent = Agent(
    name="Etsy_Cloud_REST_Agent",
    model=vertex_model,
    description="Skill 编排 + REST 调用本地 Etsy 节点（P0 envelope）",
    instruction=system_instruction,
    tools=[skill_toolset],
    after_agent_callback=generate_memories_callback,
)

etsy_cloud_agent = root_agent
