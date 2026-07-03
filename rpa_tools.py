# -*- coding: utf-8 -*-
"""
rpa_tools.py — P0 统一「工具契约」层（Agent 可调用的三个能力的真正实现）

【本文件在架构中的位置】
  main.py          → Playwright 真抓 B 站（底层 RPA，不关心 envelope）
  rpa_tools.py     → 本文件：参数校验、路径护栏、统一 JSON 返回格式
  local_node/      → 把本文件包装成 REST HTTP API（端口 8001）
  mcp_server/      → 把本文件包装成 MCP 工具（Cursor / 云端 Agent）

【什么是 envelope（统一返回格式）？】
  每个工具无论成功失败，都返回相同结构的 dict：
    ok     → True/False，一眼看出成没成
    tool   → 哪个工具回的（如 "get_up_list"）
    data   → 成功时的业务数据（各工具字段不同）
    error  → 失败时的 {code, message, retryable}，成功时为 null
    meta   → 附加信息（实际用的路径、耗时等），不是主结果

【什么是路径护栏？】
  excel_path 只允许在 Desktop 和 ~/Documents/BilibiliRPA 下，
  防止 Agent 或用户误指定 /etc/passwd 等敏感路径。

【注意】云端 REST/MCP Agent 在 Phase 2 才切换；当前仅本地 REST/MCP 服务使用本文件。
"""

from __future__ import annotations

import os
import re
import time
from typing import Literal

import pandas as pd

# 从 main.py 复用：默认 Excel 路径、Playwright 抓取函数（不在此文件重复写浏览器逻辑）
from main import get_default_excel_path, get_up_fans_data

# write_mode 只允许两种字符串，写错类型时 IDE/类型检查会提示
WriteMode = Literal["update", "append_if_missing"]

# ---------------------------------------------------------------------------
# 路径护栏：Excel 只允许出现在这些「根目录」之下（及其子文件夹）
# ---------------------------------------------------------------------------
# expanduser("~") 表示当前用户的家目录，例如 /Users/apple
ALLOWED_EXCEL_ROOTS = [
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Documents", "BilibiliRPA"),
]

# B 站登录态文件（python main.py login 后生成），dry_run 和真抓取都会检查它
LOGIN_STATE_FILE = "bilibili_state.json"


# =============================================================================
# 内部辅助：构造 envelope（成功 / 失败两种模板）
# =============================================================================

def _tool_ok(tool: str, data: dict, meta: dict | None = None) -> dict:
    """
    构造「成功」时的 envelope。
    所有 tool_* 函数成功时必须通过此函数返回，保证格式一致。
    """
    return {
        "ok": True,
        "tool": tool,
        "data": data,
        "error": None,
        "meta": meta or {},
    }


def _tool_err(
    tool: str,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    data: dict | None = None,
    meta: dict | None = None,
) -> dict:
    """
    构造「失败」时的 envelope。
    code：机器可读错误码（如 PATH_NOT_ALLOWED），Skill/Agent 可据此决定下一步
    retryable：是否建议用户重试（登录缺失=false，网络闪断可能=true）
    """
    return {
        "ok": False,
        "tool": tool,
        "data": data or {},
        "error": {"code": code, "message": message, "retryable": retryable},
        "meta": meta or {},
    }


def resolve_excel_path(excel_path: str | None) -> str:
    """
    解析用户/Agent 传入的 Excel 路径，并做「路径护栏」校验。

    参数：
      excel_path：None 表示用默认桌面 Up主名称.xlsx；也可传 ~/Desktop/xx.xlsx

    返回：
      规范化后的绝对路径（例如 /Users/apple/Desktop/Up主名称.xlsx）

    抛出：
      ValueError —— 路径不在 ALLOWED_EXCEL_ROOTS 允许范围内（由调用方捕获并转成 envelope）
    """
    raw = excel_path or get_default_excel_path()
    # abspath：转成绝对路径；expanduser：把 ~/ 展开成家目录
    path = os.path.abspath(os.path.expanduser(raw))

    for root in ALLOWED_EXCEL_ROOTS:
        allowed_root = os.path.abspath(root)
        # 允许「正好是根目录」或「根目录下的任意子路径」
        if path == allowed_root or path.startswith(allowed_root + os.sep):
            return path

    allowed = ", ".join(ALLOWED_EXCEL_ROOTS)
    raise ValueError(
        f"excel_path 不在允许目录内: {path}。允许: {allowed}"
    )


def parse_fans_count(raw: str) -> dict:
    """
    把 B 站页面上抓到的粉丝数文本，整理成 Agent 更好用的三个字段。

    例如 raw="1800万" 或 "粉丝数 65"：
      fans_count_raw      → 原始字符串
      fans_count_display  → 给人看、给 write_excel 用的 display 文本
      fans_count_value    → 尽量解析成整数（万、纯数字），解析不了则为 None
    """
    text = (raw or "").replace("粉丝数", "").strip()
    display = text or raw or ""

    value: int | None = None
    # 匹配「123.4万」这种中文单位
    m = re.match(r"^([\d.]+)\s*万$", display)
    if m:
        value = int(float(m.group(1)) * 10_000)
    else:
        # 否则去掉非数字字符，尝试当整数
        digits = re.sub(r"[^\d]", "", display)
        if digits:
            value = int(digits)

    return {
        "fans_count_raw": raw,
        "fans_count_display": display,
        "fans_count_value": value,
    }


def _normalize_fetch_result(up_name: str, result: dict, duration_ms: int) -> dict:
    """
    把 main.get_up_fans_data() 的「旧格式」转成 P0 envelope。

    main.py 历史返回示例：
      { "up_name": "...", "status": "成功获取", "fans_data": {"总粉丝数": "1800万"} }
    本函数负责映射到：
      ok=true, data.fans_count_display, meta.duration_ms 等
    """
    status = result.get("status", "")
    fans_data = result.get("fans_data") or {}
    raw_count = ""
    if isinstance(fans_data, dict):
        raw_count = fans_data.get("总粉丝数", "") or ""

    if status == "成功获取" and raw_count:
        parsed = parse_fans_count(str(raw_count))
        return _tool_ok(
            "fetch_fans_data",
            {
                "up_name": up_name,
                "status": "success",
                **parsed,
            },
            meta={"duration_ms": duration_ms, "retryable": False},
        )

    message = status or "提取失败"
    retryable = "抓取异常" in message
    return _tool_err(
        "fetch_fans_data",
        "FETCH_FAILED",
        message,
        retryable=retryable,
        data={"up_name": up_name, "status": "failed"},
        meta={"duration_ms": duration_ms},
    )


# =============================================================================
# 对外暴露的三个「工具」—— REST / MCP 最终都调这三个函数
# =============================================================================

def tool_get_up_list(
    excel_path: str | None = None,
    sheet_name: str = "Sheet1",
    name_column: str | None = None,
    limit: int | None = None,
) -> dict:
    """
    工具 1：从 Excel 读取 UP 主名单。

    参数（均可选，不传则用默认）：
      excel_path   → 哪张表；None = 桌面 Up主名称.xlsx
      sheet_name   → 哪个工作表，默认 Sheet1
      name_column  → UP 主在哪一列；None = 第一列
      limit        → 最多返回几条（防止超大表拖垮 Agent）

    返回：标准 envelope；成功时 data.up_names 为 list[str]
    """
    tool = "get_up_list"

    # --- 1. 路径护栏 ---
    try:
        path = resolve_excel_path(excel_path)
    except ValueError as exc:
        return _tool_err(tool, "PATH_NOT_ALLOWED", str(exc))

    # --- 2. 文件是否存在 ---
    if not os.path.exists(path):
        return _tool_err(
            tool,
            "FILE_NOT_FOUND",
            f"Excel 不存在: {path}",
            meta={"excel_path": path, "sheet_name": sheet_name},
        )

    # --- 3. 用 pandas 读 Excel ---
    try:
        df = pd.read_excel(path, sheet_name=sheet_name)
    except Exception as exc:
        return _tool_err(
            tool,
            "READ_FAILED",
            f"读取 Excel 失败: {exc}",
            meta={"excel_path": path, "sheet_name": sheet_name},
        )

    # --- 4. 确定 UP 主列 ---
    if name_column:
        if name_column not in df.columns:
            return _tool_err(
                tool,
                "COLUMN_NOT_FOUND",
                f"列不存在: {name_column}",
                meta={"excel_path": path, "sheet_name": sheet_name},
            )
        col = name_column
    else:
        col = df.columns[0]  # 默认第一列

    # --- 5. 提取非空 UP 主名 ---
    names = [str(x).strip() for x in df[col].dropna().tolist() if str(x).strip()]
    if limit is not None and limit > 0:
        names = names[:limit]

    return _tool_ok(
        tool,
        {"up_names": names, "count": len(names)},
        meta={
            "excel_path": path,
            "sheet_name": sheet_name,
            "column_used": col,
        },
    )


def tool_fetch_fans_data(up_name: str, dry_run: bool = False) -> dict:
    """
    工具 2：抓取指定 UP 主的粉丝数。

    参数：
      up_name  → 必填，B 站 UP 主名称
      dry_run  → True =「空跑」：只检查 bilibili_state.json 是否存在，不打开浏览器
                 False = 调用 main.get_up_fans_data 真抓（慢，30s~2min）

    返回：标准 envelope；成功时请用 data.fans_count_display 写入 Excel
    """
    tool = "fetch_fans_data"
    up_name = (up_name or "").strip()
    if not up_name:
        return _tool_err(tool, "INVALID_INPUT", "up_name 不能为空")

    # --- dry_run 分支：不启动 Playwright ---
    if dry_run:
        if not os.path.exists(LOGIN_STATE_FILE):
            return _tool_err(
                tool,
                "LOGIN_STATE_MISSING",
                "未找到 bilibili_state.json，请先执行: python main.py login",
                retryable=False,
                data={"up_name": up_name, "status": "dry_run_failed"},
            )
        return _tool_ok(
            tool,
            {
                "up_name": up_name,
                "status": "dry_run",
                "fans_count_raw": None,
                "fans_count_display": None,
                "fans_count_value": None,
            },
            meta={"duration_ms": 0, "dry_run": True},
        )

    # --- 真抓取：委托 main.py 里的 Playwright 逻辑 ---
    started = time.perf_counter()
    try:
        result = get_up_fans_data(up_name)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        code = "LOGIN_STATE_MISSING" if "bilibili_state.json" in str(exc) else "FETCH_FAILED"
        return _tool_err(
            tool,
            code,
            str(exc),
            retryable=code != "LOGIN_STATE_MISSING",
            data={"up_name": up_name, "status": "failed"},
            meta={"duration_ms": duration_ms},
        )

    duration_ms = int((time.perf_counter() - started) * 1000)
    return _normalize_fetch_result(up_name, result, duration_ms)


def tool_write_excel(
    up_name: str,
    fans_count: str,
    excel_path: str | None = None,
    sheet_name: str = "Sheet1",
    target_column: str = "粉丝数",
    write_mode: WriteMode = "update",
) -> dict:
    """
    工具 3：把粉丝数写回 Excel。

    参数：
      up_name, fans_count  → 必填
      excel_path           → 可选，默认桌面表
      target_column        → 写入哪一列，默认「粉丝数」
      write_mode：
        "update"             → 必须已有该 UP 主行，否则 UP_NOT_FOUND
        "append_if_missing"  → 没有该行就追加一行

    返回：标准 envelope；成功时 data.rows_updated 表示改了几行
    """
    tool = "write_excel"
    up_name = (up_name or "").strip()
    if not up_name:
        return _tool_err(tool, "INVALID_INPUT", "up_name 不能为空")
    if fans_count is None or str(fans_count).strip() == "":
        return _tool_err(tool, "INVALID_INPUT", "fans_count 不能为空")

    fans_count = str(fans_count).strip()

    try:
        path = resolve_excel_path(excel_path)
    except ValueError as exc:
        return _tool_err(tool, "PATH_NOT_ALLOWED", str(exc))

    if not os.path.exists(path):
        return _tool_err(
            tool,
            "FILE_NOT_FOUND",
            f"Excel 不存在: {path}",
            meta={"excel_path": path, "write_mode": write_mode},
        )

    try:
        df = pd.read_excel(path, sheet_name=sheet_name)
        up_col = df.columns[0]  # UP 主名默认在第一列

        if target_column not in df.columns:
            df[target_column] = ""
        df[target_column] = df[target_column].astype(str)

        match_idx = df[df[up_col].astype(str) == up_name].index
        rows_updated = 0

        if len(match_idx) > 0:
            # 找到行：更新粉丝数
            df.loc[match_idx, target_column] = fans_count
            rows_updated = len(match_idx)
        elif write_mode == "append_if_missing":
            # 没找到行且允许追加：新建一行
            new_row = {col: "" for col in df.columns}
            new_row[up_col] = up_name
            new_row[target_column] = fans_count
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            rows_updated = 1
        else:
            return _tool_err(
                tool,
                "UP_NOT_FOUND",
                f"Excel 中未找到 UP 主: {up_name}（write_mode=update）",
                meta={
                    "excel_path": path,
                    "sheet_name": sheet_name,
                    "write_mode": write_mode,
                },
            )

        df.to_excel(path, sheet_name=sheet_name, index=False)
        return _tool_ok(
            tool,
            {"up_name": up_name, "rows_updated": rows_updated},
            meta={
                "excel_path": path,
                "sheet_name": sheet_name,
                "target_column": target_column,
                "write_mode": write_mode,
            },
        )
    except Exception as exc:
        return _tool_err(
            tool,
            "WRITE_FAILED",
            f"写入 Excel 失败: {exc}",
            meta={"excel_path": path, "write_mode": write_mode},
        )
