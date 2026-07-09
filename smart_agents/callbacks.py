# -*- coding: utf-8 -*-
"""小智 Memory Bank 写入回调（云端 Agent Engine）。"""

from __future__ import annotations

import logging

from google.adk.agents.callback_context import CallbackContext

from smart_agents.memory_ingest import MEMORY_GENERATE_METADATA

logger = logging.getLogger(__name__)


async def generate_memories_callback(callback_context: CallbackContext):
    """Dispatcher 每轮结束后写入 Memory Bank。"""
    session = callback_context.session
    if not session.events:
        logger.warning(
            "Memory Bank 跳过(after_agent)：session 无 events user=%s session=%s",
            session.user_id,
            session.id,
        )
        return None
    try:
        await callback_context.add_events_to_memory(
            events=session.events,
            custom_metadata=MEMORY_GENERATE_METADATA,
        )
        logger.info(
            "Memory Bank generate(after_agent) user=%s session=%s events=%d",
            session.user_id,
            session.id,
            len(session.events),
        )
    except ValueError:
        return None
    except Exception:
        logger.exception("Memory Bank 写入失败 (after_agent)")
    return None
