# -*- coding: utf-8 -*-
"""
SmartAgents A2A 包装入口（并行第二 Engine）。

复用 smart_agents.agent.root_agent，不改飞书 / 现有 deploy_smart_agents.sh。

Deploy 注意：不得在 create() 前绑定已导入的 root_agent（MCP 含 `_thread.lock`，
cloudpickle 会失败）。云端由 executor_builder 懒加载 root_agent。
"""

from __future__ import annotations

import os
from typing import Optional

from vertexai.agent_engines.templates.a2a import A2aAgent

from smart_agents.a2a_card import build_agent_card
from smart_agents.a2a_executor import SmartAgentsA2aExecutor
from smart_agents.a2a_ge_compat import (
    install_rest03_body_patch,
    patch_rest_routes_for_ge,
)


# Force GE patch as soon as this module is imported (deploy entry loads a2a_agent).
from smart_agents.a2a_ge_compat import install_rest03_body_patch as _install_ge_patch

try:
    _install_ge_patch()
except Exception as _exc:  # pragma: no cover
    print(f"SmartAgents early GE patch failed: {_exc!r}", flush=True)


def default_executor_builder() -> SmartAgentsA2aExecutor:
    """Module-level builder — picklable for agent_engines.create()."""
    return SmartAgentsA2aExecutor()


class SmartAgentsA2aAgent(A2aAgent):
    """A2aAgent with GE-friendly URL rewrite + REST body normalization."""

    def set_up(self):  # noqa: D401 — matches parent API
        # Patch BEFORE super().set_up() so create_rest_routes binds rewritten handlers.
        install_rest03_body_patch()
        super().set_up()
        project = self._tmpl_attrs.get("project")
        location = self._tmpl_attrs.get("location")
        agent_engine_id = os.getenv("GOOGLE_CLOUD_AGENT_ENGINE_ID", "test-agent-engine")
        new_url = (
            f"https://{location}-aiplatform.googleapis.com/v1beta1/"
            f"projects/{project}/locations/{location}/"
            f"reasoningEngines/{agent_engine_id}/a2a"
        )
        for iface in self.agent_card.supported_interfaces:
            iface.url = new_url
        extended = self._tmpl_attrs.get("extended_agent_card")
        if extended is not None and getattr(extended, "supported_interfaces", None):
            for iface in extended.supported_interfaces:
                iface.url = new_url
        self._tmpl_attrs["agent_card"] = self.agent_card
        if extended is not None:
            self._tmpl_attrs["extended_agent_card"] = extended

        if getattr(self, "rest_routes", None):
            self.rest_routes = patch_rest_routes_for_ge(list(self.rest_routes))


def build_a2a_agent(*, agent=None) -> A2aAgent:
    """Construct Runtime-ready A2aAgent wrapping SmartAgents root_agent.

    Pass ``agent`` only for local live smoke. Deploy must omit it (lazy import).
    """
    card = build_agent_card()

    if agent is None:
        builder = default_executor_builder
    else:
        bound = agent

        def _bound_executor_builder() -> SmartAgentsA2aExecutor:
            return SmartAgentsA2aExecutor(agent=bound)

        builder = _bound_executor_builder

    return SmartAgentsA2aAgent(
        agent_card=card,
        extended_agent_card=card,
        agent_executor_builder=builder,
    )


def get_a2a_agent() -> A2aAgent:
    """Picklable A2aAgent for deploy / card smoke (no root_agent import)."""
    return build_a2a_agent()


def get_a2a_agent_with_root() -> A2aAgent:
    """Eager-bind root_agent for local live smoke only (not picklable / not for deploy)."""
    from smart_agents.agent import root_agent

    return build_a2a_agent(agent=root_agent)


a2a_agent: Optional[A2aAgent] = None
