from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import BaseAgent


@dataclass
class ScheduleConfig:
    """Describes when and how to auto-invoke an ADK agent.

    Exactly one of ``cron``, ``interval_seconds``, or ``condition`` must be set.

    Args:
        agent: The ADK agent to invoke on schedule.
        app_name: A2A app name passed to the internal :class:`Runner`.
            Defaults to ``agent.name``.
        cron: Standard 5-field crontab expression, e.g. ``"0 9 * * 1-5"``.
        interval_seconds: Fixed interval in seconds.  Must be a positive integer.
        condition: Zero-argument callable (sync or async) polled every
            ``condition_poll_interval`` seconds.  The agent fires whenever it
            returns a truthy value.
        condition_poll_interval: How often (in seconds) to evaluate ``condition``.
            Defaults to ``60``.  Ignored unless ``condition`` is set.
        trigger_text: Synthetic user message sent to the agent on each tick.
            The agent's instruction should distinguish this from real user input
            (e.g. ``"When the message is '__tick__' run the scheduled routine"``).
        user_id: User identity used for the scheduled session.
        session_service_uri: SQLAlchemy URI for a persistent session store,
            e.g. ``"sqlite:///./scheduler.db"`` or
            ``"postgresql://user:pw@host/db"``.
            Defaults to an in-memory store (state lost on restart).
        on_response: Optional callback invoked with the agent's final text after
            each scheduled invocation.
        on_error: Optional callback invoked with any exception raised during a
            scheduled invocation.  If not set, errors are only logged.
        max_concurrent_runs: Maximum number of overlapping invocations allowed
            for this schedule.  APScheduler drops additional firings beyond this
            limit rather than queuing them.
        misfire_grace_time: Seconds APScheduler will still run a job that missed
            its scheduled time (e.g. because the process was paused).
        extra_state: Key/value pairs merged into the session state on creation.
            Useful for injecting context (e.g. environment name, agent config).
    """

    agent: BaseAgent
    app_name: str | None = None
    cron: str | None = None
    interval_seconds: int | None = None
    condition: Callable[[], Any] | None = None
    condition_poll_interval: int = 60
    trigger_text: str = "__tick__"
    user_id: str = "adk-scheduler"
    session_service_uri: str | None = None
    on_response: Callable[[str], Any] | None = None
    on_error: Callable[[Exception], Any] | None = None
    max_concurrent_runs: int = 1
    misfire_grace_time: int = 30
    extra_state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Use explicit None checks so that interval_seconds=0 is caught correctly
        # and not silently treated as "not set" (any([0]) is falsy).
        has_trigger = (
            self.cron is not None
            or self.interval_seconds is not None
            or self.condition is not None
        )
        if not has_trigger:
            raise ValueError(
                "ScheduleConfig requires exactly one of: cron, interval_seconds, condition"
            )
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be a positive integer")
        if self.condition_poll_interval <= 0:
            raise ValueError("condition_poll_interval must be a positive integer")
        if self.app_name is None:
            self.app_name = self.agent.name
