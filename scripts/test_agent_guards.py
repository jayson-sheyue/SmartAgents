"""Exercise the actual ADK Runner with a deterministic offline model."""
import unittest

from google.adk.agents import Agent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types
from pydantic import PrivateAttr

from smart_agents.task_card import STATE_KEY, task_card_before_tool, make_task_card_after_tool


class _WriteOnceModel(BaseLlm):
    _called: bool = PrivateAttr(default=False)

    async def generate_content_async(self, llm_request, stream=False):
        if not self._called:
            self._called = True
            part = types.Part(function_call=types.FunctionCall(name="feishu_calendar_create", args={}))
        else:
            part = types.Part(text="任务暂停，等待核查。")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


class AgentGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_runner_blocks_actual_mutation_and_delivers_task_state(self):
        writes = []

        def feishu_calendar_create() -> dict:
            """Create a calendar event in a simulated service."""
            writes.append(True)
            return {"ok": True, "data": {"event_id": "evt1"}}

        agent = Agent(name="guard_test", model=_WriteOnceModel(model="offline"),
                      tools=[feishu_calendar_create], before_tool_callback=task_card_before_tool,
                      after_tool_callback=make_task_card_after_tool())
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="guard_test", user_id="test", state={
            STATE_KEY: {"status": "blocked", "phase": "blocked", "deliverable": "calendar_event",
                        "blocked_reason": "write_result_uncertain"},
        })
        runner = Runner(app_name="guard_test", agent=agent, session_service=sessions)
        events = [event async for event in runner.run_async(user_id="test", session_id=session.id,
                  new_message=types.Content(role="user", parts=[types.Part(text="继续")]))]
        responses = [part.function_response.response for event in events if event.content
                     for part in event.content.parts if part.function_response]
        self.assertEqual(writes, [])
        self.assertTrue(any(r.get("error", {}).get("code") == "TASK_BLOCKED" for r in responses))
        fresh = await sessions.get_session(app_name="guard_test", user_id="test", session_id=session.id)
        self.assertEqual(fresh.state[STATE_KEY]["status"], "blocked")
