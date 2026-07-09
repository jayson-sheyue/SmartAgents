# -*- coding: utf-8 -*-
"""
local_node/widget_server.py — Web Widget 中转（SmartAgents）

【干什么用？】
  浏览器 index.html 不直接调 RPA，也不直接调 Gemini；
  它 POST 到本服务 :8000/chat，由本服务代叫 GCP Agent Engine（默认 smart_agents），
  调度树再通过 MCP 调本机 B 站/Etsy 节点。

【调用链】
  index.html → widget_server :8000 → Vertex streamQuery → smart_agents
            → BILIBILI_MCP_SERVER_URL / ETSY_MCP_SERVER_URL → MCP Servers

【配置 .env】
  SMART_AGENTS_ENGINE_ID=<cloud 模式必填；local 模式可留空>
  # 或显式 AGENT_RESOURCE_NAME=projects/.../reasoningEngines/...
  GCP_PROJECT_NUMBER=<见 .env.example>
  GCP_PROJECT_ID=<见 .env.example>
  GCP_LOCATION=us-central1
  VERTEX_HTTP_PROXY=http://127.0.0.1:7890   # 国内访问 GCP 时需要（可选）
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

import google.auth
import google.auth.transport.requests
import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from google.adk.auth.credential_service.in_memory_credential_service import (
    InMemoryCredentialService,
)
from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.database_session_service import DatabaseSessionService
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.utils.context_utils import Aclosing
from google.genai import types
from pydantic import BaseModel

# 确保以 `python local_node/widget_server.py` 启动时也能导入项目包（integrations/smart_agents）
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 加载项目根 .env
load_dotenv(_ROOT / ".env")

PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
GCP_PROJECT_NUMBER = os.getenv("GCP_PROJECT_NUMBER", "")
SMART_AGENTS_ENGINE_ID = os.getenv("SMART_AGENTS_ENGINE_ID", "").strip()
WIDGET_RUN_MODE = os.getenv("WIDGET_RUN_MODE", "local").strip().lower()

if WIDGET_RUN_MODE not in {"local", "cloud"}:
    raise RuntimeError("WIDGET_RUN_MODE 仅支持 local / cloud")

if not PROJECT_ID:
    raise RuntimeError("请在 .env 中设置 GCP_PROJECT_ID")

AGENT_RESOURCE_NAME = ""
if WIDGET_RUN_MODE == "cloud":
    if not GCP_PROJECT_NUMBER:
        raise RuntimeError("cloud 模式请在 .env 中设置 GCP_PROJECT_NUMBER")
    _default_engine_id = SMART_AGENTS_ENGINE_ID
    if not _default_engine_id and not os.getenv("AGENT_RESOURCE_NAME"):
        raise RuntimeError(
            "cloud 模式请设置 AGENT_RESOURCE_NAME，或在 .env 中配置 SMART_AGENTS_ENGINE_ID"
        )
    AGENT_RESOURCE_NAME = os.getenv(
        "AGENT_RESOURCE_NAME",
        f"projects/{GCP_PROJECT_NUMBER}/locations/{LOCATION}/reasoningEngines/{_default_engine_id}",
    )

WIDGET_PORT = int(os.getenv("WIDGET_PORT", "8000"))
REST_NODE_PORT = int(os.getenv("REST_NODE_PORT", "8001"))


def _pick_vertex_proxy() -> Optional[str]:
    for key in ("VERTEX_HTTP_PROXY", "HTTPS_PROXY", "https_proxy"):
        val = (os.getenv(key) or "").strip()
        if val:
            return val
    return None


_VERTEX_PROXY = _pick_vertex_proxy()
_gcp_session = requests.Session()
_gcp_session.trust_env = False
if _VERTEX_PROXY:
    _gcp_session.proxies = {"http": _VERTEX_PROXY, "https": _VERTEX_PROXY}

app = FastAPI(title="SmartAgents Widget Gateway", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).resolve().parent

# local 模式下复用同一个 runner，避免每次请求重建
_LOCAL_RUNNER: Optional[Runner] = None
_LOCAL_SESSION_SERVICE: Optional[BaseSessionService] = None
_LOCAL_RUNNER_LOCK = asyncio.Lock()
_STREAM_LOCKS: dict[str, asyncio.Lock] = {}

_AGENT_LABELS: dict[str, str] = {
    "SmartAgents_Dispatcher": "小智",
    "Bilibili_Cloud_MCP_Agent": "阿B",
    "Etsy_Cloud_MCP_Agent": "E姐",
}


# ---------------------------------------------------------------------------
# GCP 认证（清全局代理，避免 ADC refresh 走坏掉的系统代理）
# ---------------------------------------------------------------------------

def get_gcp_token() -> str:
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
        "ALL_PROXY", "all_proxy",
    ):
        os.environ.pop(key, None)
    credentials, _ = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials.token


def _agent_engine_api_base() -> str:
    return (
        f"https://{LOCATION}-aiplatform.googleapis.com/v1beta1/"
        f"{AGENT_RESOURCE_NAME}"
    )


def _build_local_runner() -> tuple[Runner, BaseSessionService]:
    from integrations.feishu.config import apply_agent_env  # 延迟导入，避免循环依赖
    from smart_agents.agent import root_agent
    from smart_agents.app_factory import build_smart_agents_app

    # 与 smart_agents 脚本行为一致：本地默认双 MCP
    os.environ.setdefault("BILIBILI_MCP_SERVER_URL", "http://127.0.0.1:8002/mcp")
    os.environ.setdefault("ETSY_MCP_SERVER_URL", "http://127.0.0.1:8003/mcp")
    apply_agent_env(
        type(
            "_Cfg",
            (),
            {
                "mcp_server_url": os.environ["BILIBILI_MCP_SERVER_URL"],
                "etsy_mcp_server_url": os.environ["ETSY_MCP_SERVER_URL"],
            },
        )()
    )

    app_obj = build_smart_agents_app(
        name="smart_agents_widget_local",
        root_agent=root_agent,
        enable_memory=False,
    )

    try:
        db_dir = _ROOT / "local_node" / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        session_service: BaseSessionService = DatabaseSessionService(
            db_url=f"sqlite:///{db_dir / 'widget_sessions.db'}"
        )
    except Exception:
        session_service = InMemorySessionService()

    runner = Runner(
        app=app_obj,
        session_service=session_service,
        artifact_service=InMemoryArtifactService(),
        memory_service=None,
        credential_service=InMemoryCredentialService(),
    )
    return runner, session_service


async def _get_or_create_local_runner() -> tuple[Runner, BaseSessionService]:
    global _LOCAL_RUNNER, _LOCAL_SESSION_SERVICE
    async with _LOCAL_RUNNER_LOCK:
        if _LOCAL_RUNNER is None or _LOCAL_SESSION_SERVICE is None:
            _LOCAL_RUNNER, _LOCAL_SESSION_SERVICE = _build_local_runner()
    return _LOCAL_RUNNER, _LOCAL_SESSION_SERVICE


async def _ensure_local_session(
    session_service: BaseSessionService, *, user_id: str, session_id: Optional[str]
) -> str:
    sid = session_id or f"web_{uuid.uuid4().hex[:12]}"
    session = await session_service.get_session(
        app_name="smart_agents_widget_local", user_id=user_id, session_id=sid
    )
    if session is None:
        await session_service.create_session(
            app_name="smart_agents_widget_local", user_id=user_id, session_id=sid
        )
    return sid


async def _run_local_query(message: str, *, user_id: str, session_id: str) -> dict:
    runner, session_service = await _get_or_create_local_runner()
    text_parts: list[str] = []
    last_author: Optional[str] = None
    by_author: dict[str, list[str]] = {}

    await _ensure_local_session(session_service, user_id=user_id, session_id=session_id)
    content = types.Content(role="user", parts=[types.Part(text=message)])
    async with Aclosing(
        runner.run_async(user_id=user_id, session_id=session_id, new_message=content)
    ) as agen:
        async for event in agen:
            if not event.content or not event.content.parts:
                continue
            texts = [p.text for p in event.content.parts if getattr(p, "text", None)]
            if not texts:
                continue
            author = event.author or "agent"
            last_author = author
            by_author.setdefault(author, []).extend(texts)
            text_parts.extend(texts)

    reply = ""
    if last_author and last_author in by_author:
        reply = "".join(by_author[last_author]).strip()
    if not reply:
        reply = "".join(text_parts).strip() or "（任务已执行，暂无文字说明。）"
    return {"reply": reply, "session_id": session_id, "tool_events": [], "error": None}


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {get_gcp_token()}",
        "Content-Type": "application/json",
    }


def _agent_engine_query(class_method: str, input_payload: dict[str, Any]) -> Any:
    """调用 Agent Engine :query（非流式 class_method，如 create_session）。"""
    url = f"{_agent_engine_api_base()}:query"
    response = _gcp_session.post(
        url,
        headers=_auth_headers(),
        json={"class_method": class_method, "input": input_payload},
        timeout=60,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"{class_method} HTTP {response.status_code}: {response.text[:400]}"
        )
    return response.json()


def _extract_session_id(payload: Any) -> Optional[str]:
    """从 async_create_session / async_get_session 响应中取出 session id。"""
    if not isinstance(payload, dict):
        return None
    if payload.get("id"):
        return str(payload["id"])
    output = payload.get("output")
    if isinstance(output, dict) and output.get("id"):
        return str(output["id"])
    # 部分 API 再包一层
    if isinstance(output, dict) and isinstance(output.get("session"), dict):
        sid = output["session"].get("id")
        if sid:
            return str(sid)
    return None


def ensure_session(user_id: str, session_id: Optional[str]) -> str:
    """
    保证返回可用的 session_id：
      - 有 id 且云端仍存在 → 复用
      - 否则 → async_create_session 新建
    """
    if session_id:
        try:
            body = _agent_engine_query(
                "async_get_session",
                {"user_id": user_id, "session_id": session_id},
            )
            existing = _extract_session_id(body)
            if existing:
                print(f"[Widget] 复用 session {existing}")
                return existing
        except Exception as exc:
            print(f"[Widget] session 无效，将新建: {exc}")

    body = _agent_engine_query("async_create_session", {"user_id": user_id})
    new_id = _extract_session_id(body)
    if not new_id:
        raise RuntimeError(f"create_session 未返回 id: {body!r}")
    print(f"[Widget] 新建 session {new_id}")
    return new_id


# ---------------------------------------------------------------------------
# streamQuery 事件解析
# ---------------------------------------------------------------------------

def _summarize_tool_response(response: Any) -> str:
    """把 P0 envelope 或裸 dict 压成一行给前端展示。"""
    if not isinstance(response, dict):
        return str(response)[:200]
    if "ok" in response:
        if response.get("ok"):
            data = response.get("data") or {}
            if "fans_count_display" in data:
                return f"ok → fans_count_display={data['fans_count_display']}"
            if "up_names" in data:
                return f"ok → {len(data['up_names'])} 个 UP 主"
            if "rows_updated" in data:
                return f"ok → 更新 {data['rows_updated']} 行"
            return "ok"
        err = response.get("error") or {}
        return f"{err.get('code', 'ERROR')}: {err.get('message', '')[:120]}"
    return json.dumps(response, ensure_ascii=False)[:200]


def _stream_lock_key(user_id: str, session_id: str) -> str:
    return f"{user_id}:{session_id}"


def _get_stream_lock(key: str) -> asyncio.Lock:
    if key not in _STREAM_LOCKS:
        _STREAM_LOCKS[key] = asyncio.Lock()
    return _STREAM_LOCKS[key]


def _reply_from_stream_state(state: dict[str, Any]) -> str:
    """与飞书 cloud 一致：取本轮最后发言 Agent 的文本。"""
    by_author: dict[str, list[str]] = state.get("by_author") or {}
    last_author = state.get("last_author")
    if last_author and last_author in by_author:
        return "".join(by_author[last_author]).strip()
    if by_author:
        return "".join(list(by_author.values())[-1]).strip()
    return "".join(state.get("text_parts") or []).strip()


def _consume_stream_event(event_data: dict, state: dict) -> None:
    """从 Agent Engine 流式 JSON 里抽取文本、工具调用。"""
    if not isinstance(event_data, dict):
        return

    for key in ("session_id", "sessionId"):
        if event_data.get(key):
            state["session_id"] = event_data[key]

    candidates = [event_data]
    if isinstance(event_data.get("output"), dict):
        candidates.append(event_data["output"])

    for obj in candidates:
        if obj.get("partial") is True:
            continue
        content = obj.get("content")
        if not isinstance(content, dict):
            continue
        author = obj.get("author") or "agent"
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if "text" in part and part["text"]:
                text = part["text"]
                state.setdefault("by_author", {}).setdefault(author, []).append(text)
                state["last_author"] = author
                state.setdefault("text_parts", []).append(text)
            if "function_call" in part:
                fc = part["function_call"] or {}
                state["tool_events"].append({
                    "type": "tool_call",
                    "name": fc.get("name", "?"),
                    "args": fc.get("args") or {},
                })
            if "function_response" in part:
                fr = part["function_response"] or {}
                resp = fr.get("response")
                state["tool_events"].append({
                    "type": "tool_result",
                    "name": fr.get("name", "?"),
                    "ok": resp.get("ok") if isinstance(resp, dict) else None,
                    "summary": _summarize_tool_response(resp),
                })


def _jsonl(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False) + "\n"


def stream_agent_reply(
    message: str,
    user_id: str,
    session_id: str,
) -> dict:
    """调用 Agent Engine streamQuery（要求已存在的 session_id）。"""
    url = f"{_agent_engine_api_base()}:streamQuery"
    payload_input: dict[str, Any] = {
        "message": message,
        "user_id": user_id,
        "session_id": session_id,
    }

    data = {
        "class_method": "async_stream_query",
        "input": payload_input,
    }

    state: dict[str, Any] = {
        "text_parts": [],
        "by_author": {},
        "last_author": None,
        "tool_events": [],
        "session_id": session_id,
    }

    response = _gcp_session.post(
        url, headers=_auth_headers(), json=data, stream=True, timeout=300
    )
    if response.status_code != 200:
        return {
            "reply": f"云端 Agent 调用失败 (HTTP {response.status_code})",
            "session_id": session_id,
            "tool_events": [],
            "error": response.text[:500],
        }

    for line in response.iter_lines():
        if not line:
            continue
        line_str = line.decode("utf-8")
        if line_str.startswith("data: "):
            line_str = line_str[6:]
        try:
            event_data = json.loads(line_str)
            _consume_stream_event(event_data, state)
        except json.JSONDecodeError:
            continue

    reply = _reply_from_stream_state(state)
    if not reply:
        if state["tool_events"]:
            reply = "任务已执行，模型未返回额外文字说明（请查看下方工具步骤）。"
        else:
            reply = "未收到文本回复，请确认 server.py 与 Cloudflare Tunnel 已启动。"

    return {
        "reply": reply,
        "session_id": state.get("session_id") or session_id,
        "tool_events": state["tool_events"],
        "error": None,
    }


# ---------------------------------------------------------------------------
# HTTP 路由
# ---------------------------------------------------------------------------

def _resolve_widget_user_id(user_id: Optional[str]) -> str:
    """Widget 匿名访客：每个浏览器 tab 使用独立随机 user_id（无 Memory Bank）。"""
    raw = (user_id or "").strip()
    if raw and raw != "web_user_001":
        return raw
    return f"web_{uuid.uuid4().hex[:16]}"


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: str = ""


class SessionRequest(BaseModel):
    session_id: Optional[str] = None
    user_id: str = ""
    force_new: bool = False


@app.get("/")
def serve_index():
    """浏览器打开 http://localhost:8000/ 即可使用 Widget。"""
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/health")
def health():
    """启动自检：Widget 自身 + 本地 REST 节点是否在线。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    rest_ok = sock.connect_ex(("127.0.0.1", REST_NODE_PORT)) == 0
    sock.close()
    return {
        "widget": "ok",
        "mode": WIDGET_RUN_MODE,
        "rest_node_port": REST_NODE_PORT,
        "rest_node_reachable": rest_ok,
        "agent_engine": AGENT_RESOURCE_NAME if WIDGET_RUN_MODE == "cloud" else "local_runner",
        "vertex_proxy": _VERTEX_PROXY,
    }


@app.on_event("shutdown")
async def _shutdown_local_runner() -> None:
    global _LOCAL_RUNNER
    if _LOCAL_RUNNER is not None:
        await _LOCAL_RUNNER.close()
        _LOCAL_RUNNER = None


@app.post("/session")
def get_or_create_session(req: SessionRequest):
    """
    获取或创建云端 session（刷新页面后应先调此接口续接会话）。

    force_new=true 时跳过校验，强制新建 session。
    """
    try:
        uid = _resolve_widget_user_id(req.user_id)
        sid = None if req.force_new else req.session_id
        if WIDGET_RUN_MODE == "cloud":
            session_id = ensure_session(uid, sid)
        else:
            # local 模式下，session 在本地 runner 的 sqlite/in-memory 中维护
            session_id = sid or f"web_{uuid.uuid4().hex[:12]}"
        return {"session_id": session_id, "user_id": uid, "error": None}
    except Exception as exc:
        print(f"[Widget] /session 错误: {exc}")
        return {
            "session_id": req.session_id,
            "user_id": req.user_id,
            "error": str(exc),
        }


@app.post("/chat")
async def chat_with_agent(req: ChatRequest):
    print(
        f"[Widget] user={req.user_id} session={req.session_id or '(resolve)'} "
        f"msg={req.message[:80]}"
    )
    try:
        uid = _resolve_widget_user_id(req.user_id)
        if WIDGET_RUN_MODE == "cloud":
            session_id = ensure_session(uid, req.session_id)
            result = stream_agent_reply(req.message, uid, session_id)
        else:
            session_id = req.session_id or f"web_{uuid.uuid4().hex[:12]}"
            result = await _run_local_query(
                req.message, user_id=uid, session_id=session_id
            )
        result["session_id"] = session_id
        if result.get("tool_events"):
            for ev in result["tool_events"]:
                print(f"  → {ev['type']}: {ev.get('name')} {ev.get('summary', '')}")
        return result
    except Exception as exc:
        print(f"[Widget] 错误: {exc}")
        return {
            "reply": f"系统错误: {exc}",
            "session_id": req.session_id,
            "tool_events": [],
            "error": str(exc),
        }


@app.post("/chat/stream")
async def chat_with_agent_stream(req: ChatRequest):
    async def event_stream():
        uid = _resolve_widget_user_id(req.user_id)
        if WIDGET_RUN_MODE == "cloud":
            session_id = ensure_session(uid, req.session_id)
        else:
            session_id = req.session_id or f"web_{uuid.uuid4().hex[:12]}"
        lock = _get_stream_lock(_stream_lock_key(uid, session_id))
        if lock.locked():
            yield _jsonl(
                {
                    "type": "error",
                    "error": "上一条消息仍在处理中，请稍候再发。",
                }
            )
            return
        async with lock:
            try:
                yield _jsonl({"type": "session", "session_id": session_id, "user_id": uid})

                if WIDGET_RUN_MODE == "cloud":
                    url = f"{_agent_engine_api_base()}:streamQuery"
                    payload_input: dict[str, Any] = {
                        "message": req.message,
                        "user_id": uid,
                        "session_id": session_id,
                    }
                    data = {"class_method": "async_stream_query", "input": payload_input}
                    state: dict[str, Any] = {
                        "text_parts": [],
                        "by_author": {},
                        "last_author": None,
                        "tool_events": [],
                        "session_id": session_id,
                    }
                    response = _gcp_session.post(
                        url, headers=_auth_headers(), json=data, stream=True, timeout=300
                    )
                    if response.status_code != 200:
                        yield _jsonl(
                            {
                                "type": "error",
                                "error": f"云端 Agent 调用失败 (HTTP {response.status_code})",
                                "detail": response.text[:500],
                            }
                        )
                        return
                    last_stream_author: Optional[str] = None
                    for line in response.iter_lines():
                        if not line:
                            continue
                        line_str = line.decode("utf-8")
                        if line_str.startswith("data: "):
                            line_str = line_str[6:]
                        try:
                            event_data = json.loads(line_str)
                        except json.JSONDecodeError:
                            continue
                        before_counts = {
                            a: len(chunks)
                            for a, chunks in (state.get("by_author") or {}).items()
                        }
                        before_tool_len = len(state["tool_events"])
                        _consume_stream_event(event_data, state)
                        for author, chunks in (state.get("by_author") or {}).items():
                            start = before_counts.get(author, 0)
                            for chunk in chunks[start:]:
                                label = _AGENT_LABELS.get(author, author)
                                prefix = ""
                                if author != last_stream_author:
                                    prefix = f"【{label}】"
                                    last_stream_author = author
                                yield _jsonl(
                                    {
                                        "type": "text",
                                        "text": prefix + chunk,
                                        "author": author,
                                        "author_label": label,
                                    }
                                )
                        for ev in state["tool_events"][before_tool_len:]:
                            yield _jsonl({"type": "tool_event", "event": ev})

                    yield _jsonl(
                        {
                            "type": "done",
                            "session_id": state.get("session_id") or session_id,
                            "author": state.get("last_author"),
                        }
                    )
                    return

                runner, session_service = await _get_or_create_local_runner()
                await _ensure_local_session(
                    session_service, user_id=uid, session_id=session_id
                )
                content = types.Content(role="user", parts=[types.Part(text=req.message)])
                async with Aclosing(
                    runner.run_async(
                        user_id=uid, session_id=session_id, new_message=content
                    )
                ) as agen:
                    async for event in agen:
                        if not event.content or not event.content.parts:
                            continue
                        author = event.author or "agent"
                        for part in event.content.parts:
                            txt = getattr(part, "text", None)
                            if txt:
                                yield _jsonl(
                                    {
                                        "type": "text",
                                        "text": txt,
                                        "author": author,
                                        "author_label": _AGENT_LABELS.get(author, author),
                                    }
                                )
                yield _jsonl({"type": "done", "session_id": session_id})
            except Exception as exc:
                yield _jsonl({"type": "error", "error": str(exc)})

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def _preflight_checks() -> None:
    def _port_open(port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        ok = sock.connect_ex(("127.0.0.1", port)) == 0
        sock.close()
        return ok

    if WIDGET_RUN_MODE == "cloud":
        b_ok = _port_open(8002)
        e_ok = _port_open(8003)
        print(f"{'✅' if b_ok else '⚠️'} Bilibili MCP :8002 {'就绪' if b_ok else '未启动'}")
        print(f"{'✅' if e_ok else '⚠️'} Etsy MCP :8003 {'就绪' if e_ok else '未启动'}")
        if not (b_ok and e_ok):
            print(
                "💡 闲聊/调度对话不依赖本地端口；仅当触发 B 站/Etsy RPA 时才需要双 MCP + 隧道。\n"
                "   调度树走 MCP（:8002/:8003），**不需要** local_node/server.py :8001。"
            )
    else:
        b_ok = _port_open(8002)
        e_ok = _port_open(8003)
        print(f"{'✅' if b_ok else '⚠️'} Bilibili MCP :8002 {'就绪' if b_ok else '未启动'}")
        print(f"{'✅' if e_ok else '⚠️'} Etsy MCP :8003 {'就绪' if e_ok else '未启动'}")

    print(f"🌐 Widget:      http://0.0.0.0:{WIDGET_PORT}/")
    if WIDGET_RUN_MODE == "cloud":
        print(f"☁️  Mode: cloud | Agent Engine: {AGENT_RESOURCE_NAME}")
    else:
        print("🏠 Mode: local | in-process smart_agents runner")
    if _VERTEX_PROXY:
        print(f"🔐 Vertex 代理: {_VERTEX_PROXY}")
    if WIDGET_RUN_MODE == "cloud":
        print("💡 cloud 模式还需 Cloudflare Tunnel + .env 中 smart_agents 的公网 MCP URL")
    else:
        print("💡 local 模式无需部署 Agent Engine；确保本地双 MCP 已启动")


if __name__ == "__main__":
    _preflight_checks()
    uvicorn.run(app, host="0.0.0.0", port=WIDGET_PORT)
