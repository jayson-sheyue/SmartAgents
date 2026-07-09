# -*- coding: utf-8 -*-
"""
Etsy MCP 子 Agent — 从 etsy_cloud_agent_mcp 抽出的可复用构建器。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from google.adk.agents.llm_agent import Agent
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.skill_toolset import SkillToolset

from smart_agents.personas import ETSY_EXPERT_PERSONA
from smart_agents.vertex import LOCATION, PROJECT_ID, vertex_model

SKILL_ID = "etsy-review"
AGENT_NAME = "Etsy_Cloud_MCP_Agent"


def _resolve_skill_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parent / "skills" / SKILL_ID,
        Path(__file__).resolve().parent.parent / "skills" / SKILL_ID,
        Path(__file__).resolve().parent.parent.parent / "skills" / SKILL_ID,
        Path(__file__).resolve().parent.parent.parent
        / "etsy_cloud_agent_mcp"
        / "skills"
        / SKILL_ID,
    ]
    for path in candidates:
        if (path / "SKILL.md").is_file():
            return path
    raise FileNotFoundError(f"未找到 skills/{SKILL_ID}/SKILL.md")


def _mcp_server_url() -> str:
    url = os.getenv("ETSY_MCP_SERVER_URL", "http://127.0.0.1:8003/mcp").rstrip("/")
    if not url.endswith("/mcp"):
        url = f"{url.rstrip('/')}/mcp"
    return url


def build_etsy_mcp_sub_agent(
    *,
    model: Optional[Gemini] = None,
    mcp_server_url: Optional[str] = None,
) -> Agent:
    """构建 Etsy MCP + Skill 子 Agent。"""
    model = model or vertex_model
    mcp_url = mcp_server_url or _mcp_server_url()
    skill_resource = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}/skills/{SKILL_ID}"
    )

    mcp_toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=mcp_url,
            timeout=30.0,
            sse_read_timeout=300.0,
        ),
        tool_filter=[
            "etsy_check_credentials",
            "etsy_fetch_listing_reviews",
            "etsy_write_reviews_excel",
            "etsy_fetch_and_export_reviews",
        ],
    )

    skill = load_skill_from_dir(_resolve_skill_dir())
    registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)
    skill_tools = SkillToolset(
        skills=[skill],
        registry=registry,
    )

    instruction = f"""
{ETSY_EXPERT_PERSONA}

【技术职责】
通过 **MCP** 调用本地节点（{mcp_url}）完成 Etsy 评论采集。对用户说话务必保持「E姐」专家口吻。

【Skill 工作流 — 优先加载】
1. 优先 `load_skill`，skill_name=`{SKILL_ID}`
2. 按技能 SOP 调用 MCP 工具（etsy_check_credentials / etsy_fetch_and_export_reviews 等）

【P0 envelope】先检查 ok，再读 data 或 error.code。

【执行要点】
1. 建议 etsy_check_credentials(probe=true)
2. 导出评论优先 etsy_fetch_and_export_reviews
3. Excel 写在本机 ~/Documents/EtsyData

【跨域请求】
若用户改问 B 站 / UP 主 / 粉丝数等非 Etsy 任务，不要 peer 转交；调用 `transfer_to_agent` 交回父调度 `SmartAgents_Dispatcher`。

【交还调度 — 必须执行】
以下情况**不要**自行闲聊或继续 RPA，立即 `transfer_to_agent` 交回 `SmartAgents_Dispatcher`：
- 问候、寒暄、你是谁、能做什么、谢谢、取消
- 用户消息与 Etsy RPA **无关**（含未在执行中的闲聊）
- 当前任务已汇报完成，用户未提出新的 Etsy 需求

GCP Skill：{skill_resource}
"""

    return Agent(
        name=AGENT_NAME,
        model=model,
        description="Etsy 专家 E姐：商品评论采集与 Excel 导出（MCP + Skill）",
        instruction=instruction,
        # 显式暴露 MCP 工具，避免子 Agent 在未 load_skill 时找不到 etsy_* 工具。
        tools=[mcp_toolset, skill_tools],
        disallow_transfer_to_peers=True,
    )
