#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0 本地冒烟测试脚本（不经过大模型，直接调用 rpa_tools.py）

【这个文件是干什么的？】
  像一份「自动检查清单」：按固定顺序调用 get_up_list / fetch / write，
  打印 JSON 结果，帮你确认 P0 工具契约（envelope、路径护栏）是否正常。

【和 main.py 的区别】
  - main.py：会启动 Gemini 大模型，由 AI 决定调什么工具（慢、不适合测契约）
  - 本脚本：纯 Python 顺序调用，无 AI（快、适合测工具本身）

【默认会测哪几步？（不加任何 -- 参数时）】
  步骤 1：读桌面默认 Excel（真数据）
  步骤 2：故意传非法路径 /etc/passwd（测路径护栏）
  步骤 3：fetch dry_run（只查登录态，不开浏览器）
  步骤 4：在 ~/Documents/BilibiliRPA/_p0_test.xlsx 上用「假 UP 主名」测 write
  （步骤 5 只有加 --live-fetch 才会跑：真浏览器抓取）

【假数据在哪？】
  见下方「步骤 4」里的 pd.DataFrame(...)，会现场生成测试 Excel，不会改你桌面默认表。

【怎么用？】
  python scripts/test_p0_local.py
  python scripts/test_p0_local.py --live-fetch --up-name "老番茄"
  python scripts/test_p0_local.py --live-fetch --write-after-fetch --up-name "老番茄"
"""

from __future__ import annotations

import argparse  # Python 标准库：解析命令行里的 --live-fetch 等 flag
import json
import os
import sys

# ---------------------------------------------------------------------------
# 把「项目根目录」加入 Python 搜索路径
# ---------------------------------------------------------------------------
# 本文件在 scripts/ 子目录里；rpa_tools.py 在项目根目录。
# 若不加入根目录，import rpa_tools 会报 ModuleNotFoundError。
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rpa_tools import tool_fetch_fans_data, tool_get_up_list, tool_write_excel


def _print(title: str, result: dict) -> None:
    """把一次工具调用的结果漂亮地打印到终端（带标题 + 缩进 JSON）。"""
    print(f"\n=== {title} ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    # -----------------------------------------------------------------------
    # 命令行参数（CLI flags）—— 用 argparse 解析你在终端敲的 --xxx
    # -----------------------------------------------------------------------
    # 例如：python scripts/test_p0_local.py --live-fetch --up-name "老番茄"
    # 会被解析成 args.live_fetch=True, args.up_name="老番茄"
    parser = argparse.ArgumentParser(
        description="P0 rpa_tools 本地测试（详见本文件顶部文档字符串）"
    )
    parser.add_argument(
        "--live-fetch",
        action="store_true",  # 出现此 flag 则为 True，不出现则为 False
        help="是否执行真实 RPA 抓取（会弹出浏览器，较慢，需 bilibili_state.json）",
    )
    parser.add_argument(
        "--up-name",
        default="老番茄",
        help="--live-fetch 时要抓取哪个 UP 主（默认：老番茄）",
    )
    parser.add_argument(
        "--write-after-fetch",
        action="store_true",
        help="仅在 --live-fetch 且抓取成功时，把粉丝数写入 _p0_test.xlsx",
    )
    args = parser.parse_args()  # 真正读取 sys.argv 并填充 args

    # -----------------------------------------------------------------------
    # 步骤 1：读名单（使用默认桌面 Excel，真实数据）
    # -----------------------------------------------------------------------
    _print("get_up_list (default)", tool_get_up_list())

    # -----------------------------------------------------------------------
    # 步骤 2：路径护栏（故意传系统路径，必须失败）
    # -----------------------------------------------------------------------
    bad = tool_get_up_list(excel_path="/etc/passwd")
    _print("get_up_list (bad path)", bad)
    # assert：若护栏没拦住（ok 仍为 true），脚本立刻报错退出，说明有 bug
    assert not bad["ok"] and bad["error"]["code"] == "PATH_NOT_ALLOWED"

    # -----------------------------------------------------------------------
    # 步骤 3：dry_run（空跑抓取，不启动 Playwright）
    # -----------------------------------------------------------------------
    _print("fetch dry_run", tool_fetch_fans_data(args.up_name, dry_run=True))

    # -----------------------------------------------------------------------
    # 步骤 4：写入测试（假数据 + 专用测试文件，避免污染桌面 Up主名称.xlsx）
    # -----------------------------------------------------------------------
    test_dir = os.path.join(os.path.expanduser("~"), "Documents", "BilibiliRPA")
    os.makedirs(test_dir, exist_ok=True)  # 目录不存在则创建
    test_xlsx = os.path.join(test_dir, "_p0_test.xlsx")

    import pandas as pd

    # 【假数据入口】下面这一行：在测试文件里只放一行「测试UP主A」
    pd.DataFrame({"UP主": ["测试UP主A"], "粉丝数": [""]}).to_excel(
        test_xlsx, sheet_name="Sheet1", index=False
    )

    # 4a：update 模式 —— 更新已存在的「测试UP主A」的粉丝数为 12345
    _print(
        "write update",
        tool_write_excel(
            up_name="测试UP主A",
            fans_count="12345",
            excel_path=test_xlsx,
            write_mode="update",
        ),
    )
    # 4b：append_if_missing —— 表里没有「测试UP主B」，追加一行 999
    _print(
        "write append",
        tool_write_excel(
            up_name="测试UP主B",
            fans_count="999",
            excel_path=test_xlsx,
            write_mode="append_if_missing",
        ),
    )

    # -----------------------------------------------------------------------
    # 步骤 5（可选）：真实 RPA 抓取 —— 只有命令行带了 --live-fetch 才执行
    # -----------------------------------------------------------------------
    if args.live_fetch:
        fetch_result = tool_fetch_fans_data(args.up_name, dry_run=False)
        _print("fetch live", fetch_result)

        # 只有同时带了 --write-after-fetch 且抓取成功，才写入测试 Excel
        if args.write_after_fetch and fetch_result.get("ok"):
            display = fetch_result["data"].get("fans_count_display") or ""
            _print(
                "write after fetch",
                tool_write_excel(
                    up_name=args.up_name,
                    fans_count=display,
                    excel_path=test_xlsx,
                    write_mode="append_if_missing",
                ),
            )
        elif args.write_after_fetch:
            print("\n⚠️ fetch 未成功，跳过 write")

    print("\n✅ P0 本地契约测试完成（未含 live-fetch 时未启动浏览器）")
    return 0


# Python 惯例：直接运行此文件时执行 main()；被别的文件 import 时不自动跑测试
if __name__ == "__main__":
    raise SystemExit(main())
