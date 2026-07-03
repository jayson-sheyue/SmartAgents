# -*- coding: utf-8 -*-
"""
local_node/widget_server.py — Web Widget 中转（Phase 2c）

【干什么用？】
  浏览器 index.html 不直接调 RPA，也不直接调 Gemini；
  它 POST 到本服务 :8000/chat，由本服务代叫 GCP Agent Engine（REST Agent），
  Agent 再通过 ngrok 调 local_node/server.py :8001。

【调用链】
  index.html → widget_server :8000 → Vertex streamQuery → cloud_agent
            → NGROK_URL/api/* → server.py → rpa_tools.py

【配置 .env】
  REST_AGENT_ENGINE_ID=<见 .env.example>
  GCP_PROJECT_NUMBER=<见 .env.example>
  GCP_PROJECT_ID=<见 .env.example>
  GCP_LOCATION=us-central1
  VERTEX_HTTP_PROXY=http://127.0.0.1:7890   # 国内访问 GCP 时需要（可选）
"""

from __future__ import annotations

import json
import os
import socket
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
from pydantic import BaseModel

# 加载项目根 .env
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID", "")
LOCATION = os.getenv("GCP_LOCATION", "us-central1")
GCP_PROJECT_NUMBER = os.getenv("GCP_PROJECT_NUMBER", "")
REST_AGENT_ENGINE_ID = os.getenv("REST_AGENT_ENGINE_ID", "")

if not PROJECT_ID or not GCP_PROJECT_NUMBER or not REST_AGENT_ENGINE_ID:
    raise RuntimeError(
        "请在 .env 中设置 GCP_PROJECT_ID、GCP_PROJECT_NUMBER、REST_AGENT_ENGINE_ID"
    )

AGENT_RESOURCE_NAME = os.getenv(
    "AGENT_RESOURCE_NAME",
    f"projects/{GCP_PROJECT_NUMBER}/locations/{LOCATION}/reasoningEngines/{REST_AGENT_ENGINE_ID}",
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

app = FastAPI(title="Bilibili Widget Gateway", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATIC_DIR = Path(__file__).resolve().parent


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


def _consume_stream_event(event_data: dict, state: dict) -> None:
    """从 Agent Engine 流式 JSON 里抽取文本、工具调用。"""
    if not isinstance(event_data, dict):
        return

    # 部分部署可能在事件里带 session_id（不可靠，主路径用 ensure_session）
    for key in ("session_id", "sessionId"):
        if event_data.get(key):
            state["session_id"] = event_data[key]

    # 部分事件在 output 里嵌套
    candidates = [event_data]
    if isinstance(event_data.get("output"), dict):
        candidates.append(event_data["output"])

    for obj in candidates:
        content = obj.get("content")
        if not isinstance(content, dict):
            continue
        for part in content.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if "text" in part and part["text"]:
                state["text_parts"].append(part["text"])
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

    reply = "".join(state["text_parts"]).strip()
    if not reply:
        if state["tool_events"]:
            reply = "任务已执行，模型未返回额外文字说明（请查看下方工具步骤）。"
        else:
            reply = "未收到文本回复，请确认 server.py + ngrok 已启动。"

    return {
        "reply": reply,
        "session_id": state.get("session_id") or session_id,
        "tool_events": state["tool_events"],
        "error": None,
    }


# ---------------------------------------------------------------------------
# HTTP 路由
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: str = "web_user_001"


class SessionRequest(BaseModel):
    session_id: Optional[str] = None
    user_id: str = "web_user_001"
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
        "rest_node_port": REST_NODE_PORT,
        "rest_node_reachable": rest_ok,
        "agent_engine": AGENT_RESOURCE_NAME,
        "vertex_proxy": _VERTEX_PROXY,
    }


@app.post("/session")
def get_or_create_session(req: SessionRequest):
    """
    获取或创建云端 session（刷新页面后应先调此接口续接会话）。

    force_new=true 时跳过校验，强制新建 session。
    """
    try:
        sid = None if req.force_new else req.session_id
        session_id = ensure_session(req.user_id, sid)
        return {"session_id": session_id, "user_id": req.user_id, "error": None}
    except Exception as exc:
        print(f"[Widget] /session 错误: {exc}")
        return {
            "session_id": req.session_id,
            "user_id": req.user_id,
            "error": str(exc),
        }


@app.post("/chat")
def chat_with_agent(req: ChatRequest):
    print(
        f"[Widget] user={req.user_id} session={req.session_id or '(resolve)'} "
        f"msg={req.message[:80]}"
    )
    try:
        session_id = ensure_session(req.user_id, req.session_id)
        result = stream_agent_reply(req.message, req.user_id, session_id)
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


def _preflight_checks() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    if sock.connect_ex(("127.0.0.1", REST_NODE_PORT)) != 0:
        print(
            f"⚠️  本地 :{REST_NODE_PORT} 未启动，Agent 调 RPA 会失败。\n"
            f"    请先: python local_node/server.py"
        )
    else:
        print(f"✅ 本地 REST 节点 :{REST_NODE_PORT} 已就绪")
    sock.close()

    print(f"🌐 Widget:      http://0.0.0.0:{WIDGET_PORT}/")
    print(f"☁️  Agent Engine: {AGENT_RESOURCE_NAME}")
    if _VERTEX_PROXY:
        print(f"🔐 Vertex 代理: {_VERTEX_PROXY}")
    print("💡 云端 Agent 还需 ngrok http 8001 + .env NGROK_URL（与 deploy 一致）")


if __name__ == "__main__":
    _preflight_checks()
    uvicorn.run(app, host="0.0.0.0", port=WIDGET_PORT)
