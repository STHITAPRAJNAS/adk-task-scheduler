from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from .config import ConditionContext, ScheduleConfig
from .invoker import RunnerPool, evaluate_condition, invoke_agent

logger = logging.getLogger(__name__)


@dataclass
class _ConditionState:
    """Per-schedule mutable state for condition-based jobs."""

    last_value: bool = False
    last_fired_at: datetime | None = None
    fire_count: int = 0
    consecutive_false_count: int = 0
    # Initialise in the past so the first poll always runs immediately.
    next_check_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) - timedelta(seconds=1)
    )


def _should_fire(fire_mode: str, current: bool, previous: bool) -> bool:
    if fire_mode == "once_until_reset":
        return current and not previous
    return current  # "every"


def _build_condition_context(state: _ConditionState, cfg: ScheduleConfig) -> ConditionContext:
    return ConditionContext(
        last_fired_at=state.last_fired_at,
        fire_count=state.fire_count,
        extra_state=cfg.extra_state,
    )


def build_scheduler_lifespan(schedules: list[ScheduleConfig], base_dir: str = "."):
    """Build a FastAPI-compatible lifespan context manager that starts and stops
    an APScheduler ``AsyncIOScheduler`` housing all provided schedules.

    The returned lifespan is passed directly to ``get_fast_api_app(lifespan=...)``
    and composed inside ADK's own ``internal_lifespan`` — no patching required.
    Ad-hoc triggers via the ADK ``/run`` and ``/run_sse`` routes continue to
    use ADK's internal ``runner_dict`` and are completely unaffected.

    Args:
        schedules: List of :class:`~adk_task_scheduler.ScheduleConfig` instances.
        base_dir: Base directory for ADK's service factory helpers (local-file
            fallback storage).  ``build_scheduled_app`` sets this to
            ``agents_dir`` automatically.

    Returns:
        An async context manager callable suitable for ``Lifespan[FastAPI]``.
    """
    pool = RunnerPool(base_dir=base_dir)
    scheduler = AsyncIOScheduler()

    for cfg in schedules:
        _register_job(scheduler, cfg, pool)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        logger.info(
            "adk-task-scheduler: starting scheduler with %d job(s)", len(schedules)
        )
        scheduler.start()
        try:
            yield
        finally:
            logger.info("adk-task-scheduler: shutting down scheduler")
            scheduler.shutdown(wait=False)
            await pool.close_all()

    return lifespan


def _register_job(
    scheduler: AsyncIOScheduler,
    cfg: ScheduleConfig,
    pool: RunnerPool,
) -> None:
    """Register one schedule entry with the APScheduler instance."""
    job_id = cfg.app_name
    common = dict(
        id=job_id,
        max_instances=cfg.max_concurrent_runs,
        misfire_grace_time=cfg.misfire_grace_time,
        replace_existing=True,
    )

    has_schedule = cfg.cron is not None or cfg.interval_seconds is not None

    if has_schedule:
        _register_scheduled_job(scheduler, cfg, pool, common)
    else:
        _register_condition_job(scheduler, cfg, pool, common)


def _register_scheduled_job(
    scheduler: AsyncIOScheduler,
    cfg: ScheduleConfig,
    pool: RunnerPool,
    common: dict,
) -> None:
    """Register a cron or interval job, optionally gated by a condition."""
    state = _ConditionState()

    async def _job(c: ScheduleConfig = cfg, s: _ConditionState = state) -> None:
        if c.condition is not None:
            ctx = _build_condition_context(s, c)
            try:
                current = await evaluate_condition(c, ctx)
            except Exception as exc:
                logger.exception(
                    "Condition evaluation failed for app_name=%s", c.app_name
                )
                if c.on_error:
                    c.on_error(exc)
                return

            if not _should_fire(c.fire_mode, current, s.last_value):
                s.last_value = current
                return
            s.last_value = current

        now = datetime.now(timezone.utc)
        s.last_fired_at = now
        s.fire_count += 1
        await invoke_agent(c, pool)

    if cfg.cron:
        trigger = CronTrigger.from_crontab(cfg.cron)
        scheduler.add_job(_job, trigger, **common)
        logger.debug("Registered cron job '%s' with expression '%s'", job_id(cfg), cfg.cron)
    else:
        trigger = IntervalTrigger(seconds=cfg.interval_seconds)
        scheduler.add_job(_job, trigger, **common)
        logger.debug(
            "Registered interval job '%s' every %ds", job_id(cfg), cfg.interval_seconds
        )


def _register_condition_job(
    scheduler: AsyncIOScheduler,
    cfg: ScheduleConfig,
    pool: RunnerPool,
    common: dict,
) -> None:
    """Register a standalone condition-polling job with fire_mode and backoff."""
    state = _ConditionState()

    async def _job(c: ScheduleConfig = cfg, s: _ConditionState = state) -> None:
        now = datetime.now(timezone.utc)

        # Back-off: skip evaluation until the computed next_check_at.
        if now < s.next_check_at:
            return

        ctx = _build_condition_context(s, c)
        try:
            current = await evaluate_condition(c, ctx)
        except Exception as exc:
            logger.exception(
                "Condition evaluation failed for app_name=%s", c.app_name
            )
            if c.on_error:
                c.on_error(exc)
            return

        if _should_fire(c.fire_mode, current, s.last_value):
            s.last_value = current
            s.last_fired_at = now
            s.fire_count += 1
            s.consecutive_false_count = 0
            s.next_check_at = now  # reset — next normal poll fires on schedule
            await invoke_agent(c, pool)
        else:
            s.last_value = current
            if not current:
                s.consecutive_false_count += 1
                if c.condition_backoff_factor > 1.0:
                    delay = c.condition_poll_interval * (
                        c.condition_backoff_factor ** s.consecutive_false_count
                    )
                    if c.condition_max_poll_interval is not None:
                        delay = min(delay, c.condition_max_poll_interval)
                    s.next_check_at = now + timedelta(seconds=delay)
            else:
                # Truthy but once_until_reset already fired — don't backoff.
                s.consecutive_false_count = 0

    trigger = IntervalTrigger(seconds=cfg.condition_poll_interval)
    scheduler.add_job(_job, trigger, **common)
    logger.debug(
        "Registered condition-polling job '%s' every %ds (fire_mode=%s, backoff=%.1fx)",
        job_id(cfg),
        cfg.condition_poll_interval,
        cfg.fire_mode,
        cfg.condition_backoff_factor,
    )


def job_id(cfg: ScheduleConfig) -> str:
    return cfg.app_name  # type: ignore[return-value]
