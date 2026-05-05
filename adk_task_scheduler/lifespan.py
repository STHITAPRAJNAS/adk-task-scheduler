from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from .config import ScheduleConfig
from .invoker import RunnerPool, evaluate_condition, invoke_agent, make_apscheduler_job

logger = logging.getLogger(__name__)


def build_scheduler_lifespan(schedules: list[ScheduleConfig]):
    """Build a FastAPI-compatible lifespan context manager that starts and stops
    an APScheduler ``AsyncIOScheduler`` housing all provided schedules.

    The returned lifespan is passed directly to ``get_fast_api_app(lifespan=...)``
    and composed inside ADK's own ``internal_lifespan`` — no patching required.
    Ad-hoc triggers via the ADK ``/run`` and ``/run_sse`` routes continue to
    use ADK's internal ``runner_dict`` and are completely unaffected.

    Args:
        schedules: List of :class:`~adk_task_scheduler.ScheduleConfig` instances.

    Returns:
        An async context manager callable suitable for ``Lifespan[FastAPI]``.
    """
    pool = RunnerPool()
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

    if cfg.cron:
        trigger = CronTrigger.from_crontab(cfg.cron)
        scheduler.add_job(make_apscheduler_job(cfg, pool), trigger, **common)
        logger.debug("Registered cron job '%s' with expression '%s'", job_id, cfg.cron)

    elif cfg.interval_seconds:
        trigger = IntervalTrigger(seconds=cfg.interval_seconds)
        scheduler.add_job(make_apscheduler_job(cfg, pool), trigger, **common)
        logger.debug(
            "Registered interval job '%s' every %ds", job_id, cfg.interval_seconds
        )

    elif cfg.condition:
        # Condition-based: poll on cfg.condition_poll_interval and fire when truthy.
        # Async function passed directly — AsyncIOScheduler runs it via AsyncIOExecutor.
        async def _condition_job(c: ScheduleConfig = cfg) -> None:
            if await evaluate_condition(c):
                await invoke_agent(c, pool)

        trigger = IntervalTrigger(seconds=cfg.condition_poll_interval)
        scheduler.add_job(_condition_job, trigger, **common)
        logger.debug(
            "Registered condition-polling job '%s' every %ds",
            job_id,
            cfg.condition_poll_interval,
        )
