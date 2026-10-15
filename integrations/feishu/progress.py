# -*- coding: utf-8 -*-
"""将 Agent 事件转成飞书可读的进度文案。"""

from __future__ import annotations

import json
from typing import Any, Optional

AGENT_LABELS: dict[str, str] = {
    "SmartAgents_Dispatcher": "小智",
    "Bilibili_Cloud_MCP_Agent": "阿B",
    "Bilibili_Agent": "阿B",
    "Etsy_Cloud_MCP_Agent": "E姐",
    "Etsy_Agent": "E姐",
}

_ETSY_LABELS: dict[str, str] = {
    "etsy_check_credentials": "检查 Etsy 凭证",
    "etsy_fetch_listing_reviews": "拉取商品评论",
    "etsy_write_reviews_excel": "导出评论 Excel",
    "etsy_fetch_and_export_reviews": "拉取并导出评论",
    "etsy_get_listing": "读取商品信息",
    "etsy_fetch_listing_images": "拉取商品附图",
    "etsy_list_image_presets": "查看生图预设",
    "etsy_get_image_preset": "读取生图预设",
    "etsy_save_image_preset": "保存生图预设",
    "etsy_polish_scene_brief": "润色场景描述",
    "etsy_generate_listing_scene_variants": "同步换场景生图",
}

TOOL_LABELS: dict[str, str] = {
    "transfer_to_agent": "转交任务",
    "load_skill": "加载工作手册",
    "load_skill_resource": "查阅参考资料",
    "list_skills": "查看技能列表",
    "search_skills": "搜索技能",
    "run_skill_script": "运行脚本",
    "fetch_hot_videos": "抓取全站热门",
    "export_hot_videos_excel": "导出热门 Excel",
    "check_bilibili_mcp": "检查 B 站 MCP",
    "check_etsy_mcp": "检查 Etsy MCP",
    "search_tse_daily_reports": "检索 TSE 日报关键词",
    "set_tse_session_api_key": "绑定本会话 TSE Key",
    "clear_tse_session_api_key": "清除本会话 TSE Key",
    "tse_session_api_key_status": "查看本会话 TSE Key",
    "ask_tse_workspace": "TSE 开放语义问答",
    "generate_tse_global_report": "生成 TSE 全局大盘",
    "task_card_get": "读取任务主线",
    "task_card_upsert": "更新任务主线",
    "task_card_complete": "完成任务主线",
    "task_card_clear": "清除任务主线",
    "feishu_bitable_table_list": "列出多维表格数据表",
    **_ETSY_LABELS,
}


def _agent_label(name: str) -> str:
    return AGENT_LABELS.get(name, name)


def _tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name)


def _parse_args(args: Any) -> dict[str, Any]:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def format_function_call(name: str, args: Any = None) -> str:
    if name == "transfer_to_agent":
        target = _parse_args(args).get("agent_name") or _parse_args(args).get("agent")
        if target:
            return f"🔄 正在请 {_agent_label(str(target))} 接手…"
        return "🔄 正在转交专家处理…"
    return f"🔧 {_tool_label(name)}…"


def format_author_active(author: str) -> str:
    return f"💬 {_agent_label(author)} 正在处理…"


def format_from_adk_event(event: Any) -> Optional[str]:
    """从 ADK Runner 事件提取一条进度文案。"""
    author = getattr(event, "author", None) or ""
    if author and author not in ("user", "system"):
        content = getattr(event, "content", None)
        if content and getattr(content, "parts", None):
            for part in content.parts:
                fc = getattr(part, "function_call", None)
                if fc and getattr(fc, "name", None):
                    return format_function_call(fc.name, getattr(fc, "args", None))
        return format_author_active(author)
    return None


def format_from_stream_part(part: dict[str, Any]) -> Optional[str]:
    if "function_call" in part:
        fc = part.get("function_call") or {}
        name = fc.get("name")
        if name:
            return format_function_call(name, fc.get("args"))
    return None


def format_from_stream_event(event_data: dict[str, Any]) -> Optional[str]:
    """从 Agent Engine streamQuery JSON 提取进度文案。"""
    candidates = [event_data]
    if isinstance(event_data.get("output"), dict):
        candidates.append(event_data["output"])

    author: Optional[str] = None
    for obj in candidates:
        if obj.get("author"):
            author = str(obj["author"])
        content = obj.get("content")
        if not isinstance(content, dict):
            continue
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            progress = format_from_stream_part(part)
            if progress:
                return progress

    if author and author not in ("user", "system"):
        return format_author_active(author)
    return None
