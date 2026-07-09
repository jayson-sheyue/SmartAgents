# -*- coding: utf-8 -*-
"""
etsy_agent/agent.py — Etsy 评论 Agent（ADK 本地 / 部署入口）

【调用链】
  adk run etsy_agent
    → load_skill('etsy-review') + 进程内 Etsy 工具
    → etsy_tools.py → Etsy Open API v3

【本地 adk run】
  ./scripts/run_adk_etsy_agent.sh
  前置：.env 配置 ETSY_KEYSTRING + ETSY_SHARED_SECRET、GCP_PROJECT_ID（Vertex）
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import Agent
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset
from google.genai import Client

from etsy_agent.etsy_tools import (
    tool_etsy_check_credentials,
    tool_etsy_fetch_and_export_reviews,
    tool_etsy_fetch_listing_reviews,
    tool_etsy_write_reviews_excel,
)

# =============================================================================
# 0. Vertex AI 与 Skill 配置
# =============================================================================
load_dotenv()

PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
SKILL_ID = "etsy-review"

if not PROJECT_ID:
    raise RuntimeError("请在 .env 中设置 GCP_PROJECT_ID（可复制 .env.example 为 .env）")


def _pick_vertex_proxy_url() -> Optional[str]:
    for key in (
        "VERTEX_HTTP_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return None


def _isolate_global_proxy_env(vertex_proxy: Optional[str]) -> None:
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

if _VERTEX_PROXY:
    print(f"🔐 Vertex 网络：经代理 {_VERTEX_PROXY}")
else:
    print("🔐 Vertex 网络：直连")

SKILL_RESOURCE_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/skills/{SKILL_ID}"


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
    raise FileNotFoundError(
        f"未找到 Skill 目录 {SKILL_ID}，请确认 skills/{SKILL_ID}/SKILL.md 存在"
    )


# =============================================================================
# 1. Etsy 工具（执行层 — 进程内直连，P0 envelope）
# =============================================================================


def etsy_check_credentials(probe: bool = True) -> dict[str, Any]:
    """检查 Etsy API 凭证；probe 为 True 时向 Etsy 发真实请求验证 Key。

    Args:
        probe: 是否执行真实 API 探测（默认 True）。

    Returns:
        envelope，成功时 data 含 configured、api_verified、masked_key。
    """
    return tool_etsy_check_credentials(probe=probe)


def etsy_fetch_listing_reviews(
    listing_id: str,
    listing_url: str | None = None,
    limit: int = 25,
    max_pages: int = 3,
    min_created: int | None = None,
    max_created: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """分页拉取指定 Etsy listing 的评论。

    Args:
        listing_id: 商品数字 ID。
        listing_url: 可选商品页 URL。
        limit: 每页条数（1–100，默认 25）。
        max_pages: 最多翻页数（默认 3）。
        min_created: 可选，最早评论 Unix 时间戳。
        max_created: 可选，最晚评论 Unix 时间戳。
        dry_run: 为 True 时不请求 API，仅做参数校验。

    Returns:
        envelope，成功时 data.reviews 为评论列表，data.count 为条数。
    """
    return tool_etsy_fetch_listing_reviews(
        listing_id,
        listing_url=listing_url,
        limit=limit,
        max_pages=max_pages,
        min_created=min_created,
        max_created=max_created,
        dry_run=dry_run,
    )


def etsy_write_reviews_excel(
    listing_id: str,
    reviews: list[dict[str, Any]],
    listing_url: str | None = None,
    excel_path: str | None = None,
    sheet_name: str = "评论明细",
    deduplicate: bool = True,
) -> dict[str, Any]:
    """将评论列表写入 Excel（支持去重追加）。

    Args:
        listing_id: 商品数字 ID。
        reviews: 评论字典列表（通常来自 etsy_fetch_listing_reviews）。
        listing_url: 可选商品页 URL。
        excel_path: 可选输出路径（须在 Desktop 或 ~/Documents/EtsyData）。
        sheet_name: 工作表名（默认「评论明细」）。
        deduplicate: 是否按 review_id 去重（默认 True）。

    Returns:
        envelope，成功时 data.excel_path、data.total_rows。
    """
    return tool_etsy_write_reviews_excel(
        listing_id,
        reviews,
        listing_url=listing_url,
        excel_path=excel_path,
        sheet_name=sheet_name,
        deduplicate=deduplicate,
    )


def etsy_fetch_and_export_reviews(
    listing_url_or_id: str,
    limit: int = 25,
    max_pages: int = 3,
    min_created: int | None = None,
    max_created: int | None = None,
    excel_path: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """一步到位：解析 listing → 拉取评论 → 写入 Excel。

    Args:
        listing_url_or_id: Etsy 商品 URL 或数字 listing_id。
        limit: 每页条数（默认 25）。
        max_pages: 最多翻页数（默认 3）。
        min_created: 可选最早评论 Unix 时间戳。
        max_created: 可选最晚评论 Unix 时间戳。
        excel_path: 可选 Excel 路径。
        dry_run: 为 True 时不拉取、不写文件。

    Returns:
        envelope，成功时 data.fetch 与 data.write 含条数与路径。
    """
    return tool_etsy_fetch_and_export_reviews(
        listing_url_or_id,
        limit=limit,
        max_pages=max_pages,
        min_created=min_created,
        max_created=max_created,
        excel_path=excel_path,
        dry_run=dry_run,
    )


_etsy_tools = [
    etsy_check_credentials,
    etsy_fetch_listing_reviews,
    etsy_write_reviews_excel,
    etsy_fetch_and_export_reviews,
]

# =============================================================================
# 2. Skill（编排层）+ 本地 Skill 包
# =============================================================================
etsy_skill = load_skill_from_dir(_resolve_skill_dir())
gcp_skill_registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)

skill_toolset = SkillToolset(
    skills=[etsy_skill],
    registry=gcp_skill_registry,
    additional_tools=[*_etsy_tools, PreloadMemoryTool()],
)

# =============================================================================
# 3. Agent 定义
# =============================================================================


async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


system_instruction = f"""
你是 Etsy 商品评论数据采集 Agent，通过**进程内工具**调用 Etsy Open API v3。

【Skill 工作流 — 必须先加载】
处理 Etsy 评论、商品链接、listing_id、Excel 导出相关任务时：
1. 调用 `load_skill`，skill_name 设为 `{SKILL_ID}`
2. 严格按技能 instructions 执行
3. 使用 Etsy 工具完成实际操作

【工具返回格式 — P0 envelope】
每个工具返回 JSON，必须先检查 ok：
  - ok=true：读 data 字段
  - ok=false：读 error.code 和 error.message

常见 error.code：ETSY_API_KEY_MISSING、ETSY_API_KEY_PENDING、ETSY_NO_REVIEWS_FOUND、
INVALID_INPUT、PATH_NOT_ALLOWED、ETSY_NETWORK_ERROR

【执行要点】
1. 任务开始前建议 etsy_check_credentials(probe=true)
2. 用户提供 URL 或 listing_id 时，优先 etsy_fetch_and_export_reviews 一步完成
3. 仅需预览数据、不写 Excel：etsy_fetch_listing_reviews 或 dry_run=true
4. excel_path 须在 Desktop 或 ~/Documents/EtsyData；默认 ~/Documents/EtsyData/etsy_reviews.xlsx
5. Personal App 限流约 5 QPS，max_pages 默认 3，用户要求更多时再调高

GCP Skill 资源（可选上传）：{SKILL_RESOURCE_NAME}
任务结束给出成功/失败汇总与 Excel 路径。
"""

print("🛍️ 正在初始化 Etsy Skill Agent（进程内工具 + P0 envelope）...")

root_agent = Agent(
    name="Etsy_Review_Agent",
    model=vertex_model,
    description="Skill 编排 + 进程内 Etsy 评论 API（P0 envelope）",
    instruction=system_instruction,
    tools=[skill_toolset],
    after_agent_callback=generate_memories_callback,
)

etsy_agent = root_agent

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        pid = os.getenv("GCP_PROJECT_ID", "<GCP_PROJECT_ID>")
        loc = os.getenv("GCP_LOCATION", "us-central1")
        print("🚀 部署命令（待配置 ETSY_AGENT_ENGINE_ID）:")
        print(
            f"  adk deploy agent_engine etsy_agent "
            f"--project={pid} --region={loc} "
            f'--display_name="Etsy Review Agent" '
            f"--agent_engine_id=<ETSY_AGENT_ENGINE_ID>"
        )
    else:
        print("💡 本地: ./scripts/run_adk_etsy_agent.sh")
