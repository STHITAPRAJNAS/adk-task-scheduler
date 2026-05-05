"""Shared fixtures and a minimal mock ADK agent for tests."""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.adk.runners import InMemoryRunner
from google.genai import types

from adk_task_scheduler.config import ScheduleConfig

# ---------------------------------------------------------------------------
# Minimal echo agent — yields one final response without calling any LLM.
# ---------------------------------------------------------------------------

class EchoAgent(BaseAgent):
    """Returns 'echo: <input>' for every message. No LLM calls."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        user_text = ""
        if ctx.user_content and ctx.user_content.parts:
            user_text = ctx.user_content.parts[0].text or ""

        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=types.Content(
                role="model",
                parts=[types.Part(text=f"echo: {user_text}")],
            ),
        )


@pytest.fixture
def echo_agent() -> EchoAgent:
    return EchoAgent(name="echo_agent", description="test echo agent")


@pytest.fixture
def basic_config(echo_agent: EchoAgent) -> ScheduleConfig:
    return ScheduleConfig(
        agent=echo_agent,
        interval_seconds=60,
        trigger_text="__tick__",
    )


@pytest.fixture
def inmemory_runner(echo_agent: EchoAgent) -> InMemoryRunner:
    return InMemoryRunner(agent=echo_agent, app_name="test_app")
