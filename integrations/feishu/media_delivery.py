# -*- coding: utf-8 -*-
"""将 Agent Artifact 投递到飞书会话。"""

from __future__ import annotations

import io
import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateFileRequest,
    CreateFileRequestBody,
    CreateImageRequest,
    CreateImageRequestBody,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from integrations.feishu.ask_result import DeliveredArtifact

logger = logging.getLogger(__name__)

_IMAGE_MIME_PREFIXES = ("image/",)
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}


def _is_image(artifact: DeliveredArtifact) -> bool:
    mime = (artifact.mime_type or "").lower()
    if mime.startswith(_IMAGE_MIME_PREFIXES):
        return True
    ext = ""
    if "." in artifact.filename:
        ext = "." + artifact.filename.rsplit(".", 1)[-1].lower()
    return ext in _IMAGE_EXTENSIONS


def deliver_artifacts(
    api: lark.Client,
    *,
    message_id: str,
    artifacts: list[DeliveredArtifact],
) -> None:
    """在文字回复之后，把本轮新增 Artifact 发到飞书。"""
    for artifact in artifacts:
        try:
            if _is_image(artifact):
                _reply_image(api, message_id=message_id, artifact=artifact)
            else:
                _reply_file(api, message_id=message_id, artifact=artifact)
        except Exception:
            logger.exception("飞书投递 Artifact 失败 filename=%s", artifact.filename)


def _reply_image(api: lark.Client, *, message_id: str, artifact: DeliveredArtifact) -> None:
    upload = (
        CreateImageRequest.builder()
        .request_body(
            CreateImageRequestBody.builder()
            .image_type("message")
            .image(io.BytesIO(artifact.data))
            .build()
        )
        .build()
    )
    upload_resp = api.im.v1.image.create(upload)
    if not upload_resp.success() or not upload_resp.data:
        logger.error(
            "飞书上传图片失败 filename=%s code=%s msg=%s",
            artifact.filename,
            upload_resp.code,
            upload_resp.msg,
        )
        return

    content = json.dumps({"image_key": upload_resp.data.image_key}, ensure_ascii=False)
    body = (
        ReplyMessageRequestBody.builder()
        .msg_type("image")
        .content(content)
        .build()
    )
    req = ReplyMessageRequest.builder().message_id(message_id).request_body(body).build()
    resp = api.im.v1.message.reply(req)
    if not resp.success():
        logger.error(
            "飞书回复图片失败 filename=%s code=%s msg=%s",
            artifact.filename,
            resp.code,
            resp.msg,
        )


def _reply_file(api: lark.Client, *, message_id: str, artifact: DeliveredArtifact) -> None:
    upload = (
        CreateFileRequest.builder()
        .request_body(
            CreateFileRequestBody.builder()
            .file_type("stream")
            .file_name(artifact.filename)
            .file(io.BytesIO(artifact.data))
            .build()
        )
        .build()
    )
    upload_resp = api.im.v1.file.create(upload)
    if not upload_resp.success() or not upload_resp.data:
        logger.error(
            "飞书上传文件失败 filename=%s code=%s msg=%s",
            artifact.filename,
            upload_resp.code,
            upload_resp.msg,
        )
        return

    content = json.dumps({"file_key": upload_resp.data.file_key}, ensure_ascii=False)
    body = (
        ReplyMessageRequestBody.builder()
        .msg_type("file")
        .content(content)
        .build()
    )
    req = ReplyMessageRequest.builder().message_id(message_id).request_body(body).build()
    resp = api.im.v1.message.reply(req)
    if not resp.success():
        logger.error(
            "飞书回复文件失败 filename=%s code=%s msg=%s",
            artifact.filename,
            resp.code,
            resp.msg,
        )
