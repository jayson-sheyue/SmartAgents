# -*- coding: utf-8 -*-
"""SmartAgents A2A local smoke tests."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_vertex() -> None:
    import vertexai

    project = (os.getenv("GCP_PROJECT_ID") or "").strip()
    location = (os.getenv("GCP_LOCATION") or "us-central1").strip() or "us-central1"
    if not project:
        raise SystemExit("GCP_PROJECT_ID required for A2A smoke (vertexai.init)")
    vertexai.init(project=project, location=location)


def _card_to_dict(card) -> dict:
    try:
        from google.protobuf.json_format import MessageToDict

        pb = getattr(card, "_pb", card)
        return MessageToDict(pb, preserving_proto_field_name=False)
    except Exception:
        return {"repr": repr(card)}


async def smoke_card() -> None:
    from smart_agents.a2a_agent import get_a2a_agent
    from smart_agents.a2a_card import build_agent_card

    card = build_agent_card()
    data = _card_to_dict(card)
    print("✅ Agent Card OK")
    print(json.dumps(data, ensure_ascii=False, indent=2))

    a2a = get_a2a_agent()
    a2a.set_up()
    print("✅ set_up OK")
    print("agent_card.url =", a2a.agent_card.supported_interfaces[0].url)

    from a2a.server.context import ServerCallContext

    resp = await a2a.on_get_extended_agent_card(
        request=None, context=ServerCallContext()
    )
    print("✅ on_get_extended_agent_card OK")
    print(json.dumps(_card_to_dict(resp), ensure_ascii=False, indent=2))


async def smoke_live() -> None:
    from a2a.server.context import ServerCallContext
    from a2a.types import Message, Part, Role, SendMessageRequest

    from smart_agents.a2a_agent import get_a2a_agent_with_root

    a2a = get_a2a_agent_with_root()
    a2a.set_up()

    message = Message(
        role=Role.ROLE_USER,
        message_id="local-smoke-message",
        parts=[Part(text="你好，用一句话介绍你自己，不要 transfer。")],
    )
    request = SendMessageRequest(message=message)
    context = ServerCallContext()
    print("⏳ on_message_send ...")
    send_resp = await a2a.on_message_send(request=request, context=context)
    print("✅ on_message_send OK")
    print(send_resp)

    task_id = getattr(send_resp, "id", None) or ""
    if not task_id and hasattr(send_resp, "task") and send_resp.task:
        task_id = send_resp.task.id
    if task_id:
        from a2a.types import GetTaskRequest

        get_req = GetTaskRequest(id=task_id)
        task_resp = await a2a.on_get_task(request=get_req, context=context)
        print("✅ on_get_task OK")
        print(task_resp)


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartAgents A2A smoke")
    parser.add_argument(
        "--mode",
        choices=("card", "live"),
        default="card",
        help="card=名片+set_up；live=导入 root_agent 并发一轮消息（需 MCP）",
    )
    args = parser.parse_args()
    _ensure_vertex()
    if args.mode == "card":
        asyncio.run(smoke_card())
    else:
        asyncio.run(smoke_live())


if __name__ == "__main__":
    main()
