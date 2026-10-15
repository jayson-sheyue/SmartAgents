# -*- coding: utf-8 -*-
"""Deploy SmartAgents A2A wrapper as a **parallel second** Reasoning Engine."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _require_env(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        raise SystemExit(f"Missing required env: {name}")
    return val


def _filter_env(env_vars: dict[str, str]) -> dict[str, str]:
    """Drop empty values so Vertex does not persist blank env overrides."""
    return {k: v for k, v in env_vars.items() if (v or "").strip()}


def main() -> None:
    project = _require_env("GCP_PROJECT_ID")
    location = os.getenv("GCP_LOCATION", "us-central1").strip() or "us-central1"
    staging = (os.getenv("SMART_AGENTS_A2A_STAGING_BUCKET") or "").strip()
    if not staging:
        staging = f"gs://{project}-adk-staging"
        print(f"ℹ️  SMART_AGENTS_A2A_STAGING_BUCKET unset; using {staging}")

    existing_id = (os.getenv("SMART_AGENTS_A2A_ENGINE_ID") or "").strip()

    import vertexai
    from vertexai import agent_engines

    vertexai.init(project=project, location=location, staging_bucket=staging)

    from smart_agents.a2a_agent import get_a2a_agent
    from smart_agents.a2a_card import A2A_DISPLAY_NAME

    # Do NOT bind root_agent here — MCP sessions hold locks and break cloudpickle.
    # Cloud Runtime will lazy-import root_agent via default_executor_builder.
    print("🧩 Building picklable A2aAgent (lazy root_agent on Runtime)...")
    local_a2a = get_a2a_agent()

    requirements = [
        "google-cloud-aiplatform[agent_engines]>=1.154.0",
        # Do NOT use google-adk[a2a]: that extra still pins a2a-sdk<0.4,
        # but Vertex A2aAgent templates need a2a-sdk>=1.0 (same as local .venvAgents).
        "google-adk>=2.3.0",
        "a2a-sdk[http-server]>=1.0.0",
        "google-genai",
        "python-dotenv",
        "httpx",
        "requests",
        "PyYAML",
        "mcp>=1.28.0",
        "pypinyin>=0.53.0",
    ]

    # Must be relative paths so tar members are `smart_agents/...` (importable).
    packages_root = Path(
        (os.getenv("SMART_AGENTS_A2A_EXTRA_PACKAGES_ROOT") or "").strip()
        or (ROOT / ".a2a_deploy_staging")
    ).resolve()
    for name in ("smart_agents", "domains", "skills"):
        if not (packages_root / name).is_dir():
            raise SystemExit(
                f"Missing package dir {packages_root / name}. "
                "Run via ./scripts/deploy_smart_agents_a2a.sh (builds staging)."
            )
    # tar.add(relative) archives under the given name; cwd must be packages_root.
    os.chdir(packages_root)
    extra_packages = ["smart_agents", "domains", "skills"]
    print(f"📦 extra_packages (cwd={packages_root}): {extra_packages}")

    env_vars = _filter_env(
        {
            "GCP_PROJECT_ID": project,
            "GCP_LOCATION": location,
            "BILIBILI_MCP_SERVER_URL": os.getenv(
                "BILIBILI_MCP_SERVER_URL", "http://127.0.0.1:8002/mcp"
            ),
            "ETSY_MCP_SERVER_URL": os.getenv(
                "ETSY_MCP_SERVER_URL", "http://127.0.0.1:8003/mcp"
            ),
            "BILIBILI_TUNNEL_HOST": os.getenv("BILIBILI_TUNNEL_HOST", ""),
            "ETSY_TUNNEL_HOST": os.getenv("ETSY_TUNNEL_HOST", ""),
            "RAG_ENABLED": os.getenv("RAG_ENABLED", "false"),
            "RAG_CORPUS_NAME": os.getenv("RAG_CORPUS_NAME", ""),
            "RAG_LOCATION": os.getenv("RAG_LOCATION", ""),
            "RAG_PROJECT_ID": os.getenv("RAG_PROJECT_ID", "") or project,
            "GCP_DATA_MCP_ENABLED": os.getenv("GCP_DATA_MCP_ENABLED", "false"),
            "TSE_FIRESTORE_PROJECT_ID": os.getenv("TSE_FIRESTORE_PROJECT_ID", ""),
            "TSE_FIRESTORE_DATABASE": os.getenv("TSE_FIRESTORE_DATABASE", ""),
            "TSE_API_BASE_URL": os.getenv("TSE_API_BASE_URL", ""),
            "TSE_API_KEY": os.getenv("TSE_API_KEY", ""),
            "CODE_EXECUTION_ENABLED": os.getenv("CODE_EXECUTION_ENABLED", "false"),
            "CODE_EXEC_LOCATION": os.getenv("CODE_EXEC_LOCATION", "us-central1"),
            # Code Exec sandbox resource can reuse the *primary* xiaozhi engine
            "SMART_AGENTS_ENGINE_ID": os.getenv("SMART_AGENTS_ENGINE_ID", ""),
            "SAP_COMPUTER_USE_ENABLED": os.getenv("SAP_COMPUTER_USE_ENABLED", "false"),
            "SAP_COMPUTER_USE_WORKER_URL": os.getenv("SAP_COMPUTER_USE_WORKER_URL", ""),
            "SAP_COMPUTER_USE_TOKEN": os.getenv("SAP_COMPUTER_USE_TOKEN", ""),
            "INVOICE_RECOGNITION_MODEL": os.getenv("INVOICE_RECOGNITION_MODEL", "gemini-3.8-flash"),
        }
    )

    from scripts.check_sap_deployment import validate_sap_deployment
    validate_sap_deployment(env_vars)

    common_kwargs = dict(
        agent_engine=local_a2a,
        display_name=A2A_DISPLAY_NAME,
        description=(
            "Parallel A2A exposure for SmartAgents dispatcher "
            "(does not replace SMART_AGENTS_ENGINE_ID / xiaozhi)."
        ),
        requirements=requirements,
        extra_packages=extra_packages,
        env_vars=env_vars,
    )

    if existing_id:
        resource = (
            f"projects/{project}/locations/{location}/reasoningEngines/{existing_id}"
        )
        print(f"🚀 Updating existing A2A Engine: {resource}")
        remote = agent_engines.update(resource_name=resource, **common_kwargs)
    else:
        print("🚀 Creating NEW parallel A2A Engine ...")
        remote = agent_engines.create(**common_kwargs)

    resource_name = getattr(remote, "resource_name", None) or str(remote)
    print("✅ Deployed:", resource_name)
    print()
    print("👉 将下列值写入根 .env（不要覆盖 SMART_AGENTS_ENGINE_ID）：")
    engine_id = resource_name.rstrip("/").split("/")[-1]
    print(f"SMART_AGENTS_A2A_ENGINE_ID={engine_id}")
    print()
    print("Agent Card URL (IAM required), typically:")
    print(
        f"https://{location}-aiplatform.googleapis.com/v1beta1/"
        f"{resource_name}/a2a/.well-known/agent.json"
    )
    print()
    print("Existing xiaozhi Engine is unchanged (SMART_AGENTS_ENGINE_ID).")


if __name__ == "__main__":
    main()
