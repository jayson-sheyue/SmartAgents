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
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd
import requests
from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

WriteMode = Literal["update", "append_if_missing"]
HotVideoSource = Literal["popular", "ranking"]
HotVideoPeriod = Literal["day", "week"]

BILIBILI_API_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

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


def get_default_trend_output_dir() -> str:
    return os.path.join(os.path.expanduser("~"), "Documents", "BilibiliRPA")


def resolve_trend_output_path(excel_path: str | None, *, prefix: str) -> str:
    if excel_path:
        path = os.path.abspath(os.path.expanduser(excel_path))
        for root in ALLOWED_EXCEL_ROOTS:
            allowed_root = os.path.abspath(root)
            if path == allowed_root or path.startswith(allowed_root + os.sep):
                return path
        allowed = ", ".join(ALLOWED_EXCEL_ROOTS)
        raise ValueError(f"excel_path 不在允许目录内: {path}。允许: {allowed}")

    out_dir = get_default_trend_output_dir()
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(out_dir, f"{prefix}_{stamp}.xlsx")


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
# Playwright RPA（已下线 MCP；仅本地遗留函数懒加载 playwright）
# =============================================================================


def _load_playwright():
    from playwright.sync_api import sync_playwright

    try:
        from playwright_stealth import stealth_sync
    except ImportError:
        from playwright_stealth import Stealth

        def stealth_sync(page):  # type: ignore
            Stealth().apply_stealth_sync(page)

    return sync_playwright, stealth_sync


def get_up_fans_data(up_name: str) -> dict:
    """根据 UP 主名称，自动化抓取粉丝数（Playwright 同步 API）。"""
    sync_playwright, stealth_sync = _load_playwright()
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
    sync_playwright, stealth_sync = _load_playwright()
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


# =============================================================================
# 全站热门 / 爆款抓取（公开 API，无需登录态）
# =============================================================================


def _parse_count_value(raw: int | float | str | None) -> int:
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip().replace(",", "")
    if not text:
        return 0
    m = re.match(r"^([\d.]+)\s*万$", text)
    if m:
        return int(float(m.group(1)) * 10_000)
    m = re.match(r"^([\d.]+)\s*亿$", text)
    if m:
        return int(float(m.group(1)) * 100_000_000)
    digits = re.sub(r"[^\d]", "", text)
    return int(digits) if digits else 0


def _rate_pct(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 3)


def _engagement_score(view: int, like: int, coin: int, favorite: int, share: int) -> float | None:
    if view <= 0:
        return None
    raw = (like + coin * 2 + favorite * 1.5 + share * 3) / view * 100
    return round(raw, 3)


def _format_pub_time(ts: int | None) -> str | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M"
    )


def _parse_duration_sec(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    if ":" in text:
        parts = text.split(":")
        try:
            nums = [int(p) for p in parts]
        except ValueError:
            return 0
        if len(nums) == 2:
            return nums[0] * 60 + nums[1]
        if len(nums) == 3:
            return nums[0] * 3600 + nums[1] * 60 + nums[2]
    return 0


def _normalize_hot_video_item(item: dict[str, Any], *, rank: int, source: str) -> dict[str, Any]:
    stat = item.get("stat") or {}
    owner = item.get("owner") or {}
    bvid = item.get("bvid") or ""
    view = _parse_count_value(stat.get("view"))
    like = _parse_count_value(stat.get("like"))
    coin = _parse_count_value(stat.get("coin"))
    favorite = _parse_count_value(stat.get("favorite"))
    share = _parse_count_value(stat.get("share"))
    danmaku = _parse_count_value(stat.get("danmaku"))
    reply = _parse_count_value(stat.get("reply"))
    duration_sec = _parse_duration_sec(item.get("duration"))
    rcmd = item.get("rcmd_reason")
    if isinstance(rcmd, dict):
        rcmd_text = (rcmd.get("content") or "").strip() or None
    elif rcmd:
        rcmd_text = str(rcmd).strip() or None
    else:
        rcmd_text = None
    return {
        "rank": rank,
        "bvid": bvid,
        "aid": item.get("aid"),
        "title": (item.get("title") or "").strip(),
        "url": f"https://www.bilibili.com/video/{bvid}" if bvid else "",
        "partition": (item.get("tname") or item.get("typename") or "").strip(),
        "duration_sec": duration_sec,
        "duration_display": (
            f"{duration_sec // 60}:{duration_sec % 60:02d}" if duration_sec else ""
        ),
        "pub_time": _format_pub_time(item.get("pubdate") or item.get("ctime")),
        "up_name": (owner.get("name") or "").strip(),
        "up_mid": owner.get("mid"),
        "view": view,
        "like": like,
        "coin": coin,
        "favorite": favorite,
        "share": share,
        "danmaku": danmaku,
        "reply": reply,
        "like_rate_pct": _rate_pct(like, view),
        "coin_rate_pct": _rate_pct(coin, view),
        "favorite_rate_pct": _rate_pct(favorite, view),
        "engagement_score": _engagement_score(view, like, coin, favorite, share),
        "rcmd_reason": rcmd_text,
        "source": source,
    }


def _fetch_popular_videos(limit: int) -> list[dict[str, Any]]:
    page_size = min(max(limit, 1), 50)
    pages = (limit + page_size - 1) // page_size
    videos: list[dict[str, Any]] = []
    for page in range(1, pages + 1):
        resp = requests.get(
            "https://api.bilibili.com/x/web-interface/popular",
            params={"ps": page_size, "pn": page},
            headers=BILIBILI_API_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or f"popular API code={payload.get('code')}")
        batch = payload.get("data", {}).get("list") or []
        for item in batch:
            videos.append(_normalize_hot_video_item(item, rank=len(videos) + 1, source="popular"))
            if len(videos) >= limit:
                return videos
        if not batch:
            break
        time.sleep(0.4)
    return videos[:limit]


def _fetch_ranking_videos(*, limit: int, period: HotVideoPeriod, rid: int) -> list[dict[str, Any]]:
    day = 1 if period == "day" else 7
    resp = requests.get(
        "https://api.bilibili.com/x/web-interface/ranking",
        params={"rid": rid, "day": day, "original": 0},
        headers=BILIBILI_API_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message") or f"ranking API code={payload.get('code')}")
    items = payload.get("data", {}).get("list") or []
    videos = [
        _normalize_hot_video_item(item, rank=idx + 1, source=f"ranking_{period}")
        for idx, item in enumerate(items[:limit])
    ]
    return videos


def _summarize_hot_videos(videos: list[dict[str, Any]]) -> dict[str, Any]:
    if not videos:
        return {"count": 0}

    partition_counts: dict[str, int] = {}
    durations: list[int] = []
    views: list[int] = []
    scores: list[float] = []
    for v in videos:
        part = v.get("partition") or "未知"
        partition_counts[part] = partition_counts.get(part, 0) + 1
        if v.get("duration_sec"):
            durations.append(int(v["duration_sec"]))
        if v.get("view"):
            views.append(int(v["view"]))
        if v.get("engagement_score") is not None:
            scores.append(float(v["engagement_score"]))

    top_partitions = sorted(partition_counts.items(), key=lambda x: (-x[1], x[0]))[:8]
    by_engagement = sorted(
        videos,
        key=lambda x: (x.get("engagement_score") is not None, x.get("engagement_score") or 0),
        reverse=True,
    )[:5]

    def _median(nums: list[int | float]) -> float | None:
        if not nums:
            return None
        ordered = sorted(nums)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return round(float(ordered[mid]), 2)
        return round((ordered[mid - 1] + ordered[mid]) / 2, 2)

    return {
        "count": len(videos),
        "partition_distribution": dict(top_partitions),
        "median_duration_min": (
            round(_median(durations) / 60, 2) if durations and _median(durations) else None
        ),
        "median_view": int(_median(views)) if views and _median(views) is not None else None,
        "median_engagement_score": _median(scores),
        "top_engagement_bvids": [v.get("bvid") for v in by_engagement if v.get("bvid")],
        "top_engagement_titles": [v.get("title") for v in by_engagement if v.get("title")],
    }


def _videos_to_dataframe(videos: list[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for v in videos:
        rows.append(
            {
                "排名": v.get("rank"),
                "标题": v.get("title"),
                "BV号": v.get("bvid"),
                "链接": v.get("url"),
                "分区": v.get("partition"),
                "UP主": v.get("up_name"),
                "时长": v.get("duration_display"),
                "发布时间": v.get("pub_time"),
                "播放": v.get("view"),
                "点赞": v.get("like"),
                "投币": v.get("coin"),
                "收藏": v.get("favorite"),
                "分享": v.get("share"),
                "弹幕": v.get("danmaku"),
                "评论": v.get("reply"),
                "点赞率%": v.get("like_rate_pct"),
                "投币率%": v.get("coin_rate_pct"),
                "收藏率%": v.get("favorite_rate_pct"),
                "互动分": v.get("engagement_score"),
                "推荐理由": v.get("rcmd_reason"),
                "数据源": v.get("source"),
            }
        )
    return pd.DataFrame(rows)


def _write_hot_videos_excel(
    videos: list[dict[str, Any]],
    *,
    excel_path: str,
    sheet_name: str = "热门视频",
) -> None:
    df = _videos_to_dataframe(videos)
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)


def tool_fetch_hot_videos(
    source: HotVideoSource = "popular",
    period: HotVideoPeriod = "day",
    limit: int = 50,
    rid: int = 0,
    export_excel: bool = False,
    excel_path: str | None = None,
    sheet_name: str = "热门视频",
) -> dict:
    """抓取热门视频；默认只返回 JSON。export_excel=True 时写入 GCS（需 MCP_ARTIFACT_GCS_BUCKET）。"""
    tool = "fetch_hot_videos"
    limit = max(1, min(int(limit or 50), 100))
    if source not in ("popular", "ranking"):
        return _tool_err(tool, "INVALID_INPUT", f"不支持的 source: {source}")
    if period not in ("day", "week"):
        return _tool_err(tool, "INVALID_INPUT", f"不支持的 period: {period}")

    started = time.perf_counter()
    try:
        if source == "popular":
            videos = _fetch_popular_videos(limit)
        else:
            videos = _fetch_ranking_videos(limit=limit, period=period, rid=rid)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return _tool_err(
            tool,
            "FETCH_FAILED",
            str(exc),
            retryable=True,
            meta={"duration_ms": duration_ms, "source": source, "period": period},
        )

    summary = _summarize_hot_videos(videos)
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    meta: dict[str, Any] = {
        "duration_ms": int((time.perf_counter() - started) * 1000),
        "source": source,
        "period": period if source == "ranking" else None,
        "rid": rid if source == "ranking" else None,
        "limit": limit,
        "fetched_at": fetched_at,
    }

    artifact: dict[str, Any] | None = None
    if export_excel:
        try:
            prefix = f"hot_{source}" + (f"_{period}" if source == "ranking" else "")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{prefix}_{stamp}.xlsx"
            if excel_path:
                # 兼容本地调试：显式路径仍写本地；云上请走 GCS
                out_path = resolve_trend_output_path(excel_path, prefix=prefix)
                _write_hot_videos_excel(videos, excel_path=out_path, sheet_name=sheet_name)
                meta["excel_path"] = out_path
            else:
                from domains.shared.artifact_store import write_dataframe_excel_to_gcs

                artifact = write_dataframe_excel_to_gcs(
                    _videos_to_dataframe(videos),
                    filename=filename,
                    sheet_name=sheet_name,
                    subdomain="bilibili/hot",
                )
                meta["gcs_uri"] = artifact.get("gcs_uri")
                meta["signed_url"] = artifact.get("signed_url")
            meta["sheet_name"] = sheet_name
        except ValueError as exc:
            return _tool_err(
                tool,
                "GCS_BUCKET_MISSING",
                str(exc),
                data={"videos": videos, "summary": summary, "fetched_at": fetched_at},
                meta=meta,
            )
        except Exception as exc:
            return _tool_err(
                tool,
                "WRITE_FAILED",
                f"导出 Excel 失败: {exc}",
                data={"videos": videos, "summary": summary, "fetched_at": fetched_at},
                meta=meta,
            )

    data: dict[str, Any] = {
        "videos": videos,
        "summary": summary,
        "fetched_at": fetched_at,
    }
    if artifact:
        data.update(
            {
                "gcs_uri": artifact.get("gcs_uri"),
                "signed_url": artifact.get("signed_url"),
                "rows_written": len(videos),
            }
        )
    elif meta.get("excel_path"):
        data["excel_path"] = meta["excel_path"]

    return _tool_ok(tool, data, meta=meta)


def tool_export_hot_videos_excel(
    videos: list[dict[str, Any]],
    excel_path: str | None = None,
    sheet_name: str = "热门视频",
) -> dict:
    tool = "export_hot_videos_excel"
    if not videos:
        return _tool_err(tool, "INVALID_INPUT", "videos 不能为空")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        if excel_path:
            out_path = resolve_trend_output_path(excel_path, prefix="hot_export")
            _write_hot_videos_excel(videos, excel_path=out_path, sheet_name=sheet_name)
            return _tool_ok(
                tool,
                {"rows_written": len(videos), "excel_path": out_path},
                meta={"excel_path": out_path, "sheet_name": sheet_name},
            )
        from domains.shared.artifact_store import write_dataframe_excel_to_gcs

        artifact = write_dataframe_excel_to_gcs(
            _videos_to_dataframe(videos),
            filename=f"hot_export_{stamp}.xlsx",
            sheet_name=sheet_name,
            subdomain="bilibili/hot",
        )
    except ValueError as exc:
        return _tool_err(tool, "GCS_BUCKET_MISSING", str(exc))
    except Exception as exc:
        return _tool_err(tool, "WRITE_FAILED", str(exc))

    return _tool_ok(
        tool,
        {
            "rows_written": len(videos),
            "gcs_uri": artifact.get("gcs_uri"),
            "signed_url": artifact.get("signed_url"),
        },
        meta={
            "gcs_uri": artifact.get("gcs_uri"),
            "signed_url": artifact.get("signed_url"),
            "sheet_name": sheet_name,
        },
    )


__all__ = [
    "ALLOWED_EXCEL_ROOTS",
    "LOGIN_STATE_FILE",
    "LOGIN_HINT",
    "WriteMode",
    "get_default_excel_path",
    "get_default_trend_output_dir",
    "resolve_excel_path",
    "resolve_trend_output_path",
    "read_up_names_from_excel",
    "write_fans_to_excel",
    "get_up_fans_data",
    "manual_login",
    "parse_fans_count",
    "tool_get_up_list",
    "tool_fetch_fans_data",
    "tool_write_excel",
    "tool_fetch_hot_videos",
    "tool_export_hot_videos_excel",
]
