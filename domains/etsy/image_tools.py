# -*- coding: utf-8 -*-
"""
etsy_agent/image_tools.py — Listing 上架素材：Imagen / Gemini 生图 + GCS + 规格校验 + manifest Excel

环境变量（见根目录 .env.example）：
  ETSY_IMAGE_MODEL          Imagen: imagen-3.0-generate-002；Gemini 生图: gemini-3.1-flash-image
  ETSY_IMAGE_LOCATION       Imagen 常用 us-central1；Gemini 生图常用 global
  ETSY_IMAGE_GCS_BUCKET     必填（真实生图/upload 时，--no-gcs 可省略）
  ETSY_IMAGE_GCS_PREFIX     默认 etsy/
  ETSY_IMAGE_ASPECT_RATIO   默认 1:1
  GOOGLE_GENAI_USE_ENTERPRISE  Gemini Enterprise 生图（默认 true）
"""

from __future__ import annotations

import io
import os
import re
import uuid
from datetime import datetime
from typing import Any

import pandas as pd
import requests
from smart_agents.env_runtime import load_runtime_env

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_runtime_env(default_env_path=os.path.join(PROJECT_ROOT, ".env"))

DEFAULT_MANIFEST_PATH = os.path.join(
    os.path.expanduser("~"), "Documents", "EtsyData", "etsy_listing_assets.xlsx"
)
_IMAGE_DOWNLOAD_SESSION = requests.Session()
_IMAGE_DOWNLOAD_SESSION.trust_env = False
ALLOWED_EXCEL_ROOTS = [
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Documents", "EtsyData"),
]

MANIFEST_COLUMNS = [
    "platform",
    "listing_id",
    "shop_id",
    "generation_mode",
    "image_role",
    "prompt",
    "model",
    "aspect_ratio",
    "width_px",
    "height_px",
    "file_size_bytes",
    "reference_listing_image_id",
    "reference_rank",
    "reference_image_url",
    "gcs_uri",
    "local_path",
    "spec_ok",
    "spec_notes",
    "created_at",
]

# Etsy 建议：listing 图最短边 ≥ 2000px（PoC 用 Imagen 2K/最大边校验）
MIN_SHORT_EDGE_PX = 2000
MAX_FILE_BYTES = 10 * 1024 * 1024


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


def _resolve_excel_path(excel_path: str | None) -> str:
    raw = excel_path or DEFAULT_MANIFEST_PATH
    path = os.path.abspath(os.path.expanduser(raw))
    for root in ALLOWED_EXCEL_ROOTS:
        allowed = os.path.abspath(root)
        if path == allowed or path.startswith(allowed + os.sep):
            return path
    raise ValueError(f"excel_path 不在允许目录内: {path}")


def _image_model() -> str:
    return (os.getenv("ETSY_IMAGE_MODEL") or "imagen-3.0-generate-002").strip()


def _image_location() -> str:
    return (
        os.getenv("ETSY_IMAGE_LOCATION")
        or os.getenv("GCP_LOCATION")
        or "us-central1"
    ).strip()


def _gcs_bucket() -> str:
    return (os.getenv("ETSY_IMAGE_GCS_BUCKET") or "").strip()


def _gcs_prefix() -> str:
    p = (os.getenv("ETSY_IMAGE_GCS_PREFIX") or "etsy/").strip()
    return p if p.endswith("/") else f"{p}/"


def _aspect_ratio() -> str:
    return (os.getenv("ETSY_IMAGE_ASPECT_RATIO") or "1:1").strip()


def _gcp_project() -> str:
    return (
        os.getenv("GCP_PROJECT_ID")
        or os.getenv("PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or ""
    ).strip()


def _use_genai_enterprise() -> bool:
    raw = (os.getenv("GOOGLE_GENAI_USE_ENTERPRISE") or "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _is_gemini_image_model(model: str) -> bool:
    """Gemini 系列生图模型走 generateContent，而非 Imagen generate_images。"""
    name = (model or "").strip().lower()
    return name.startswith("gemini-") and "image" in name


def _image_api_mode(model: str | None = None) -> str:
    m = (model or _image_model()).strip()
    if _is_gemini_image_model(m):
        return "gemini_generate_content"
    return "imagen_generate_images"


def _create_genai_client(*, project: str, location: str, api_mode: str):
    from google import genai
    from google.genai import types

    proxy = (os.getenv("VERTEX_HTTP_PROXY") or "").strip() or None
    http_options_kwargs: dict[str, Any] = {}
    if api_mode == "gemini_generate_content":
        http_options_kwargs["api_version"] = "v1"
    if proxy:
        import httpx

        http_options_kwargs["httpx_client"] = httpx.Client(proxy=proxy, trust_env=False)

    client_kwargs: dict[str, Any] = {
        "vertexai": True,
        "project": project,
        "location": location,
    }
    if api_mode == "gemini_generate_content":
        client_kwargs["enterprise"] = _use_genai_enterprise()
    if http_options_kwargs:
        client_kwargs["http_options"] = types.HttpOptions(**http_options_kwargs)

    return genai.Client(**client_kwargs)


def _extract_image_bytes_from_generate_content(response) -> bytes | None:
    parts_sources = []
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if content and getattr(content, "parts", None):
            parts_sources.append(content.parts)
    if getattr(response, "parts", None):
        parts_sources.append(response.parts)

    for parts in parts_sources:
        for part in parts or []:
            inline = getattr(part, "inline_data", None)
            if inline and getattr(inline, "data", None):
                return inline.data
    return None


def _generate_with_imagen(client, *, model: str, prompt: str, aspect_ratio: str) -> bytes:
    from google.genai import types

    response = client.models.generate_images(
        model=model,
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio=aspect_ratio,
            output_mime_type="image/png",
        ),
    )
    if not response.generated_images:
        raise RuntimeError("模型未返回图片（可能被安全策略过滤）")
    return response.generated_images[0].image.image_bytes


def _generate_with_gemini_image(client, *, model: str, prompt: str, aspect_ratio: str) -> bytes:
    from google.genai import types

    # Enterprise 文档要求 Gemini 生图同时请求 TEXT + IMAGE 模态
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=[types.Modality.TEXT, types.Modality.IMAGE],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                output_mime_type="image/png",
            ),
        ),
    )
    image_bytes = _extract_image_bytes_from_generate_content(response)
    if not image_bytes:
        raise RuntimeError("Gemini 未返回图片 part（可能被安全策略过滤）")
    return image_bytes


def _guess_image_mime_type(url: str, content_type: str = "") -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct.startswith("image/"):
        return ct
    lower = (url or "").lower()
    if ".png" in lower:
        return "image/png"
    if ".webp" in lower:
        return "image/webp"
    return "image/jpeg"


def tool_download_image_url(url: str) -> dict:
    """下载远程商品图（用于 scene-swap 参考图）。"""
    tool = "download_image_url"
    url = (url or "").strip()
    if not url.startswith("http"):
        return _tool_err(tool, "INVALID_INPUT", "url 必须是 http(s) 地址")

    try:
        resp = _IMAGE_DOWNLOAD_SESSION.get(url, timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return _tool_err(tool, "IMAGE_DOWNLOAD_FAILED", str(exc), retryable=True, data={"url": url})

    mime = _guess_image_mime_type(url, resp.headers.get("Content-Type", ""))
    data = resp.content
    if not data:
        return _tool_err(tool, "IMAGE_DOWNLOAD_EMPTY", "下载内容为空", data={"url": url})

    return _tool_ok(
        tool,
        {
            "url": url,
            "bytes": len(data),
            "mime_type": mime,
            "image_bytes": data,
        },
    )


def build_scene_swap_prompt(
    *,
    title: str,
    style: str = "professional e-commerce product photography scene appropriate for the product",
    image_role: str = "lifestyle",
    description: str = "",
) -> str:
    """参考主图换场景：强调保持产品外观不变，只改背景/场景。"""
    desc = re.sub(r"\s+", " ", (description or ""))[:200]
    parts = [
        "Edit the reference product image for an Etsy listing.",
        "Keep the exact same product, packaging, label, colors, and branding unchanged.",
        f"Only change the background and scene to: {style}.",
        f"Shot type: {image_role}.",
        f"Product: {title.strip()}.",
    ]
    if desc:
        parts.append(f"Context: {desc}")
    parts.append(
        "Professional e-commerce product photography, natural lighting, "
        "no watermark, no added text overlay."
    )
    return " ".join(parts)


_ROLE_BY_LISTING_RANK = {
    1: "lifestyle",
    2: "detail",
    3: "in-context",
    4: "banner",
}

DEFAULT_SCENE_STYLE = (
    "professional e-commerce product photography scene appropriate for the product category"
)


def image_role_for_listing_rank(rank: int, index: int = 0) -> str:
    """按 Etsy 附图 rank 映射 shot 类型。"""
    try:
        r = int(rank)
    except (TypeError, ValueError):
        r = 0
    if r in _ROLE_BY_LISTING_RANK:
        return _ROLE_BY_LISTING_RANK[r]
    return f"variant_{r or index + 1}"


def infer_scene_style_from_listing(
    *,
    title: str = "",
    tags: list[str] | None = None,
    description: str = "",
) -> str:
    """从 listing 标签/标题/描述推断场景风格（无 LLM）。"""
    tag_list = [t.strip() for t in (tags or []) if t.strip()][:8]
    tag_phrase = ", ".join(tag_list)

    desc = re.sub(r"\s+", " ", (description or "").strip())
    desc_snippet = re.sub(r"[^\w\s,.'-]", "", desc.split(".")[0])[:140].strip()

    title_short = re.sub(r"[^\w\s,.'-]", "", (title or "").strip())[:100]

    parts: list[str] = []
    if tag_phrase:
        parts.append(f"Scene mood and props inspired by tags: {tag_phrase}")
    if title_short:
        parts.append(f"Product context: {title_short}")
    if desc_snippet and desc_snippet.lower() not in (title_short or "").lower():
        parts.append(f"Listing tone: {desc_snippet}")
    parts.append(
        "Cohesive e-commerce lifestyle or studio setting with soft natural lighting "
        "that fits this product category"
    )
    return ". ".join(parts)


def resolve_scene_style(
    *,
    title: str = "",
    tags: list[str] | None = None,
    description: str = "",
    style: str | None = None,
    infer_style: bool = False,
) -> tuple[str, str]:
    """
    解析 scene-swap 风格。
    返回 (style_text, source)，source 为 explicit | inferred | default。
    """
    explicit = (style or "").strip()
    if explicit:
        return explicit, "explicit"
    if infer_style:
        return (
            infer_scene_style_from_listing(
                title=title, tags=tags, description=description
            ),
            "inferred",
        )
    return DEFAULT_SCENE_STYLE, "default"


def _generate_gemini_scene_swap(
    client,
    *,
    model: str,
    prompt: str,
    reference_image_bytes: bytes,
    reference_mime_type: str,
    aspect_ratio: str,
) -> bytes:
    from google.genai import types

    ref_part = types.Part.from_bytes(
        data=reference_image_bytes,
        mime_type=reference_mime_type or "image/jpeg",
    )
    response = client.models.generate_content(
        model=model,
        contents=[prompt, ref_part],
        config=types.GenerateContentConfig(
            response_modalities=[types.Modality.TEXT, types.Modality.IMAGE],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                output_mime_type="image/png",
            ),
        ),
    )
    image_bytes = _extract_image_bytes_from_generate_content(response)
    if not image_bytes:
        raise RuntimeError("Gemini 未返回场景替换图片（可能被安全策略过滤）")
    return image_bytes


def tool_generate_scene_variant_image(
    *,
    prompt: str,
    listing_id: str,
    shop_id: str = "",
    image_role: str = "lifestyle",
    reference_image_bytes: bytes,
    reference_mime_type: str = "image/jpeg",
    reference_listing_image_id: str = "",
    reference_image_url: str = "",
    reference_rank: int | None = None,
    aspect_ratio: str | None = None,
    upload_to_gcs: bool = True,
    save_local_copy: bool = True,
    dry_run: bool = False,
) -> dict:
    """参考 listing 主图换场景（需 Gemini *-image 模型）。"""
    tool = "generate_scene_variant_image"
    listing_id = (listing_id or "").strip()
    if not listing_id.isdigit():
        return _tool_err(tool, "INVALID_INPUT", "listing_id 必须是数字")
    prompt = (prompt or "").strip()
    if not prompt:
        return _tool_err(tool, "INVALID_INPUT", "prompt 不能为空")
    if not reference_image_bytes and not dry_run:
        return _tool_err(tool, "INVALID_INPUT", "reference_image_bytes 不能为空")

    ar = (aspect_ratio or _aspect_ratio()).strip()
    model = _image_model()
    api_mode = _image_api_mode(model)
    location = _image_location()

    if api_mode != "gemini_generate_content":
        return _tool_err(
            tool,
            "UNSUPPORTED_MODEL",
            "场景替换需 Gemini 生图模型（如 gemini-3.1-flash-image）；Imagen 请用文生图流程",
            data={"model": model, "api_mode": api_mode},
        )

    if dry_run:
        cfg = image_env_config()
        bucket_label = cfg["gcs_bucket"] or "(未设置 ETSY_IMAGE_GCS_BUCKET)"
        fake_uri = (
            f"gs://{bucket_label}/{_gcs_prefix()}"
            f"{shop_id or 'shop'}/{listing_id}/scene_swap_dry_run.png"
        )
        return _tool_ok(
            tool,
            {
                "listing_id": listing_id,
                "shop_id": shop_id,
                "image_role": image_role,
                "generation_mode": "scene_swap",
                "prompt": prompt,
                "model": model,
                "aspect_ratio": ar,
                "reference_listing_image_id": reference_listing_image_id,
                "reference_image_url": reference_image_url,
                "reference_rank": reference_rank,
                "reference_bytes": len(reference_image_bytes) if reference_image_bytes else 0,
                "gcs_uri": fake_uri,
                "spec_ok": True,
                "spec_notes": "dry_run",
                "status": "dry_run",
            },
            meta={"dry_run": True, "image_config": cfg},
        )

    project = _gcp_project()
    if not project:
        return _tool_err(tool, "GCP_PROJECT_MISSING", "未设置 GCP_PROJECT_ID")

    try:
        client = _create_genai_client(
            project=project,
            location=location,
            api_mode=api_mode,
        )
        image_bytes = _generate_gemini_scene_swap(
            client,
            model=model,
            prompt=prompt,
            reference_image_bytes=reference_image_bytes,
            reference_mime_type=reference_mime_type,
            aspect_ratio=ar,
        )
    except Exception as exc:
        return _tool_err(
            tool,
            "SCENE_SWAP_FAILED",
            str(exc),
            retryable=True,
            meta={"model": model, "location": location, "api_mode": api_mode},
        )

    spec = tool_validate_listing_image_spec(image_bytes=image_bytes)
    spec_data = spec.get("data") or {}
    spec_ok = bool(spec.get("ok") and spec_data.get("spec_ok"))

    result_data: dict[str, Any] = {
        "listing_id": listing_id,
        "shop_id": shop_id,
        "image_role": image_role,
        "generation_mode": "scene_swap",
        "prompt": prompt,
        "model": model,
        "aspect_ratio": ar,
        "reference_listing_image_id": reference_listing_image_id,
        "reference_image_url": reference_image_url,
        "reference_rank": reference_rank,
        "width_px": spec_data.get("width_px"),
        "height_px": spec_data.get("height_px"),
        "file_size_bytes": spec_data.get("file_size_bytes"),
        "spec_ok": spec_ok,
        "spec_notes": spec_data.get("spec_notes", ""),
    }

    if upload_to_gcs:
        up = tool_upload_image_to_gcs(
            image_bytes=image_bytes,
            listing_id=listing_id,
            shop_id=shop_id,
            content_type="image/png",
        )
        if not up.get("ok"):
            up["data"] = {**result_data, **up.get("data", {})}
            up["tool"] = tool
            return up
        result_data["gcs_uri"] = up["data"]["gcs_uri"]
        result_data["object_name"] = up["data"]["object_name"]
    if save_local_copy:
        local_dir = os.path.join(
            os.path.expanduser("~"),
            "Documents",
            "EtsyData",
            "generated",
            listing_id,
            "scene_swap",
        )
        os.makedirs(local_dir, exist_ok=True)
        rank_part = f"rank{reference_rank}_" if reference_rank else ""
        local_path = os.path.join(
            local_dir, f"{rank_part}{image_role}_{uuid.uuid4().hex[:8]}.png"
        )
        with open(local_path, "wb") as f:
            f.write(image_bytes)
        result_data["local_path"] = local_path

    return _tool_ok(tool, result_data, meta={"model": model, "generation_mode": "scene_swap"})


def image_env_config() -> dict[str, Any]:
    """
    解析当前生图相关 .env（供测试脚本与 dry-run 展示）。
    未设置的项会标明 default，便于确认是否读到了你的配置。
    """
    model_raw = (os.getenv("ETSY_IMAGE_MODEL") or "").strip()
    loc_raw = (os.getenv("ETSY_IMAGE_LOCATION") or "").strip()
    bucket_raw = (os.getenv("ETSY_IMAGE_GCS_BUCKET") or "").strip()
    prefix_raw = (os.getenv("ETSY_IMAGE_GCS_PREFIX") or "").strip()
    ar_raw = (os.getenv("ETSY_IMAGE_ASPECT_RATIO") or "").strip()

    return {
        "model": _image_model(),
        "model_from_env": bool(model_raw),
        "api_mode": _image_api_mode(model_raw or _image_model()),
        "location": _image_location(),
        "location_from_env": bool(loc_raw),
        "gcs_bucket": bucket_raw,
        "gcs_bucket_configured": bool(bucket_raw),
        "gcs_prefix": _gcs_prefix(),
        "gcs_prefix_from_env": bool(prefix_raw),
        "aspect_ratio": _aspect_ratio(),
        "aspect_ratio_from_env": bool(ar_raw),
        "gcp_project_id": _gcp_project(),
        "genai_enterprise": _use_genai_enterprise(),
        "env_file_hint": os.path.join(PROJECT_ROOT, ".env"),
    }


def tool_check_image_config(*, require_gcs_bucket: bool = False) -> dict:
    """生图前配置预检（不调用 Imagen / 不写 GCS）。"""
    tool = "check_image_config"
    cfg = image_env_config()
    issues: list[str] = []

    if not cfg["gcp_project_id"]:
        issues.append("未设置 GCP_PROJECT_ID（生图需要 Vertex）")
    if require_gcs_bucket and not cfg["gcs_bucket_configured"]:
        issues.append(
            "未设置 ETSY_IMAGE_GCS_BUCKET；请在 .env 填写桶名，"
            "或使用 --no-gcs 只保存到本地 ~/Documents/EtsyData/generated/"
        )

    if issues:
        return _tool_err(
            tool,
            "IMAGE_CONFIG_INCOMPLETE",
            "；".join(issues),
            data=cfg,
        )
    return _tool_ok(
        tool,
        cfg,
        meta={
            "note": (
                f"将使用模型 {cfg['model']}"
                + ("（来自 .env ETSY_IMAGE_MODEL）" if cfg["model_from_env"] else "（代码默认值，建议在 .env 指定）")
            ),
        },
    )


def build_listing_image_prompt(
    *,
    title: str,
    tags: list[str] | None = None,
    description: str = "",
    review_keywords: list[str] | None = None,
    style: str = "clean e-commerce lifestyle product scene",
    image_role: str = "lifestyle",
) -> str:
    """根据 listing 上下文拼 Imagen prompt（不含平台禁词规避的完整合规，由 Skill 补充）。"""
    tag_text = ", ".join((tags or [])[:8])
    kw = ", ".join((review_keywords or [])[:6])
    desc = re.sub(r"\s+", " ", (description or ""))[:400]
    parts = [
        f"E-commerce product listing photo for Etsy, {image_role} shot.",
        f"Product: {title.strip()}.",
    ]
    if tag_text:
        parts.append(f"Tags: {tag_text}.")
    if kw:
        parts.append(f"Highlight buyer-loved aspects: {kw}.")
    if desc:
        parts.append(f"Context: {desc}")
    parts.append(f"Style: {style}.")
    parts.append(
        "Professional studio lighting, no watermark, no text overlay, "
        "suitable as marketplace listing supplementary image."
    )
    return " ".join(p for p in parts if p)


def tool_validate_listing_image_spec(
    *,
    image_bytes: bytes | None = None,
    file_path: str | None = None,
) -> dict:
    """校验图片是否满足 Etsy listing 附图 PoC 规格（最短边、文件大小）。"""
    tool = "validate_listing_image_spec"
    try:
        from PIL import Image
    except ImportError:
        return _tool_err(
            tool,
            "PILLOW_MISSING",
            "请 pip install Pillow 以校验图片尺寸",
            retryable=False,
        )

    if file_path:
        path = os.path.abspath(os.path.expanduser(file_path))
        if not os.path.isfile(path):
            return _tool_err(tool, "FILE_NOT_FOUND", f"文件不存在: {path}")
        size_bytes = os.path.getsize(path)
        with Image.open(path) as im:
            width, height = im.size
    elif image_bytes:
        size_bytes = len(image_bytes)
        with Image.open(io.BytesIO(image_bytes)) as im:
            width, height = im.size
    else:
        return _tool_err(tool, "INVALID_INPUT", "需要 image_bytes 或 file_path")

    short_edge = min(width, height)
    notes: list[str] = []
    ok = True
    if short_edge < MIN_SHORT_EDGE_PX:
        ok = False
        notes.append(f"short_edge {short_edge}px < {MIN_SHORT_EDGE_PX}px")
    if size_bytes > MAX_FILE_BYTES:
        ok = False
        notes.append(f"file_size {size_bytes} > {MAX_FILE_BYTES}")

    return _tool_ok(
        tool,
        {
            "spec_ok": ok,
            "width_px": width,
            "height_px": height,
            "short_edge_px": short_edge,
            "file_size_bytes": size_bytes,
            "spec_notes": "; ".join(notes) if notes else "ok",
        },
    )


def tool_upload_image_to_gcs(
    *,
    image_bytes: bytes,
    listing_id: str,
    shop_id: str = "",
    filename: str | None = None,
    content_type: str = "image/png",
    dry_run: bool = False,
) -> dict:
    tool = "upload_image_to_gcs"
    bucket_name = _gcs_bucket()
    if not bucket_name and not dry_run:
        return _tool_err(
            tool,
            "GCS_BUCKET_MISSING",
            "请在 .env 设置 ETSY_IMAGE_GCS_BUCKET",
        )

    shop_part = shop_id or "unknown_shop"
    fname = filename or f"{listing_id}_{uuid.uuid4().hex[:12]}.png"
    object_name = f"{_gcs_prefix()}{shop_part}/{listing_id}/{fname}"
    gcs_uri = f"gs://{bucket_name}/{object_name}" if bucket_name else f"gs://<bucket>/{object_name}"

    if dry_run:
        return _tool_ok(
            tool,
            {
                "gcs_uri": gcs_uri,
                "object_name": object_name,
                "bucket": bucket_name or "(dry_run)",
                "bytes": len(image_bytes),
                "status": "dry_run",
            },
            meta={"dry_run": True},
        )

    project = _gcp_project()
    if not project:
        return _tool_err(tool, "GCP_PROJECT_MISSING", "未设置 GCP_PROJECT_ID")

    try:
        from google.cloud import storage

        client = storage.Client(project=project)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        blob.upload_from_string(image_bytes, content_type=content_type)
    except Exception as exc:
        return _tool_err(
            tool,
            "GCS_UPLOAD_FAILED",
            str(exc),
            retryable=True,
            data={"object_name": object_name},
        )

    return _tool_ok(
        tool,
        {
            "gcs_uri": gcs_uri,
            "object_name": object_name,
            "bucket": bucket_name,
            "bytes": len(image_bytes),
        },
    )


def tool_generate_listing_image(
    *,
    prompt: str,
    listing_id: str,
    shop_id: str = "",
    image_role: str = "lifestyle",
    aspect_ratio: str | None = None,
    upload_to_gcs: bool = True,
    dry_run: bool = False,
) -> dict:
    """调用 Vertex Imagen 或 Gemini 生图，可选上传 GCS 并做规格校验。"""
    tool = "generate_listing_image"
    listing_id = (listing_id or "").strip()
    if not listing_id.isdigit():
        return _tool_err(tool, "INVALID_INPUT", "listing_id 必须是数字")
    prompt = (prompt or "").strip()
    if not prompt:
        return _tool_err(tool, "INVALID_INPUT", "prompt 不能为空")

    ar = (aspect_ratio or _aspect_ratio()).strip()
    model = _image_model()
    api_mode = _image_api_mode(model)
    location = _image_location()

    if dry_run:
        cfg = image_env_config()
        bucket_label = cfg["gcs_bucket"] or "(未设置 ETSY_IMAGE_GCS_BUCKET)"
        fake_uri = (
            f"gs://{bucket_label}/{_gcs_prefix()}"
            f"{shop_id or 'shop'}/{listing_id}/dry_run.png"
        )
        return _tool_ok(
            tool,
            {
                "listing_id": listing_id,
                "shop_id": shop_id,
                "image_role": image_role,
                "prompt": prompt,
                "model": model,
                "aspect_ratio": ar,
                "api_mode": api_mode,
                "gcs_uri": fake_uri,
                "spec_ok": True,
                "spec_notes": "dry_run",
                "status": "dry_run",
            },
            meta={"dry_run": True, "image_config": cfg},
        )

    project = _gcp_project()
    if not project:
        return _tool_err(tool, "GCP_PROJECT_MISSING", "未设置 GCP_PROJECT_ID")

    try:
        client = _create_genai_client(
            project=project,
            location=location,
            api_mode=api_mode,
        )
        if api_mode == "gemini_generate_content":
            image_bytes = _generate_with_gemini_image(
                client, model=model, prompt=prompt, aspect_ratio=ar
            )
        else:
            image_bytes = _generate_with_imagen(
                client, model=model, prompt=prompt, aspect_ratio=ar
            )
    except Exception as exc:
        hint = ""
        if _is_gemini_image_model(model):
            hint = (
                " Gemini 生图需 ETSY_IMAGE_LOCATION=global，"
                "且使用 generateContent 端点（代码已自动路由）。"
            )
        elif model.lower().startswith("imagen-"):
            hint = " Imagen 模型通常需 ETSY_IMAGE_LOCATION=us-central1。"
        return _tool_err(
            tool,
            "IMAGE_GENERATION_FAILED",
            f"{exc}{hint}",
            retryable=True,
            meta={
                "model": model,
                "location": location,
                "api_mode": api_mode,
            },
        )

    spec = tool_validate_listing_image_spec(image_bytes=image_bytes)
    spec_data = spec.get("data") or {}
    spec_ok = bool(spec.get("ok") and spec_data.get("spec_ok"))

    result_data: dict[str, Any] = {
        "listing_id": listing_id,
        "shop_id": shop_id,
        "image_role": image_role,
        "generation_mode": "text_to_image",
        "prompt": prompt,
        "model": model,
        "aspect_ratio": ar,
        "width_px": spec_data.get("width_px"),
        "height_px": spec_data.get("height_px"),
        "file_size_bytes": spec_data.get("file_size_bytes"),
        "spec_ok": spec_ok,
        "spec_notes": spec_data.get("spec_notes", ""),
    }

    if upload_to_gcs:
        up = tool_upload_image_to_gcs(
            image_bytes=image_bytes,
            listing_id=listing_id,
            shop_id=shop_id,
            content_type="image/png",
        )
        if not up.get("ok"):
            up["data"] = {**result_data, **up.get("data", {})}
            up["tool"] = tool
            return up
        result_data["gcs_uri"] = up["data"]["gcs_uri"]
        result_data["object_name"] = up["data"]["object_name"]
    else:
        local_dir = os.path.join(
            os.path.expanduser("~"),
            "Documents",
            "EtsyData",
            "generated",
            listing_id,
        )
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, f"{image_role}_{uuid.uuid4().hex[:8]}.png")
        with open(local_path, "wb") as f:
            f.write(image_bytes)
        result_data["local_path"] = local_path

    return _tool_ok(tool, result_data, meta={"model": model})


def tool_export_image_manifest_excel(
    rows: list[dict[str, Any]],
    *,
    excel_path: str | None = None,
    sheet_name: str = "上架素材",
    deduplicate: bool = True,
) -> dict:
    tool = "export_image_manifest_excel"
    if not rows:
        return _tool_err(tool, "INVALID_INPUT", "没有可写入的 manifest 行")
    try:
        path = _resolve_excel_path(excel_path)
    except ValueError as exc:
        return _tool_err(tool, "PATH_NOT_ALLOWED", str(exc))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    normalized = []
    for r in rows:
        row = {col: r.get(col, "") for col in MANIFEST_COLUMNS}
        row.setdefault("platform", "etsy")
        row.setdefault("created_at", created_at)
        normalized.append(row)

    incoming_df = pd.DataFrame(normalized, columns=MANIFEST_COLUMNS)
    if os.path.exists(path):
        try:
            existing_df = pd.read_excel(path, sheet_name=sheet_name)
        except Exception:
            existing_df = pd.DataFrame(columns=MANIFEST_COLUMNS)
    else:
        existing_df = pd.DataFrame(columns=MANIFEST_COLUMNS)

    merged = pd.concat([existing_df, incoming_df], ignore_index=True)
    before = len(merged)
    if deduplicate:
        merged = merged.drop_duplicates(
            subset=["listing_id", "gcs_uri", "local_path", "prompt"],
            keep="last",
        )

    try:
        merged.to_excel(path, sheet_name=sheet_name, index=False)
    except Exception as exc:
        return _tool_err(tool, "WRITE_FAILED", str(exc), data={"excel_path": path})

    return _tool_ok(
        tool,
        {
            "rows_written": len(incoming_df),
            "rows_deduplicated": before - len(merged),
            "total_rows": len(merged),
            "excel_path": path,
        },
        meta={"sheet_name": sheet_name},
    )
