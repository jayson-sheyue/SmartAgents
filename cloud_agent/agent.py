# -*- coding: utf-8 -*-
"""
cloud_agent/agent.py — 云端 REST Agent（ADK 部署入口）

【本 Agent 做什么？】
  运行在 GCP Agent Engine（或本地 adk run），通过 HTTP 调用你电脑上的 REST 节点：
    NGROK_URL → local_node/server.py :8001 → rpa_tools.py → main.py

【P0 升级说明】
  三个工具函数现在：
    1. 支持新参数（excel_path、dry_run、write_mode 等）
    2. 返回完整 envelope { ok, tool, data, error, meta }，不再返回裸 list/字符串

【本地 adk run 前置条件】
  终端 1: python local_node/server.py
  终端 2: ngrok http 8001  （或 .env 设 NGROK_URL=http://127.0.0.1:8001 免 ngrok）
  .env:   NGROK_URL=https://你的-ngrok域名.ngrok-free.dev

【部署】
  adk deploy agent_engine cloud_agent \\
    --project=$GCP_PROJECT_ID --region=$GCP_LOCATION \\
    --display_name="Bilibili-Cloud-Agent" \\
    --agent_engine_id=$REST_AGENT_ENGINE_ID
"""

from __future__ import annotations

import os
from functools import cached_property
from typing import Literal, Optional

import httpx
import requests
from dotenv import load_dotenv
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import Agent
from google.adk.models import Gemini
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import Client

# =============================================================================
# 0. Vertex AI 与 ngrok 配置
# =============================================================================
load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")

if not PROJECT_ID:
    raise RuntimeError("请在 .env 中设置 GCP_PROJECT_ID（可复制 .env.example 为 .env）")

# -----------------------------------------------------------------------------
# 网络：Vertex（可走 Clash） vs 本地 REST（必须直连）
# -----------------------------------------------------------------------------
# 国内常见两种失败：
#   1) 全局 HTTP_PROXY → httpx 自动走代理 → TLS/ConnectError（堆栈含 http_proxy.py）
#   2) 清掉代理 → 无法直连 googleapis → ConnectError（堆栈含 connect_tcp）
# 做法：仅对 Vertex 使用 VERTEX_HTTP_PROXY（或启动前 shell 里的 HTTPS_PROXY），
#       清掉全局代理变量；本地 127.0.0.1 REST 用 trust_env=False 直连。


def _pick_vertex_proxy_url() -> Optional[str]:
    """Vertex / Google API 专用代理；优先 VERTEX_HTTP_PROXY，其次启动前的 HTTPS_PROXY。"""
    for key in ("VERTEX_HTTP_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return None


def _isolate_global_proxy_env(vertex_proxy: Optional[str]) -> None:
    """去掉全局代理 env，避免 httpx/requests 自动套用导致 TLS 异常。"""
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
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

# 调本地 REST 节点不走代理（即使 NGROK_URL 是 ngrok 域名也由调用方网络决定）
_REST_SESSION = requests.Session()
_REST_SESSION.trust_env = False

if _VERTEX_PROXY:
    print(f"🔐 Vertex 网络：经代理 {_VERTEX_PROXY}")
else:
    print("🔐 Vertex 网络：直连（未配置 VERTEX_HTTP_PROXY / HTTPS_PROXY）")

NGROK_URL = os.getenv("NGROK_URL", "http://127.0.0.1:8001").rstrip("/")
if "NGROK_URL" not in os.environ:
    print("ℹ️ 未在 .env 配置 NGROK_URL，本地默认 http://127.0.0.1:8001；云端联调请配置 ngrok 地址。")

# ngrok 免费版需此头，否则可能返回 HTML 拦截页而非 JSON
_REST_HEADERS = {"ngrok-skip-browser-warning": "true"}

print("🔐 正在初始化基于 Vertex AI 的底层 Client...")


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
                "client_args": {"trust_env": False, **({"proxy": _VERTEX_PROXY} if _VERTEX_PROXY else {})},
            },
        )


vertex_model = VertexGemini(model="gemini-2.5-pro")


# =============================================================================
# 1. REST 辅助：解析 HTTP 响应为 envelope
# =============================================================================

def _envelope_from_response(response: requests.Response, tool: str) -> dict:
    """
    把 local_node REST API 的 HTTP 响应转成 envelope dict。

    成功 200：body 本身就是 envelope。
    失败 4xx：FastAPI 通常返回 {"detail": envelope}。
    网络/解析失败：构造本地 NETWORK_ERROR envelope。
    """
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
        "meta": {"status_code": response.status_code},
    }


def _network_error_envelope(tool: str, exc: Exception, url: str) -> dict:
    return {
        "ok": False,
        "tool": tool,
        "data": {},
        "error": {"code": "NETWORK_ERROR", "message": str(exc), "retryable": True},
        "meta": {"url": url},
    }


# =============================================================================
# 2. 三个 REST 工具（Agent 可见；名称带 _from_node 以区分 MCP 直连）
# =============================================================================

def get_up_list_from_node(
    excel_path: Optional[str] = None,
    sheet_name: str = "Sheet1",
    name_column: Optional[str] = None,
    limit: Optional[int] = None,
) -> dict:
    """调用本地 REST 节点：读取 Excel 中的 UP 主名单（P0 envelope）。

    Args:
        excel_path: Excel 路径，默认桌面 Up主名称.xlsx；须在 Desktop 或 ~/Documents/BilibiliRPA
        sheet_name: 工作表名，默认 Sheet1
        name_column: UP 主列名，省略则第一列
        limit: 最多返回条数

    Returns:
        envelope；成功时 data.up_names 为名单，务必先检查 ok 是否为 true
    """
    tool = "get_up_list"
    print("🌐 [REST] get_up_list ...")
    params = {
        "excel_path": excel_path,
        "sheet_name": sheet_name,
        "name_column": name_column,
        "limit": limit,
    }
    params = {k: v for k, v in params.items() if v is not None}
    url = f"{NGROK_URL}/api/get_up_list"
    try:
        resp = _REST_SESSION.get(url, params=params, headers=_REST_HEADERS, timeout=30)
        return _envelope_from_response(resp, tool)
    except requests.RequestException as exc:
        return _network_error_envelope(tool, exc, url)


def fetch_fans_data_from_node(up_name: str, dry_run: bool = False) -> dict:
    """调用本地 REST 节点：抓取 UP 主粉丝数（P0 envelope）。

    Args:
        up_name: UP 主名称
        dry_run: True 时只检查登录态，不打开浏览器

    Returns:
        envelope；成功时用 data.fans_count_display 作为 write 的 fans_count
    """
    tool = "fetch_fans_data"
    print(f"🌐 [REST] fetch_fans_data up_name={up_name} dry_run={dry_run}")
    url = f"{NGROK_URL}/api/fetch_fans_data"
    try:
        resp = _REST_SESSION.post(
            url,
            json={"up_name": up_name, "dry_run": dry_run},
            headers=_REST_HEADERS,
            timeout=180,
        )
        return _envelope_from_response(resp, tool)
    except requests.RequestException as exc:
        return _network_error_envelope(tool, exc, url)


def write_excel_to_node(
    up_name: str,
    fans_count: str,
    excel_path: Optional[str] = None,
    sheet_name: str = "Sheet1",
    target_column: str = "粉丝数",
    write_mode: Literal["update", "append_if_missing"] = "update",
) -> dict:
    """调用本地 REST 节点：写回 Excel（P0 envelope）。

    Args:
        up_name: UP 主名称
        fans_count: 粉丝数，建议使用 fetch 返回的 fans_count_display
        excel_path: 目标 Excel，默认桌面表
        sheet_name: 工作表
        target_column: 写入列，默认「粉丝数」
        write_mode: update 仅更新已有行；append_if_missing 可追加新行
    """
    tool = "write_excel"
    print(f"🌐 [REST] write_excel {up_name} -> {fans_count}")
    url = f"{NGROK_URL}/api/write_excel"
    payload = {
        "up_name": up_name,
        "fans_count": fans_count,
        "excel_path": excel_path,
        "sheet_name": sheet_name,
        "target_column": target_column,
        "write_mode": write_mode,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    try:
        resp = _REST_SESSION.post(url, json=payload, headers=_REST_HEADERS, timeout=30)
        return _envelope_from_response(resp, tool)
    except requests.RequestException as exc:
        return _network_error_envelope(tool, exc, url)


# =============================================================================
# 3. Agent 定义
# =============================================================================

async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


adk_tools = [
    get_up_list_from_node,
    fetch_fans_data_from_node,
    write_excel_to_node,
    PreloadMemoryTool(),
]

system_instruction = f"""
你是 B 站 UP 主数据分析 RPA Agent，运行在云端，通过 REST 调用本地节点（{NGROK_URL}）。

【工具返回格式 — envelope】
每个工具返回 JSON，必须先检查 ok：
  - ok=true：读 data 字段
  - ok=false：读 error.code 和 error.message，按 code 提示用户

常见 error.code：FILE_NOT_FOUND、PATH_NOT_ALLOWED、LOGIN_STATE_MISSING、FETCH_FAILED、UP_NOT_FOUND

【工作流】
1. 批量任务：get_up_list_from_node → 对每个 UP 依次 fetch_fans_data_from_node → write_excel_to_node
2. 单 UP 查询：可跳过 get_up_list，直接 fetch
3. 用户说「只查不写」：不要调用 write_excel_to_node
4. 大规模抓取前可先 fetch_fans_data_from_node(..., dry_run=true) 检查登录态
5. fetch 成功后，write 时使用 data.fans_count_display 作为 fans_count
6. 用户指定 Excel 时在 get_up_list / write 中传 excel_path（须在 Desktop 或 Documents/BilibiliRPA）
7. 表中无该 UP 但需写入时，write_mode 用 append_if_missing

遵守 Memory Bank 中的用户偏好。任务结束给出成功/失败汇总。
"""

print("☁️ 正在初始化 REST Agent（P0 envelope）...")

root_agent = Agent(
    name="Bilibili_Cloud_ADK_Agent",
    model=vertex_model,
    description="通过 REST API（P0 envelope）调用本地 Bilibili RPA 节点",
    instruction=system_instruction,
    tools=adk_tools,
    after_agent_callback=generate_memories_callback,
)

cloud_agent = root_agent

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        pid = os.getenv("GCP_PROJECT_ID", "<GCP_PROJECT_ID>")
        loc = os.getenv("GCP_LOCATION", "us-central1")
        eid = os.getenv("REST_AGENT_ENGINE_ID", "<REST_AGENT_ENGINE_ID>")
        print("🚀 部署命令:")
        print(
            f"  adk deploy agent_engine cloud_agent "
            f"--project={pid} --region={loc} "
            f'--display_name="Bilibili-Cloud-Agent" '
            f"--agent_engine_id={eid}"
        )
    else:
        print("💡 本地: adk run cloud_agent")
        print("💡 需先: python local_node/server.py + ngrok http 8001（或 NGROK_URL=http://127.0.0.1:8001）")
