# -*- coding: utf-8 -*-
"""Etsy tool registry — single source of truth for MCP bindings.

Manifest constants are import-safe for Agent Engine / A2A.
L1 TOOL_IMPLEMENTATIONS load lazily when MCP servers need them.
"""

from __future__ import annotations

from typing import Any, Callable

from domains.shared.manifest import DomainManifest

MANIFEST = DomainManifest.load("etsy")

AGENT_NAME = MANIFEST.agent_name
STANDALONE_NAME = MANIFEST.standalone_name
SKILL_IDS = MANIFEST.skills
MCP_TOOL_NAMES = MANIFEST.mcp_tools


def _load_tool_implementations() -> dict[str, Callable[..., dict[str, Any]]]:
    from domains.etsy.etsy_tools import (
        tool_etsy_check_credentials,
        tool_etsy_fetch_and_export_reviews,
        tool_etsy_fetch_listing_images,
        tool_etsy_fetch_listing_reviews,
        tool_etsy_generate_listing_scene_variants,
        tool_etsy_get_listing,
        tool_etsy_write_reviews_excel,
    )
    from domains.etsy.preset_tools import (
        tool_get_image_preset,
        tool_list_image_presets,
        tool_polish_scene_brief,
        tool_save_image_preset,
    )

    return {
        "etsy_check_credentials": tool_etsy_check_credentials,
        "etsy_fetch_listing_reviews": tool_etsy_fetch_listing_reviews,
        "etsy_write_reviews_excel": tool_etsy_write_reviews_excel,
        "etsy_fetch_and_export_reviews": tool_etsy_fetch_and_export_reviews,
        "etsy_get_listing": tool_etsy_get_listing,
        "etsy_fetch_listing_images": tool_etsy_fetch_listing_images,
        "etsy_list_image_presets": tool_list_image_presets,
        "etsy_get_image_preset": tool_get_image_preset,
        "etsy_save_image_preset": tool_save_image_preset,
        "etsy_polish_scene_brief": tool_polish_scene_brief,
        "etsy_generate_listing_scene_variants": tool_etsy_generate_listing_scene_variants,
    }


def __getattr__(name: str) -> Any:
    if name == "TOOL_IMPLEMENTATIONS":
        value = _load_tool_implementations()
        globals()["TOOL_IMPLEMENTATIONS"] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
