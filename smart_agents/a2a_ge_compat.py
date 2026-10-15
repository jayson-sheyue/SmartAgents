# -*- coding: utf-8 -*-
"""Normalize Gemini Enterprise A2A payloads to a2a-sdk v0.3 REST protobuf JSON.

GE/clients often send JSON-RPC envelopes, ``parts``, or ``query``/``text``.
Vertex ``REST03Handler`` expects::

    {"message": {"messageId": "...", "role": "1", "content": [{"text": "..."}]}}
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


def _extract_text_blob(data: dict[str, Any]) -> str | None:
    for key in ("query", "text", "input", "prompt", "content"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict):
            # StreamAssist-like: {"query": {"text": "..."}}
            nested = val.get("text") or val.get("query")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def normalize_ge_send_message_body(raw: bytes) -> bytes:
    """Rewrite HTTP body for ``/v1/message:send`` before protobuf Parse."""
    try:
        text = raw.decode("utf-8") if raw else "{}"
        data = json.loads(text or "{}")
    except Exception:
        logger.warning("A2A GE body not JSON, len=%s", len(raw or b""))
        return raw
    if not isinstance(data, dict):
        return raw

    preview = text[:800] if isinstance(text, str) else ""
    logger.warning("A2A GE raw body preview: %s", preview)
    print(f"SmartAgents GE raw body preview: {preview}", flush=True)

    original_keys = list(data.keys())

    # JSON-RPC → params
    params = data.get("params")
    if isinstance(params, dict) and (
        "message" in params
        or "messageId" in params
        or "parts" in params
        or "content" in params
        or "query" in params
        or "text" in params
    ):
        data = params

    # Bare Message / query fields at top level → wrap
    if "message" not in data and "request" not in data:
        if any(
            k in data
            for k in (
                "messageId",
                "message_id",
                "parts",
                "content",
                "role",
                "query",
                "text",
                "input",
                "prompt",
            )
        ):
            blob = _extract_text_blob(data)
            if blob and "parts" not in data and "content" not in data:
                data = {
                    "message": {
                        "messageId": data.get("messageId") or data.get("message_id"),
                        "role": data.get("role", "user"),
                        "parts": [{"text": blob}],
                    }
                }
            else:
                data = {"message": data}

    msg = data.get("message")
    if msg is None and "request" in data:
        msg = data.get("request")
    if not isinstance(msg, dict):
        # Last resort: whole payload is a query string wrapper
        blob = _extract_text_blob(data)
        if not blob:
            logger.warning("A2A GE body has no message/query keys=%s", original_keys)
            return raw
        msg = {"role": "user", "parts": [{"text": blob}]}

    msg = dict(msg)

    # Nested query inside message
    if not msg.get("content") and not msg.get("parts"):
        blob = _extract_text_blob(msg) or _extract_text_blob(data)
        if blob:
            msg["parts"] = [{"text": blob}]

    # parts → content (v0.3 protobuf field name)
    if not msg.get("content") and isinstance(msg.get("parts"), list):
        content: list[dict[str, Any]] = []
        for part in msg["parts"]:
            if isinstance(part, str) and part.strip():
                content.append({"text": part.strip()})
                continue
            if not isinstance(part, dict):
                continue
            if part.get("text") is not None:
                content.append({"text": str(part["text"])})
                continue
            root = part.get("root")
            if isinstance(root, dict) and root.get("text") is not None:
                content.append({"text": str(root["text"])})
        msg["content"] = content
        msg.pop("parts", None)

    mid = msg.get("messageId") or msg.get("message_id")
    if not mid:
        mid = str(uuid4())
    msg["messageId"] = str(mid)
    msg.pop("message_id", None)

    role = msg.get("role", "user")
    if role in ("user", "ROLE_USER", "USER", "role_user"):
        msg["role"] = "1"
    elif role in ("agent", "ROLE_AGENT", "AGENT", "role_agent"):
        msg["role"] = "2"
    elif role in (1, "1", 2, "2"):
        msg["role"] = str(role)
    else:
        msg["role"] = "1"

    if not msg.get("content"):
        logger.warning("A2A GE normalize produced empty content; keys=%s", original_keys)

    out: dict[str, Any] = {"message": msg}
    if isinstance(data.get("configuration"), dict):
        out["configuration"] = data["configuration"]
    if isinstance(data.get("metadata"), dict):
        out["metadata"] = data["metadata"]

    normalized = json.dumps(out, ensure_ascii=False).encode("utf-8")
    logger.warning(
        "A2A GE body normalized keys=%s → %s",
        original_keys,
        normalized.decode("utf-8")[:500],
    )
    return normalized


def _rebuild_request(request, new_body: bytes):
    from starlette.requests import Request

    async def receive():
        return {
            "type": "http.request",
            "body": new_body,
            "more_body": False,
        }

    return Request(request.scope, receive)


_TASK_STATE_TO_JSONRPC = {
    "TASK_STATE_UNSPECIFIED": "unknown",
    "TASK_STATE_SUBMITTED": "submitted",
    "TASK_STATE_WORKING": "working",
    "TASK_STATE_COMPLETED": "completed",
    "TASK_STATE_FAILED": "failed",
    "TASK_STATE_CANCELLED": "canceled",
    "TASK_STATE_CANCELED": "canceled",
    "TASK_STATE_INPUT_REQUIRED": "input-required",
    "TASK_STATE_REJECTED": "rejected",
    "TASK_STATE_AUTH_REQUIRED": "auth-required",
}


def _role_to_jsonrpc(role: Any) -> str:
    if role in ("user", "agent"):
        return str(role)
    if role in (1, "1", "ROLE_USER", "USER", "role_user"):
        return "user"
    if role in (2, "2", "ROLE_AGENT", "AGENT", "role_agent"):
        return "agent"
    return "agent"


def _extract_file_bytes_b64(file_obj: dict[str, Any], item: dict[str, Any]) -> str | None:
    """Recover image/file base64 for JSON-RPC FileWithBytes.

    REST03 ``MessageToDict`` emits ``file.fileWithBytes`` as *base64(utf8(image_b64))*,
    because ToProto stores the already-base64 string as protobuf bytes.
    """
    # Already JSON-RPC shape
    direct = file_obj.get("bytes") or item.get("bytes") or item.get("raw")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    wrapped = (
        file_obj.get("fileWithBytes")
        or file_obj.get("file_with_bytes")
        or item.get("fileWithBytes")
        or item.get("file_with_bytes")
    )
    if not isinstance(wrapped, str) or not wrapped.strip():
        return None
    wrapped = wrapped.strip()
    try:
        import base64

        decoded = base64.b64decode(wrapped)
        # ToProto path: decoded is utf-8 of the image base64 string
        try:
            as_text = decoded.decode("utf-8")
            if as_text and all(c.isalnum() or c in "+/=\n\r" for c in as_text[:80]):
                return as_text.strip()
        except UnicodeDecodeError:
            pass
        # Fallback: wrapped was raw file bytes already base64'd once
        return wrapped
    except Exception:
        return wrapped


def _normalize_parts_jsonrpc(parts: Any) -> list[dict[str, Any]]:
    """Map REST03 Part JSON → A2A 0.3 JSON-RPC parts (text / file)."""
    out: list[dict[str, Any]] = []
    if not isinstance(parts, list):
        return out
    for part in parts:
        if isinstance(part, str) and part.strip():
            out.append({"kind": "text", "text": part.strip()})
            continue
        if not isinstance(part, dict):
            continue
        item = dict(part)

        file_obj = item.get("file") if isinstance(item.get("file"), dict) else {}
        looks_like_file = (
            item.get("kind") == "file"
            or bool(file_obj)
            or item.get("raw") is not None
            or item.get("fileWithBytes") is not None
            or item.get("mediaType")
            or item.get("media_type")
        )
        if looks_like_file and (
            file_obj
            or item.get("raw") is not None
            or item.get("fileWithBytes") is not None
        ):
            b64 = _extract_file_bytes_b64(file_obj, item)
            mime = (
                file_obj.get("mimeType")
                or file_obj.get("mime_type")
                or item.get("mediaType")
                or item.get("media_type")
                or "application/octet-stream"
            )
            name = (
                file_obj.get("name")
                or item.get("filename")
                or item.get("name")
                or "file.bin"
            )
            # URI form
            uri = file_obj.get("fileWithUri") or file_obj.get("file_with_uri") or item.get("url")
            if uri and not b64:
                out.append(
                    {
                        "kind": "file",
                        "file": {
                            "uri": uri,
                            "mimeType": mime,
                            "name": name,
                        },
                    }
                )
                continue
            if b64:
                out.append(
                    {
                        "kind": "file",
                        "file": {
                            "bytes": b64,
                            "mimeType": mime,
                            "name": name,
                        },
                    }
                )
                continue

        if item.get("text") is not None:
            out.append({"kind": "text", "text": str(item["text"])})
            continue
        if item.get("kind") == "text":
            out.append({"kind": "text", "text": str(item.get("text") or "")})
            continue
        out.append(item)
    return out


def _normalize_message_jsonrpc(msg: Any) -> dict[str, Any] | None:
    if not isinstance(msg, dict):
        return None
    out = dict(msg)
    out["kind"] = "message"
    if "parts" not in out and isinstance(out.get("content"), list):
        out["parts"] = out.pop("content")
    out["parts"] = _normalize_parts_jsonrpc(out.get("parts"))
    if "role" in out:
        out["role"] = _role_to_jsonrpc(out["role"])
    return out


def rest_payload_to_jsonrpc_result(rest_resp: dict[str, Any]) -> dict[str, Any]:
    """Convert REST03 protobuf JSON ({task|message}) to A2A JSON-RPC result object."""
    if "task" in rest_resp and isinstance(rest_resp["task"], dict):
        task = dict(rest_resp["task"])
        task["kind"] = "task"
        status = task.get("status")
        if isinstance(status, dict):
            st = dict(status)
            raw_state = st.get("state")
            if isinstance(raw_state, str):
                st["state"] = _TASK_STATE_TO_JSONRPC.get(raw_state, raw_state)
            if "message" in st:
                st["message"] = _normalize_message_jsonrpc(st.get("message"))
            task["status"] = st
        artifacts = task.get("artifacts")
        if isinstance(artifacts, list):
            norm_arts = []
            for art in artifacts:
                if not isinstance(art, dict):
                    continue
                a = dict(art)
                a["parts"] = _normalize_parts_jsonrpc(a.get("parts"))
                norm_arts.append(a)
            task["artifacts"] = norm_arts
        history = task.get("history")
        if isinstance(history, list):
            task["history"] = [
                m
                for m in (_normalize_message_jsonrpc(h) for h in history)
                if m is not None
            ]
        return task

    if "message" in rest_resp and isinstance(rest_resp["message"], dict):
        msg = _normalize_message_jsonrpc(rest_resp["message"])
        return msg or rest_resp["message"]

    # Already a bare Task/Message
    if rest_resp.get("kind") in ("task", "message") or "status" in rest_resp:
        if "status" in rest_resp:
            return rest_payload_to_jsonrpc_result({"task": rest_resp})
        return _normalize_message_jsonrpc(rest_resp) or rest_resp
    return rest_resp


def wrap_jsonrpc_send_response(
    original_body: bytes, rest_resp: Any
) -> Any:
    """If GE sent JSON-RPC, wrap REST dict as JSON-RPC success response."""
    try:
        data = json.loads(original_body.decode("utf-8") if original_body else "{}")
    except Exception:
        return rest_resp
    if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
        return rest_resp
    if not isinstance(rest_resp, dict):
        return rest_resp

    req_id = data.get("id")
    result = rest_payload_to_jsonrpc_result(rest_resp)
    wrapped = {"jsonrpc": "2.0", "id": req_id, "result": result}
    preview = json.dumps(wrapped, ensure_ascii=False)[:500]
    logger.warning("A2A GE JSON-RPC response wrap: %s", preview)
    print(f"SmartAgents GE JSON-RPC response wrap: {preview}", flush=True)
    return wrapped


def install_rest03_body_patch() -> None:
    """Patch REST03Handler so GE payload rewrite runs even if routes are recreated."""
    from a2a.compat.v0_3.rest_handler import REST03Handler

    if getattr(REST03Handler, "_smartagents_ge_patched", False):
        print("SmartAgents GE REST03 patch already installed", flush=True)
        return

    _orig_send = REST03Handler.on_message_send
    _orig_stream = REST03Handler.on_message_send_stream

    async def on_message_send(self, request, context):
        body = await request.body()
        print(f"SmartAgents GE /message:send raw={body[:800]!r}", flush=True)
        new_body = normalize_ge_send_message_body(body)
        print(f"SmartAgents GE /message:send normalized={new_body[:800]!r}", flush=True)
        rest_resp = await _orig_send(
            self, _rebuild_request(request, new_body), context
        )
        return wrap_jsonrpc_send_response(body, rest_resp)

    async def on_message_send_stream(self, request, context):
        body = await request.body()
        print(f"SmartAgents GE /message:stream raw={body[:800]!r}", flush=True)
        new_body = normalize_ge_send_message_body(body)
        async for item in _orig_stream(self, _rebuild_request(request, new_body), context):
            yield item

    REST03Handler.on_message_send = on_message_send  # type: ignore[method-assign]
    REST03Handler.on_message_send_stream = on_message_send_stream  # type: ignore[method-assign]
    REST03Handler._smartagents_ge_patched = True
    print("Installed SmartAgents GE REST03Handler body patch", flush=True)


def wrap_starlette_endpoint(endpoint: Callable) -> Callable:
    async def _wrapped(request):
        body = await request.body()
        print(f"SmartAgents GE route-wrap raw={body[:800]!r}", flush=True)
        new_body = normalize_ge_send_message_body(body)
        return await endpoint(_rebuild_request(request, new_body))

    return _wrapped


def patch_rest_routes_for_ge(routes: list) -> list:
    from starlette.routing import Mount, Route

    patched: list = []
    for route in routes:
        path = getattr(route, "path", "") or ""
        nested = getattr(route, "routes", None)
        if nested is not None:
            patched.append(
                Mount(path=path, routes=patch_rest_routes_for_ge(list(nested)))
            )
            continue
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if endpoint is not None and (
            "message:send" in path or "message:stream" in path
        ):
            patched.append(
                Route(
                    path=path,
                    endpoint=wrap_starlette_endpoint(endpoint),
                    methods=list(methods) if methods else ["POST"],
                )
            )
        else:
            patched.append(route)
    return patched


# Import-time install: Agent Engine may bind REST03Handler methods BEFORE set_up().
try:
    install_rest03_body_patch()
except Exception as exc:  # pragma: no cover
    print(f"SmartAgents GE REST03 patch deferred: {exc!r}", flush=True)
