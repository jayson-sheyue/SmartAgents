#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Etsy 评论拉取 — 本地测试入口

用法见 etsy_agent/README.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from etsy_agent.etsy_tools import (  # noqa: E402
    DEFAULT_EXPORT_PATH,
    extract_listing_id,
    tool_etsy_check_credentials,
    tool_etsy_fetch_and_export_reviews,
)


def _print(title: str, result: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Etsy 评论 API 本地测试")
    parser.add_argument("--check-credentials", action="store_true", help="检查 .env 凭证")
    parser.add_argument("--verify-api", action="store_true", help="与 --check-credentials 联用，真实请求 Etsy")
    parser.add_argument("--listing-id", default="", help="Listing 数字 ID")
    parser.add_argument("--listing-url", default="", help="Etsy 商品页 URL")
    parser.add_argument("--live-fetch", action="store_true", help="真实拉取并写 Excel")
    parser.add_argument("--limit", type=int, default=25, help="每页条数")
    parser.add_argument("--max-pages", type=int, default=3, help="最多翻页")
    parser.add_argument("--excel-path", default=DEFAULT_EXPORT_PATH, help="导出 Excel 路径")
    args = parser.parse_args()

    if args.check_credentials:
        result = tool_etsy_check_credentials(probe=args.verify_api)
        _print("etsy_check_credentials", result)
        if not result.get("ok"):
            return 1
        if args.verify_api:
            print("\n✅ Etsy API 凭证验证通过")
        else:
            print("\n✅ .env 已配置；建议加 --verify-api 做真实探测")
        return 0

    ref = args.listing_url.strip() or args.listing_id.strip()
    if not ref:
        print("请提供 --listing-id 或 --listing-url")
        return 1
    if not extract_listing_id(ref):
        print("无法解析 listing_id")
        return 1

    cred = tool_etsy_check_credentials(probe=True)
    _print("etsy_check_credentials (verify_api)", cred)
    if not cred.get("ok"):
        return 2

    dry = tool_etsy_fetch_and_export_reviews(
        ref, limit=args.limit, max_pages=args.max_pages, excel_path=args.excel_path, dry_run=True
    )
    _print("etsy_fetch_and_export_reviews (dry_run)", dry)
    if not dry.get("ok"):
        return 3

    if not args.live_fetch:
        print("\n✅ dry_run 成功。加 --live-fetch 执行真实拉取。")
        return 0

    live = tool_etsy_fetch_and_export_reviews(
        ref, limit=args.limit, max_pages=args.max_pages, excel_path=args.excel_path, dry_run=False
    )
    _print("etsy_fetch_and_export_reviews (live_fetch)", live)
    if not live.get("ok"):
        return 4

    count = live["data"]["fetch"]["count"]
    out = live["data"]["write"]["excel_path"]
    if count <= 0 or not os.path.exists(out):
        print("\n❌ 未生成有效 Excel")
        return 5

    print(f"\n✅ 完成，评论数: {count}")
    print(f"📁 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
