# -*- coding: utf-8 -*-
"""Vertex Agent Engine Code Execution（仅挂在小智调度员）。"""

from __future__ import annotations

import mimetypes
import os
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.code_executors.base_code_executor import BaseCodeExecutor
from google.adk.code_executors.code_execution_utils import CodeExecutionUtils, File
from google.adk.tools.tool_context import ToolContext

from smart_agents.artifact_runtime import part_from_output_file
from smart_agents.artifact_callbacks import record_image_artifact_for_delivery
from smart_agents.vertex import LOCATION as DEFAULT_GCP_LOCATION
from smart_agents.vertex import PROJECT_ID

_INPUT_FILE_KEY = "_code_executor_input_files"
_MAX_FILE_BYTES = 100 * 1024 * 1024  # sandbox I/O limit per request
_executor_singleton: BaseCodeExecutor | None = None

# 与 B站 / Etsy 导出目录对齐，避免任意路径读文件
ALLOWED_DATA_ROOTS = [
    os.path.join(os.path.expanduser("~"), "Desktop"),
    os.path.join(os.path.expanduser("~"), "Documents", "BilibiliRPA"),
    os.path.join(os.path.expanduser("~"), "Documents", "EtsyData"),
]

# TSE 管家对话框挂载默认媒体桶（可被 CODE_EXEC_ALLOWED_GCS_BUCKETS 覆盖/扩充）
_DEFAULT_REMOTE_BUCKETS = ("tse-medias-asia",)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def code_exec_enabled() -> bool:
    if not _env_bool("CODE_EXECUTION_ENABLED", False):
        return False
    return bool(
        (os.getenv("CODE_EXEC_AGENT_ENGINE_RESOURCE_NAME") or "").strip()
        or (os.getenv("CODE_EXEC_SANDBOX_RESOURCE_NAME") or "").strip()
        or (os.getenv("SMART_AGENTS_ENGINE_ID") or "").strip()
    )


def _code_exec_location() -> str:
    return (
        (os.getenv("CODE_EXEC_LOCATION") or "").strip()
        or DEFAULT_GCP_LOCATION
        or "us-central1"
    )


def resolve_agent_engine_resource_name() -> Optional[str]:
    explicit = (os.getenv("CODE_EXEC_AGENT_ENGINE_RESOURCE_NAME") or "").strip()
    if explicit:
        return explicit
    engine_id = (os.getenv("SMART_AGENTS_ENGINE_ID") or "").strip()
    if not engine_id or engine_id.startswith("your-"):
        return None
    project = (os.getenv("GCP_PROJECT_ID") or PROJECT_ID or "").strip()
    if not project:
        return None
    location = _code_exec_location()
    return f"projects/{project}/locations/{location}/reasoningEngines/{engine_id}"


def _resolve_allowed_path(file_path: str) -> Path:
    raw = (file_path or "").strip()
    if not raw:
        raise ValueError("file_path 不能为空")
    path = Path(raw).expanduser().resolve()
    for root in ALLOWED_DATA_ROOTS:
        allowed = Path(root).expanduser().resolve()
        if path == allowed or str(path).startswith(str(allowed) + os.sep):
            return path
    allowed = ", ".join(ALLOWED_DATA_ROOTS)
    raise ValueError(f"file_path 不在允许目录内: {path}。允许: {allowed}")


def _allowed_gcs_buckets() -> set[str]:
    buckets: set[str] = set(_DEFAULT_REMOTE_BUCKETS)
    for key in (
        "CODE_EXEC_ALLOWED_GCS_BUCKETS",
        "MCP_ARTIFACT_GCS_BUCKET",
        "ETSY_IMAGE_GCS_BUCKET",
        "TSE_MEDIA_BUCKET_NAME",
        "MEDIA_BUCKET_NAME",
    ):
        raw = (os.getenv(key) or "").strip()
        if not raw:
            continue
        for part in re.split(r"[,;\s]+", raw):
            name = part.strip()
            if name:
                buckets.add(name)
    return buckets


def _parse_gcs_ref(raw: str) -> tuple[str, str] | None:
    """把 gs:// 或常见 GCS HTTPS URL 解析为 (bucket, object)。"""
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("gs://"):
        rest = text[5:]
        bucket, _, obj = rest.partition("/")
        if bucket and obj:
            return bucket, unquote(obj)
        return None

    parsed = urlparse(text)
    host = (parsed.netloc or "").lower()
    path = unquote((parsed.path or "").lstrip("/"))
    if not host or not path:
        return None

    if host == "storage.googleapis.com" or host == "storage.cloud.google.com":
        bucket, _, obj = path.partition("/")
        if bucket and obj:
            return bucket, obj
        return None

    if host.endswith(".storage.googleapis.com"):
        bucket = host[: -len(".storage.googleapis.com")]
        if bucket and path:
            return bucket, path
    return None


def _looks_like_remote_ref(raw: str) -> bool:
    text = (raw or "").strip().lower()
    return text.startswith("gs://") or text.startswith("http://") or text.startswith("https://")


def _safe_sandbox_name(name: str, fallback: str) -> str:
    base = (name or "").strip() or fallback
    base = base.replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^\w.\-()+ ]+", "_", base).strip(" ._")
    return base or fallback


def _guess_mime_type_name(name: str) -> str:
    mime, _ = mimetypes.guess_type(name)
    if mime:
        return mime
    lower = name.lower()
    if lower.endswith((".xlsx", ".xls")):
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if lower.endswith(".csv"):
        return "text/csv"
    if lower.endswith(".json"):
        return "application/json"
    if lower.endswith(".txt"):
        return "text/plain"
    return "application/octet-stream"


def _guess_mime_type(path: Path) -> str:
    return _guess_mime_type_name(path.name)


def _download_gcs_bytes(bucket: str, object_name: str) -> bytes:
    from google.cloud import storage  # lazy

    client = storage.Client()
    blob = client.bucket(bucket).blob(object_name)
    return blob.download_as_bytes()


def _load_remote_bytes(file_ref: str) -> tuple[bytes, str, str]:
    """
    下载允许桶内的远程附件。

    Returns:
        (raw_bytes, sandbox_file_name, source_label)
    """
    gcs = _parse_gcs_ref(file_ref)
    if not gcs:
        raise ValueError(
            "无法解析远程地址。请传 gs://bucket/object 或 "
            "https://storage.googleapis.com/bucket/object"
        )
    bucket, object_name = gcs
    allowed = _allowed_gcs_buckets()
    if bucket not in allowed:
        raise ValueError(
            f"远程桶不在白名单: {bucket}。允许: {', '.join(sorted(allowed))}。"
            "可在 CODE_EXEC_ALLOWED_GCS_BUCKETS 中追加。"
        )
    raw = _download_gcs_bytes(bucket, object_name)
    sandbox_name = _safe_sandbox_name(object_name.split("/")[-1], "upload.bin")
    return raw, sandbox_name, f"gs://{bucket}/{object_name}"


def _stage_bytes_into_state(
    *,
    tool_context: ToolContext,
    raw: bytes,
    sandbox_name: str,
    mime_type: str,
    source_label: str,
) -> dict[str, Any]:
    size = len(raw)
    if size > _MAX_FILE_BYTES:
        return {
            "ok": False,
            "tool": "stage_data_file",
            "data": {"source": source_label, "size_bytes": size},
            "error": {
                "code": "FILE_TOO_LARGE",
                "message": f"文件超过沙箱单次 100MB 限制: {size} bytes",
            },
            "meta": {},
        }

    encoded = CodeExecutionUtils.get_encoded_file_content(raw).decode("ascii")
    staged = File(name=sandbox_name, content=encoded, mime_type=mime_type)

    existing = tool_context.state.get(_INPUT_FILE_KEY) or []
    names = {item.get("name") for item in existing if isinstance(item, dict)}
    already = sandbox_name in names
    if not already:
        existing = list(existing)
        existing.append(
            {
                "name": staged.name,
                "content": staged.content,
                "mime_type": staged.mime_type,
            }
        )
        tool_context.state[_INPUT_FILE_KEY] = existing

    read_hint = (
        f"pd.read_csv('{sandbox_name}')"
        if sandbox_name.lower().endswith(".csv")
        else f"pd.read_excel('{sandbox_name}')"
        if sandbox_name.lower().endswith((".xlsx", ".xls"))
        else f"open('{sandbox_name}')"
    )
    return {
        "ok": True,
        "tool": "stage_data_file",
        "data": {
            "sandbox_file_name": sandbox_name,
            "source_path": source_label,
            "size_bytes": size,
            "mime_type": mime_type,
            "hint": (
                f"文件已送入沙箱，分析时用 Python 读取 `{sandbox_name}` "
                f"（例如 {read_hint}）"
            ),
        },
        "error": None,
        "meta": {"already_staged": already},
    }


def build_code_executor() -> BaseCodeExecutor:
    """构造 Agent Engine Sandbox code executor（由 ADK 自动触发写码与执行）。"""
    sandbox_name = (os.getenv("CODE_EXEC_SANDBOX_RESOURCE_NAME") or "").strip() or None
    agent_engine_name = resolve_agent_engine_resource_name()

    kwargs: dict[str, Any] = {
        "stateful": _env_bool("CODE_EXECUTION_STATEFUL", True),
        "optimize_data_file": _env_bool("CODE_EXECUTION_OPTIMIZE_DATA_FILE", True),
        "error_retry_attempts": _env_int("CODE_EXECUTION_ERROR_RETRY", 2),
    }
    timeout = _env_int("CODE_EXECUTION_TIMEOUT_SECONDS", 0)
    if timeout > 0:
        kwargs["timeout_seconds"] = timeout

    if sandbox_name:
        return AgentEngineSandboxCodeExecutor(
            sandbox_resource_name=sandbox_name,
            **kwargs,
        )
    if not agent_engine_name:
        raise RuntimeError(
            "Code Execution 已启用但缺少 Agent Engine："
            "设置 SMART_AGENTS_ENGINE_ID 或 CODE_EXEC_AGENT_ENGINE_RESOURCE_NAME"
        )
    return AgentEngineSandboxCodeExecutor(
        agent_engine_resource_name=agent_engine_name,
        **kwargs,
    )


def set_code_executor(executor: BaseCodeExecutor) -> None:
    """由 agent 模块在启动时注入，供 run_code 工具复用同一 sandbox。"""
    global _executor_singleton
    _executor_singleton = executor


def get_code_executor() -> BaseCodeExecutor:
    global _executor_singleton
    if _executor_singleton is None:
        _executor_singleton = build_code_executor()
    return _executor_singleton


def _execution_id_for(
    executor: BaseCodeExecutor, tool_context: ToolContext
) -> str | None:
    if not executor.stateful:
        return None
    from google.adk.code_executors.code_executor_context import CodeExecutorContext

    ctx = CodeExecutorContext(tool_context.state)
    execution_id = ctx.get_execution_id()
    if execution_id:
        return execution_id
    inv = getattr(tool_context, "_invocation_context", None)
    session_id = getattr(getattr(inv, "session", None), "id", None) if inv else None
    if session_id:
        ctx.set_execution_id(session_id)
        return session_id
    return None


async def run_code(code: str, tool_context: ToolContext) -> dict[str, Any]:
    """
    在 GCP Code Execution 沙箱中执行 Python 代码并返回 stdout/stderr。

    适用：统计、计算、pandas 分析、matplotlib 画图（预装库；无网络）。
    分析本机 Excel/CSV 前，若文件在 Desktop/EtsyData/BilibiliRPA，先 `stage_data_file`。
    生成的文件会注册为 Session Artifact，供各通道（飞书/adk）取用。
    """
    from google.adk.code_executors.code_execution_utils import CodeExecutionInput
    from google.adk.code_executors.code_executor_context import CodeExecutorContext

    tool = "run_code"
    source = (code or "").strip()
    if not source:
        return {
            "ok": False,
            "tool": tool,
            "data": {},
            "error": {"code": "EMPTY_CODE", "message": "code 不能为空"},
            "meta": {},
        }

    inv = getattr(tool_context, "_invocation_context", None)
    if inv is None:
        return {
            "ok": False,
            "tool": tool,
            "data": {},
            "error": {
                "code": "NO_INVOCATION_CONTEXT",
                "message": "无法获取 invocation context",
            },
            "meta": {},
        }

    executor = get_code_executor()
    ctx = CodeExecutorContext(tool_context.state)
    try:
        result = executor.execute_code(
            inv,
            CodeExecutionInput(
                code=source,
                input_files=ctx.get_input_files(),
                execution_id=_execution_id_for(executor, tool_context),
            ),
        )
    except Exception as exc:
        return {
            "ok": False,
            "tool": tool,
            "data": {},
            "error": {"code": "EXECUTION_FAILED", "message": str(exc)},
            "meta": {},
        }

    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    saved_artifacts: list[dict[str, Any]] = []
    for output_file in result.output_files:
        filename = (output_file.name or "output.bin").strip() or "output.bin"
        try:
            version = await tool_context.save_artifact(
                filename=filename,
                artifact=part_from_output_file(output_file),
                custom_metadata={"source": "run_code"},
            )
            saved_artifacts.append(
                {
                    "filename": filename,
                    "version": version,
                    "mime_type": output_file.mime_type or "application/octet-stream",
                }
            )
            record_image_artifact_for_delivery(
                tool_context.state,
                filename=filename,
                version=version,
                mime_type=output_file.mime_type or "application/octet-stream",
            )
        except Exception as exc:
            saved_artifacts.append(
                {
                    "filename": filename,
                    "error": str(exc),
                }
            )

    artifact_root = ""
    try:
        from smart_agents.artifact_runtime import smart_agents_artifact_root

        artifact_root = str(smart_agents_artifact_root())
    except Exception:
        pass

    return {
        "ok": not stderr,
        "tool": tool,
        "data": {
            "stdout": stdout,
            "stderr": stderr,
            "artifacts": saved_artifacts,
            "output_file_names": [a.get("filename") for a in saved_artifacts if a.get("filename")],
        },
        "error": (
            {"code": "RUNTIME_ERROR", "message": stderr} if stderr else None
        ),
        "meta": {
            "sandbox_name": tool_context.state.get("sandbox_name"),
            "artifact_root": artifact_root,
        },
    }


def stage_data_file(
    file_path: str,
    tool_context: ToolContext,
    as_name: str = "",
) -> dict[str, Any]:
    """
    将数据文件送入 Code Execution 沙箱（供后续 `run_code` 用 pandas 分析）。

    ``file_path`` 支持：
    - 本机路径（Desktop / Documents/BilibiliRPA / Documents/EtsyData）
    - TSE 对话框挂载的 GCS URL：
      ``https://storage.googleapis.com/<bucket>/...`` 或 ``gs://<bucket>/...``

    ``as_name`` 可选：沙箱内文件名（例如用户附件显示名
    ``hot_ranking_day_....csv``）。TSE 上传常把 xlsx 转成 csv，请用 ``.csv``。
    """
    tool = "stage_data_file"
    raw_ref = (file_path or "").strip()
    if not raw_ref:
        return {
            "ok": False,
            "tool": tool,
            "data": {},
            "error": {"code": "EMPTY_PATH", "message": "file_path 不能为空"},
            "meta": {},
        }

    # Markdown 误传整段时，尽量抽出第一个 URL
    md = re.search(r"\((https?://[^)\s]+|gs://[^)\s]+)\)", raw_ref)
    if md:
        raw_ref = md.group(1)

    try:
        if _looks_like_remote_ref(raw_ref):
            data, default_name, source_label = _load_remote_bytes(raw_ref)
            sandbox_name = _safe_sandbox_name(as_name, default_name)
            # 显示名仍带 .xlsx 但对象已是 csv 时，纠正扩展名以免 pd.read_excel 失败
            if default_name.lower().endswith(".csv") and sandbox_name.lower().endswith(
                (".xlsx", ".xls")
            ):
                sandbox_name = Path(sandbox_name).with_suffix(".csv").name
            mime_type = _guess_mime_type_name(sandbox_name)
            return _stage_bytes_into_state(
                tool_context=tool_context,
                raw=data,
                sandbox_name=sandbox_name,
                mime_type=mime_type,
                source_label=source_label,
            )

        path = _resolve_allowed_path(raw_ref)
    except ValueError as exc:
        return {
            "ok": False,
            "tool": tool,
            "data": {},
            "error": {"code": "PATH_NOT_ALLOWED", "message": str(exc)},
            "meta": {},
        }
    except Exception as exc:
        return {
            "ok": False,
            "tool": tool,
            "data": {"file_path": raw_ref},
            "error": {
                "code": "DOWNLOAD_FAILED",
                "message": (
                    f"下载远程附件失败: {exc}。"
                    "请确认 Agent Engine 服务账号对媒体桶有 storage.objectViewer。"
                ),
            },
            "meta": {},
        }

    if not path.is_file():
        return {
            "ok": False,
            "tool": tool,
            "data": {"file_path": str(path)},
            "error": {"code": "FILE_NOT_FOUND", "message": f"文件不存在: {path}"},
            "meta": {},
        }

    data = path.read_bytes()
    sandbox_name = _safe_sandbox_name(as_name, path.name)
    mime_type = _guess_mime_type_name(sandbox_name)
    return _stage_bytes_into_state(
        tool_context=tool_context,
        raw=data,
        sandbox_name=sandbox_name,
        mime_type=mime_type,
        source_label=str(path),
    )
