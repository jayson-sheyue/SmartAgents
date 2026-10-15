# -*- coding: utf-8 -*-
"""飞书 Bridge 与 Agent 之间的结构化回复。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DeliveredArtifact:
    filename: str
    mime_type: str
    data: bytes
    version: int


@dataclass
class AskResult:
    text: str
    artifacts: list[DeliveredArtifact] = field(default_factory=list)
