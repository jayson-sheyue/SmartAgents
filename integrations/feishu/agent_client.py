# -*- coding: utf-8 -*-
"""ADK Client 封装：支持 local Runner / cloud Agent Engine 双通道。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Callable, Optional

import google.auth
import google.auth.transport.requests
import requests
from google.adk.artifacts.base_artifact_service import BaseArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService
from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.database_session_service import DatabaseSessionService
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.sessions.session import Session
from google.adk.utils.context_utils import Aclosing
from google.genai import types

from integrations.feishu.ask_result import AskResult, DeliveredArtifact
from integrations.feishu.config import FeishuBridgeConfig, apply_agent_env
from integrations.feishu.cloud_session_store import CloudSessionStore
from integrations.feishu.progress import format_from_adk_event, format_from_stream_event
from smart_agents.app_factory import build_smart_agents_app
from smart_agents.artifact_runtime import create_smart_agents_artifact_service
from smart_agents.memory_ingest import flush_session_to_memory_bank

ProgressCallback = Callable[[str], None]

logger = logging.getLogger(__name__)


class SmartAgentsClient:
    """支持双通道：
    - local: 进程内 Runner（adk run 风格）
    - cloud: Agent Engine Runtime（query/streamQuery）
    """

    def __init__(self, cfg: FeishuBridgeConfig) -> None:
        self._cfg = cfg
        self._runner: Optional[Runner] = None
        self._session_service: Optional[BaseSessionService] = None
        self._artifact_service: Optional[BaseArtifactService] = None
        self._init_lock = asyncio.Lock()
        self._gcp_session = requests.Session()
        self._gcp_session.trust_env = False
        self._cloud_session_store = CloudSessionStore(
            cfg.session_db_path.parent / "feishu_cloud_sessions.db"
        )
        self._cloud_memory_service: Optional[VertexAiMemoryBankService] = None
        if cfg.run_mode == "cloud":
            if not cfg.gcp_project_id or not cfg.smart_agents_engine_id:
                logger.warning("cloud 模式缺少 GCP 配置，Memory Bank 刷写将不可用")
            else:
                self._cloud_memory_service = VertexAiMemoryBankService(
                    project=cfg.gcp_project_id,
                    location=cfg.gcp_location,
                    agent_engine_id=cfg.smart_agents_engine_id,
                )
        if self._cfg.vertex_http_proxy:
            self._gcp_session.proxies = {
                "http": self._cfg.vertex_http_proxy,
                "https": self._cfg.vertex_http_proxy,
            }

    def _agent_engine_resource_name(self) -> str:
        if self._cfg.agent_resource_name:
            return self._cfg.agent_resource_name
        if (
            self._cfg.gcp_project_number
            and self._cfg.gcp_location
            and self._cfg.smart_agents_engine_id
        ):
            return (
                f"projects/{self._cfg.gcp_project_number}/locations/"
                f"{self._cfg.gcp_location}/reasoningEngines/{self._cfg.smart_agents_engine_id}"
            )
        raise RuntimeError(
            "cloud 模式需配置 AGENT_RESOURCE_NAME，或同时配置 "
            "GCP_PROJECT_NUMBER + GCP_LOCATION + SMART_AGENTS_ENGINE_ID"
        )

    def _agent_engine_api_base(self) -> str:
        resource = self._agent_engine_resource_name()
        return f"https://{self._cfg.gcp_location}-aiplatform.googleapis.com/v1beta1/{resource}"

    def _gcp_token(self) -> str:
        for key in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "http_proxy",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
        ):
            os.environ.pop(key, None)
        credentials, _ = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        return credentials.token

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._gcp_token()}",
            "Content-Type": "application/json",
        }

    def _cloud_query(self, class_method: str, payload: dict) -> dict:
        url = f"{self._agent_engine_api_base()}:query"
        resp = self._gcp_session.post(
            url,
            headers=self._auth_headers(),
            json={"class_method": class_method, "input": payload},
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"{class_method} HTTP {resp.status_code}: {resp.text[:400]}")
        return resp.json()

    @staticmethod
    def _extract_session_id(payload: dict) -> Optional[str]:
        if payload.get("id"):
            return str(payload["id"])
        output = payload.get("output")
        if isinstance(output, dict) and output.get("id"):
            return str(output["id"])
        if isinstance(output, dict) and isinstance(output.get("session"), dict):
            sid = output["session"].get("id")
            if sid:
                return str(sid)
        return None

    def _ensure_cloud_session(self, user_id: str, logical_session_id: str) -> str:
        """logical_session_id 为飞书群/私聊键；云端只认 Engine 分配的 id。"""
        store = self._cloud_session_store
        cloud_id = store.get_cloud_session_id(logical_session_id)
        if cloud_id:
            try:
                body = self._cloud_query(
                    "async_get_session",
                    {"user_id": user_id, "session_id": cloud_id},
                )
                existing = self._extract_session_id(body)
                if existing:
                    return existing
            except Exception:
                pass

        body = self._cloud_query("async_create_session", {"user_id": user_id})
        cloud_id = self._extract_session_id(body)
        if not cloud_id:
            raise RuntimeError(f"create_session 未返回 id: {body!r}")
        store.put(
            logical_session_id=logical_session_id,
            user_id=user_id,
            cloud_session_id=cloud_id,
        )
        logger.info(
            "新建云端 Session logical=%s cloud=%s user=%s",
            logical_session_id,
            cloud_id,
            user_id,
        )
        return cloud_id

    def _delete_cloud_session_sync(self, *, user_id: str, session_id: str) -> None:
        cloud_id = self._cloud_session_store.delete(session_id)
        if not cloud_id:
            logger.info("云端 Session 映射不存在 logical=%s", session_id)
            return
        self._cloud_query(
            "async_delete_session",
            {"user_id": user_id, "session_id": cloud_id},
        )
        logger.info(
            "已删除云端 Session logical=%s cloud=%s user=%s",
            session_id,
            cloud_id,
            user_id,
        )

    def _schedule_cloud_memory_flush(self, *, user_id: str, cloud_session_id: str) -> None:
        """云端 Engine 内 callback 可能未生效；Bridge 侧兜底刷写 Memory Bank。"""
        if self._cloud_memory_service is None:
            return
        threading.Thread(
            target=self._flush_cloud_memory_sync,
            kwargs={"user_id": user_id, "cloud_session_id": cloud_session_id},
            daemon=True,
            name=f"memory-flush-{cloud_session_id[:8]}",
        ).start()

    def _flush_cloud_memory_sync(self, *, user_id: str, cloud_session_id: str) -> None:
        try:
            body = self._cloud_query(
                "async_get_session",
                {"user_id": user_id, "session_id": cloud_session_id},
            )
            output = body.get("output") or body
            events = output.get("events") or []
            if not events:
                logger.warning(
                    "Memory Bank 刷写跳过：session 无 events cloud=%s",
                    cloud_session_id,
                )
                return
            session = Session.model_validate(output)

            async def _run() -> None:
                assert self._cloud_memory_service is not None
                await flush_session_to_memory_bank(
                    memory_service=self._cloud_memory_service,
                    session=session,
                    wait=True,
                )

            asyncio.run(_run())
            logger.info(
                "Memory Bank 刷写完成 user=%s cloud_session=%s events=%d",
                user_id,
                cloud_session_id,
                len(session.events),
            )
        except Exception:
            logger.exception(
                "Memory Bank 刷写失败 user=%s cloud_session=%s",
                user_id,
                cloud_session_id,
            )

    async def delete_session(self, *, user_id: str, session_id: str) -> None:
        """删除当前群/私聊 Session（不影响 Memory Bank 长期记忆）。"""
        if self._cfg.run_mode == "cloud":
            await asyncio.to_thread(
                self._delete_cloud_session_sync,
                user_id=user_id,
                session_id=session_id,
            )
            return
        runner = await self._ensure_runner()
        assert self._session_service is not None
        await self._session_service.delete_session(
            app_name=self._cfg.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        logger.info("已删除本地 Session user=%s session=%s", user_id, session_id)

    async def _ensure_runner(self) -> Runner:
        if self._runner is not None:
            return self._runner
        async with self._init_lock:
            if self._runner is not None:
                return self._runner
            apply_agent_env(self._cfg)
            from smart_agents.agent import root_agent

            app = build_smart_agents_app(
                name=self._cfg.app_name,
                root_agent=root_agent,
                enable_memory=True,
            )
            try:
                self._session_service = DatabaseSessionService(
                    db_url=f"sqlite:///{self._cfg.session_db_path}"
                )
                logger.info("Session 持久化: %s", self._cfg.session_db_path)
            except Exception as exc:
                logger.warning("SQLite session 不可用，回退内存: %s", exc)
                self._session_service = InMemorySessionService()

            self._artifact_service = create_smart_agents_artifact_service()
            logger.info("Artifact 持久化: smart_agents/.adk/artifacts/")

            self._runner = Runner(
                app=app,
                session_service=self._session_service,
                artifact_service=self._artifact_service,
                memory_service=InMemoryMemoryService(),
                credential_service=InMemoryCredentialService(),
            )
            logger.info(
                "SmartAgents Runner 就绪 | Bilibili MCP=%s | Etsy MCP=%s",
                self._cfg.mcp_server_url,
                self._cfg.etsy_mcp_server_url,
            )
            return self._runner

    async def _ensure_session(self, user_id: str, session_id: str):
        runner = await self._ensure_runner()
        assert self._session_service is not None
        session = await self._session_service.get_session(
            app_name=self._cfg.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        if session is None:
            session = await self._session_service.create_session(
                app_name=self._cfg.app_name,
                user_id=user_id,
                session_id=session_id,
            )
            logger.info("新建 ADK session user=%s session=%s", user_id, session_id)
        return session, runner

    async def _load_round_artifacts(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        artifact_delta: dict[str, int],
    ) -> list[DeliveredArtifact]:
        if not artifact_delta or self._artifact_service is None:
            return []

        loaded: list[DeliveredArtifact] = []
        for filename, version in artifact_delta.items():
            part = await self._artifact_service.load_artifact(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                filename=filename,
                version=version,
            )
            if part is None:
                continue
            data = b""
            mime = "application/octet-stream"
            if part.inline_data and part.inline_data.data:
                data = part.inline_data.data
                mime = part.inline_data.mime_type or mime
            elif part.text:
                data = part.text.encode("utf-8")
                mime = "text/plain"
            if not data:
                continue
            loaded.append(
                DeliveredArtifact(
                    filename=filename,
                    mime_type=mime,
                    data=data,
                    version=version,
                )
            )
        return loaded

    @staticmethod
    def _is_context_overflow_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "input token count" in msg
            and "exceeds the maximum number of tokens allowed" in msg
        )

    @staticmethod
    def _estimate_session_chars(session: Session) -> int:
        total = 0
        for event in session.events or []:
            content = event.content
            if not content or not content.parts:
                continue
            for part in content.parts:
                text = getattr(part, "text", None)
                if text:
                    total += len(text)
        return total

    async def _rotate_local_session(
        self, *, user_id: str, session_id: str, reason: str
    ) -> Session:
        assert self._session_service is not None
        await self._session_service.delete_session(
            app_name=self._cfg.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        session = await self._session_service.create_session(
            app_name=self._cfg.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        logger.warning(
            "本地会话已轮转 user=%s session=%s reason=%s",
            user_id,
            session_id,
            reason,
        )
        return session

    async def _guard_local_session_size(
        self, *, user_id: str, session_id: str, session: Session
    ) -> tuple[Session, bool]:
        if not self._cfg.local_session_guard_enabled:
            return session, False
        events = len(session.events or [])
        chars = self._estimate_session_chars(session)
        if (
            events <= self._cfg.local_session_max_events
            and chars <= self._cfg.local_session_max_chars
        ):
            return session, False
        reason = (
            f"events={events}/{self._cfg.local_session_max_events}, "
            f"chars={chars}/{self._cfg.local_session_max_chars}"
        )
        rotated = await self._rotate_local_session(
            user_id=user_id, session_id=session_id, reason=reason
        )
        return rotated, True

    async def _run_local_round(
        self,
        *,
        runner: Runner,
        session: Session,
        text: str,
        on_progress: Optional[ProgressCallback],
    ) -> tuple[dict[str, list[str]], Optional[str], dict[str, int]]:
        by_author: dict[str, list[str]] = {}
        last_author: Optional[str] = None
        artifact_delta: dict[str, int] = {}

        content = types.Content(role="user", parts=[types.Part(text=text)])
        async with Aclosing(
            runner.run_async(
                user_id=session.user_id,
                session_id=session.id,
                new_message=content,
            )
        ) as agen:
            async for event in agen:
                if on_progress:
                    progress = format_from_adk_event(event)
                    if progress:
                        on_progress(progress)
                if event.actions and event.actions.artifact_delta:
                    artifact_delta.update(event.actions.artifact_delta)
                if not event.content or not event.content.parts:
                    continue
                texts = [p.text for p in event.content.parts if p.text]
                if not texts:
                    continue
                author = event.author or "agent"
                last_author = author
                by_author.setdefault(author, []).extend(texts)
        return by_author, last_author, artifact_delta

    async def ask(
        self,
        *,
        user_id: str,
        session_id: str,
        text: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> AskResult:
        if self._cfg.run_mode == "cloud":
            reply = await asyncio.to_thread(
                self._ask_cloud_sync,
                user_id=user_id,
                session_id=session_id,
                text=text,
                on_progress=on_progress,
            )
            return AskResult(text=reply)

        """发送用户消息，取本轮最终 Agent 文本回复与新增 Artifact。"""
        session, runner = await self._ensure_session(user_id, session_id)
        session, pre_rotated = await self._guard_local_session_size(
            user_id=user_id, session_id=session_id, session=session
        )
        retried_after_overflow = False
        try:
            by_author, last_author, artifact_delta = await self._run_local_round(
                runner=runner,
                session=session,
                text=text,
                on_progress=on_progress,
            )
        except Exception as exc:
            if not self._is_context_overflow_error(exc):
                raise
            session = await self._rotate_local_session(
                user_id=user_id,
                session_id=session_id,
                reason="token-overflow",
            )
            by_author, last_author, artifact_delta = await self._run_local_round(
                runner=runner,
                session=session,
                text=text,
                on_progress=on_progress,
            )
            retried_after_overflow = True

        reply = ""
        if last_author and last_author in by_author:
            reply = "".join(by_author[last_author]).strip()
        elif by_author:
            reply = "".join(list(by_author.values())[-1]).strip()

        if not reply:
            reply = "（任务已执行，暂无文字说明。）"
        if pre_rotated:
            reply = (
                "（提示：为避免上下文过长，本会话已自动开始新轮次，长期记忆不受影响。）\n\n"
                + reply
            )
        elif retried_after_overflow:
            reply = (
                "（提示：检测到上下文超长，已自动重置当前会话后重试。）\n\n"
                + reply
            )

        artifacts = await self._load_round_artifacts(
            app_name=self._cfg.app_name,
            user_id=session.user_id,
            session_id=session.id,
            artifact_delta=artifact_delta,
        )
        logger.info(
            "Agent 回复完成 session=%s author=%s len=%d artifacts=%d",
            session_id,
            last_author,
            len(reply),
            len(artifacts),
        )
        return AskResult(text=reply, artifacts=artifacts)

    def _ask_cloud_sync(
        self,
        *,
        user_id: str,
        session_id: str,
        text: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> str:
        sid = self._ensure_cloud_session(user_id, session_id)
        url = f"{self._agent_engine_api_base()}:streamQuery"
        data = {
            "class_method": "async_stream_query",
            "input": {"message": text, "user_id": user_id, "session_id": sid},
        }
        resp = self._gcp_session.post(
            url,
            headers=self._auth_headers(),
            json=data,
            stream=True,
            timeout=300,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"streamQuery HTTP {resp.status_code}: {resp.text[:500]}")

        text_parts: list[str] = []
        for line in resp.iter_lines():
            if not line:
                continue
            line_str = line.decode("utf-8")
            if line_str.startswith("data: "):
                line_str = line_str[6:]
            try:
                event_data = json.loads(line_str)
            except json.JSONDecodeError:
                continue

            if on_progress:
                progress = format_from_stream_event(event_data)
                if progress:
                    on_progress(progress)

            candidates = [event_data]
            if isinstance(event_data.get("output"), dict):
                candidates.append(event_data["output"])
            for obj in candidates:
                content = obj.get("content")
                if not isinstance(content, dict):
                    continue
                for part in content.get("parts") or []:
                    if isinstance(part, dict) and part.get("text"):
                        text_parts.append(part["text"])

        reply = "".join(text_parts).strip()
        reply = reply or "（任务已执行，暂无文字说明。）"
        self._schedule_cloud_memory_flush(user_id=user_id, cloud_session_id=sid)
        return reply

    async def close(self) -> None:
        if self._runner is not None:
            await self._runner.close()
            self._runner = None
