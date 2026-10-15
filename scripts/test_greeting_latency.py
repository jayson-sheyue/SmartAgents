"""Greeting must bypass remote tool discovery, memory preload and the model."""
import unittest

from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types

from smart_agents.greeting import make_greeting_agent_callback, is_greeting_only


class _NoDiscovery(BaseToolset):
    async def get_tools(self, readonly_context=None):
        raise AssertionError("Greeting must not discover tools")

    async def close(self):
        pass


class _NoModel(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        raise AssertionError("Greeting must not call the model")
        yield


class GreetingLatencyTests(unittest.IsolatedAsyncioTestCase):
    def test_pinyin_greetings_and_real_tasks(self):
        for text in ("nihao", "ni hao!", "你好", "hello"):
            self.assertTrue(is_greeting_only(text))
        self.assertFalse(is_greeting_only("nihao，帮我查日报"))

    async def test_actual_runner_answers_before_any_remote_dependency(self):
        agent = Agent(name="greeting_test", model=_NoModel(model="offline"), tools=[_NoDiscovery()],
                      before_agent_callback=make_greeting_agent_callback(
                          bilibili_agent_name="bilibili", etsy_agent_name="etsy", feishu_agent_name="feishu"))
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="greeting_test", user_id="test")
        runner = Runner(app_name="greeting_test", agent=agent, session_service=sessions)
        events = [event async for event in runner.run_async(user_id="test", session_id=session.id,
                  new_message=types.Content(role="user", parts=[types.Part(text="nihao")]))]
        self.assertTrue(any("小智" in (part.text or "") for event in events if event.content for part in event.content.parts))
