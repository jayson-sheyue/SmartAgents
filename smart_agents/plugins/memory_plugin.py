# -*- coding: utf-8 -*-
"""整轮 invocation 结束后写入 Memory Bank（Plugin 兜底）。"""

from __future__ import annotations

import logging

from google.adk.agents.invocation_context import InvocationContext
from google.adk.plugins.base_plugin import BasePlugin

from smart_agents.memory_ingest import flush_session_to_memory_bank

logger = logging.getLogger(__name__)


class MemoryPersistencePlugin(BasePlugin):
    """Runner 一次 run 完成后 flush Session 到 Memory Bank。"""

    def __init__(self) -> None:
        super().__init__(name="memory_persistence")

    async def _resolve_session(self, invocation_context: InvocationContext):
        session = invocation_context.session
        if session is None:
            return None
        session_service = invocation_context.session_service
        if session_service is None:
            return session
        try:
            fresh = await session_service.get_session(
                app_name=session.app_name,
                user_id=session.user_id,
                session_id=session.id,
            )
            if fresh is not None and fresh.events:
                return fresh
        except Exception:
            logger.exception("Memory Bank 刷新 session 失败，使用内存副本")
        return session

    async def after_run_callback(
        self, *, invocation_context: InvocationContext
    ) -> None:
        memory_service = invocation_context.memory_service
        if memory_service is None:
            logger.warning("Memory Bank 跳过(plugin)：memory_service 未配置")
            return

        session = await self._resolve_session(invocation_context)
        if session is None or not session.events:
            logger.warning(
                "Memory Bank 跳过(plugin)：session 无 events user=%s",
                getattr(session, "user_id", "?"),
            )
            return

        try:
            await flush_session_to_memory_bank(
                memory_service=memory_service,
                session=session,
                wait=False,
            )
        except Exception:
            logger.exception("Memory Bank 写入失败 (plugin)")
