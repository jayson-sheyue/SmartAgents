# -*- coding: utf-8 -*-
"""Verify A2A card enables v0.3 /v1/card route."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import vertexai
from vertexai.agent_engines.templates.a2a import _is_version_enabled

vertexai.init(
    project=os.environ["GCP_PROJECT_ID"],
    location=os.environ.get("GCP_LOCATION", "us-central1"),
)

from smart_agents.a2a_agent import get_a2a_agent
from smart_agents.a2a_card import build_agent_card

card = build_agent_card()
print("interfaces:")
for iface in card.supported_interfaces:
    print(" ", iface.protocol_version, iface.protocol_binding, iface.url)
print("v0.3 enabled?", _is_version_enabled(card, "0.3"))
print("v1.0 enabled?", _is_version_enabled(card, "1.0"))

a2a = get_a2a_agent()
a2a.set_up()


def walk(routes, prefix=""):
    out = []
    for r in routes:
        path = getattr(r, "path", None)
        methods = getattr(r, "methods", None)
        if path is not None and methods:
            out.append((sorted(methods), f"{prefix}{path}"))
        nested = getattr(r, "routes", None)
        if nested:
            out.extend(walk(nested, f"{prefix}{path or ''}"))
    return out


for methods, path in walk(a2a.rest_routes):
    if "card" in path.lower():
        print("ROUTE", methods, path)
