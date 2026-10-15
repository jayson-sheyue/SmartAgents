# -*- coding: utf-8 -*-
"""Unified Etsy agent builder — Cloud Run MCP + Skill (sync image gen)."""

from __future__ import annotations

import os
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import Agent
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset

from domains.etsy.registry import AGENT_NAME, MCP_TOOL_NAMES, SKILL_IDS, STANDALONE_NAME
from domains.shared.mcp_guard import (
    build_check_mcp_tool,
    expert_handback_instruction,
    make_mcp_fail_fast_after_tool,
    make_mcp_guard_before_model,
    make_mcp_on_tool_error,
    mcp_fail_fast_instruction,
)
from domains.shared.runtime_mode import normalize_mcp_url
from domains.shared.skill_resolver import resolve_skill_dir
from smart_agents.personas import ETSY_EXPERT_PERSONA
from smart_agents.vertex import LOCATION, PROJECT_ID, vertex_model

DISPATCHER_NAME = "SmartAgents_Dispatcher"
_CHECK_TOOL = "check_etsy_mcp"


def _require_mcp_url() -> str:
    url = (os.getenv("ETSY_MCP_SERVER_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "未设置 ETSY_MCP_SERVER_URL。请先部署 Cloud Run MCP："
            " ./scripts/deploy_etsy_mcp_cloudrun.sh"
        )
    if "127.0.0.1" in url or "localhost" in url:
        raise RuntimeError(
            f"ETSY_MCP_SERVER_URL 不能是本地地址（当前: {url}）。"
            "请改为 Cloud Run URL，例如 https://etsy-mcp-xxx.run.app/mcp"
        )
    return normalize_mcp_url(url)


def _mcp_server_url() -> str:
    return _require_mcp_url()


def _mcp_toolset(mcp_url: str) -> McpToolset:
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=mcp_url,
            timeout=60.0,
            sse_read_timeout=600.0,
        ),
        tool_filter=list(MCP_TOOL_NAMES),
    )


def _skill_toolset() -> SkillToolset:
    skills = [load_skill_from_dir(resolve_skill_dir("etsy", sid)) for sid in SKILL_IDS]
    registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)
    return SkillToolset(skills=skills, registry=registry)


def _mcp_instruction(mcp_url: str, *, standalone: bool) -> str:
    handback = ""
    if not standalone:
        handback = "\n" + expert_handback_instruction(DISPATCHER_NAME)
    return f"""
{ETSY_EXPERT_PERSONA}

【技术职责】
通过 **Cloud Run MCP**（{mcp_url}）完成 Etsy 评论与同步生图。保持「E姐」口吻。
你可拉评论/导出/生图；**不能**自己对表格做 pandas 统计或画图——那是小智的 Code Exec。

【Skill 工作流 — 必须先 load_skill】
1. 评论 → `load_skill`，skill_name=`{SKILL_IDS[0]}` → 优先 `etsy_fetch_listing_reviews`（JSON）；需要表格再 `etsy_fetch_and_export_reviews`（GCS）
2. 换场景出图 / 预设 → `load_skill`，skill_name=`{SKILL_IDS[1]}` → **同步** `etsy_generate_listing_scene_variants`（可能 1–3 分钟，返回 GCS URI）
3. 用户要「基于评论表/附件写调研报告 / 统计 / 画图」→ **不要硬撑**，交回 `{DISPATCHER_NAME}`

【P0 envelope】先检查 ok，再读 data 或 error.code。

{mcp_fail_fast_instruction(domain_label="Etsy", check_tool_name=_CHECK_TOOL)}
{handback}
""".strip()


async def _memory_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


def build_etsy_agent(
    *,
    model: Optional[Gemini] = None,
    mcp_server_url: str | None = None,
    standalone: bool = False,
) -> Agent:
    """Build Etsy specialist (MCP + dual Skill)."""
    model = model or vertex_model
    name = STANDALONE_NAME if standalone else AGENT_NAME
    mcp_url = normalize_mcp_url(mcp_server_url or _mcp_server_url())

    tools: list = [
        build_check_mcp_tool(mcp_url=mcp_url, label="Etsy", tool_name=_CHECK_TOOL),
        _mcp_toolset(mcp_url),
        _skill_toolset(),
    ]
    if standalone:
        tools.append(PreloadMemoryTool())

    return Agent(
        name=name,
        model=model,
        description="Etsy 专家 E姐：评论 + 同步生图（Cloud Run MCP + GCS）",
        instruction=_mcp_instruction(mcp_url, standalone=standalone),
        tools=tools,
        before_model_callback=make_mcp_guard_before_model(
            mcp_url=mcp_url,
            label="Etsy",
            expert_name="E姐",
            domain_label="Etsy",
            domain_request_hints=(
                "etsy",
                "listing",
                "评论",
                "review",
                "生图",
                "场景",
                "预设",
                "scene",
                "etsy.com",
            ),
            other_domain_hints=(
                "b站",
                "b 站",
                "bilibili",
                "阿b",
                "阿 b",
                "热门",
                "选品",
                "排行榜",
                "飞书",
                "feishu",
                "小飞",
                "日历",
                "云文档",
                "调研报告",
                "数据分析",
                "统计分析",
                "画图",
                "可视化",
                "pandas",
                "run_code",
            ),
        ),
        after_tool_callback=make_mcp_fail_fast_after_tool(
            mcp_url=mcp_url, label="Etsy"
        ),
        on_tool_error_callback=make_mcp_on_tool_error(
            mcp_url=mcp_url, label="Etsy"
        ),
        after_agent_callback=_memory_callback if standalone else None,
        disallow_transfer_to_peers=not standalone,
    )


build_etsy_mcp_sub_agent = build_etsy_agent
