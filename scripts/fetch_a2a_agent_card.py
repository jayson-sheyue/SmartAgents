# -*- coding: utf-8 -*-
"""Fetch / print Agent Card for GE A2A registration."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from google.auth import default
from google.auth.transport.requests import Request

ROOT = Path(__file__).resolve().parents[1]
env_path = ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

PROJECT = os.environ["GCP_PROJECT_ID"]
PROJECT_NUMBER = os.getenv("GCP_PROJECT_NUMBER", "123456789012").strip()
LOCATION = os.environ.get("GCP_LOCATION", "us-central1").strip()
ENGINE_ID = (
    os.getenv("SMART_AGENTS_A2A_ENGINE_ID") or "1234567890123456789"
).strip()

creds, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
creds.refresh(Request())
token = creds.token
headers = {"Authorization": f"Bearer {token}"}

resource = (
    f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/reasoningEngines/{ENGINE_ID}"
)
a2a_url = (
    f"https://{LOCATION}-aiplatform.googleapis.com/v1beta1/{resource}/a2a"
)

print("=== A2A base URL (put this in Agent Card `url` / `supportedInterfaces`) ===")
print(a2a_url)
print()

candidates = [
    f"{a2a_url}/v1/card",
    f"{a2a_url}/.well-known/agent-card.json",
    f"{a2a_url}/.well-known/agent.json",
    f"https://{LOCATION}-aiplatform.googleapis.com/v1beta1/"
    f"projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{ENGINE_ID}/a2a/v1/card",
]

print("=== HTTP probe (needs IAM) ===")
for url in candidates:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(f"{resp.status}  {url}")
            try:
                print(json.dumps(json.loads(body), ensure_ascii=False, indent=2)[:2000])
            except Exception:
                print(body[:500])
            print("---")
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:300]
        print(f"{e.code}  {url}")
        print(err)
        print("---")
    except Exception as e:
        print(f"ERR {url}: {e}")
        print("---")

print("\n=== Fallback: card embedded in Engine operation_schemas ===")
import vertexai
from vertexai import agent_engines

vertexai.init(project=PROJECT, location=LOCATION)
ae = agent_engines.get(resource)
schemas = ae.operation_schemas() or []
raw = None
for s in schemas:
    if s.get("name") == "on_get_extended_agent_card" and s.get("a2a_agent_card"):
        raw = s["a2a_agent_card"]
        break
if not raw and schemas:
    raw = schemas[0].get("a2a_agent_card")

if not raw:
    raise SystemExit("No a2a_agent_card on operation_schemas")

card = json.loads(raw)
# Fix deploy-time placeholder URL for GE registration
# Prefer supportedInterfaces[0].url if present; rewrite localhost.
interfaces = card.get("supportedInterfaces") or []
if interfaces:
    interfaces[0]["url"] = a2a_url
    card["supportedInterfaces"] = interfaces
# Some GE samples also expect top-level "url" (older card shape)
card["url"] = a2a_url

out = ROOT / "smart_agents" / "a2a_agent_card.ge.json"
out.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(card, ensure_ascii=False, indent=2))
print(f"\nWrote {out}")
