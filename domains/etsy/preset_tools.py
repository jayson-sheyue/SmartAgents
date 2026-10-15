# -*- coding: utf-8 -*-
"""
etsy_agent/preset_tools.py — 生图风格预设（内置 + 本机持久化）

目录：
  内置：etsy_agent/presets/builtin/*.yaml
  用户：~/Documents/EtsyData/presets/*.yaml（可用 ETSY_PRESET_DIR 覆盖）

环境变量：
  ETSY_PRESET_DIR          用户预设目录
  ETSY_PROMPT_MODEL        LLM 润色 scene 用文本模型（默认 gemini-2.5-flash）
  ETSY_PROMPT_LOCATION     润色模型区域（默认与 GCP_LOCATION 一致）
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from smart_agents.env_runtime import load_runtime_env

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_runtime_env(default_env_path=os.path.join(PROJECT_ROOT, ".env"))

BUILTIN_PRESET_DIR = os.path.join(os.path.dirname(__file__), "presets", "builtin")
DEFAULT_USER_PRESET_DIR = os.path.join(
    os.path.expanduser("~"), "Documents", "EtsyData", "presets"
)
_PRESET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _tool_ok(tool: str, data: dict, meta: dict | None = None) -> dict:
    return {"ok": True, "tool": tool, "data": data, "error": None, "meta": meta or {}}


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


def user_preset_dir(*, create: bool = False) -> str:
    raw = (os.getenv("ETSY_PRESET_DIR") or "").strip()
    path = os.path.abspath(os.path.expanduser(raw or DEFAULT_USER_PRESET_DIR))
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def _normalize_preset(raw: dict[str, Any], *, source: str, path: str = "") -> dict[str, Any]:
    preset_id = str(raw.get("id") or "").strip()
    if not preset_id:
        raise ValueError("preset 缺少 id")
    return {
        "id": preset_id,
        "label": str(raw.get("label") or preset_id).strip(),
        "description": str(raw.get("description") or "").strip(),
        "scene_default": str(raw.get("scene_default") or "").strip(),
        "slots": dict(raw.get("slots") or {}),
        "constraints": dict(raw.get("constraints") or {}),
        "source": source,
        "path": path,
    }


def _load_preset_file(path: str, *, source: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"预设文件格式错误: {path}")
    preset = _normalize_preset(raw, source=source, path=path)
    if not preset["scene_default"]:
        raise ValueError(f"预设 {preset['id']} 缺少 scene_default")
    return preset


def _scan_preset_dir(directory: str, *, source: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not os.path.isdir(directory):
        return out
    for name in sorted(os.listdir(directory)):
        if not name.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(directory, name)
        try:
            preset = _load_preset_file(path, source=source)
            out[preset["id"]] = preset
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return out


def load_all_presets() -> dict[str, dict[str, Any]]:
    """内置预设 + 用户目录预设（用户同名覆盖内置）。"""
    merged = _scan_preset_dir(BUILTIN_PRESET_DIR, source="builtin")
    merged.update(_scan_preset_dir(user_preset_dir(), source="user"))
    return merged


def _rank_slot_key(rank: int | None) -> str:
    if rank is not None and rank > 0:
        return f"rank_{int(rank)}"
    return "default"


def _format_slot_template(template: str, *, listing: dict[str, Any], preset: dict[str, Any]) -> str:
    tags = listing.get("tags") or []
    tag_phrase = ", ".join(str(t).strip() for t in tags[:8] if str(t).strip())
    mapping = {
        "scene_default": preset.get("scene_default") or "",
        "title": (listing.get("title") or "").strip(),
        "tags": tag_phrase,
        "shop_id": str(listing.get("shop_id") or ""),
        "listing_id": str(listing.get("listing_id") or ""),
    }
    try:
        return template.format(**mapping).strip()
    except KeyError:
        return template.strip()


def resolve_scene_from_preset(
    preset: dict[str, Any],
    *,
    listing: dict[str, Any],
    reference_rank: int | None = None,
) -> tuple[str, str]:
    """从预设解析某 rank 的 scene 文本。返回 (scene, slot_key)。"""
    slots = preset.get("slots") or {}
    rank_key = _rank_slot_key(reference_rank)
    slot = slots.get(rank_key) or slots.get("default") or {}
    if isinstance(slot, str):
        template = slot
    elif isinstance(slot, dict):
        template = str(slot.get("scene") or preset.get("scene_default") or "")
    else:
        template = preset.get("scene_default") or ""
    if not template:
        template = preset.get("scene_default") or ""
    return _format_slot_template(template, listing=listing, preset=preset), rank_key


def tool_list_image_presets() -> dict:
    """列出全部生图预设（内置 + 本机用户目录）。"""
    tool = "list_image_presets"
    presets = load_all_presets()
    items = [
        {
            "id": p["id"],
            "label": p["label"],
            "description": p["description"],
            "source": p["source"],
            "path": p.get("path") or "",
        }
        for p in presets.values()
    ]
    items.sort(key=lambda x: (x["source"] != "builtin", x["id"]))
    return _tool_ok(
        tool,
        {"presets": items, "count": len(items)},
        meta={
            "builtin_dir": BUILTIN_PRESET_DIR,
            "user_dir": user_preset_dir(create=False),
        },
    )


def tool_get_image_preset(preset_id: str) -> dict:
    tool = "get_image_preset"
    preset_id = (preset_id or "").strip()
    if not preset_id:
        return _tool_err(tool, "INVALID_INPUT", "preset_id 不能为空")
    presets = load_all_presets()
    preset = presets.get(preset_id)
    if not preset:
        return _tool_err(
            tool,
            "PRESET_NOT_FOUND",
            f"未找到预设: {preset_id}",
            data={"available_ids": sorted(presets.keys())},
        )
    return _tool_ok(tool, preset)


def tool_save_image_preset(
    preset_id: str,
    *,
    label: str,
    description: str = "",
    scene_default: str,
    slots: dict[str, Any] | None = None,
    constraints: dict[str, Any] | None = None,
    overwrite: bool = False,
) -> dict:
    """将预设保存到本机用户目录（YAML）。"""
    tool = "save_image_preset"
    preset_id = (preset_id or "").strip().lower().replace(" ", "_")
    if not _PRESET_ID_RE.match(preset_id):
        return _tool_err(
            tool,
            "INVALID_INPUT",
            "preset_id 仅允许小写字母、数字、下划线、连字符",
        )
    scene_default = (scene_default or "").strip()
    if not scene_default:
        return _tool_err(tool, "INVALID_INPUT", "scene_default 不能为空")

    body = {
        "id": preset_id,
        "label": (label or preset_id).strip(),
        "description": (description or "").strip(),
        "scene_default": scene_default,
        "slots": slots or {"default": {"scene": "{scene_default}"}},
        "constraints": constraints
        or {"keep_product": True, "no_text_overlay": True},
    }
    try:
        preset = _normalize_preset(body, source="user")
    except ValueError as exc:
        return _tool_err(tool, "INVALID_INPUT", str(exc))

    out_dir = user_preset_dir(create=True)
    out_path = os.path.join(out_dir, f"{preset_id}.yaml")
    if os.path.exists(out_path) and not overwrite:
        return _tool_err(
            tool,
            "PRESET_EXISTS",
            f"预设已存在: {out_path}；设 overwrite=true 覆盖",
            data={"path": out_path},
        )

    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {
                "id": preset["id"],
                "label": preset["label"],
                "description": preset["description"],
                "scene_default": preset["scene_default"],
                "slots": preset["slots"],
                "constraints": preset["constraints"],
            },
            f,
            allow_unicode=True,
            sort_keys=False,
        )
    preset["path"] = out_path
    return _tool_ok(tool, preset, meta={"saved_to": out_path})


def _prompt_model() -> str:
    return (os.getenv("ETSY_PROMPT_MODEL") or "gemini-2.5-flash").strip()


def _prompt_location() -> str:
    return (
        os.getenv("ETSY_PROMPT_LOCATION")
        or os.getenv("GCP_LOCATION")
        or os.getenv("ETSY_IMAGE_LOCATION")
        or "us-central1"
    ).strip()


def _gcp_project() -> str:
    return (
        os.getenv("GCP_PROJECT_ID")
        or os.getenv("PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or ""
    ).strip()


def tool_polish_scene_brief(
    scene_seed: str,
    *,
    title: str = "",
    tags: list[str] | None = None,
    image_role: str = "lifestyle",
    reference_rank: int | None = None,
    dry_run: bool = False,
) -> dict:
    """
    用 LLM 将 scene 种子润色为一句英文场景描述（供 scene-swap 模板填入）。
    只润色场景，不改产品保真等约束（由 build_scene_swap_prompt 负责）。
    """
    tool = "polish_scene_brief"
    scene_seed = (scene_seed or "").strip()
    if not scene_seed:
        return _tool_err(tool, "INVALID_INPUT", "scene_seed 不能为空")

    if dry_run:
        return _tool_ok(
            tool,
            {
                "scene_seed": scene_seed,
                "polished_scene": scene_seed,
                "polished": False,
                "status": "dry_run",
            },
            meta={"model": _prompt_model()},
        )

    project = _gcp_project()
    if not project:
        return _tool_err(tool, "GCP_PROJECT_MISSING", "未设置 GCP_PROJECT_ID")

    tag_text = ", ".join((tags or [])[:8])
    rank_note = f"listing image rank {reference_rank}" if reference_rank else "listing image"
    system_hint = (
        "You write concise English scene descriptions for e-commerce product image editing. "
        "Output ONE paragraph only, max 60 words. Describe background, lighting, props and mood. "
        "Do NOT mention watermarks, text overlays, or changing the product itself."
    )
    user_prompt = (
        f"Product title: {title or 'N/A'}\n"
        f"Tags: {tag_text or 'N/A'}\n"
        f"Shot type: {image_role}\n"
        f"Image slot: {rank_note}\n"
        f"Scene seed to refine:\n{scene_seed}\n\n"
        "Polish the scene seed into a single fluent scene brief for image generation."
    )

    try:
        from google import genai
        from google.genai import types

        proxy = (os.getenv("VERTEX_HTTP_PROXY") or "").strip() or None
        http_options_kwargs: dict[str, Any] = {"api_version": "v1"}
        if proxy:
            import httpx

            http_options_kwargs["httpx_client"] = httpx.Client(
                proxy=proxy, trust_env=False
            )

        client = genai.Client(
            vertexai=True,
            project=project,
            location=_prompt_location(),
            http_options=types.HttpOptions(**http_options_kwargs),
        )
        response = client.models.generate_content(
            model=_prompt_model(),
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_hint,
                temperature=0.4,
                max_output_tokens=256,
            ),
        )
        polished = (response.text or "").strip()
        if not polished:
            polished = scene_seed
    except Exception as exc:
        return _tool_err(
            tool,
            "POLISH_FAILED",
            str(exc),
            retryable=True,
            data={"scene_seed": scene_seed},
            meta={"model": _prompt_model(), "location": _prompt_location()},
        )

    return _tool_ok(
        tool,
        {
            "scene_seed": scene_seed,
            "polished_scene": polished,
            "polished": polished != scene_seed,
        },
        meta={"model": _prompt_model(), "location": _prompt_location()},
    )


def resolve_scene_for_generation(
    *,
    listing: dict[str, Any],
    reference_rank: int | None = None,
    image_role: str = "lifestyle",
    preset_id: str | None = None,
    custom_scene: str | None = None,
    style: str | None = None,
    infer_style: bool = False,
    polish_with_llm: bool = True,
    dry_run: bool = False,
) -> tuple[str, dict[str, Any]]:
    """
    统一解析 scene 文本。优先级：
    custom_scene > preset_id > style > infer_style > default
    可选 LLM 润色（polish_with_llm）。
    返回 (scene_text, meta)
    """
    from domains.etsy.image_tools import (  # noqa: WPS433
        DEFAULT_SCENE_STYLE,
        infer_scene_style_from_listing,
    )

    meta: dict[str, Any] = {
        "reference_rank": reference_rank,
        "image_role": image_role,
        "polish_with_llm": polish_with_llm,
    }

    custom = (custom_scene or "").strip()
    if custom:
        scene_seed = custom
        meta["source"] = "custom"
    elif (preset_id or "").strip():
        pid = preset_id.strip()
        presets = load_all_presets()
        preset = presets.get(pid)
        if not preset:
            raise ValueError(f"PRESET_NOT_FOUND:{pid}")
        scene_seed, slot_key = resolve_scene_from_preset(
            preset,
            listing=listing,
            reference_rank=reference_rank,
        )
        meta["source"] = "preset"
        meta["preset_id"] = pid
        meta["preset_label"] = preset.get("label")
        meta["slot_key"] = slot_key
    elif (style or "").strip():
        scene_seed = style.strip()
        meta["source"] = "explicit_style"
    elif infer_style:
        scene_seed = infer_scene_style_from_listing(
            title=listing.get("title") or "",
            tags=listing.get("tags"),
            description=listing.get("description") or "",
        )
        meta["source"] = "inferred"
    else:
        scene_seed = DEFAULT_SCENE_STYLE
        meta["source"] = "default"

    meta["scene_seed"] = scene_seed

    if polish_with_llm:
        polish = tool_polish_scene_brief(
            scene_seed,
            title=listing.get("title") or "",
            tags=listing.get("tags"),
            image_role=image_role,
            reference_rank=reference_rank,
            dry_run=dry_run,
        )
        if not polish.get("ok"):
            raise RuntimeError(polish["error"]["message"])
        scene_text = polish["data"]["polished_scene"]
        meta["polished"] = polish["data"].get("polished", False)
        if dry_run:
            meta["polish_status"] = "dry_run"
    else:
        scene_text = scene_seed
        meta["polished"] = False

    meta["scene"] = scene_text
    return scene_text, meta
