from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import BaseAgent


@dataclass
class ScheduleConfig:
    """Describes when and how to auto-invoke an ADK agent.

    Exactly one of ``cron``, ``interval_seconds``, or ``condition`` is required.

    Args:
        agent: The ADK agent to invoke on schedule.
        app_name: A2A app name. Defaults to ``agent.name``.
        cron: Standard 5-field crontab expression (e.g. ``"0 * * * *"``).
        interval_seconds: Fixed interval in seconds.
        condition: Zero-arg callable (sync or async) polled every 60 s.
            The agent fires whenever it returns a truthy value.
        trigger_text: Synthetic user message sent to the agent on each tick.
        user_id: User identity to use for the scheduled session.
        session_service_uri: SQLAlchemy URI for persistent sessions
            (e.g. ``"sqlite:///./scheduler.db"``). Defaults to in-memory.
        on_response: Optional callback invoked with the agent's final text.
        on_error: Optional callback invoked with any exception during invocation.
        max_concurrent_runs: Maximum overlapping invocations for this schedule.
        misfire_grace_time: Seconds APScheduler will still fire a misfired job.
        extra_state: Key/value pairs merged into the session state on creation.
    """

    agent: BaseAgent
    app_name: str | None = None
    cron: str | None = None
    interval_seconds: int | None = None
    condition: Callable[[], Any] | None = None
    trigger_text: str = "__tick__"
    user_id: str = "adk-scheduler"
    session_service_uri: str | None = None
    on_response: Callable[[str], Any] | None = None
    on_error: Callable[[Exception], Any] | None = None
    max_concurrent_runs: int = 1
    misfire_grace_time: int = 30
    extra_state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not any([self.cron, self.interval_seconds, self.condition]):
            raise ValueError(
                "ScheduleConfig requires exactly one of: cron, interval_seconds, condition"
            )
        if self.app_name is None:
            self.app_name = self.agent.name
