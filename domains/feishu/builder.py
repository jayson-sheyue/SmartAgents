# -*- coding: utf-8 -*-
"""Unified Feishu agent builder — Cloud Run MCP + lark-cli (bot + user OAuth)."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import Agent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.integrations.skill_registry import GCPSkillRegistry
from google.adk.models import Gemini
from google.adk.skills import load_skill_from_dir
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.skill_toolset import SkillToolset

from domains.feishu.registry import AGENT_NAME, MCP_TOOL_NAMES, SKILL_IDS, STANDALONE_NAME
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
from smart_agents.personas import FEISHU_EXPERT_PERSONA
from smart_agents.task_card import (
    compose_after_tool_callbacks,
    format_task_card_block,
    make_task_card_after_tool,
    task_card_clear,
    task_card_before_tool,
    task_card_complete,
    task_card_get,
    task_card_upsert,
)
from smart_agents.vertex import LOCATION, PROJECT_ID, vertex_model

DISPATCHER_NAME = "SmartAgents_Dispatcher"
OPS_SKILL_ID = "feishu-ops"
_CHECK_TOOL = "check_feishu_mcp"


def _require_mcp_url() -> str:
    url = (os.getenv("FEISHU_MCP_SERVER_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "未设置 FEISHU_MCP_SERVER_URL。请先部署 Cloud Run MCP："
            " ./scripts/deploy_feishu_mcp_cloudrun.sh"
        )
    if "127.0.0.1" in url or "localhost" in url:
        raise RuntimeError(
            f"FEISHU_MCP_SERVER_URL 不能是本地地址（当前: {url}）。"
            "请改为 Cloud Run URL，例如 https://feishu-mcp-xxx.run.app/mcp"
        )
    return normalize_mcp_url(url)


def _mcp_server_url() -> str:
    return _require_mcp_url()


def _feishu_mcp_header_provider(ctx: ReadonlyContext) -> dict[str, str]:
    """Pass ADK session.user_id so MCP can load per-user OAuth tokens."""
    uid = (getattr(ctx, "user_id", None) or "").strip()
    headers: dict[str, str] = {}
    if uid:
        headers["X-Adk-User-Id"] = uid
        if uid.startswith("feishu_"):
            headers["X-Feishu-Open-Id"] = uid[len("feishu_") :]
    return headers


def _mcp_toolset(mcp_url: str) -> McpToolset:
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=mcp_url,
            timeout=60.0,
            sse_read_timeout=180.0,
        ),
        tool_filter=list(MCP_TOOL_NAMES),
        header_provider=_feishu_mcp_header_provider,
    )


def _skill_toolset() -> SkillToolset:
    skills = [load_skill_from_dir(resolve_skill_dir("feishu", sid)) for sid in SKILL_IDS]
    registry = GCPSkillRegistry(project_id=PROJECT_ID, location=LOCATION)
    return SkillToolset(skills=skills, registry=registry)


def _mcp_instruction(mcp_url: str, *, standalone: bool):
    handback = ""
    if not standalone:
        handback = "\n" + expert_handback_instruction(DISPATCHER_NAME)
    base = f"""
{FEISHU_EXPERT_PERSONA}

【技术职责】
通过 **Cloud Run MCP**（{mcp_url}）调用 **lark-cli**：
- 个人日历（查/建/忙闲）/ 搜人 / 搜群 / **搜聊天记录** / 搜文档 / 文档读 / 表格读 / **多维表格** → **用户 OAuth**（`--as user`）
- 发消息 / 列群消息（Bot 在群内）→ **Bot**（`--as bot`）
保持「小飞」口吻。这与「飞书机器人入站桥接 SmartAgents」是反方向能力。

【Skill 工作流 — 必须先 load_skill】
- 日历 / 约会 / 多维表格 / 搜人 / 搜群 / 消息 / **按话题搜聊天** / 搜文档 / 文档 / 表格 → `load_skill('{OPS_SKILL_ID}')` → 再调白名单 MCP 工具
- **被 transfer 接手后立刻自然语言开口并继续**；transfer 返回 null 属正常，禁止静默
- **Task Card（一层真相）**：开场 `task_card_get`；完成契约以注入的【Task Card】块为准（按 deliverable 分支）。
  upsert 必须带规范 `deliverable`：`bitable_with_rows` / `doc_search_answer` / `doc_created` /
  `calendar_event` / `calendar_agenda` / `im_message_sent` / `im_chat_topic_summary` / `sheet_updated` 等；并带 `phase`/`next_action`。
- 「新建/写入多维表格」→ `task_card_upsert(deliverable=bitable_with_rows, …)` →
  `feishu_bitable_create(fields_json仅含 name/type/options)` → **本轮内** `record_batch_create`
- **禁止**对「刚 create 的空表」调用 `write_tse_records`；新建写入一律 `record_batch_create`
- fields_json **禁止**带 `property`；丢失 table_id → `table_list`，禁止让用户找 `table=`
- **同步 TSE 日报到已有表**：parse_url → field_list →（小智 map）→ `write_tse_records`；无 TSE 数据交回 `{DISPATCHER_NAME}`
- 「约会议」→ upsert `calendar_event` → `feishu_calendar_create`
- 「发消息」→ upsert `im_message_sent` → contact/chat search → send
- 「某群最近 N 天聊天 / 总结要点」（无主题词）→ upsert `im_chat_topic_summary` → chat_search →
  **`feishu_im_chat_messages_list`(start/end, as_user=true, 翻页)** → 汇总 → complete
- 「某群关于 XXX」→ upsert `im_chat_topic_summary` → chat_search →
  **`feishu_im_messages_search`(query=主题词, page_all)**；0 命中再 list 复核 → complete
  （禁止把「聊天记录/要点」当 search query；禁止单页空结果就宣称无消息）
- 「搜云文档」→ upsert `doc_search_answer` → `feishu_doc_search` → 按 `data.items[].title/url` 列表交付 → `task_card_complete`
  （**链接仅用工具返回的 url**；0 命中如实说未找到；禁止编造链接；禁止建多维表格或空转 task_card_get）
- **写操作**：Task Card 已锁定 goal 时直接执行；仅多候选时先确认

【用户 OAuth — 两步，禁止同轮阻塞】
1. `feishu_oauth_status`；若未授权或工具返回 `NEED_USER_OAUTH` / `NEED_REAUTH` → `feishu_oauth_start`
2. 把返回的 **verification_url 放进代码块原样**发给用户（禁止 Markdown 链接语法），`task_card_upsert(status=blocked, blocked_reason=waiting_user_oauth)`，**结束本轮**（不要立刻 complete）；**禁止**用 `feishu_im_send_text` 发授权链接
3. 用户回复已授权后 → `feishu_oauth_complete` → **立刻按 Task Card 继续原 goal**（重试 `feishu_im_messages_search` 等）；**禁止**未重试就 transfer 回小智宣称失败
4. 若工具返回 `MISSING_APP_SCOPE`：**禁止**再发个人授权链接；把 `action_url`/`scope_enable_url` 放进代码块请用户点开（开通 scope 并提交管理员发布）；若 `admin_apply.ok=true` 说明已自动向管理员提交，告知用户等待审批后回复「权限已开通」再重试。也可调用 `feishu_app_scopes_remediate`。

【日历日期 — 禁止臆测】
- 查「今天/今日」：`feishu_calendar_agenda` 的 start/end **必须留空**（服务端按 Asia/Shanghai 填今天）
- **禁止**使用训练记忆里的旧日期（例如 2024-xx-xx）
- 向用户播报日期时，以工具返回的 `server_today` / `queried_start` / `queried_end` 为准

【P0 envelope】先检查 ok，再读 data 或 error.code（关注 NEED_USER_OAUTH / NEED_REAUTH / MISSING_APP_SCOPE / MISSING_USER_ID / STALE_DATE / CREATE_MISSING_TABLE_ID）。

{mcp_fail_fast_instruction(domain_label="飞书", check_tool_name=_CHECK_TOOL)}
{handback}
""".strip()

    def _dyn(ctx: ReadonlyContext) -> str:
        today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        return (
            base
            + f"\n\n【当前日期】今天是 **{today}**（Asia/Shanghai）。"
            "口播「今天」必须用这个日期，不要用记忆中的年份。"
            "若任务涉及「本月 TSE 日报」但上下文没有查询结果："
            f"立刻 transfer 给 {DISPATCHER_NAME}，不要搜飞书云文档。"
            + format_task_card_block(ctx)
        )

    return _dyn


async def _memory_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


def build_feishu_agent(
    *,
    model: Optional[Gemini] = None,
    mcp_server_url: str | None = None,
    standalone: bool = False,
) -> Agent:
    model = model or vertex_model
    name = STANDALONE_NAME if standalone else AGENT_NAME
    mcp_url = normalize_mcp_url(mcp_server_url or _mcp_server_url())

    tools: list = [
        build_check_mcp_tool(mcp_url=mcp_url, label="Feishu", tool_name=_CHECK_TOOL),
        task_card_get,
        task_card_upsert,
        task_card_complete,
        task_card_clear,
        _mcp_toolset(mcp_url),
        _skill_toolset(),
    ]
    if standalone:
        tools.append(PreloadMemoryTool())

    return Agent(
        name=name,
        model=model,
        description="飞书专家小飞：日历/消息/文档/表格（lark-cli + 用户 OAuth + Cloud Run MCP）",
        instruction=_mcp_instruction(mcp_url, standalone=standalone),
        tools=tools,
        before_model_callback=make_mcp_guard_before_model(
            mcp_url=mcp_url,
            label="Feishu",
            expert_name="小飞",
            domain_label="飞书",
            domain_request_hints=(
                "飞书",
                "feishu",
                "lark",
                "日历",
                "日程",
                "约会议",
                "发消息",
                "群聊",
                "通讯录",
                "云文档",
                "搜文档",
                "电子表格",
                "多维表格",
                "bitable",
                "spreadsheet",
                "docx",
                "授权",
                "oauth",
            ),
            other_domain_hints=(
                "b站",
                "b 站",
                "bilibili",
                "阿b",
                "etsy",
                "e姐",
                "listing",
                "生图",
                "调研报告",
                "数据分析",
                "画图",
                "pandas",
                "run_code",
            ),
        ),
        after_tool_callback=compose_after_tool_callbacks(
            make_mcp_fail_fast_after_tool(mcp_url=mcp_url, label="Feishu"),
            make_task_card_after_tool(),
        ),
        before_tool_callback=task_card_before_tool,
        on_tool_error_callback=make_mcp_on_tool_error(
            mcp_url=mcp_url, label="Feishu"
        ),
        after_agent_callback=_memory_callback if standalone else None,
        disallow_transfer_to_peers=not standalone,
    )


build_feishu_mcp_sub_agent = build_feishu_agent
