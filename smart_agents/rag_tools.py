# -*- coding: utf-8 -*-
"""Vertex RAG Engine 检索工具（挂在调度员小智）。"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_CORPUS_RE = re.compile(
    r"^projects/[^/]+/locations/([^/]+)/ragCorpora/[^/]+$"
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def rag_enabled() -> bool:
    return _env_bool("RAG_ENABLED", False) and bool(
        (os.getenv("RAG_CORPUS_NAME") or "").strip()
    )


def rag_search(query: str, top_k: int = 5) -> dict[str, Any]:
    """
    从 Vertex RAG corpus 检索相关文档片段。

    适用：知识库问答（PDF/手册/FAQ）、产品说明、内部文档问题。
    不适用：B 站/Etsy 实时 RPA、用户个人偏好（用 Memory）、时效新闻（用 google_search）。
    """
    corpus = (os.getenv("RAG_CORPUS_NAME") or "").strip()
    if not corpus:
        return {
            "ok": False,
            "tool": "rag_search",
            "data": {"snippets": [], "sources": []},
            "error": {"code": "RAG_NOT_CONFIGURED", "message": "未设置 RAG_CORPUS_NAME"},
            "meta": {},
        }

    q = (query or "").strip()
    if not q:
        return {
            "ok": False,
            "tool": "rag_search",
            "data": {"snippets": [], "sources": []},
            "error": {"code": "EMPTY_QUERY", "message": "query 不能为空"},
            "meta": {},
        }

    k = max(1, min(int(top_k or 5), 10))
    project = (
        os.getenv("RAG_PROJECT_ID")
        or os.getenv("GCP_PROJECT_ID")
        or os.getenv("PROJECT_ID")
        or ""
    ).strip()
    match = _CORPUS_RE.match(corpus)
    location = (
        (os.getenv("RAG_LOCATION") or "").strip()
        or (match.group(1) if match else "")
        or "us-central1"
    )

    try:
        import vertexai
        from vertexai import rag

        if project:
            vertexai.init(project=project, location=location)

        response = rag.retrieval_query(
            rag_resources=[rag.RagResource(rag_corpus=corpus)],
            text=q,
            rag_retrieval_config=rag.RagRetrievalConfig(top_k=k),
        )

        snippets: list[dict[str, Any]] = []
        sources: list[str] = []
        contexts = getattr(getattr(response, "contexts", None), "contexts", None) or []
        for ctx in contexts:
            text = (getattr(ctx, "text", None) or "").strip()
            source_uri = (
                getattr(ctx, "source_uri", None)
                or getattr(ctx, "source_display_name", None)
                or getattr(ctx, "uri", None)
                or ""
            )
            source = str(source_uri).strip() if source_uri else ""
            if source and source not in sources:
                sources.append(source)
            if text:
                snippets.append(
                    {
                        "text": text[:2000],
                        "source": source or None,
                        "score": getattr(ctx, "score", None),
                    }
                )

        return {
            "ok": True,
            "tool": "rag_search",
            "data": {
                "snippets": snippets,
                "sources": sources,
                "count": len(snippets),
            },
            "error": None,
            "meta": {"corpus": corpus, "location": location, "top_k": k},
        }
    except Exception as exc:
        logger.exception("rag_search failed")
        return {
            "ok": False,
            "tool": "rag_search",
            "data": {"snippets": [], "sources": []},
            "error": {"code": "RAG_QUERY_FAILED", "message": str(exc)[:500]},
            "meta": {"corpus": corpus, "location": location},
        }
