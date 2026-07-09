# -*- coding: utf-8 -*-
"""将 Agent 事件转成飞书可读的进度文案。"""

from __future__ import annotations

import json
from typing import Any, Optional

AGENT_LABELS: dict[str, str] = {
    "SmartAgents_Dispatcher": "小智",
    "Bilibili_Cloud_MCP_Agent": "阿B",
    "Etsy_Cloud_MCP_Agent": "E姐",
}

TOOL_LABELS: dict[str, str] = {
    "transfer_to_agent": "转交任务",
    "load_skill": "加载工作手册",
    "load_skill_resource": "查阅参考资料",
    "list_skills": "查看技能列表",
    "search_skills": "搜索技能",
    "run_skill_script": "运行脚本",
    "get_up_list": "获取 UP 主名单",
    "fetch_fans_data": "查询粉丝数据",
    "write_excel": "写入 Excel",
    "etsy_check_credentials": "检查 Etsy 凭证",
    "etsy_fetch_listing_reviews": "拉取商品评论",
    "etsy_write_reviews_excel": "导出评论 Excel",
    "etsy_fetch_and_export_reviews": "拉取并导出评论",
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
