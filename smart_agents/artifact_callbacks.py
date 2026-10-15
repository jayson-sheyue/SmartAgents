# -*- coding: utf-8 -*-
"""Session Artifact → 可渲染图片（GE / Playground / streamQuery / TSE）。

streamQuery 对外经常只剩 ``[Image]`` + 文件名，二进制 Part 被丢掉。
因此除 after_agent 追加 inline Part 外，再用 after_model 把图嵌进
markdown data URI，文本通道客户端（含 TSE）也能直接 ``<img>`` 渲染。
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.genai import types

logger = logging.getLogger(__name__)

_ROUND_IMAGE_ARTIFACTS_KEY = "_smartagents_round_image_artifacts"
_DELIVERED_IMAGES_KEY = "_smartagents_delivered_images"

_IMAGE_MIME_PREFIXES = ("image/",)
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}


def _is_image_mime(mime: str, filename: str) -> bool:
    m = (mime or "").lower()
    if any(m.startswith(p) for p in _IMAGE_MIME_PREFIXES):
        return True
    name = (filename or "").lower()
    return any(name.endswith(ext) for ext in _IMAGE_EXTENSIONS)


def record_image_artifact_for_delivery(
    state: dict[str, Any],
    *,
    filename: str,
    version: int,
    mime_type: str,
) -> None:
    """run_code 保存 Artifact 后登记，供 after_model / after_agent 出图。"""
    if not filename or not _is_image_mime(mime_type, filename):
        return
    entries: list[dict[str, Any]] = state.setdefault(
        _ROUND_IMAGE_ARTIFACTS_KEY, []
    )
    entries.append(
        {
            "filename": filename,
            "version": version,
            "mime_type": mime_type or "application/octet-stream",
        }
    )


def _artifact_delta_for_invocation(callback_context: CallbackContext) -> dict[str, int]:
    """从本轮 events 收集 artifact_delta（兜底）。"""
    delta: dict[str, int] = {}
    inv_id = callback_context.invocation_id
    session = callback_context.session
    for event in session.events or []:
        if inv_id and getattr(event, "invocation_id", None) not in (None, inv_id):
            continue
        actions = getattr(event, "actions", None)
        if actions and getattr(actions, "artifact_delta", None):
            delta.update(actions.artifact_delta)
    return delta


def _pending_image_entries(callback_context: CallbackContext) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = list(
        callback_context.state.get(_ROUND_IMAGE_ARTIFACTS_KEY, []) or []
    )
    seen: set[tuple[str, Optional[int]]] = {
        (e["filename"], e.get("version")) for e in pending if e.get("filename")
    }
    for filename, version in _artifact_delta_for_invocation(callback_context).items():
        key = (filename, version)
        if key in seen:
            continue
        seen.add(key)
        if _is_image_mime("", filename):
            pending.append(
                {"filename": filename, "version": version, "mime_type": ""}
            )
    delivered = callback_context.state.get(_DELIVERED_IMAGES_KEY) or {}
    if delivered.get("invocation_id") == callback_context.invocation_id:
        sent = {(entry["filename"], entry.get("version")) for entry in delivered.get("entries", [])}
        pending = [entry for entry in pending if (entry.get("filename"), entry.get("version")) not in sent]
    return pending


def mark_image_artifacts_delivered(callback_context: CallbackContext, entries: list[dict[str, Any]]) -> None:
    """Avoid delivering SAP screenshots a second time in after_agent."""
    callback_context.state[_DELIVERED_IMAGES_KEY] = {
        "invocation_id": callback_context.invocation_id, "entries": entries,
    }


def _bytes_to_b64(data: Any) -> Optional[str]:
    if data is None:
        return None
    if isinstance(data, bytes):
        return base64.b64encode(data).decode("ascii")
    if isinstance(data, str):
        raw = data.strip()
        return raw or None
    return None


async def _load_image_data_uris(
    callback_context: CallbackContext,
    pending: list[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """返回 [(filename, mime, data_uri), ...]。"""
    loaded: list[tuple[str, str, str]] = []
    for entry in pending:
        filename = str(entry.get("filename") or "").strip()
        if not filename:
            continue
        version = entry.get("version")
        try:
            part = await callback_context.load_artifact(
                filename=filename,
                version=version if isinstance(version, int) else None,
            )
        except Exception:
            logger.exception("load_artifact failed filename=%s", filename)
            continue
        if part is None:
            continue
        data = b""
        mime = str(entry.get("mime_type") or "application/octet-stream")
        if part.inline_data and part.inline_data.data:
            data = part.inline_data.data
            mime = part.inline_data.mime_type or mime
        if not data or not _is_image_mime(mime, filename):
            continue
        b64 = _bytes_to_b64(data)
        if not b64:
            continue
        loaded.append((filename, mime, f"data:{mime};base64,{b64}"))
        logger.info(
            "image ready for embed filename=%s mime=%s bytes=%d",
            filename,
            mime,
            len(data) if isinstance(data, bytes) else -1,
        )
    return loaded


def _embed_data_uris_in_text(text: str, images: list[tuple[str, str, str]]) -> str:
    """把 ``[Image]`` / ``![..](file.png)`` 替换为 data URI；未引用的图追加到文末。"""
    if not text or not images:
        return text

    out = text
    used: set[str] = set()

    for filename, _mime, data_uri in images:
        esc = re.escape(filename)
        md_pat = re.compile(rf"!\[[^\]]*\]\s*\(\s*{esc}\s*\)")
        if md_pat.search(out):
            out = md_pat.sub(f"![{filename}]({data_uri})", out)
            used.add(filename)
            continue
        # 形如 (output_xxx.png) 的引用
        paren_pat = re.compile(rf"\({esc}\)")
        if paren_pat.search(out):
            # A bare (filename) reference must become an image, not a visible
            # parenthesized Base64 string. Models may also split Markdown lines.
            out = paren_pat.sub(f"![{filename}]({data_uri})", out)
            used.add(filename)

    # 占位符 [Image] / 【图片】：按未使用图片顺序替换
    unused = [(f, m, u) for f, m, u in images if f not in used]
    placeholder_pat = re.compile(r"\[Image\]|【图片】|\[image\]", re.IGNORECASE)

    def _repl_placeholder(_match: re.Match[str]) -> str:
        nonlocal unused
        if not unused:
            return _match.group(0)
        filename, _mime, data_uri = unused.pop(0)
        used.add(filename)
        return f"![{filename}]({data_uri})"

    out = placeholder_pat.sub(_repl_placeholder, out)

    # 仍未嵌入的图，追加到文末（保证 TSE 一定能看到）
    leftovers = [(f, m, u) for f, m, u in images if f not in used]
    if leftovers:
        chunks = [f"\n\n![{fn}]({uri})\n" for fn, _m, uri in leftovers]
        out = out.rstrip() + "".join(chunks)

    return out


async def embed_round_images_after_model_callback(
    callback_context: CallbackContext,
    llm_response: LlmResponse,
) -> Optional[LlmResponse]:
    """after_model：把本轮 Code Exec 图写入模型文本（data URI），供 streamQuery/TSE。"""
    if getattr(llm_response, "partial", None) is True:
        return None

    pending = _pending_image_entries(callback_context)
    if not pending:
        return None

    content = llm_response.content
    if content is None or not content.parts:
        return None

    images = await _load_image_data_uris(callback_context, pending)
    if not images:
        return None

    changed = False
    new_parts: list[types.Part] = []
    for part in content.parts:
        txt = getattr(part, "text", None)
        if txt:
            embedded = _embed_data_uris_in_text(txt, images)
            if embedded != txt:
                changed = True
            new_parts.append(types.Part(text=embedded))
        else:
            new_parts.append(part)

    # 若全是非 text part，或文本里完全没机会嵌入，仍强制追加
    if not any(getattr(p, "text", None) for p in new_parts):
        for filename, _mime, data_uri in images:
            new_parts.append(types.Part(text=f"![{filename}]({data_uri})"))
            changed = True
    elif "data:image" not in "".join(
        getattr(p, "text", "") or "" for p in new_parts
    ):
        for filename, _mime, data_uri in images:
            new_parts.append(types.Part(text=f"\n\n![{filename}]({data_uri})\n"))
            changed = True

    if not changed:
        return None

    llm_response.content = types.Content(
        role=content.role or "model",
        parts=new_parts,
    )
    return llm_response


async def deliver_session_artifacts_callback(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """after_agent：把本轮 Code Execution 图片以 inline Part 追加到 agent 响应。

    Gemini Enterprise / ADK streamQuery 只渲染最终响应里的 inline ``types.Part``，
    不会自动展示 ``save_artifact`` alone（见 adk-python #4273）。
    """
    pending = _pending_image_entries(callback_context)
    if pending or _ROUND_IMAGE_ARTIFACTS_KEY in callback_context.state:
        callback_context.state[_ROUND_IMAGE_ARTIFACTS_KEY] = []

    if not pending:
        return None

    parts: list[types.Part] = []
    for entry in pending:
        filename = str(entry.get("filename") or "").strip()
        if not filename:
            continue
        version = entry.get("version")
        try:
            loaded = await callback_context.load_artifact(
                filename=filename,
                version=version if isinstance(version, int) else None,
            )
        except Exception:
            logger.exception("GE artifact load failed filename=%s", filename)
            continue
        if loaded is None:
            continue

        data = b""
        mime = str(entry.get("mime_type") or "application/octet-stream")
        if loaded.inline_data and loaded.inline_data.data:
            data = loaded.inline_data.data
            mime = loaded.inline_data.mime_type or mime
        elif loaded.text:
            data = loaded.text.encode("utf-8")
            mime = "text/plain"
        if not data or not _is_image_mime(mime, filename):
            continue

        parts.append(
            types.Part(
                inline_data=types.Blob(
                    data=data,
                    mime_type=mime,
                    display_name=filename,
                )
            )
        )
        logger.info(
            "GE inline artifact queued filename=%s mime=%s bytes=%d",
            filename,
            mime,
            len(data),
        )

    if not parts:
        return None

    return types.Content(role="model", parts=parts)
