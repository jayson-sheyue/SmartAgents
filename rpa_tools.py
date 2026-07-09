# -*- coding: utf-8 -*-
"""
rpa_tools.py — 兼容层（re-export）

实现已迁至 `bilibili_agent/bilibili_tools.py`（与 Etsy `etsy_tools` 对称）。
REST / MCP / 测试脚本可继续 `from rpa_tools import ...`。
"""

from __future__ import annotations

from bilibili_agent.bilibili_tools import (
    ALLOWED_EXCEL_ROOTS,
    LOGIN_STATE_FILE,
    LOGIN_HINT,
    WriteMode,
    get_default_excel_path,
    get_up_fans_data,
    manual_login,
    parse_fans_count,
    read_up_names_from_excel,
    resolve_excel_path,
    tool_fetch_fans_data,
    tool_get_up_list,
    tool_write_excel,
    write_fans_to_excel,
)

__all__ = [
    "ALLOWED_EXCEL_ROOTS",
    "LOGIN_STATE_FILE",
    "LOGIN_HINT",
    "WriteMode",
    "get_default_excel_path",
    "resolve_excel_path",
    "read_up_names_from_excel",
    "write_fans_to_excel",
    "get_up_fans_data",
    "manual_login",
    "parse_fans_count",
    "tool_get_up_list",
    "tool_fetch_fans_data",
    "tool_write_excel",
]
