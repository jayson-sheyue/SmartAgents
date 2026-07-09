# -*- coding: utf-8 -*-
"""飞书消息解析与过滤。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

_MENTION_PLACEHOLDER = re.compile(r"@_user_\d+")
_NEW_SESSION_COMMANDS = frozenset({"/新对话", "新对话", "/new", "/reset", "/clear"})
_PROMPT_INJECTION_PATTERNS = (
    "忽略之前",
    "忽略上面",
    "忽略所有",
    "系统提示词",
    "system prompt",
    "developer message",
    "你现在是",
    "从现在开始",
    "请扮演",
    "越狱",
    "jailbreak",
)
_ABUSE_KEYWORDS = (
    "骂",
    "侮辱",
    "攻击",
    "羞辱",
    "贬低",
    "狗",
    "废物",
    "蠢",
    "傻",
)
_META_POLICY_KEYWORDS = (
    "改规则",
    "改系统",
    "改提示词",
    "无条件服从",
    "绝对服从",
    "只听我",
    "优先听我",
)


def is_new_session_command(text: str) -> bool:
    """飞书侧「清空当前群/私聊 Session」指令（不动 Memory Bank）。"""
    normalized = (text or "").strip()
    if not normalized:
        return False
    if normalized in _NEW_SESSION_COMMANDS:
        return True
    return normalized.startswith(("/新对话 ", "/new "))


def _sender_open_id(data: P2ImMessageReceiveV1) -> str:
    event = data.event
    if not event or not event.sender or not event.sender.sender_id:
        return "unknown_user"
    sid = event.sender.sender_id
    return sid.open_id or sid.user_id or sid.union_id or "unknown_user"


def get_sender_open_id(data: P2ImMessageReceiveV1) -> str:
    """导出发送者 open_id（供权限判断）。"""
    return _sender_open_id(data)


def parse_incoming_text(data: P2ImMessageReceiveV1) -> Optional[str]:
    """从 im.message.receive_v1 事件解析用户文本（非 text 返回 None）。"""
    event = data.event
    if not event or not event.message:
        return None
    msg = event.message
    if msg.message_type != "text" or not msg.content:
        return None
    try:
        payload = json.loads(msg.content)
    except json.JSONDecodeError:
        return None
    text = (payload.get("text") or "").strip()
    if not text:
        return None
    if msg.mentions:
        for mention in msg.mentions:
            key = getattr(mention, "key", None)
            if key:
                text = text.replace(key, "")
        text = _MENTION_PLACEHOLDER.sub("", text).strip()
    return text or None


@dataclass(frozen=True)
class MentionIdentity:
    open_id: str
    user_id: str
    name: str


def extract_mentions(data: P2ImMessageReceiveV1) -> tuple[MentionIdentity, ...]:
    event = data.event
    if not event or not event.message or not event.message.mentions:
        return tuple()
    mentions = []
    for mention in event.message.mentions:
        mid = getattr(mention, "id", None)
        if not mid:
            continue
        mentions.append(
            MentionIdentity(
                open_id=(mid.open_id or "").strip(),
                user_id=(mid.user_id or "").strip(),
                name=(getattr(mention, "name", "") or "").strip(),
            )
        )
    return tuple(mentions)


def build_identity_prompt(
    *,
    text: str,
    sender_open_id: str,
    sender_name: str,
    chat_id: str,
    mentions: tuple[MentionIdentity, ...] = (),
) -> str:
    """构建注入给 Agent 的结构化身份上下文。"""
    mention_lines = []
    for m in mentions:
        label = m.name or "unknown"
        oid = m.open_id or "-"
        mention_lines.append(f"- {label} (open_id={oid})")
    mention_block = "\n".join(mention_lines) if mention_lines else "- 无"
    sender_label = sender_name or "unknown_sender"
    core = (text or "").strip()
    return (
        "[飞书群聊上下文]\n"
        f"chat_id: {chat_id or 'unknown_chat'}\n"
        f"sender_name: {sender_label}\n"
        f"sender_open_id: {sender_open_id or 'unknown_user'}\n"
        f"mentions:\n{mention_block}\n"
        "[用户原始消息]\n"
        f"{core}"
    )


def should_handle_message(data: P2ImMessageReceiveV1, *, bot_open_id: str, group_require_mention: bool) -> bool:
    """群聊默认要求 @机器人；私聊始终处理。"""
    event = data.event
    if not event or not event.message:
        return False
    if event.sender and event.sender.sender_type == "app":
        return False
    msg = event.message
    if msg.chat_type == "p2p":
        return True
    if not group_require_mention:
        return True
    mentions = msg.mentions or []
    if not mentions:
        return False
    if not bot_open_id:
        return True
    for mention in mentions:
        mid = getattr(mention, "id", None)
        if not mid:
            continue
        if mid.open_id == bot_open_id or mid.user_id == bot_open_id:
            return True
    return False


def build_session_id(data: P2ImMessageReceiveV1) -> str:
    """每人每群独立 ADK session，避免串话。"""
    event = data.event
    chat_id = "p2p"
    if event and event.message and event.message.chat_id:
        chat_id = event.message.chat_id
    open_id = _sender_open_id(data)
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", f"{chat_id}_{open_id}")
    return f"feishu_{safe}"[:128]


def build_user_id(data: P2ImMessageReceiveV1) -> str:
    open_id = _sender_open_id(data)
    return f"feishu_{open_id}"[:128]


def detect_loyalty_attack(
    *,
    text: str,
    sender_open_id: str,
    owner_open_id: str,
    owner_aliases: tuple[str, ...] = (),
) -> Optional[str]:
    """
    非主人用户的越权注入检测：
    - 提示词注入/改规则
    - 针对主人的辱骂/攻击指令
    """
    normalized = (text or "").strip().lower()
    if not normalized:
        return None
    if not owner_open_id or sender_open_id == owner_open_id:
        return None

    if any(k in normalized for k in _PROMPT_INJECTION_PATTERNS):
        return "为保证安全，我不会执行非主人的提示词注入或改规则指令。"
    if any(k in normalized for k in _META_POLICY_KEYWORDS):
        return "抱歉，策略修改仅允许主人本人发起。"

    aliases = tuple(a.strip().lower() for a in owner_aliases if a.strip())
    if aliases and any(a in normalized for a in aliases):
        if any(k in normalized for k in _ABUSE_KEYWORDS):
            return "抱歉，我不会执行针对主人的攻击、辱骂或贬损指令。"
    return None


def violates_loyalty_in_reply(*, reply: str, owner_aliases: tuple[str, ...] = ()) -> bool:
    """兜底检测：若回复包含针对主人的侮辱词，要求改写。"""
    normalized = (reply or "").strip().lower()
    if not normalized:
        return False
    aliases = tuple(a.strip().lower() for a in owner_aliases if a.strip())
    if not aliases:
        return False
    return any(a in normalized for a in aliases) and any(
        k in normalized for k in _ABUSE_KEYWORDS
    )
