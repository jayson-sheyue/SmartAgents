# -*- coding: utf-8 -*-
"""ADK Artifact 服务工厂（小智 / 飞书 / adk run 共用路径）。"""

from __future__ import annotations

import base64
from pathlib import Path

from google.adk.artifacts.base_artifact_service import BaseArtifactService
from google.adk.cli.utils.local_storage import create_local_artifact_service
from google.adk.code_executors.code_execution_utils import File
from google.genai import types

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SMART_AGENTS_APP = "smart_agents"


def smart_agents_artifact_root() -> Path:
    """本机 Artifact 根目录：smart_agents/.adk/artifacts/"""
    return _REPO_ROOT / _SMART_AGENTS_APP / ".adk" / "artifacts"


def create_smart_agents_artifact_service() -> BaseArtifactService:
    """与 `adk run smart_agents` 使用同一 per-agent 文件 Artifact 后端。"""
    return create_local_artifact_service(base_dir=_REPO_ROOT / _SMART_AGENTS_APP)


def output_file_to_bytes(output_file: File) -> bytes:
    """将沙箱 output File 转为原始 bytes（支持 base64 str）。"""
    content = output_file.content
    if isinstance(content, bytes):
        return content
    return base64.b64decode(content)


def part_from_output_file(output_file: File) -> types.Part:
    raw = output_file_to_bytes(output_file)
    mime = output_file.mime_type or "application/octet-stream"
    return types.Part.from_bytes(data=raw, mime_type=mime)
