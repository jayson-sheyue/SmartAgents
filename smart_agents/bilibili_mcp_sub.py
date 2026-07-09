# -*- coding: utf-8 -*-
"""
Bilibili MCP 子 Agent — 从 bilibili_cloud_agent_mcp 抽出的可复用构建器。

供 standalone `adk run bilibili_cloud_agent_mcp` 与 `smart_agents` 调度树共用。
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

from smart_agents.personas import BILIBILI_EXPERT_PERSONA
from smart_agents.vertex import LOCATION, PROJECT_ID, vertex_model

SKILL_ID = "bilibili-rpa"
AGENT_NAME = "Bilibili_Cloud_MCP_Agent"


def _resolve_skill_dir() -> Path:
    candidates = [
        Path(__file__).resolve().parent / "skills" / SKILL_ID,
        Path(__file__).resolve().parent.parent / "skills" / SKILL_ID,
        Path(__file__).resolve().parent.parent.parent / "skills" / SKILL_ID,
        Path(__file__).resolve().parent.parent.parent
        / "bilibili_cloud_agent_mcp"
        / "skills"
        / SKILL_ID,
    ]
    for path in candidates:
        if (path / "SKILL.md").is_file():
            return path
    raise FileNotFoundError(
        f"未找到 Skill 目录 {SKILL_ID}，请确认 skills/{SKILL_ID}/SKILL.md 存在"
    )


def _mcp_server_url() -> str:
    url = os.getenv("BILIBILI_MCP_SERVER_URL", "http://127.0.0.1:8002/mcp").rstrip("/")
    if not url.endswith("/mcp"):
        url = f"{url.rstrip('/')}/mcp"
    return url


def build_bilibili_mcp_sub_agent(
    *,
    model: Optional[Gemini] = None,
    mcp_server_url: Optional[str] = None,
) -> Agent:
    """构建 Bilibili MCP + Skill 子 Agent。"""
    model = model or vertex_model
    mcp_url = mcp_server_url or _mcp_server_url()
    skill_resource = (
        f"projects/{PROJECT_ID}/locations/{LOCATION}/skills/{SKILL_ID}"
    )

    mcp_toolset = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=mcp_url,
            timeout=30.0,
            sse_read_timeout=180.0,
        ),
        tool_filter=["get_up_list", "fetch_fans_data", "write_excel"],
    )

    skill = load_skill_from_dir(_resolve_skill_dir())
    registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)
    skill_tools = SkillToolset(
        skills=[skill],
        registry=registry,
    )

    instruction = f"""
{BILIBILI_EXPERT_PERSONA}

【技术职责】
通过 **MCP** 调用本地节点（{mcp_url}）完成 B 站 RPA 任务。对用户说话务必保持「阿B」专家口吻。

【Skill 工作流 — 优先加载】
处理 UP 主 / Excel / 粉丝数相关任务时：
1. 优先调用 `load_skill`，skill_name 设为 `{SKILL_ID}`
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

【跨域请求】
若用户改问 Etsy / 商品评论等非 B 站任务，不要 peer 转交；调用 `transfer_to_agent` 交回父调度 `SmartAgents_Dispatcher`。

【交还调度 — 必须执行】
以下情况**不要**自行闲聊或继续 RPA，立即 `transfer_to_agent` 交回 `SmartAgents_Dispatcher`：
- 问候、寒暄、你是谁、能做什么、谢谢、取消
- 用户消息与 B 站 RPA **无关**（含未在执行中的闲聊）
- 当前任务已汇报完成，用户未提出新的 B 站需求

GCP Skill 资源：{skill_resource}
遵守 Memory Bank 中的用户偏好。任务结束给出成功/失败汇总。
"""

    return Agent(
        name=AGENT_NAME,
        model=model,
        description="B 站专家阿B：UP 主粉丝数采集与 Excel RPA（MCP + Skill）",
        instruction=instruction,
        # 显式暴露 MCP 工具，避免子 Agent 在未 load_skill 时找不到 fetch_fans_data。
        tools=[mcp_toolset, skill_tools],
        disallow_transfer_to_peers=True,
    )
