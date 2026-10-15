# -*- coding: utf-8 -*-
"""小智固定开场白（首轮纯招呼 / 能力咨询）。"""

from __future__ import annotations

import re
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

_FEISHU_USER_MARKER = "[用户原始消息]\n"

# 含以下词视为已有明确任务，不走固定开场白
_TASK_HINTS = (
    "查",
    "帮",
    "请",
    "拉",
    "导",
    "抓",
    "写",
    "生图",
    "换场景",
    "评论",
    "粉丝",
    "up主",
    "up 主",
    "listing",
    "etsy",
    "b站",
    "bilibili",
    "哔哩",
    "excel",
    "分析",
    "统计",
    "上传",
    "下载",
    "运行",
    "执行",
)

_GREETING_RE = re.compile(
    r"^("
    r"你好|您好|ni\s*hao|nin\s*hao|hi|hello|hey|哈喽|嗨|在吗|在么|在不在|"
    r"早上好|上午好|中午好|下午好|晚上好|晚安|"
    r"你是谁|你是哪位|介绍一下你自己|自我介绍|"
    r"你能做什么|你会什么|有什么功能|能帮我什么|你会些什么"
    r")[\s!！?？。,，~～呀啊呐哦吧]*$",
    re.IGNORECASE,
)


def extract_user_message(text: str) -> str:
    """从飞书身份注入块中取出用户原文。"""
    raw = (text or "").strip()
    if _FEISHU_USER_MARKER in raw:
        return raw.split(_FEISHU_USER_MARKER, 1)[1].strip()
    return raw


def is_greeting_only(text: str) -> bool:
    """是否为无明确任务指令的招呼或能力咨询。"""
    core = extract_user_message(text)
    core = re.sub(r"\s+", " ", core).strip()
    if not core or len(core) > 80:
        return False
    lower = core.lower()
    if any(hint in lower for hint in _TASK_HINTS):
        return False
    if _GREETING_RE.match(core):
        return True
    # 极短寒暄（如「嗯」「ok」）不触发开场白
    return False


def is_session_opening(callback_context: CallbackContext) -> bool:
    """本会话是否尚无助手回复（首轮）。"""
    for event in callback_context.session.events or []:
        content = event.content
        if not content or not content.parts:
            continue
        if content.role == "model":
            return False
    return True


def latest_user_text(llm_request: LlmRequest) -> str:
    for content in reversed(llm_request.contents or []):
        if content.role != "user" or not content.parts:
            continue
        chunks = [p.text for p in content.parts if p.text]
        if chunks:
            return "".join(chunks)
    return ""


def build_dispatcher_greeting_opener(
    *,
    bilibili_agent_name: str,
    etsy_agent_name: str,
    feishu_agent_name: str = "",
    code_execution_enabled: bool = False,
    rag_enabled: bool = False,
    data_mcp_enabled: bool = False,
    sap_enabled: bool = False,
) -> str:
    """固定开场白正文（可按能力开关微调段落）。"""
    _ = (bilibili_agent_name, etsy_agent_name, feishu_agent_name)
    lines = [
        "您好，我是您的私人秘书「小智」，很高兴为您服务。",
        "",
        "我们团队有三位领域专家，我可以帮您对接：",
        "- **阿B（B站）**：全站热门/排行榜选品分析（公开 API）",
        "- **E姐（Etsy）**：商品评论采集、listing 上架素材同步生图（换场景 / 预设 / GCS）",
        "- **小飞（飞书）**：日历日程、搜/读云文档、发/查消息、电子表格（出站）",
        "",
        "我本人还可以：",
        "- 接待闲聊、澄清您的需求并分派给合适的专家",
        "- 查询实时资讯（新闻、天气等，联网搜索）",
    ]
    if rag_enabled:
        lines.append("- 检索内部知识库文档（产品说明、GCP/配置手册等）")
    if code_execution_enabled:
        lines.append(
            "- 对已导出的 Excel/CSV 做统计、对比、画图（Code Execution 数据分析）"
        )
    if data_mcp_enabled:
        lines.append(
            "- 查询 TSE Smart Workspace（确定性工具优先；有 API Key 走 External API，Firestore/KC 仅兜底与元数据）"
        )
    if sap_enabled:
        lines.append("- 通过 Computer Use 查询 SAP 采购订单并返回截图；识别上传的发票图片/PDF后查询对应订单（需 SAP 登录）")
    lines.extend(
        [
            "",
            "您可以直接告诉我要做什么，例如：",
            "「抓一下 B 站全站热门 Top50 做选品分析」",
            "「拉 listing 123456 的评论」",
            "「给这个 Etsy 链接换节日暖色场景出图」",
            "「查一下今天飞书日历」 / 「给某群发一条测试消息」",
            "",
            "请问今天有什么可以帮您的？",
        ]
    )
    return "\n".join(lines)


def make_greeting_callback(
    *,
    bilibili_agent_name: str,
    etsy_agent_name: str,
    feishu_agent_name: str = "",
    code_execution_enabled: bool = False,
    rag_enabled: bool = False,
    data_mcp_enabled: bool = False,
    sap_enabled: bool = False,
):
    """构造 Dispatcher 的 before_model_callback（首轮纯招呼返回固定文案）。"""
    opener = build_dispatcher_greeting_opener(
        bilibili_agent_name=bilibili_agent_name,
        etsy_agent_name=etsy_agent_name,
        feishu_agent_name=feishu_agent_name,
        code_execution_enabled=code_execution_enabled,
        rag_enabled=rag_enabled,
        data_mcp_enabled=data_mcp_enabled,
        sap_enabled=sap_enabled,
    )

    async def dispatcher_greeting_callback(
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        if not is_session_opening(callback_context):
            return None
        user_text = latest_user_text(llm_request)
        if not is_greeting_only(user_text):
            return None
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=opener)],
            )
        )

    return dispatcher_greeting_callback


def make_greeting_agent_callback(**capabilities):
    """Reply before ADK discovers remote tools or preloads memory.

    before_model runs after tool discovery; a first-turn greeting does not
    require MCP, Memory Bank or a model call.
    """
    opener = build_dispatcher_greeting_opener(**capabilities)

    async def greeting_before_agent(callback_context: CallbackContext):
        if not is_session_opening(callback_context):
            return None
        for event in reversed(callback_context.session.events or []):
            content = event.content
            if not content or content.role != "user":
                continue
            text = "".join(part.text for part in content.parts or [] if part.text)
            if is_greeting_only(text) and not any(
                part.inline_data or part.file_data for part in content.parts or []
            ):
                return types.Content(role="model", parts=[types.Part(text=opener)])
            return None
        return None

    return greeting_before_agent
