# -*- coding: utf-8 -*-
"""Vertex Gemini + 代理隔离（调度树与各子 Agent 共用）。"""

from __future__ import annotations

import os
from functools import cached_property
from typing import Optional

import httpx
from dotenv import load_dotenv
from google.adk.models import Gemini
from google.genai import Client

load_dotenv()

# Agent Engine / Cloud Run 自动注入 GOOGLE_CLOUD_PROJECT，本地开发用 GCP_PROJECT_ID
PROJECT_ID = (
    os.getenv("GCP_PROJECT_ID")
    or os.getenv("PROJECT_ID")
    or os.getenv("GOOGLE_CLOUD_PROJECT")
    or ""
)
LOCATION = (
    os.getenv("GCP_LOCATION")
    or os.getenv("GOOGLE_CLOUD_REGION")
    or os.getenv("GOOGLE_CLOUD_LOCATION")
    or "us-central1"
)

if not PROJECT_ID:
    raise RuntimeError(
        "请设置 GCP_PROJECT_ID（本地 .env）或确保运行在已注入 GOOGLE_CLOUD_PROJECT 的 GCP 环境"
    )


def _pick_vertex_proxy_url() -> Optional[str]:
    for key in (
        "VERTEX_HTTP_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return None


def _isolate_global_proxy_env(vertex_proxy: Optional[str]) -> None:
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "http_proxy",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
    ):
        os.environ.pop(key, None)
    if vertex_proxy:
        os.environ["VERTEX_HTTP_PROXY"] = vertex_proxy
    no_proxy = os.getenv("NO_PROXY") or os.getenv("no_proxy") or ""
    parts = {p.strip() for p in no_proxy.split(",") if p.strip()}
    parts.update({"127.0.0.1", "localhost", ".local"})
    os.environ["NO_PROXY"] = ",".join(sorted(parts))


_VERTEX_PROXY = _pick_vertex_proxy_url()
_isolate_global_proxy_env(_VERTEX_PROXY)

_vertex_httpx_kwargs: dict = {"trust_env": False, "follow_redirects": True}
if _VERTEX_PROXY:
    _vertex_httpx_kwargs["proxy"] = _VERTEX_PROXY

_VERTEX_HTTPX_ASYNC = httpx.AsyncClient(**_vertex_httpx_kwargs)
_VERTEX_HTTPX_SYNC = httpx.Client(**_vertex_httpx_kwargs)

if _VERTEX_PROXY:
    print(f"🔐 Vertex 网络：经代理 {_VERTEX_PROXY}")
else:
    print("🔐 Vertex 网络：直连")


class VertexGemini(Gemini):
    @cached_property
    def api_client(self) -> Client:
        return Client(
            vertexai=True,
            project=PROJECT_ID,
            location=LOCATION,
            http_options={
                "httpx_async_client": _VERTEX_HTTPX_ASYNC,
                "httpx_client": _VERTEX_HTTPX_SYNC,
                "client_args": {
                    "trust_env": False,
                    **({"proxy": _VERTEX_PROXY} if _VERTEX_PROXY else {}),
                },
            },
        )


vertex_model = VertexGemini(model="gemini-2.5-pro")
