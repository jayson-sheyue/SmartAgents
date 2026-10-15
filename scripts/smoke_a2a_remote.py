# -*- coding: utf-8 -*-
"""Smoke-test remote SmartAgents A2A Engine via on_message_send."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import vertexai
from a2a.types import Message, Part, Role, SendMessageRequest
from vertexai import agent_engines

project = os.environ["GCP_PROJECT_ID"]
location = os.environ.get("GCP_LOCATION", "us-central1")
engine_id = (
    os.getenv("SMART_AGENTS_A2A_ENGINE_ID") or "1234567890123456789"
).strip()

vertexai.init(project=project, location=location)
resource = f"projects/123456789012/locations/{location}/reasoningEngines/{engine_id}"
ae = agent_engines.get(resource)

msg = Message(
    role=Role.ROLE_USER,
    message_id="console-smoke",
    parts=[Part(text="你好，用一句话介绍你自己")],
)
req = SendMessageRequest(message=msg)
import asyncio

print("calling on_message_send ...")
resp = asyncio.run(ae.on_message_send(request=req))
print("OK")
print(resp)
