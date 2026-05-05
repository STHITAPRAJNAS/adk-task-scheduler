from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.adk.agents import BaseAgent

from .config import ScheduleConfig

# Out-of-band attribute name — does not clash with Pydantic fields.
_SCHEDULE_ATTR = "__adk_schedule_config__"


def scheduled(
    *,
    cron: str | None = None,
    interval_seconds: int | None = None,
    condition: Callable[[], Any] | None = None,
    trigger_text: str = "__tick__",
    user_id: str = "adk-scheduler",
    session_service_uri: str | None = None,
    on_response: Callable[[str], Any] | None = None,
    on_error: Callable[[Exception], Any] | None = None,
    max_concurrent_runs: int = 1,
    misfire_grace_time: int = 30,
) -> Callable[[BaseAgent], BaseAgent]:
    """Decorator that attaches a :class:`ScheduleConfig` to an ADK agent.

    Usage::

        @scheduled(cron="0 * * * *")
        root_agent = Agent(name="my_agent", ...)

    The decorator is idempotent — applying it again on an already-decorated
    agent overwrites the previous schedule config.

    Because ``BaseAgent`` is a Pydantic ``BaseModel``, the config is stored via
    ``object.__setattr__`` to bypass Pydantic's field validation.
    """

    def decorator(agent: BaseAgent) -> BaseAgent:
        cfg = ScheduleConfig(
            agent=agent,
            cron=cron,
            interval_seconds=interval_seconds,
            condition=condition,
            trigger_text=trigger_text,
            user_id=user_id,
            session_service_uri=session_service_uri,
            on_response=on_response,
            on_error=on_error,
            max_concurrent_runs=max_concurrent_runs,
            misfire_grace_time=misfire_grace_time,
        )
        object.__setattr__(agent, _SCHEDULE_ATTR, cfg)
        return agent

    return decorator


def get_schedule_config(agent: BaseAgent) -> ScheduleConfig | None:
    """Return the :class:`ScheduleConfig` attached by :func:`scheduled`, or ``None``."""
    return getattr(agent, _SCHEDULE_ATTR, None)


def with_schedule(
    agent: BaseAgent,
    *,
    cron: str | None = None,
    interval_seconds: int | None = None,
    condition: Callable[[], Any] | None = None,
    trigger_text: str = "__tick__",
    user_id: str = "adk-scheduler",
    session_service_uri: str | None = None,
    on_response: Callable[[str], Any] | None = None,
    on_error: Callable[[Exception], Any] | None = None,
    max_concurrent_runs: int = 1,
    misfire_grace_time: int = 30,
) -> BaseAgent:
    """Attach a schedule to *agent* and return it.

    This is a convenience wrapper around :func:`scheduled` with a more readable
    call site when building agents inline::

        root_agent = with_schedule(
            Agent(name="my_agent", model="gemini-2.0-flash", ...),
            cron="0 * * * *",
        )

    All parameters are identical to :func:`scheduled`.
    """
    return scheduled(
        cron=cron,
        interval_seconds=interval_seconds,
        condition=condition,
        trigger_text=trigger_text,
        user_id=user_id,
        session_service_uri=session_service_uri,
        on_response=on_response,
        on_error=on_error,
        max_concurrent_runs=max_concurrent_runs,
        misfire_grace_time=misfire_grace_time,
    )(agent)
