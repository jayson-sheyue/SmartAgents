# -*- coding: utf-8 -*-
"""
bilibili_agent/bilibili_tools.py — B 站 RPA 工具层（L1）

与 `etsy_agent/etsy_tools.py` 对称：Playwright 抓取、Excel、P0 envelope 均在此模块。
`rpa_tools.py` 为兼容 re-export（REST/MCP 调用链仍经此模块）。
"""

from __future__ import annotations

import os
import re
import time
from typing import Literal

import pandas as pd
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import stealth_sync
except ImportError:
    from playwright_stealth import Stealth

    def stealth_sync(page):
        Stealth().apply_stealth_sync(page)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

WriteMode = Literal["update", "append_if_missing"]

ALLOWED_EXCEL_ROOTS = [
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Documents", "BilibiliRPA"),
]

LOGIN_STATE_FILE = "bilibili_state.json"
LOGIN_HINT = (
    "未找到 bilibili_state.json，请先执行: "
    "python -m bilibili_agent login"
)


# =============================================================================
# Excel 路径
# =============================================================================


def get_default_excel_path() -> str:
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(desktop_path, "Up主名称.xlsx")


def resolve_excel_path(excel_path: str | None) -> str:
    raw = excel_path or get_default_excel_path()
    path = os.path.abspath(os.path.expanduser(raw))
    for root in ALLOWED_EXCEL_ROOTS:
        allowed_root = os.path.abspath(root)
        if path == allowed_root or path.startswith(allowed_root + os.sep):
            return path
    allowed = ", ".join(ALLOWED_EXCEL_ROOTS)
    raise ValueError(f"excel_path 不在允许目录内: {path}。允许: {allowed}")


def read_up_names_from_excel(file_path: str | None = None) -> list:
    """旧版 Agent 用：读取 UP 主名单（非 envelope）。"""
    if not file_path:
        file_path = get_default_excel_path()
    up_list: list = []
    if os.path.exists(file_path):
        print(f"✅ 成功找到 Excel 文件: {file_path}")
        try:
            df = pd.read_excel(file_path, sheet_name="Sheet1")
            up_list = df.iloc[:, 0].dropna().tolist()
        except Exception as e:
            print(f"❌ 读取 Excel 出错: {e}")
    else:
        print(f"⚠️ 未在 {file_path} 找到文件，使用 SOP 默认值。")
        up_list = ["schmoyoho官号"]
    return up_list


def write_fans_to_excel(up_name: str, fans_count: str, file_path: str | None = None) -> None:
    """旧版 Agent 用：写回粉丝数（非 envelope）。"""
    if not file_path:
        file_path = get_default_excel_path()
    if not os.path.exists(file_path):
        print(f"⚠️ 找不到 Excel 文件 {file_path}，无法同步数据。")
        return
    try:
        df = pd.read_excel(file_path, sheet_name="Sheet1")
        if "粉丝数" not in df.columns:
            df["粉丝数"] = ""
        df["粉丝数"] = df["粉丝数"].astype(str)
        up_col_name = df.columns[0]
        match_idx = df[df[up_col_name] == up_name].index
        if len(match_idx) > 0:
            df.loc[match_idx, "粉丝数"] = fans_count
            df.to_excel(file_path, sheet_name="Sheet1", index=False)
            print(f"📝 成功将 {up_name} 的粉丝数 ({fans_count}) 同步到 Excel 表格！")
        else:
            print(f"⚠️ 在 Excel 中未找到 UP 主: {up_name}，无法写入粉丝数。")
    except Exception as e:
        print(f"❌ 写入 Excel 出错: {e}")


# =============================================================================
# Playwright RPA
# =============================================================================


def get_up_fans_data(up_name: str) -> dict:
    """根据 UP 主名称，自动化抓取粉丝数（Playwright 同步 API）。"""
    print(f"\n🚀 开始执行 RPA 任务，当前目标 UP 主: {up_name}")
    result = {"up_name": up_name, "status": "", "fans_data": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        state_file = LOGIN_STATE_FILE

        if os.path.exists(state_file):
            print("🔑 发现本地保存的登录状态，正在尝试免密自动登录...")
            context = browser.new_context(storage_state=state_file)
            page = context.new_page()
            stealth_sync(page)
        else:
            browser.close()
            error_msg = f"⚠️ {LOGIN_HINT}"
            print(error_msg)
            raise RuntimeError(error_msg)

        try:
            page.goto("https://search.bilibili.com/all")
            page.locator("input.search-input-el").fill(up_name)
            page.locator("button.search-button").click()
            time.sleep(4)
            page.get_by_text("用户", exact=True).click()
            time.sleep(3)

            with context.expect_page() as new_page_info:
                page.locator(
                    f"a[href*='space.bilibili.com']", has_text=up_name
                ).first.click()
            new_page = new_page_info.value
            new_page.wait_for_load_state()

            print("👁️ 正在尝试提取粉丝总数...")
            fans_count_text = ""

            try:
                fans_count_text = new_page.locator(
                    "div.vui_sidebar-item-right"
                ).inner_text(timeout=3000)
                if fans_count_text:
                    print(f"🎯 通过侧边栏定位器获取到粉丝数: {fans_count_text}")
            except Exception:
                pass

            if not fans_count_text:
                try:
                    fans_element = new_page.locator(
                        "span.nav-statistics__item-text", has_text="粉丝数"
                    )
                    if fans_element.is_visible():
                        fans_count_text = fans_element.locator("..").inner_text()
                        print(f"🎯 通过顶部导航定位器获取到文本: {fans_count_text}")
                except Exception:
                    pass

            if fans_count_text:
                result["status"] = "成功获取"
                result["fans_data"] = {
                    "总粉丝数": fans_count_text.replace("粉丝数", "").strip()
                }
                print(
                    f"✅ 成功提取到 {up_name} 的粉丝数: {result['fans_data']['总粉丝数']}"
                )
            else:
                result["status"] = "提取失败"
                print("⚠️ 无法在页面上找到粉丝数元素。")
        except Exception as e:
            print(f"❌ 抓取 {up_name} 时发生错误: {str(e)}")
            result["status"] = f"抓取异常: {str(e)}"
        finally:
            browser.close()

    return result


def manual_login() -> None:
    """手动登录 B 站并保存 bilibili_state.json。"""
    print("准备进行初次手动授权登录...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context()
        page = context.new_page()
        stealth_sync(page)
        page.goto("https://passport.bilibili.com/login")
        print("\n=======================================================")
        print("👉 请在弹出的浏览器窗口中，使用【扫码】或【密码】完成登录。")
        print("👉 登录成功并看到 B 站首页后，请回到这个终端界面。")
        print("=======================================================\n")
        input("✅ 如果您已经登录成功，请按【回车键 (Enter)】继续执行脚本...")
        context.storage_state(path=LOGIN_STATE_FILE)
        print(f"💾 登录状态已成功保存至 {LOGIN_STATE_FILE}，下次运行将自动登录！")
        browser.close()


# =============================================================================
# P0 envelope 辅助
# =============================================================================


def _tool_ok(tool: str, data: dict, meta: dict | None = None) -> dict:
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
    return {
        "ok": False,
        "tool": tool,
        "data": data or {},
        "error": {"code": code, "message": message, "retryable": retryable},
        "meta": meta or {},
    }


def parse_fans_count(raw: str) -> dict:
    text = (raw or "").replace("粉丝数", "").strip()
    display = text or raw or ""
    value: int | None = None
    m = re.match(r"^([\d.]+)\s*万$", display)
    if m:
        value = int(float(m.group(1)) * 10_000)
    else:
        digits = re.sub(r"[^\d]", "", display)
        if digits:
            value = int(digits)
    return {
        "fans_count_raw": raw,
        "fans_count_display": display,
        "fans_count_value": value,
    }


def _normalize_fetch_result(up_name: str, result: dict, duration_ms: int) -> dict:
    status = result.get("status", "")
    fans_data = result.get("fans_data") or {}
    raw_count = ""
    if isinstance(fans_data, dict):
        raw_count = fans_data.get("总粉丝数", "") or ""

    if status == "成功获取" and raw_count:
        parsed = parse_fans_count(str(raw_count))
        return _tool_ok(
            "fetch_fans_data",
            {"up_name": up_name, "status": "success", **parsed},
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
# P0 对外工具（REST / MCP / ADK 进程内）
# =============================================================================


def tool_get_up_list(
    excel_path: str | None = None,
    sheet_name: str = "Sheet1",
    name_column: str | None = None,
    limit: int | None = None,
) -> dict:
    tool = "get_up_list"
    try:
        path = resolve_excel_path(excel_path)
    except ValueError as exc:
        return _tool_err(tool, "PATH_NOT_ALLOWED", str(exc))

    if not os.path.exists(path):
        return _tool_err(
            tool,
            "FILE_NOT_FOUND",
            f"Excel 不存在: {path}",
            meta={"excel_path": path, "sheet_name": sheet_name},
        )

    try:
        df = pd.read_excel(path, sheet_name=sheet_name)
    except Exception as exc:
        return _tool_err(
            tool,
            "READ_FAILED",
            f"读取 Excel 失败: {exc}",
            meta={"excel_path": path, "sheet_name": sheet_name},
        )

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
        col = df.columns[0]

    names = [str(x).strip() for x in df[col].dropna().tolist() if str(x).strip()]
    if limit is not None and limit > 0:
        names = names[:limit]

    return _tool_ok(
        tool,
        {"up_names": names, "count": len(names)},
        meta={"excel_path": path, "sheet_name": sheet_name, "column_used": col},
    )


def tool_fetch_fans_data(up_name: str, dry_run: bool = False) -> dict:
    tool = "fetch_fans_data"
    up_name = (up_name or "").strip()
    if not up_name:
        return _tool_err(tool, "INVALID_INPUT", "up_name 不能为空")

    if dry_run:
        if not os.path.exists(LOGIN_STATE_FILE):
            return _tool_err(
                tool,
                "LOGIN_STATE_MISSING",
                LOGIN_HINT,
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

    started = time.perf_counter()
    try:
        result = get_up_fans_data(up_name)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        code = (
            "LOGIN_STATE_MISSING"
            if "bilibili_state.json" in str(exc)
            else "FETCH_FAILED"
        )
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
        up_col = df.columns[0]

        if target_column not in df.columns:
            df[target_column] = ""
        df[target_column] = df[target_column].astype(str)

        match_idx = df[df[up_col].astype(str) == up_name].index
        rows_updated = 0

        if len(match_idx) > 0:
            df.loc[match_idx, target_column] = fans_count
            rows_updated = len(match_idx)
        elif write_mode == "append_if_missing":
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
