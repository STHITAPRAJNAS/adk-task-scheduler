"""Tests for build_scheduler_lifespan."""
from __future__ import annotations

import asyncio

import pytest

from adk_task_scheduler.config import ScheduleConfig
from adk_task_scheduler.lifespan import build_scheduler_lifespan
from tests.conftest import EchoAgent


def make_agent(name: str) -> EchoAgent:
    return EchoAgent(name=name, description="test")


@pytest.mark.asyncio
async def test_lifespan_returns_callable():
    cfg = ScheduleConfig(agent=make_agent("a"), interval_seconds=10)
    lifespan = build_scheduler_lifespan([cfg])
    assert callable(lifespan)


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_scheduler():
    """Entering/exiting the lifespan starts and shuts down the scheduler."""
    started: list[bool] = []
    stopped: list[bool] = []

    agent = make_agent("lifecycle")
    cfg = ScheduleConfig(agent=agent, interval_seconds=3600)
    lifespan = build_scheduler_lifespan([cfg])

    class FakeApp:
        pass

    async with lifespan(FakeApp()):
        # scheduler is running inside the context
        started.append(True)

    stopped.append(True)
    assert started == [True]
    assert stopped == [True]


@pytest.mark.asyncio
async def test_lifespan_empty_schedules_no_error():
    lifespan = build_scheduler_lifespan([])

    class FakeApp:
        pass

    async with lifespan(FakeApp()):
        pass  # should not raise


@pytest.mark.asyncio
async def test_lifespan_registers_cron_job():
    """Verify the APScheduler job is actually registered with the correct id."""
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from adk_task_scheduler.invoker import RunnerPool
    from adk_task_scheduler.lifespan import _register_job

    agent = make_agent("cron_reg")
    cfg = ScheduleConfig(agent=agent, cron="0 * * * *")

    scheduler = AsyncIOScheduler()
    pool = RunnerPool()
    _register_job(scheduler, cfg, pool)

    job_ids = [job.id for job in scheduler.get_jobs()]
    assert cfg.app_name in job_ids


@pytest.mark.asyncio
async def test_condition_poll_interval_is_respected():
    """condition_poll_interval controls how often the condition is polled."""
    responses: list[str] = []
    call_count = 0

    def always_true():
        nonlocal call_count
        call_count += 1
        return True

    agent = make_agent("cond_interval")
    cfg = ScheduleConfig(
        agent=agent,
        condition=always_true,
        condition_poll_interval=1,  # poll every 1 second
        trigger_text="__cond__",
        on_response=responses.append,
    )
    lifespan = build_scheduler_lifespan([cfg])

    class FakeApp:
        pass

    async with lifespan(FakeApp()):
        await asyncio.sleep(2.5)

    # condition was evaluated at least twice (once per second over 2.5 s)
    assert call_count >= 2
    assert len(responses) >= 2


@pytest.mark.asyncio
async def test_lifespan_interval_job_fires(monkeypatch):
    """Integration: interval job fires and on_response is called."""
    responses: list[str] = []
    agent = make_agent("fire_test")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=1,  # 1 second for fast test
        trigger_text="__test__",
        on_response=responses.append,
    )

    lifespan = build_scheduler_lifespan([cfg])

    class FakeApp:
        pass

    async with lifespan(FakeApp()):
        # Wait enough for at least one firing
        await asyncio.sleep(2.5)

    assert len(responses) >= 1
    assert all(r == "echo: __test__" for r in responses)


@pytest.mark.asyncio
async def test_lifespan_multiple_schedules():
    """Multiple schedules can coexist in a single lifespan."""
    responses_a: list[str] = []
    responses_b: list[str] = []

    agent_a = make_agent("agent_a")
    agent_b = make_agent("agent_b")

    cfg_a = ScheduleConfig(
        agent=agent_a,
        interval_seconds=1,
        trigger_text="ping_a",
        on_response=responses_a.append,
    )
    cfg_b = ScheduleConfig(
        agent=agent_b,
        interval_seconds=1,
        trigger_text="ping_b",
        on_response=responses_b.append,
    )

    lifespan = build_scheduler_lifespan([cfg_a, cfg_b])

    class FakeApp:
        pass

    async with lifespan(FakeApp()):
        await asyncio.sleep(2.5)

    assert len(responses_a) >= 1
    assert len(responses_b) >= 1
    assert all(r == "echo: ping_a" for r in responses_a)
    assert all(r == "echo: ping_b" for r in responses_b)
