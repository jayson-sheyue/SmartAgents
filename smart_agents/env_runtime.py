# -*- coding: utf-8 -*-
"""Runtime env loading: .env then env/local.env (same order as shell scripts)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_runtime_env(*, default_env_path: str | None = None) -> None:
    """
    Load environment variables in a deterministic way.

    Priority:
    1) <repo>/.env (or default_env_path)
    2) <repo>/env/local.env (override)
    """
    base = Path(default_env_path).expanduser() if default_env_path else _REPO_ROOT / ".env"
    if not base.is_absolute():
        base = _REPO_ROOT / base

    if base.is_file():
        load_dotenv(base, override=False)

    local_env = _REPO_ROOT / "env" / "local.env"
    if local_env.is_file():
        load_dotenv(local_env, override=True)
