# -*- coding: utf-8 -*-
"""飞书 Bridge 环境配置。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from smart_agents.env_runtime import load_runtime_env

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]
load_runtime_env(default_env_path=str(_ROOT / ".env"))


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class FeishuBridgeConfig:
    app_id: str
    app_secret: str
    verification_token: str
    encrypt_key: str
    bot_open_id: str
    owner_open_id: str
    owner_aliases: tuple[str, ...]
    strict_loyalty_mode: bool
    group_require_mention: bool
    send_ack: bool
    send_progress: bool
    progress_min_interval_sec: float
    ack_text: str
    app_name: str
    run_mode: str
    mcp_server_url: str
    etsy_mcp_server_url: str
    session_db_path: Path
    ssl_verify: bool
    gcp_project_id: str
    gcp_project_number: str
    gcp_location: str
    smart_agents_engine_id: str
    agent_resource_name: str
    vertex_http_proxy: str
    local_session_guard_enabled: bool
    local_session_max_events: int
    local_session_max_chars: int

    @classmethod
    def from_env(cls) -> "FeishuBridgeConfig":
        app_id = (os.getenv("FEISHU_APP_ID") or "").strip()
        app_secret = (
            os.getenv("FEISHU_APP_SECRET")
            or os.getenv("FEISHU_APP_TOKEN")
            or ""
        ).strip()
        if not app_id or not app_secret:
            raise RuntimeError(
                "请在根 .env 设置 FEISHU_APP_ID 与 FEISHU_APP_SECRET（或 FEISHU_APP_TOKEN）"
            )

        db_dir = _ROOT / "integrations" / "feishu" / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        run_mode = (os.getenv("FEISHU_RUN_MODE") or "local").strip().lower()
        if run_mode not in {"local", "cloud"}:
            raise RuntimeError("FEISHU_RUN_MODE 仅支持 local / cloud")
        project_id = (os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID") or "").strip()
        project_number = (os.getenv("GCP_PROJECT_NUMBER") or "").strip()
        location = (os.getenv("GCP_LOCATION") or "us-central1").strip()
        smart_agents_engine_id = (os.getenv("SMART_AGENTS_ENGINE_ID") or "").strip()
        agent_resource_name = (os.getenv("AGENT_RESOURCE_NAME") or "").strip()
        vertex_http_proxy = (
            (os.getenv("VERTEX_HTTP_PROXY") or os.getenv("HTTPS_PROXY") or "").strip()
        )
        local_session_guard_enabled = _env_bool("FEISHU_LOCAL_SESSION_GUARD_ENABLED", True)
        local_session_max_events = int(os.getenv("FEISHU_LOCAL_SESSION_MAX_EVENTS", "240"))
        local_session_max_chars = int(
            os.getenv("FEISHU_LOCAL_SESSION_MAX_CHARS", "600000")
        )

        owner_open_id = (os.getenv("FEISHU_OWNER_OPEN_ID") or "").strip()
        owner_aliases = tuple(
            x.strip()
            for x in (os.getenv("FEISHU_OWNER_ALIASES") or "").split(",")
            if x.strip()
        )
        strict_loyalty_mode = _env_bool("FEISHU_STRICT_LOYALTY_MODE", True)
        if strict_loyalty_mode:
            if not owner_open_id:
                logger.warning(
                    "FEISHU_STRICT_LOYALTY_MODE=true 但未设置 FEISHU_OWNER_OPEN_ID；"
                    "无法区分主人与非主人，注入拦截可能误伤或漏拦"
                )
            if not owner_aliases:
                logger.warning(
                    "FEISHU_STRICT_LOYALTY_MODE=true 但未设置 FEISHU_OWNER_ALIASES；"
                    "针对主人别名的辱骂/攻击指令将不会被拦截"
                )

        return cls(
            app_id=app_id,
            app_secret=app_secret,
            verification_token=(os.getenv("FEISHU_VERIFICATION_TOKEN") or "").strip(),
            encrypt_key=(os.getenv("FEISHU_ENCRYPT_KEY") or "").strip(),
            bot_open_id=(os.getenv("FEISHU_BOT_OPEN_ID") or "").strip(),
            owner_open_id=owner_open_id,
            owner_aliases=owner_aliases,
            strict_loyalty_mode=strict_loyalty_mode,
            group_require_mention=_env_bool("FEISHU_GROUP_REQUIRE_MENTION", True),
            send_ack=_env_bool("FEISHU_SEND_ACK", True),
            send_progress=_env_bool("FEISHU_SEND_PROGRESS", True),
            progress_min_interval_sec=float(
                os.getenv("FEISHU_PROGRESS_MIN_INTERVAL_SEC", "1.5")
            ),
            ack_text=os.getenv(
                "FEISHU_ACK_TEXT", "小智已收到，正在为您处理，请稍候…"
            ),
            app_name=os.getenv("FEISHU_ADK_APP_NAME", "smart_agents"),
            run_mode=run_mode,
            mcp_server_url=os.getenv(
                "SMART_AGENTS_BILIBILI_MCP_SERVER_URL",
                os.getenv("BILIBILI_MCP_SERVER_URL", ""),
            ),
            etsy_mcp_server_url=os.getenv(
                "SMART_AGENTS_ETSY_MCP_SERVER_URL",
                os.getenv("ETSY_MCP_SERVER_URL", ""),
            ),
            session_db_path=db_dir / "feishu_sessions.db",
            ssl_verify=_env_bool("FEISHU_SSL_VERIFY", True),
            gcp_project_id=project_id,
            gcp_project_number=project_number,
            gcp_location=location,
            smart_agents_engine_id=smart_agents_engine_id,
            agent_resource_name=agent_resource_name,
            vertex_http_proxy=vertex_http_proxy,
            local_session_guard_enabled=local_session_guard_enabled,
            local_session_max_events=local_session_max_events,
            local_session_max_chars=local_session_max_chars,
        )


def apply_agent_env(cfg: FeishuBridgeConfig) -> None:
    """在 import smart_agents 之前注入 MCP 端点（与 run_adk_smart_agents.sh 一致）。"""
    mcp = cfg.mcp_server_url.rstrip("/")
    if not mcp.endswith("/mcp"):
        mcp = f"{mcp}/mcp"
    etsy = cfg.etsy_mcp_server_url.rstrip("/")
    if not etsy.endswith("/mcp"):
        etsy = f"{etsy}/mcp"
    os.environ["BILIBILI_MCP_SERVER_URL"] = mcp
    os.environ["ETSY_MCP_SERVER_URL"] = etsy

    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        os.environ.pop(key, None)
    no_proxy = os.getenv("NO_PROXY") or os.getenv("no_proxy") or ""
    parts = {p.strip() for p in no_proxy.split(",") if p.strip()}
    parts.update({"127.0.0.1", "localhost", ".local"})
    os.environ["NO_PROXY"] = ",".join(sorted(parts))
