# -*- coding: utf-8 -*-
"""Load domain manifest.yaml (tools + skills registry)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DomainManifest:
    domain: str
    agent_name: str
    standalone_name: str
    description: str
    skills: tuple[str, ...]
    mcp_tools: tuple[str, ...]
    routing_keywords: tuple[str, ...]

    @classmethod
    def load(cls, domain: str) -> "DomainManifest":
        path = _REPO_ROOT / "domains" / domain / "manifest.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"缺少 manifest: {path}")
        raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            domain=domain,
            agent_name=str(raw.get("agent_name", f"{domain}_agent")),
            standalone_name=str(raw.get("standalone_name", f"{domain.title()}_Agent")),
            description=str(raw.get("description", "")),
            skills=tuple(raw.get("skills") or ()),
            mcp_tools=tuple(raw.get("mcp_tools") or ()),
            routing_keywords=tuple(raw.get("routing_keywords") or ()),
        )
