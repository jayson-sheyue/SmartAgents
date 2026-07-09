# -*- coding: utf-8 -*-
"""统一构造 SmartAgents App（记忆 Plugin、Session 事件压缩）。"""

from __future__ import annotations

import os
from typing import Optional

from google.adk.apps import App
from google.adk.apps._configs import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.agents.llm_agent import Agent

from smart_agents.plugins.memory_plugin import MemoryPersistencePlugin
from smart_agents.vertex import vertex_model


def _events_compaction_config() -> Optional[EventsCompactionConfig]:
    if os.getenv("SMART_AGENTS_DISABLE_EVENT_COMPACTION", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return None
    token_threshold = int(os.getenv("SMART_AGENTS_COMPACTION_TOKEN_THRESHOLD", "80000"))
    event_retention_size = int(
        os.getenv("SMART_AGENTS_COMPACTION_EVENT_RETENTION", "20")
    )
    compaction_interval = int(os.getenv("SMART_AGENTS_COMPACTION_INTERVAL", "5"))
    overlap_size = int(os.getenv("SMART_AGENTS_COMPACTION_OVERLAP", "2"))
    return EventsCompactionConfig(
        summarizer=LlmEventSummarizer(llm=vertex_model),
        compaction_interval=compaction_interval,
        overlap_size=overlap_size,
        token_threshold=token_threshold,
        event_retention_size=event_retention_size,
    )


def build_smart_agents_app(
    *,
    name: str,
    root_agent: Agent,
    enable_memory: bool = True,
    enable_compaction: bool = True,
) -> App:
    """构建 App：可选 Memory Plugin 与 events compaction。"""
    plugins = [MemoryPersistencePlugin()] if enable_memory else []
    compaction = _events_compaction_config() if enable_compaction else None
    return App(
        name=name,
        root_agent=root_agent,
        plugins=plugins,
        events_compaction_config=compaction,
    )
