# -*- coding: utf-8 -*-
"""Unified skill directory resolution."""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_skill_dir(domain: str, skill_id: str) -> Path:
    """Find skills/<skill_id> for a domain package."""
    candidates = [
        _REPO_ROOT / "domains" / domain / "skills" / skill_id,
        _REPO_ROOT / "skills" / skill_id,
        _REPO_ROOT / domain / "skills" / skill_id,
        _REPO_ROOT / f"{domain}_cloud_agent" / "skills" / skill_id,
        _REPO_ROOT / f"{domain}_cloud_agent_mcp" / "skills" / skill_id,
        _REPO_ROOT / "smart_agents" / "skills" / skill_id,
    ]
    for path in candidates:
        if (path / "SKILL.md").is_file():
            return path
    raise FileNotFoundError(
        f"未找到 Skill {domain}/{skill_id}，请确认 skills/{skill_id}/SKILL.md 存在"
    )
