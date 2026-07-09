# -*- coding: utf-8 -*-
"""Memory Bank 写入：走 memories.generate（比 ingest_events 更易产出可检索 fact）。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Sequence

if TYPE_CHECKING:
    from google.adk.events.event import Event
    from google.adk.memory.base_memory_service import BaseMemoryService
    from google.adk.sessions.session import Session

logger = logging.getLogger(__name__)

# wait_for_completion 属于 generate API 专属键 → 触发 direct_contents generate 路径
MEMORY_GENERATE_METADATA: dict[str, object] = {"wait_for_completion": False}
MEMORY_GENERATE_METADATA_SYNC: dict[str, object] = {"wait_for_completion": True}


async def flush_events_to_memory_bank(
    *,
    memory_service: "BaseMemoryService",
    app_name: str,
    user_id: str,
    events: Sequence["Event"],
    session_id: Optional[str] = None,
    wait: bool = False,
) -> None:
    """将 events 写入 Vertex Memory Bank（generate 路径）。"""
    if not events:
        logger.warning("Memory Bank 跳过：无 events user=%s", user_id)
        return
    metadata = MEMORY_GENERATE_METADATA_SYNC if wait else MEMORY_GENERATE_METADATA
    await memory_service.add_events_to_memory(
        app_name=app_name,
        user_id=user_id,
        events=events,
        session_id=session_id,
        custom_metadata=metadata,
    )
    logger.info(
        "Memory Bank generate 已触发 user=%s session=%s events=%d wait=%s",
        user_id,
        session_id,
        len(events),
        wait,
    )


async def flush_session_to_memory_bank(
    *,
    memory_service: "BaseMemoryService",
    session: "Session",
    wait: bool = False,
) -> None:
    await flush_events_to_memory_bank(
        memory_service=memory_service,
        app_name=session.app_name,
        user_id=session.user_id,
        events=session.events,
        session_id=session.id,
        wait=wait,
    )
