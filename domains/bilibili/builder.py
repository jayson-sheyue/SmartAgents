# -*- coding: utf-8 -*-
"""Unified Bilibili agent builder — Cloud Run MCP + Skill (热门 API only)."""

from __future__ import annotations

import os
from typing import Optional

from google.adk.agents.llm_agent import Agent
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset

from domains.bilibili.registry import AGENT_NAME, MCP_TOOL_NAMES, SKILL_IDS, STANDALONE_NAME
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
from smart_agents.callbacks import generate_memories_callback
from smart_agents.personas import BILIBILI_EXPERT_PERSONA
from smart_agents.vertex import LOCATION, PROJECT_ID, vertex_model

DISPATCHER_NAME = "SmartAgents_Dispatcher"
TREND_SKILL_ID = "bilibili-trend"
_CHECK_TOOL = "check_bilibili_mcp"


def _require_mcp_url() -> str:
    url = (os.getenv("BILIBILI_MCP_SERVER_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "未设置 BILIBILI_MCP_SERVER_URL。请先部署 Cloud Run MCP："
            " ./scripts/deploy_bilibili_mcp_cloudrun.sh"
        )
    if "127.0.0.1" in url or "localhost" in url:
        raise RuntimeError(
            f"BILIBILI_MCP_SERVER_URL 不能是本地地址（当前: {url}）。"
            "请改为 Cloud Run URL，例如 https://bilibili-mcp-xxx.run.app/mcp"
        )
    return normalize_mcp_url(url)


def _mcp_server_url() -> str:
    return _require_mcp_url()


def _mcp_toolset(mcp_url: str) -> McpToolset:
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=mcp_url,
            timeout=30.0,
            sse_read_timeout=180.0,
        ),
        tool_filter=list(MCP_TOOL_NAMES),
    )


def _skill_toolset() -> SkillToolset:
    skills = [load_skill_from_dir(resolve_skill_dir("bilibili", sid)) for sid in SKILL_IDS]
    registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)
    return SkillToolset(skills=skills, registry=registry)


def _mcp_instruction(mcp_url: str, *, standalone: bool) -> str:
    handback = ""
    if not standalone:
        handback = "\n" + expert_handback_instruction(DISPATCHER_NAME)
    return f"""
{BILIBILI_EXPERT_PERSONA}

【技术职责】
通过 **Cloud Run MCP**（{mcp_url}）完成 B 站热门选品。保持「阿B」口吻。
粉丝 Excel RPA 已下线；若用户要查粉丝数，明确告知已下线并建议交回小智。
你可用 MCP 拉热门/导出表格；**不能**自己对表格做 pandas 统计或画图——那是小智的 Code Exec。

【Skill 工作流 — 必须先 load_skill】
- 热点 / 爆款 / 选品 → `load_skill('{TREND_SKILL_ID}')` → fetch_hot_videos / export_hot_videos_excel
- 默认 `fetch_hot_videos(export_excel=false)` 返回 JSON；需要表格时再 export 或 export_excel=true（产物在 GCS）
- 用户要「基于这份表写调研报告 / 统计 / 画图」→ **不要硬撑**，交回 `{DISPATCHER_NAME}`

【P0 envelope】先检查 ok，再读 data 或 error.code。

{mcp_fail_fast_instruction(domain_label="B 站", check_tool_name=_CHECK_TOOL)}
{handback}
""".strip()


def build_bilibili_agent(
    *,
    model: Optional[Gemini] = None,
    mcp_server_url: str | None = None,
    standalone: bool = False,
) -> Agent:
    model = model or vertex_model
    name = STANDALONE_NAME if standalone else AGENT_NAME
    mcp_url = normalize_mcp_url(mcp_server_url or _mcp_server_url())

    tools: list = [
        build_check_mcp_tool(mcp_url=mcp_url, label="Bilibili", tool_name=_CHECK_TOOL),
        _mcp_toolset(mcp_url),
        _skill_toolset(),
    ]
    if standalone:
        tools.append(PreloadMemoryTool())

    return Agent(
        name=name,
        model=model,
        description="B 站专家阿B：全站热门选品（公开 API + Cloud Run MCP）",
        instruction=_mcp_instruction(mcp_url, standalone=standalone),
        tools=tools,
        before_model_callback=make_mcp_guard_before_model(
            mcp_url=mcp_url,
            label="Bilibili",
            expert_name="阿B",
            domain_label="B 站",
            domain_request_hints=(
                "热门",
                "热点",
                "爆款",
                "选品",
                "排行榜",
                "b站",
                "b 站",
                "bilibili",
                "fetch_hot",
            ),
            other_domain_hints=(
                "etsy",
                "e姐",
                "e 姐",
                "listing",
                "评论",
                "生图",
                "场景图",
                "etsy.com",
                "飞书",
                "feishu",
                "小飞",
                "日历",
                "云文档",
                "粉丝",
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
            mcp_url=mcp_url, label="Bilibili"
        ),
        on_tool_error_callback=make_mcp_on_tool_error(
            mcp_url=mcp_url, label="Bilibili"
        ),
        after_agent_callback=generate_memories_callback if standalone else None,
        disallow_transfer_to_peers=not standalone,
    )


build_bilibili_mcp_sub_agent = build_bilibili_agent
