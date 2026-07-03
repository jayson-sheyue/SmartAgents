# -*- coding: utf-8 -*-
"""
cloud_agent_mcp/agent.py — 云端 MCP + Skill Agent（ADK 部署入口）

【调用链】
  Playground / adk run
    → load_skill('bilibili-rpa') + MCP tools
    → MCP_SERVER_URL（ngrok :8002 或本机 127.0.0.1:8002）
    → mcp_server/bilibili_mcp.py → rpa_tools.py → main.py

【与 cloud_agent（REST）的区别】
  - 执行层：McpToolset 直连 MCP 协议（非 HTTP REST 包装函数）
  - 编排层：SkillToolset + GCP Skill Registry + 本地 skills/ 兜底
  - MCP 工具名：get_up_list / fetch_fans_data / write_excel（无 _from_node 后缀）

【本地 adk run】
  终端 1: python mcp_server/bilibili_mcp.py --http
  终端 2: MCP_SERVER_URL=http://127.0.0.1:8002/mcp ./scripts/run_adk_cloud_agent_mcp.sh
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import Agent
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import Client

# =============================================================================
# 0. Vertex AI、MCP、Skill 配置
# =============================================================================
load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
SKILL_ID = "bilibili-rpa"

if not PROJECT_ID:
    raise RuntimeError("请在 .env 中设置 GCP_PROJECT_ID（可复制 .env.example 为 .env）")


def _pick_vertex_proxy_url() -> Optional[str]:
    for key in (
        "VERTEX_HTTP_PROXY", "HTTPS_PROXY", "https_proxy",
        "HTTP_PROXY", "http_proxy",
    ):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return None


def _isolate_global_proxy_env(vertex_proxy: Optional[str]) -> None:
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
        "ALL_PROXY", "all_proxy",
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

MCP_SERVER_REGISTRY_ID = os.getenv("MCP_SERVER_REGISTRY_ID", "")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8002/mcp").rstrip("/")
if not MCP_SERVER_URL.endswith("/mcp"):
    MCP_SERVER_URL = f"{MCP_SERVER_URL.rstrip('/')}/mcp"
if "MCP_SERVER_URL" not in os.environ:
    print("ℹ️ 未在 .env 配置 MCP_SERVER_URL，本地默认 http://127.0.0.1:8002/mcp")

SKILL_RESOURCE_NAME = (
    f"projects/{PROJECT_ID}/locations/{LOCATION}/skills/{SKILL_ID}"
)

if _VERTEX_PROXY:
    print(f"🔐 Vertex 网络：经代理 {_VERTEX_PROXY}")
else:
    print("🔐 Vertex 网络：直连")
print(f"🔌 MCP 端点：{MCP_SERVER_URL}")


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
    """部署包内 skills/ 优先，本地开发回退到项目根 skills/。"""
    candidates = [
        Path(__file__).parent / "skills" / SKILL_ID,
        Path(__file__).resolve().parent.parent / "skills" / SKILL_ID,
    ]
    for path in candidates:
        if (path / "SKILL.md").is_file():
            return path
    raise FileNotFoundError(
        f"未找到 Skill 目录 {SKILL_ID}，请确认 skills/{SKILL_ID}/SKILL.md 存在"
    )


# =============================================================================
# 1. MCP 工具（执行层 — P0 envelope 由 mcp_server 返回）
# =============================================================================
bilibili_mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_SERVER_URL,
        headers={"ngrok-skip-browser-warning": "true"},
        timeout=30.0,
        sse_read_timeout=180.0,
    ),
    tool_filter=["get_up_list", "fetch_fans_data", "write_excel"],
)

# =============================================================================
# 2. Skill Registry（编排层）+ 本地 Skill 包（部署兜底）
# =============================================================================
bilibili_skill = load_skill_from_dir(_resolve_skill_dir())
gcp_skill_registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)

skill_toolset = SkillToolset(
    skills=[bilibili_skill],
    registry=gcp_skill_registry,
    additional_tools=[bilibili_mcp_toolset, PreloadMemoryTool()],
)

# =============================================================================
# 3. Agent 定义
# =============================================================================


async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


system_instruction = f"""
你是 B 站 UP 主数据分析 RPA Agent，通过 **MCP** 调用本地节点（{MCP_SERVER_URL}）。

【Skill 工作流 — 必须先加载】
处理 UP 主 / Excel / 粉丝数相关任务时：
1. 调用 `load_skill`，skill_name 设为 `{SKILL_ID}`
2. 严格按技能 instructions 执行
3. 使用 MCP 工具完成实际操作（get_up_list / fetch_fans_data / write_excel）

【工具返回格式 — P0 envelope】
每个 MCP 工具返回 JSON，必须先检查 ok：
  - ok=true：读 data 字段
  - ok=false：读 error.code 和 error.message

常见 error.code：FILE_NOT_FOUND、PATH_NOT_ALLOWED、LOGIN_STATE_MISSING、FETCH_FAILED、UP_NOT_FOUND

【执行要点】
1. 批量：get_up_list → 对每个 UP 依次 fetch_fans_data → write_excel
2. 单 UP：可跳过 get_up_list，直接 fetch_fans_data
3. 用户说「只查不写」：不要调用 write_excel
4. 大规模前可先 fetch_fans_data(..., dry_run=true) 检查登录态
5. fetch 成功后，write 使用 data.fans_count_display 作为 fans_count
6. excel_path 须在 Desktop 或 ~/Documents/BilibiliRPA
7. 表中无该 UP 需写入时，write_mode 用 append_if_missing

GCP Skill 资源：{SKILL_RESOURCE_NAME}
遵守 Memory Bank 中的用户偏好。任务结束给出成功/失败汇总。
"""

print("☁️ 正在初始化 MCP + Skill Agent（P0 envelope）...")

root_agent = Agent(
    name="Bilibili_Cloud_MCP_Agent",
    model=vertex_model,
    description="Skill 编排 + MCP 调用本地 Bilibili RPA（P0 envelope）",
    instruction=system_instruction,
    tools=[skill_toolset],
    after_agent_callback=generate_memories_callback,
)

cloud_agent_mcp = root_agent

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        pid = os.getenv("GCP_PROJECT_ID", "<GCP_PROJECT_ID>")
        loc = os.getenv("GCP_LOCATION", "us-central1")
        eid = os.getenv("MCP_AGENT_ENGINE_ID", "<MCP_AGENT_ENGINE_ID>")
        print("🚀 部署命令:")
        print(
            f"  adk deploy agent_engine cloud_agent_mcp "
            f"--project={pid} --region={loc} "
            f'--display_name="Bilibili Cloud MCP Agent" '
            f"--agent_engine_id={eid}"
        )
    else:
        print("💡 本地: ./scripts/run_adk_cloud_agent_mcp.sh")
        print("💡 需先: python mcp_server/bilibili_mcp.py --http")
