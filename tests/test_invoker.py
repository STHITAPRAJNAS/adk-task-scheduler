"""Tests for RunnerPool and invoke_agent."""
from __future__ import annotations

import asyncio

import pytest

from adk_task_scheduler.config import ScheduleConfig
from adk_task_scheduler.invoker import RunnerPool, evaluate_condition, invoke_agent
from tests.conftest import EchoAgent


def make_agent(name: str = "a") -> EchoAgent:
    return EchoAgent(name=name, description="test")


# ---------------------------------------------------------------------------
# RunnerPool
# ---------------------------------------------------------------------------

def test_runner_pool_creates_runner_lazily():
    agent = make_agent("lazy")
    cfg = ScheduleConfig(agent=agent, interval_seconds=10)
    pool = RunnerPool()
    assert len(pool._entries) == 0
    runner, svc = pool.get_or_create(cfg)
    assert runner is not None
    assert len(pool._entries) == 1


def test_runner_pool_reuses_runner():
    agent = make_agent("reuse")
    cfg = ScheduleConfig(agent=agent, interval_seconds=10)
    pool = RunnerPool()
    r1, _ = pool.get_or_create(cfg)
    r2, _ = pool.get_or_create(cfg)
    assert r1 is r2


def test_runner_pool_different_app_names_separate():
    a1 = make_agent("app_a")
    a2 = make_agent("app_b")
    cfg1 = ScheduleConfig(agent=a1, interval_seconds=10)
    cfg2 = ScheduleConfig(agent=a2, interval_seconds=10)
    pool = RunnerPool()
    r1, _ = pool.get_or_create(cfg1)
    r2, _ = pool.get_or_create(cfg2)
    assert r1 is not r2
    assert len(pool._entries) == 2


@pytest.mark.asyncio
async def test_runner_pool_close_all():
    agent = make_agent("close")
    cfg = ScheduleConfig(agent=agent, interval_seconds=10)
    pool = RunnerPool()
    pool.get_or_create(cfg)
    await pool.close_all()
    assert len(pool._entries) == 0


# ---------------------------------------------------------------------------
# invoke_agent — end-to-end with real EchoAgent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_invoke_agent_calls_on_response():
    responses: list[str] = []
    agent = make_agent("responder")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=10,
        trigger_text="__tick__",
        on_response=responses.append,
    )
    pool = RunnerPool()
    await invoke_agent(cfg, pool)
    assert len(responses) == 1
    assert responses[0] == "echo: __tick__"


@pytest.mark.asyncio
async def test_invoke_agent_custom_trigger_text():
    responses: list[str] = []
    agent = make_agent("custom_trigger")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=10,
        trigger_text="hello world",
        on_response=responses.append,
    )
    pool = RunnerPool()
    await invoke_agent(cfg, pool)
    assert responses[0] == "echo: hello world"


@pytest.mark.asyncio
async def test_invoke_agent_no_on_response_does_not_raise():
    agent = make_agent("silent")
    cfg = ScheduleConfig(agent=agent, interval_seconds=10)
    pool = RunnerPool()
    # Should complete without error even with no on_response
    await invoke_agent(cfg, pool)


@pytest.mark.asyncio
async def test_invoke_agent_calls_on_error_on_failure():
    errors: list[Exception] = []

    class FailingAgent(EchoAgent):
        async def _run_async_impl(self, ctx):
            raise RuntimeError("boom")
            # Make it a generator
            yield  # noqa: unreachable

    agent = FailingAgent(name="failer", description="fails")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=10,
        on_error=errors.append,
    )
    pool = RunnerPool()
    await invoke_agent(cfg, pool)
    assert len(errors) == 1
    assert "boom" in str(errors[0])


@pytest.mark.asyncio
async def test_invoke_agent_multiple_times_independent_sessions():
    """Each invocation creates a fresh session."""
    session_ids: list[str] = []

    agent = make_agent("multi")
    cfg = ScheduleConfig(agent=agent, interval_seconds=10)
    pool = RunnerPool()
    runner, svc = pool.get_or_create(cfg)

    # Track session creation by wrapping create_session
    original_create = svc.create_session

    async def tracking_create(**kwargs):
        session = await original_create(**kwargs)
        session_ids.append(session.id)
        return session

    svc.create_session = tracking_create

    await invoke_agent(cfg, pool)
    await invoke_agent(cfg, pool)

    assert len(session_ids) == 2
    assert session_ids[0] != session_ids[1]


# ---------------------------------------------------------------------------
# evaluate_condition
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_condition_sync():
    agent = make_agent("sync_cond")
    cfg = ScheduleConfig(agent=agent, condition=lambda: True)
    assert await evaluate_condition(cfg) is True


@pytest.mark.asyncio
async def test_evaluate_condition_async():
    agent = make_agent("async_cond")

    async def _cond():
        await asyncio.sleep(0)
        return True

    cfg = ScheduleConfig(agent=agent, condition=_cond)
    assert await evaluate_condition(cfg) is True


@pytest.mark.asyncio
async def test_evaluate_condition_falsy():
    agent = make_agent("false_cond")
    cfg = ScheduleConfig(agent=agent, condition=lambda: 0)
    assert await evaluate_condition(cfg) is False


@pytest.mark.asyncio
async def test_evaluate_condition_none():
    agent = make_agent("no_cond")
    cfg = ScheduleConfig(agent=agent, interval_seconds=10)
    assert await evaluate_condition(cfg) is False
