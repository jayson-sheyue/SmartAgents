# -*- coding: utf-8 -*-
"""Deploy smart_agents ADK runtime with sibling ``domains/`` package bundled.

``adk deploy agent_engine`` only copies the agent folder into the container at
``/app/agents/{app_name}/``.  ``smart_agents.agent`` imports ``domains.*``, so
we also copy ``domains/`` to ``/app/agents/domains/`` and extend the generated
Dockerfile + source_packages accordingly.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP_NAME = "smart_agents"
DOMAINS_SRC = ROOT / "domains"


def _require_env(name: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        raise SystemExit(f"Missing required env: {name}")
    return val


def _install_deploy_patches() -> tuple[object, str, object]:
    """Patch ADK deploy so ``domains/`` is included in the Agent Engine image."""
    from google.adk.cli import cli_deploy
    from vertexai._genai import agent_engines as ae_mod

    orig_copytree = shutil.copytree
    orig_template = cli_deploy._DOCKERFILE_TEMPLATE
    orig_ae_update = ae_mod.AgentEngines.update

    copy_marker = (
        'COPY --chown=myuser:myuser "agents/{app_name}/" "/app/agents/{app_name}/"'
    )
    domains_copy = (
        'COPY --chown=myuser:myuser "agents/{app_name}/" "/app/agents/{app_name}/"\n'
        'COPY --chown=myuser:myuser "agents/domains/" "/app/agents/domains/"'
    )
    if domains_copy not in orig_template:
        cli_deploy._DOCKERFILE_TEMPLATE = orig_template.replace(
            copy_marker, domains_copy
        )

    def copytree_with_domains(src, dst, *args, **kwargs):
        orig_copytree(src, dst, *args, **kwargs)
        dst_path = Path(dst)
        if dst_path.name == APP_NAME and dst_path.parent.name == "agents":
            domains_dst = dst_path.parent / "domains"
            if not DOMAINS_SRC.is_dir():
                raise SystemExit(f"Missing domains package at {DOMAINS_SRC}")
            if domains_dst.exists():
                shutil.rmtree(domains_dst)
            orig_copytree(DOMAINS_SRC, domains_dst, dirs_exist_ok=True)
            print(f"📦 Bundled domains → {domains_dst}")

    shutil.copytree = copytree_with_domains

    def update_with_domains(self, name, config=None, **kw):
        cfg = dict(config or {})
        pkgs = list(cfg.get("source_packages") or [])
        if pkgs and "agents/domains" not in pkgs:
            insert_at = pkgs.index("Dockerfile") if "Dockerfile" in pkgs else len(pkgs)
            pkgs.insert(insert_at, "agents/domains")
            cfg["source_packages"] = pkgs
            print(f"📦 source_packages: {pkgs}")
        return orig_ae_update(self, name=name, config=cfg, **kw)

    ae_mod.AgentEngines.update = update_with_domains
    return orig_copytree, orig_template, orig_ae_update


def _restore_deploy_patches(orig_copytree, orig_template, orig_ae_update) -> None:
    from google.adk.cli import cli_deploy
    from vertexai._genai import agent_engines as ae_mod

    shutil.copytree = orig_copytree
    cli_deploy._DOCKERFILE_TEMPLATE = orig_template
    ae_mod.AgentEngines.update = orig_ae_update


def main() -> None:
    if not DOMAINS_SRC.is_dir():
        raise SystemExit(f"Missing domains package at {DOMAINS_SRC}")

    project = _require_env("GCP_PROJECT_ID")
    region = _require_env("GCP_LOCATION")
    engine_id = _require_env("SMART_AGENTS_ENGINE_ID")
    import asyncio
    from scripts.check_sap_deployment import validate_sap_online
    asyncio.run(validate_sap_online(os.environ))
    agent_folder = str((ROOT / APP_NAME).resolve())

    from google.adk.cli.cli_deploy import to_agent_engine

    orig_copytree, orig_template, orig_ae_update = _install_deploy_patches()
    try:
        to_agent_engine(
            agent_folder=agent_folder,
            project=project,
            region=region,
            display_name="SmartAgents Dispatcher",
            agent_engine_id=engine_id,
        )
    finally:
        _restore_deploy_patches(orig_copytree, orig_template, orig_ae_update)


if __name__ == "__main__":
    main()
