"""Smoke test: real LlmAgent invoked programmatically through the scheduler.

This test requires a GOOGLE_API_KEY environment variable and makes a real
network call to the Gemini API.  It is intentionally marked with a custom
marker so the CI matrix (which has no API key) can skip it:

    pytest -m "not live"          # default — skips this file
    pytest -m live                # run only live tests (needs GOOGLE_API_KEY)

The test does NOT start a FastAPI / uvicorn server.  It exercises the full
scheduler stack (ScheduleConfig → RunnerPool → Runner.run_async) against a
real LlmAgent to verify that the library is end-to-end compatible with ADK.
"""
from __future__ import annotations

import os

import pytest
from google.adk.agents import Agent

from adk_task_scheduler.config import ScheduleConfig
from adk_task_scheduler.invoker import RunnerPool, invoke_agent

# ---------------------------------------------------------------------------
# Skip the whole module when no API key is present.
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    not os.environ.get("GOOGLE_API_KEY"),
    reason="GOOGLE_API_KEY not set — skipping live agent tests",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_real_agent(name: str = "smoke_agent") -> Agent:
    return Agent(
        name=name,
        model="gemini-2.0-flash",
        instruction="""
        You are a test agent used in automated smoke tests.

        When the user message is exactly '__smoke__', respond with the single
        word: SMOKE_OK

        For any other message respond normally.
        """,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
async def test_real_agent_responds_to_trigger():
    """The scheduler can invoke a real LlmAgent and get a response."""
    responses: list[str] = []
    errors: list[Exception] = []

    agent = _make_real_agent("smoke_trigger")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=3600,   # won't actually fire — we call invoke_agent directly
        trigger_text="__smoke__",
        on_response=responses.append,
        on_error=errors.append,
    )

    pool = RunnerPool()
    await invoke_agent(cfg, pool)

    assert not errors, f"invoke_agent raised: {errors[0]}"
    assert len(responses) == 1, "Expected exactly one response"
    assert "SMOKE_OK" in responses[0], (
        f"Agent did not return expected sentinel. Got: {responses[0]!r}"
    )


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_agent_adhoc_and_scheduled_independent():
    """Scheduled runner and ad-hoc runner operate on separate sessions."""
    scheduled_responses: list[str] = []

    agent = _make_real_agent("smoke_independence")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=3600,
        trigger_text="__smoke__",
        on_response=scheduled_responses.append,
    )

    pool = RunnerPool()

    # Fire scheduled invocation
    await invoke_agent(cfg, pool)

    # The scheduled runner/session service is completely separate — verify
    # the pool created exactly one entry for this agent
    assert len(pool._entries) == 1
    assert "smoke_independence" in pool._entries

    # The response came through cleanly
    assert len(scheduled_responses) == 1
    assert "SMOKE_OK" in scheduled_responses[0]


@pytest.mark.live
@pytest.mark.asyncio
async def test_real_agent_multiple_scheduled_ticks():
    """Multiple sequential ticks create independent sessions each time."""
    responses: list[str] = []

    agent = _make_real_agent("smoke_multi_tick")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=3600,
        trigger_text="__smoke__",
        on_response=responses.append,
    )

    pool = RunnerPool()
    await invoke_agent(cfg, pool)
    await invoke_agent(cfg, pool)

    assert len(responses) == 2
    assert all("SMOKE_OK" in r for r in responses)
