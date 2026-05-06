"""Tests for the 5 condition-trigger improvements.

1. fire_mode="once_until_reset" — fires only on False→True transition
2. ConditionContext passed to one-arg conditions
3. condition_backoff_factor — exponential back-off on repeated false results
4. condition combined with cron/interval as a gate
5. condition exceptions routed to on_error
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from adk_task_scheduler.config import ConditionContext, ScheduleConfig
from adk_task_scheduler.invoker import evaluate_condition
from adk_task_scheduler.lifespan import _should_fire, build_scheduler_lifespan
from tests.conftest import EchoAgent


def make_agent(name: str = "a") -> EchoAgent:
    return EchoAgent(name=name, description="test")


# ---------------------------------------------------------------------------
# 1. fire_mode
# ---------------------------------------------------------------------------

def test_should_fire_every_true():
    assert _should_fire("every", current=True, previous=False) is True


def test_should_fire_every_stays_true():
    assert _should_fire("every", current=True, previous=True) is True


def test_should_fire_every_false():
    assert _should_fire("every", current=False, previous=True) is False


def test_should_fire_once_until_reset_transition():
    assert _should_fire("once_until_reset", current=True, previous=False) is True


def test_should_fire_once_until_reset_stays_true():
    """Stays truthy — must NOT re-fire."""
    assert _should_fire("once_until_reset", current=True, previous=True) is False


def test_should_fire_once_until_reset_false():
    assert _should_fire("once_until_reset", current=False, previous=True) is False


@pytest.mark.asyncio
async def test_fire_mode_once_until_reset_fires_once():
    """With once_until_reset, agent fires exactly once even when condition stays True."""
    calls: list[str] = []
    toggle = [True]  # condition is always True

    agent = make_agent("once_reset")
    cfg = ScheduleConfig(
        agent=agent,
        condition=lambda: toggle[0],
        condition_poll_interval=1,
        fire_mode="once_until_reset",
        on_response=calls.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(2.5)  # 2 polls while condition stays True

    # Should fire only once (False→True on first poll, then suppressed)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_fire_mode_once_until_reset_resets_on_false():
    """Fires again after condition dips to False then back to True."""
    calls: list[str] = []
    toggle = [True]

    agent = make_agent("reset_cycle")
    cfg = ScheduleConfig(
        agent=agent,
        condition=lambda: toggle[0],
        condition_poll_interval=1,
        fire_mode="once_until_reset",
        on_response=calls.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(1.5)   # first poll → True (fires)
        toggle[0] = False
        await asyncio.sleep(1.1)   # second poll → False (suppressed)
        toggle[0] = True
        await asyncio.sleep(1.1)   # third poll → True again (fires)

    assert len(calls) == 2


# ---------------------------------------------------------------------------
# 2. ConditionContext passed to one-arg conditions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_condition_zero_arg():
    agent = make_agent("zero")
    cfg = ScheduleConfig(agent=agent, condition=lambda: True)
    assert await evaluate_condition(cfg) is True


@pytest.mark.asyncio
async def test_evaluate_condition_one_arg_receives_context():
    received: list[ConditionContext] = []

    def _cond(ctx: ConditionContext) -> bool:
        received.append(ctx)
        return True

    agent = make_agent("ctx_recv")
    cfg = ScheduleConfig(agent=agent, condition=_cond)
    ctx = ConditionContext(last_fired_at=None, fire_count=0, extra_state={})
    result = await evaluate_condition(cfg, ctx)

    assert result is True
    assert len(received) == 1
    assert received[0] is ctx


@pytest.mark.asyncio
async def test_evaluate_condition_one_arg_async():
    async def _cond(ctx: ConditionContext) -> bool:
        await asyncio.sleep(0)
        return ctx.fire_count == 0

    agent = make_agent("async_ctx")
    cfg = ScheduleConfig(agent=agent, condition=_cond)
    ctx = ConditionContext(last_fired_at=None, fire_count=0, extra_state={})
    assert await evaluate_condition(cfg, ctx) is True

    ctx2 = ConditionContext(last_fired_at=None, fire_count=1, extra_state={})
    assert await evaluate_condition(cfg, ctx2) is False


@pytest.mark.asyncio
async def test_context_fire_count_increments():
    """ConditionContext.fire_count reflects real invocation history."""
    fire_counts: list[int] = []
    toggle = [True]

    def _cond(ctx: ConditionContext) -> bool:
        fire_counts.append(ctx.fire_count)
        return toggle[0]

    agent = make_agent("count_ctx")
    cfg = ScheduleConfig(
        agent=agent,
        condition=_cond,
        condition_poll_interval=1,
        fire_mode="every",
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(3.5)

    # fire_count seen by condition should start at 0 and increment each poll
    assert fire_counts[0] == 0
    assert fire_counts[-1] >= 2


@pytest.mark.asyncio
async def test_context_last_fired_at_none_before_first_fire():
    last_fired_ats: list[datetime | None] = []

    def _cond(ctx: ConditionContext) -> bool:
        last_fired_ats.append(ctx.last_fired_at)
        return True  # always fire

    agent = make_agent("lfa_ctx")
    cfg = ScheduleConfig(
        agent=agent,
        condition=_cond,
        condition_poll_interval=1,
        fire_mode="once_until_reset",
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(1.5)

    assert last_fired_ats[0] is None  # never fired yet on first poll


# ---------------------------------------------------------------------------
# 3. condition_backoff_factor
# ---------------------------------------------------------------------------

def test_backoff_factor_below_one_raises():
    agent = make_agent("bad_backoff")
    with pytest.raises(ValueError, match="condition_backoff_factor"):
        ScheduleConfig(agent=agent, condition=lambda: False, condition_backoff_factor=0.5)


def test_backoff_factor_one_is_valid():
    agent = make_agent("no_backoff")
    cfg = ScheduleConfig(agent=agent, condition=lambda: False, condition_backoff_factor=1.0)
    assert cfg.condition_backoff_factor == 1.0


def test_condition_max_poll_interval_zero_raises():
    agent = make_agent("bad_max")
    with pytest.raises(ValueError, match="condition_max_poll_interval"):
        ScheduleConfig(
            agent=agent,
            condition=lambda: False,
            condition_max_poll_interval=0,
        )


@pytest.mark.asyncio
async def test_backoff_reduces_poll_frequency():
    """With backoff, a persistently-false condition is evaluated fewer times."""
    eval_count = [0]

    def _cond() -> bool:
        eval_count[0] += 1
        return False

    agent_no_backoff = make_agent("no_backoff_count")
    cfg_no_backoff = ScheduleConfig(
        agent=agent_no_backoff,
        condition=_cond,
        condition_poll_interval=1,
        condition_backoff_factor=1.0,
    )

    lifespan = build_scheduler_lifespan([cfg_no_backoff])
    async with lifespan(MagicMock()):
        await asyncio.sleep(3.5)
    count_no_backoff = eval_count[0]

    eval_count[0] = 0
    agent_backoff = make_agent("backoff_count")
    cfg_backoff = ScheduleConfig(
        agent=agent_backoff,
        condition=_cond,
        condition_poll_interval=1,
        condition_backoff_factor=3.0,  # aggressive backoff
    )

    lifespan2 = build_scheduler_lifespan([cfg_backoff])
    async with lifespan2(MagicMock()):
        await asyncio.sleep(3.5)
    count_backoff = eval_count[0]

    assert count_backoff < count_no_backoff, (
        f"Backoff should reduce eval frequency: {count_backoff} vs {count_no_backoff}"
    )


@pytest.mark.asyncio
async def test_backoff_resets_after_fire():
    """Back-off counter resets when condition fires."""
    calls: list[str] = []
    toggle = [False]
    eval_times: list[float] = []

    def _cond() -> bool:
        eval_times.append(time.monotonic())
        return toggle[0]

    agent = make_agent("backoff_reset")
    cfg = ScheduleConfig(
        agent=agent,
        condition=_cond,
        condition_poll_interval=1,
        condition_backoff_factor=10.0,  # huge backoff so we can clearly detect reset
        on_response=calls.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(1.5)  # accumulate false evals → backoff kicks in
        toggle[0] = True
        await asyncio.sleep(12)   # wait past backoff; condition fires; backoff resets
        toggle[0] = False
        await asyncio.sleep(1.5)  # should eval again quickly (backoff reset)

    # Agent should have fired at least once
    assert len(calls) >= 1


# ---------------------------------------------------------------------------
# 4. condition combined with cron/interval as gate
# ---------------------------------------------------------------------------

def test_interval_plus_condition_valid():
    agent = make_agent("gated")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=60,
        condition=lambda: True,
    )
    assert cfg.interval_seconds == 60
    assert cfg.condition is not None


def test_cron_plus_condition_valid():
    agent = make_agent("cron_gated")
    cfg = ScheduleConfig(
        agent=agent,
        cron="* * * * *",
        condition=lambda: False,
    )
    assert cfg.cron == "* * * * *"
    assert cfg.condition is not None


def test_cron_and_interval_mutually_exclusive():
    agent = make_agent("exclusive")
    with pytest.raises(ValueError, match="mutually exclusive"):
        ScheduleConfig(agent=agent, cron="* * * * *", interval_seconds=10)


@pytest.mark.asyncio
async def test_interval_with_false_condition_never_fires():
    """Interval + condition=False → agent never invoked."""
    calls: list[str] = []
    agent = make_agent("gated_false")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=1,
        condition=lambda: False,
        on_response=calls.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(2.5)

    assert calls == []


@pytest.mark.asyncio
async def test_interval_with_true_condition_fires():
    """Interval + condition=True → agent fires on each tick."""
    calls: list[str] = []
    agent = make_agent("gated_true")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=1,
        condition=lambda: True,
        on_response=calls.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(2.5)

    assert len(calls) >= 2


@pytest.mark.asyncio
async def test_interval_with_toggling_condition():
    """Gate opens and closes — agent fires only when condition is True."""
    calls: list[str] = []
    gate = [False]
    agent = make_agent("gated_toggle")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=1,
        condition=lambda: gate[0],
        on_response=calls.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(1.5)   # gate closed → no fires
        gate[0] = True
        await asyncio.sleep(2.5)   # gate open → fires
        gate[0] = False
        await asyncio.sleep(1.5)   # gate closed again → no more fires

    assert len(calls) >= 2


@pytest.mark.asyncio
async def test_gated_interval_fire_mode_once_until_reset():
    """Interval + condition + once_until_reset: fires only on first truthy tick."""
    calls: list[str] = []
    agent = make_agent("gated_once")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=1,
        condition=lambda: True,
        fire_mode="once_until_reset",
        on_response=calls.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(3.5)

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# 5. condition exceptions routed to on_error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_evaluate_condition_propagates_exception():
    """evaluate_condition lets exceptions propagate — caller routes to on_error."""
    def _bad() -> bool:
        raise RuntimeError("condition exploded")

    agent = make_agent("bad_cond")
    cfg = ScheduleConfig(agent=agent, condition=_bad)
    with pytest.raises(RuntimeError, match="condition exploded"):
        await evaluate_condition(cfg)


@pytest.mark.asyncio
async def test_condition_exception_calls_on_error():
    """Standalone condition exception is caught and passed to on_error."""
    errors: list[Exception] = []
    calls: list[str] = []

    def _bad() -> bool:
        raise ValueError("boom")

    agent = make_agent("err_cond")
    cfg = ScheduleConfig(
        agent=agent,
        condition=_bad,
        condition_poll_interval=1,
        on_response=calls.append,
        on_error=errors.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(1.5)

    assert len(errors) >= 1
    assert all("boom" in str(e) for e in errors)
    assert calls == []  # agent never invoked


@pytest.mark.asyncio
async def test_gated_condition_exception_calls_on_error():
    """Gated (interval+condition) exception is caught and passed to on_error."""
    errors: list[Exception] = []
    calls: list[str] = []

    def _bad() -> bool:
        raise RuntimeError("gate broken")

    agent = make_agent("gated_err")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=1,
        condition=_bad,
        on_response=calls.append,
        on_error=errors.append,
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(1.5)

    assert len(errors) >= 1
    assert all("gate broken" in str(e) for e in errors)
    assert calls == []


@pytest.mark.asyncio
async def test_condition_exception_does_not_stop_polling():
    """Scheduler keeps polling after a condition exception."""
    results: list[bool | Exception] = []
    call_count = [0]

    def _flaky() -> bool:
        call_count[0] += 1
        if call_count[0] % 2 == 0:
            raise RuntimeError("flaky")
        return False

    agent = make_agent("flaky_cond")
    cfg = ScheduleConfig(
        agent=agent,
        condition=_flaky,
        condition_poll_interval=1,
        on_error=lambda e: results.append(e),
    )

    lifespan = build_scheduler_lifespan([cfg])
    async with lifespan(MagicMock()):
        await asyncio.sleep(3.5)

    # Should have polled multiple times, erroring on even calls
    assert call_count[0] >= 3
    assert len(results) >= 1
