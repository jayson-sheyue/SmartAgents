#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B 站全站热门选品 — 本地冒烟（不经 LLM / ADK）。"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from rpa_tools import tool_fetch_hot_videos


def _print(title: str, result: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Test fetch_hot_videos without LLM")
    parser.add_argument("--source", choices=("popular", "ranking"), default="popular")
    parser.add_argument("--period", choices=("day", "week"), default="day")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--no-excel", action="store_true", help="Skip Excel export")
    args = parser.parse_args()

    result = tool_fetch_hot_videos(
        source=args.source,
        period=args.period,
        limit=args.limit,
        export_excel=not args.no_excel,
    )
    _print("fetch_hot_videos", result)
    if not result.get("ok"):
        return 1

    data = result.get("data") or {}
    videos = data.get("videos") or []
    summary = data.get("summary") or {}
    print(f"\n✅ {len(videos)} videos | partitions={summary.get('partition_distribution')}")
    if data.get("excel_path"):
        print(f"📄 Excel: {data['excel_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
