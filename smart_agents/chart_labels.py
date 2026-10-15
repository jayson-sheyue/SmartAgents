# -*- coding: utf-8 -*-
"""图表标签：中文销售名/术语 → 拼音或英文，避免 matplotlib 缺 CJK 字体。"""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 非人名的固定术语优先走英文（人名仍走拼音）
_TERM_EN: dict[str, str] = {
    "旧版app知识库沉淀": "Legacy App KB Archive",
    "系统自愈补丁区": "Self-healing Patch Area",
    "方案库": "Solution Library",
    "杂记": "Misc Notes",
}


def contains_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def to_chart_label(text: str) -> str:
    """将可能含中文的文本转为图例安全标签（英文术语表优先，否则拼音）。"""
    raw = (text or "").strip()
    if not raw:
        return "(unknown)"
    if raw in _TERM_EN:
        return _TERM_EN[raw]
    if not contains_cjk(raw):
        return raw

    try:
        from pypinyin import Style, lazy_pinyin

        tokens = lazy_pinyin(raw, style=Style.NORMAL)
    except ImportError:
        # 无 pypinyin 时保留 alias，由调用方兜底
        return raw

    parts: list[str] = []
    for token in tokens:
        if not token:
            continue
        parts.append(token.capitalize() if token.isascii() else token)
    return " ".join(parts) if parts else raw
