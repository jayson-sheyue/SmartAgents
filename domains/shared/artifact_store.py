# -*- coding: utf-8 -*-
"""Cloud Run MCP 产物：写 GCS + 可选签名下载 URL。"""

from __future__ import annotations

import os
import tempfile
from datetime import timedelta
from typing import Any, Optional


def artifact_bucket() -> str:
    return (
        (os.getenv("MCP_ARTIFACT_GCS_BUCKET") or "").strip()
        or (os.getenv("ETSY_IMAGE_GCS_BUCKET") or "").strip()
    )


def artifact_prefix() -> str:
    p = (os.getenv("MCP_ARTIFACT_GCS_PREFIX") or "mcp-artifacts/").strip()
    if p and not p.endswith("/"):
        p += "/"
    return p or "mcp-artifacts/"


def signed_url_ttl_seconds() -> int:
    raw = (os.getenv("MCP_ARTIFACT_SIGNED_URL_TTL_SEC") or "").strip()
    if raw.isdigit():
        return max(60, int(raw))
    return 7 * 24 * 3600


def require_artifact_bucket() -> str:
    bucket = artifact_bucket()
    if not bucket:
        raise ValueError(
            "未配置 MCP_ARTIFACT_GCS_BUCKET（或 ETSY_IMAGE_GCS_BUCKET）。"
            "Cloud Run MCP 禁止写本地盘，请先配置 GCS 桶。"
        )
    return bucket


def upload_bytes(
    data: bytes,
    *,
    object_name: str,
    content_type: str = "application/octet-stream",
    make_signed_url: bool = True,
) -> dict[str, Any]:
    """上传字节到 GCS，返回 gcs_uri / object_name / signed_url?。"""
    from google.cloud import storage  # lazy

    bucket_name = require_artifact_bucket()
    prefix = artifact_prefix()
    name = object_name.lstrip("/")
    if not name.startswith(prefix):
        name = f"{prefix}{name}"

    client = storage.Client()
    blob = client.bucket(bucket_name).blob(name)
    blob.upload_from_string(data, content_type=content_type)
    gcs_uri = f"gs://{bucket_name}/{name}"
    out: dict[str, Any] = {
        "gcs_uri": gcs_uri,
        "bucket": bucket_name,
        "object_name": name,
        "content_type": content_type,
        "size_bytes": len(data),
    }
    if make_signed_url:
        try:
            out["signed_url"] = blob.generate_signed_url(
                expiration=timedelta(seconds=signed_url_ttl_seconds()),
                method="GET",
            )
        except Exception as exc:
            # Cloud Run 默认 SA 可能无签名密钥；仍返回 gs://
            out["signed_url"] = None
            out["signed_url_error"] = str(exc)[:200]
    return out


def upload_file(
    path: str,
    *,
    object_name: str,
    content_type: str = "application/octet-stream",
    make_signed_url: bool = True,
) -> dict[str, Any]:
    with open(path, "rb") as f:
        data = f.read()
    return upload_bytes(
        data,
        object_name=object_name,
        content_type=content_type,
        make_signed_url=make_signed_url,
    )


def upload_excel_bytes(
    data: bytes,
    *,
    filename: str,
    subdomain: str = "excel",
) -> dict[str, Any]:
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename) or "export.xlsx"
    if not safe.lower().endswith(".xlsx"):
        safe += ".xlsx"
    return upload_bytes(
        data,
        object_name=f"{subdomain}/{safe}",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def write_dataframe_excel_to_gcs(
    df: Any,
    *,
    filename: str,
    sheet_name: str = "Sheet1",
    subdomain: str = "excel",
) -> dict[str, Any]:
    """pandas DataFrame → 临时 xlsx → GCS。"""
    import pandas as pd  # noqa: F401 — df already pandas-like

    require_artifact_bucket()
    fd, tmp_path = tempfile.mkstemp(suffix=".xlsx")
    os.close(fd)
    try:
        with pd.ExcelWriter(tmp_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name=sheet_name, index=False)
        return upload_file(
            tmp_path,
            object_name=f"{subdomain}/{filename}",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def gcs_error_envelope(tool: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool,
        "data": {},
        "error": {
            "code": "GCS_BUCKET_MISSING",
            "message": message,
            "retryable": False,
        },
        "meta": {},
    }
