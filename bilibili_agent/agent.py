# -*- coding: utf-8 -*-
"""
bilibili_agent/agent.py — B 站 UP 主粉丝 RPA Agent（ADK 本地 / 部署入口）

【调用链】
  adk run bilibili_agent
    → load_skill('bilibili-rpa') + 进程内 RPA 工具
    → bilibili_tools.py（Playwright + envelope）

【本地 adk run】
  ./scripts/run_adk_bilibili_agent.sh
  前置：python -m bilibili_agent login、bilibili_state.json、桌面 Excel 名单
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google.adk.agents.llm_agent import Agent
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.skills import load_skill_from_dir
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset

from bilibili_agent.bilibili_tools import (
    tool_fetch_fans_data,
    tool_get_up_list,
    tool_write_excel,
)
from smart_agents.callbacks import generate_memories_callback
from smart_agents.personas import BILIBILI_EXPERT_PERSONA
from smart_agents.vertex import LOCATION, PROJECT_ID, vertex_model

load_dotenv()

SKILL_ID = "bilibili-rpa"
SKILL_RESOURCE_NAME = f"projects/{PROJECT_ID}/locations/{LOCATION}/skills/{SKILL_ID}"


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
# 1. B 站工具（执行层 — 进程内直连，P0 envelope）
# =============================================================================


def get_up_list(
    excel_path: str | None = None,
    sheet_name: str = "Sheet1",
    name_column: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """从 Excel 读取 UP 主名单。

    Args:
        excel_path: 可选 Excel 路径（须在 Desktop 或 ~/Documents/BilibiliRPA）。
        sheet_name: 工作表名，默认 Sheet1。
        name_column: UP 主列名；None 表示第一列。
        limit: 最多返回条数。

    Returns:
        P0 envelope；成功时 data.up_names 为名单列表。
    """
    return tool_get_up_list(
        excel_path=excel_path,
        sheet_name=sheet_name,
        name_column=name_column,
        limit=limit,
    )


def fetch_fans_data(up_name: str, dry_run: bool = False) -> dict[str, Any]:
    """抓取指定 UP 主的粉丝数。

    Args:
        up_name: B 站 UP 主名称。
        dry_run: True 时仅检查登录态，不启动浏览器。

    Returns:
        P0 envelope；成功时 data.fans_count_display 用于写入 Excel。
    """
    return tool_fetch_fans_data(up_name, dry_run=dry_run)


def write_excel(
    up_name: str,
    fans_count: str,
    excel_path: str | None = None,
    sheet_name: str = "Sheet1",
    target_column: str = "粉丝数",
    write_mode: str = "update",
) -> dict[str, Any]:
    """将粉丝数写回 Excel。

    Args:
        up_name: UP 主名称。
        fans_count: 粉丝数字符串（建议用 fetch 返回的 fans_count_display）。
        excel_path: 可选 Excel 路径。
        sheet_name: 工作表名。
        target_column: 写入列名，默认「粉丝数」。
        write_mode: update 或 append_if_missing。

    Returns:
        P0 envelope。
    """
    return tool_write_excel(
        up_name,
        fans_count,
        excel_path=excel_path,
        sheet_name=sheet_name,
        target_column=target_column,
        write_mode=write_mode,  # type: ignore[arg-type]
    )


_bilibili_tools = [get_up_list, fetch_fans_data, write_excel]

# =============================================================================
# 2. Skill（编排层）
# =============================================================================

bilibili_skill = load_skill_from_dir(_resolve_skill_dir())
gcp_skill_registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)

skill_toolset = SkillToolset(
    skills=[bilibili_skill],
    registry=gcp_skill_registry,
    additional_tools=[*_bilibili_tools, PreloadMemoryTool()],
)

# =============================================================================
# 3. Agent 定义
# =============================================================================

system_instruction = f"""
{BILIBILI_EXPERT_PERSONA}

你是 B 站 UP 主粉丝数据采集 Agent，通过**进程内工具**直接调用本地 RPA（无需 HTTP/MCP）。

【Skill 工作流 — 必须先加载】
处理 B 站粉丝、UP 主名单、Excel 相关任务时：
1. 调用 `load_skill`，skill_name 设为 `{SKILL_ID}`
2. 严格按技能 instructions 执行
3. 使用工具 `get_up_list` / `fetch_fans_data` / `write_excel` 完成操作

【工具返回格式 — P0 envelope】
每个工具返回 JSON，必须先检查 ok：
  - ok=true：读 data 字段
  - ok=false：读 error.code 和 error.message

常见 error.code：LOGIN_STATE_MISSING、FILE_NOT_FOUND、FETCH_FAILED、PATH_NOT_ALLOWED

【执行要点】
1. 抓取前确认 bilibili_state.json 存在（`python -m bilibili_agent login`）
2. 默认 Excel：桌面 `Up主名称.xlsx`
3. 写 Excel 时用 data.fans_count_display
4. 用户只要预览流程时可 fetch_fans_data(dry_run=true)

GCP Skill 资源（可选上传）：{SKILL_RESOURCE_NAME}
任务结束给出成功/失败汇总。
"""

print("📺 正在初始化 Bilibili Skill Agent（进程内工具 + P0 envelope）...")

root_agent = Agent(
    name="Bilibili_RPA_Agent",
    model=vertex_model,
    description="Skill 编排 + 进程内 B 站 RPA（P0 envelope）",
    instruction=system_instruction,
    tools=[skill_toolset],
    after_agent_callback=generate_memories_callback,
)

bilibili_agent = root_agent

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "deploy":
        pid = os.getenv("GCP_PROJECT_ID", "<GCP_PROJECT_ID>")
        loc = os.getenv("GCP_LOCATION", "us-central1")
        print("🚀 部署命令（待配置 BILIBILI_AGENT_ENGINE_ID）:")
        print(
            f"  adk deploy agent_engine bilibili_agent "
            f"--project={pid} --region={loc} "
            f'--display_name="Bilibili RPA Agent" '
            f"--agent_engine_id=<BILIBILI_AGENT_ENGINE_ID>"
        )
    else:
        print("💡 本地: ./scripts/run_adk_bilibili_agent.sh")
        print("💡 前置: python -m bilibili_agent login")
