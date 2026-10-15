# -*- coding: utf-8 -*-
"""A2A AgentExecutor：把 A2A message 转进现有 ADK root_agent（不重写调度树）。"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from a2a import types as a2a_types
from a2a.server.agent_execution.agent_executor import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TaskState
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

_IMAGE_MIME_PREFIXES = ("image/",)
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico"}
_UNSAFE_USER_ID_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _safe_user_id(raw: Any) -> str:
    """GE may pass email / resource names; keep a stable path-safe id."""
    s = str(raw or "").strip() or "a2a_user"
    s = s.replace("@", "_at_").replace("/", "_").replace("\\", "_").replace(" ", "_")
    s = _UNSAFE_USER_ID_RE.sub("_", s).strip("._-") or "a2a_user"
    return s[:128]


def _is_image_mime(mime: str, filename: str) -> bool:
    m = (mime or "").lower()
    if any(m.startswith(p) for p in _IMAGE_MIME_PREFIXES):
        return True
    name = (filename or "").lower()
    return any(name.endswith(ext) for ext in _IMAGE_EXTENSIONS)


def _part_from_bytes(*, data: bytes, filename: str, mime_type: str) -> Part:
    """Build A2A protobuf Part carrying inline file bytes (REST ``raw`` field)."""
    return Part(raw=data, filename=filename, media_type=mime_type)


class SmartAgentsA2aExecutor(AgentExecutor):
    """Reuses SmartAgents root_agent via ADK Runner (in-memory Session/Memory for PoC)."""

    def __init__(self, agent=None) -> None:
        self._agent = agent
        self._runner: Optional[Runner] = None
        self._artifact_service: Optional[InMemoryArtifactService] = None

    def _resolve_agent(self):
        if self._agent is not None:
            return self._agent
        from smart_agents.agent import root_agent

        self._agent = root_agent
        return self._agent

    def _init_runner(self) -> Runner:
        if self._runner is not None:
            return self._runner
        agent = self._resolve_agent()
        self._artifact_service = InMemoryArtifactService()
        self._runner = Runner(
            app_name=getattr(agent, "name", None) or "SmartAgents_Dispatcher",
            agent=agent,
            artifact_service=self._artifact_service,
            session_service=InMemorySessionService(),
            memory_service=InMemoryMemoryService(),
            credential_service=InMemoryCredentialService(),
        )
        return self._runner

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id or "",
            context_id=context.context_id or "",
        )
        await updater.cancel()

    async def _load_image_parts(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        artifact_delta: dict[str, int],
    ) -> list[Part]:
        if not artifact_delta or self._artifact_service is None:
            return []

        parts: list[Part] = []
        for filename, version in artifact_delta.items():
            try:
                adk_part = await self._artifact_service.load_artifact(
                    app_name=app_name,
                    user_id=user_id,
                    session_id=session_id,
                    filename=filename,
                    version=version,
                )
            except Exception:
                logger.exception("load_artifact failed filename=%s", filename)
                continue
            if adk_part is None:
                continue

            data = b""
            mime = "application/octet-stream"
            if adk_part.inline_data and adk_part.inline_data.data:
                data = adk_part.inline_data.data
                mime = adk_part.inline_data.mime_type or mime
            if not data or not _is_image_mime(mime, filename):
                continue

            parts.append(
                _part_from_bytes(data=data, filename=filename, mime_type=mime)
            )
            logger.warning(
                "A2A image artifact ready filename=%s mime=%s bytes=%d",
                filename,
                mime,
                len(data),
            )
        return parts

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        if not context.message:
            return

        runner = self._init_runner()
        metadata: dict[str, Any] = {}
        if context.message.metadata:
            try:
                metadata = dict(context.message.metadata)
            except Exception:
                metadata = {}

        raw_uid = (
            metadata.get("user_id")
            or metadata.get("userId")
            or metadata.get("user")
            or metadata.get("email")
            or "a2a_user"
        )
        user_id = _safe_user_id(raw_uid)
        session_id = context.context_id or context.task_id or "a2a_session"

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id or "",
            context_id=context.context_id or "",
        )

        task = a2a_types.Task(
            id=context.task_id,
            context_id=context.context_id,
            status=a2a_types.TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            history=[context.message] if context.message else [],
        )
        await event_queue.enqueue_event(task)
        await updater.start_work()

        query = ""
        try:
            query = (context.get_user_input() or "").strip()
        except Exception:
            query = ""
        if not query and context.message and context.message.parts:
            texts = []
            for part in context.message.parts:
                text = getattr(part, "text", None)
                if text:
                    texts.append(text)
            query = "\n".join(texts).strip()

        if not query:
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=updater.new_agent_message(
                    [Part(text="Empty user message; nothing to execute.")]
                ),
            )
            return

        content = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=query)],
        )

        try:
            session = await runner.session_service.get_session(
                app_name=runner.app_name,
                user_id=user_id,
                session_id=session_id,
            )
            if session is None:
                session = await runner.session_service.create_session(
                    app_name=runner.app_name,
                    user_id=user_id,
                    session_id=session_id,
                )

            by_author: dict[str, list[str]] = {}
            last_author: Optional[str] = None
            artifact_delta: dict[str, int] = {}

            async for event in runner.run_async(
                session_id=session.id,
                user_id=user_id,
                new_message=content,
            ):
                if event.actions and getattr(event.actions, "artifact_delta", None):
                    artifact_delta.update(event.actions.artifact_delta)

                if not getattr(event, "content", None) or not event.content.parts:
                    continue
                chunk = [
                    p.text
                    for p in event.content.parts
                    if getattr(p, "text", None)
                ]
                if not chunk:
                    continue
                author = getattr(event, "author", None) or "agent"
                last_author = author
                by_author.setdefault(author, []).extend(chunk)

            if last_author and by_author.get(last_author):
                response_text = "\n".join(by_author[last_author]).strip()
            else:
                flat = [t for texts in by_author.values() for t in texts]
                response_text = "\n".join(flat).strip()

            image_parts = await self._load_image_parts(
                app_name=runner.app_name,
                user_id=user_id,
                session_id=session.id,
                artifact_delta=artifact_delta,
            )

            if not response_text and not image_parts:
                await updater.update_status(
                    TaskState.TASK_STATE_FAILED,
                    message=updater.new_agent_message(
                        [
                            Part(
                                text=(
                                    "No textual response from SmartAgents. "
                                    "Check MCP / tools / model events."
                                )
                            )
                        ]
                    ),
                )
                return

            if not response_text and image_parts:
                response_text = f"已生成 {len(image_parts)} 张图片。"

            message_parts: list[Part] = [Part(text=response_text), *image_parts]
            agent_message = updater.new_agent_message(message_parts)

            # Text artifact for GE clients that render task.artifacts
            await updater.add_artifact(
                [Part(text=response_text)],
                name="result",
                last_chunk=True,
            )
            for img in image_parts:
                name = getattr(img, "filename", None) or "image.png"
                await updater.add_artifact(
                    [img],
                    name=name,
                    last_chunk=True,
                )

            await updater.complete(message=agent_message)
        except Exception as exc:
            logger.exception("SmartAgents A2A execute failed")
            await updater.update_status(
                TaskState.TASK_STATE_FAILED,
                message=updater.new_agent_message(
                    [Part(text=f"SmartAgents A2A error: {exc}")]
                ),
            )


def build_executor(agent=None) -> SmartAgentsA2aExecutor:
    return SmartAgentsA2aExecutor(agent=agent)
