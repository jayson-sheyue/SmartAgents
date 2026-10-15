"""Disabled-SAP diagnosis and cloud deployment preflight; no cloud calls."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from pydantic import PrivateAttr

from scripts.check_sap_deployment import validate_sap_deployment
from smart_agents.sap_tools import sap_prepare_browser, sap_enabled, SAP_DISABLED_INSTRUCTION
from smart_agents.greeting import build_dispatcher_greeting_opener


class DeploymentConfigTests(unittest.TestCase):
    def enabled(self, **updates):
        return {"SAP_COMPUTER_USE_ENABLED": "true", "SAP_COMPUTER_USE_WORKER_URL": "https://worker.example.com",
                "SAP_COMPUTER_USE_TOKEN": "t" * 32, **updates}

    def test_disabled_does_not_require_worker(self):
        validate_sap_deployment({})
        validate_sap_deployment({"SAP_COMPUTER_USE_ENABLED": "false"})

    def test_enabled_accepts_https_and_token(self):
        validate_sap_deployment(self.enabled())

    def test_cloud_rejects_local_or_missing_worker(self):
        for url in ("", "http://127.0.0.1:8010", "https://localhost:8010", "https://127.0.0.1", "https://[::1]",
                    "https://user:pass@worker.example.com", "https://worker.example.com?token=secret"):
            with self.assertRaises(ValueError):
                validate_sap_deployment(self.enabled(SAP_COMPUTER_USE_WORKER_URL=url))

    def test_token_required_and_errors_do_not_echo_secrets(self):
        for token in ("", "SECRET_SHORT"):
            with self.assertRaises(ValueError) as exc:
                validate_sap_deployment(self.enabled(SAP_COMPUTER_USE_TOKEN=token))
            if token:
                self.assertNotIn(token, str(exc.exception))

    def test_invalid_flag_rejected_and_whitespace_matches_runtime(self):
        with self.assertRaises(ValueError):
            validate_sap_deployment({"SAP_COMPUTER_USE_ENABLED": "tru"})
        with patch.dict("os.environ", {"SAP_COMPUTER_USE_ENABLED": " TRUE "}):
            self.assertTrue(sap_enabled())
        validate_sap_deployment(self.enabled(SAP_COMPUTER_USE_ENABLED=" TRUE "))

    def test_greeting_lists_only_enabled_sap(self):
        kwargs = {"bilibili_agent_name": "b", "etsy_agent_name": "e"}
        self.assertNotIn("SAP", build_dispatcher_greeting_opener(**kwargs))
        self.assertIn("SAP", build_dispatcher_greeting_opener(**kwargs, sap_enabled=True))


class DisabledConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_never_opens_network_or_requires_identity(self):
        with patch.dict("os.environ", {"SAP_COMPUTER_USE_ENABLED": "false"}), \
             patch("smart_agents.sap_tools.httpx.AsyncClient") as transport:
            result = await sap_prepare_browser(SimpleNamespace())
        self.assertEqual(result["error"]["code"], "SAP_DISABLED")
        self.assertIn("Agent Engine", result["error"]["message"])
        self.assertTrue(result["wait_user"])
        transport.assert_not_called()

    async def test_actual_runner_can_diagnose_disabled_deployment(self):
        class Model(BaseLlm):
            _called: bool = PrivateAttr(default=False)
            async def generate_content_async(self, llm_request, stream=False):
                if not self._called:
                    self._called = True
                    part = types.Part(function_call=types.FunctionCall(name="sap_prepare_browser", args={}))
                else:
                    part = types.Part(text="当前部署尚未开启 SAP，请管理员配置 Agent Engine。")
                yield LlmResponse(content=types.Content(role="model", parts=[part]))

        agent = Agent(name="disabled_sap", instruction=SAP_DISABLED_INSTRUCTION,
                      model=Model(model="offline"), tools=[sap_prepare_browser])
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="disabled_sap", user_id="one")
        runner = Runner(app_name="disabled_sap", agent=agent, session_service=sessions)
        with patch.dict("os.environ", {"SAP_COMPUTER_USE_ENABLED": "false"}), \
             patch("smart_agents.sap_tools.httpx.AsyncClient") as transport:
            events = [event async for event in runner.run_async(user_id="one", session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part(text="连接SAP")]))]
        responses = [part.function_response.response for event in events if event.content
                     for part in event.content.parts if part.function_response]
        self.assertEqual(responses[0]["error"]["code"], "SAP_DISABLED")
        transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
