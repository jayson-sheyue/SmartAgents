#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Etsy Listing 上架素材 — Phase 0 本地 L1 测试（无 LLM Agent 壳，工具直调）

用法示例：
  python scripts/test_etsy_listing_assets_local.py --list-presets

  python scripts/test_etsy_listing_assets_local.py --listing-id 786582119 --scene-swap \\
    --all-images --preset holiday_warm --dry-run --no-polish

  python scripts/test_etsy_listing_assets_local.py --listing-id 786582119 --scene-swap \\
    --all-images --preset nordic_lifestyle --generate --no-gcs --skip-reviews

  python scripts/test_etsy_listing_assets_local.py --save-preset rainforest_mist \\
    --preset-label "雨林晨雾" --scene-default "tropical rainforest morning mist, lush greenery"

  ./scripts/run_adk_etsy_agent.sh
"""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from domains.etsy.etsy_tools import (  # noqa: E402
    tool_etsy_generate_listing_assets,
    tool_etsy_generate_listing_scene_variants,
    tool_etsy_get_listing,
    tool_etsy_summarize_reviews_for_prompt,
)
from domains.etsy.image_tools import (  # noqa: E402
    image_env_config,
    tool_check_image_config,
)
from domains.etsy.preset_tools import (  # noqa: E402
    tool_list_image_presets,
    tool_save_image_preset,
)

TEXT_TO_IMAGE_DEFAULT_STYLE = "clean nordic e-commerce lifestyle product scene"


def _print(title: str, result: dict) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Etsy listing 上架素材 L1 测试")
    parser.add_argument("--listing-id", default="786582119", help="Etsy listing 数字 ID")
    parser.add_argument("--listing-url", default="", help="可选完整商品 URL")
    parser.add_argument("--dry-run", action="store_true", help="mock 生图/GCS，测编排")
    parser.add_argument("--generate", action="store_true", help="真实调用生图（会产生费用）")
    parser.add_argument("--no-gcs", action="store_true", help="生图后只写本地，不上传 GCS")
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="生图张数：文生图 1-4；scene-swap 时 0=全部附图",
    )
    parser.add_argument("--style", default=None, help="显式场景风格（覆盖 preset/infer）")
    parser.add_argument("--preset", default=None, help="生图预设 id，如 holiday_warm")
    parser.add_argument("--custom-scene", default=None, help="自然语言自定义场景（优先级最高）")
    parser.add_argument(
        "--infer-style",
        action="store_true",
        help="无 preset/custom 时从 tags/描述规则推断",
    )
    parser.add_argument(
        "--no-polish",
        action="store_true",
        help="不用 LLM 润色 scene（dry-run 省钱）",
    )
    parser.add_argument("--skip-reviews", action="store_true", help="不从评论提炼关键词")
    parser.add_argument("--scene-swap", action="store_true", help="参考附图换场景")
    parser.add_argument(
        "--all-images",
        action="store_true",
        help="scene-swap：按 listing 全部附图逐张参考",
    )
    parser.add_argument("--list-presets", action="store_true", help="列出预设后退出")
    parser.add_argument("--save-preset", default=None, help="保存预设 id 到本机目录")
    parser.add_argument("--preset-label", default="", help="配合 --save-preset")
    parser.add_argument("--scene-default", default="", help="配合 --save-preset")
    parser.add_argument("--preset-desc", default="", help="配合 --save-preset")
    parser.add_argument("--overwrite-preset", action="store_true", help="覆盖已有预设")
    parser.add_argument("--show-config", action="store_true", help="打印生图配置后退出")
    args = parser.parse_args()

    if args.list_presets:
        _print("list_image_presets", tool_list_image_presets())
        return 0

    if args.save_preset:
        if not args.scene_default.strip():
            print("❌ --save-preset 需配合 --scene-default")
            return 1
        saved = tool_save_image_preset(
            args.save_preset.strip(),
            label=args.preset_label.strip() or args.save_preset.strip(),
            description=args.preset_desc.strip(),
            scene_default=args.scene_default.strip(),
            overwrite=args.overwrite_preset,
        )
        _print("save_image_preset", saved)
        return 0 if saved.get("ok") else 1

    if args.show_config:
        cfg = image_env_config()
        check = tool_check_image_config(require_gcs_bucket=False)
        _print("image_env_config", {"ok": True, "data": cfg})
        _print("check_image_config", check)
        _print("list_image_presets", tool_list_image_presets())
        return 0 if check.get("ok") else 1

    listing_id = args.listing_id.strip()
    listing_url = args.listing_url.strip() or None

    _print("Step 0: image_env_config", {"ok": True, "data": image_env_config()})

    _print("Step 1: etsy_get_listing", {})
    listing = tool_etsy_get_listing(listing_id, listing_url=listing_url)
    _print("etsy_get_listing", listing)
    if not listing.get("ok"):
        return 1

    if not args.skip_reviews and not args.scene_swap:
        _print("Step 2: summarize_reviews_for_prompt", {})
        summ = tool_etsy_summarize_reviews_for_prompt(listing_id, listing_url=listing_url)
        _print("etsy_summarize_reviews_for_prompt", summ)

    if not args.dry_run and not args.generate:
        print(
            "\n✅ 读 listing 完成。加 --dry-run / --generate；"
            "scene-swap 加 --preset 或 --custom-scene；列预设 --list-presets。"
        )
        return 0

    polish = not args.no_polish

    if args.scene_swap:
        _print("Step 3: generate_listing_scene_variants", {})
        package = tool_etsy_generate_listing_scene_variants(
            listing_url or listing_id,
            count=args.count,
            all_images=args.all_images,
            preset_id=args.preset,
            custom_scene=args.custom_scene,
            polish_with_llm=polish,
            style=args.style,
            infer_style=args.infer_style,
            upload_to_gcs=not args.no_gcs,
            dry_run=args.dry_run,
        )
        _print("etsy_generate_listing_scene_variants", package)
    else:
        _print("Step 3: generate_listing_assets", {})
        package = tool_etsy_generate_listing_assets(
            listing_url or listing_id,
            count=args.count,
            style=args.style or TEXT_TO_IMAGE_DEFAULT_STYLE,
            use_reviews=not args.skip_reviews,
            upload_to_gcs=not args.no_gcs,
            dry_run=args.dry_run,
        )
        _print("etsy_generate_listing_assets", package)

    if not package.get("ok"):
        return 1

    print("\n✅ Phase 0 L1 测试完成。Agent 演示：./scripts/run_adk_etsy_agent.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
