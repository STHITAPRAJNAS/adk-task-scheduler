from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from google.adk.agents import BaseAgent


@dataclass
class ConditionContext:
    """Runtime context passed to condition callables that declare one parameter.

    Condition functions may either take no arguments (legacy, still supported)
    or accept a single ``ConditionContext`` argument::

        def my_condition(ctx: ConditionContext) -> bool:
            if ctx.last_fired_at is None:
                return True          # never fired — fire now
            elapsed = (datetime.now(timezone.utc) - ctx.last_fired_at).total_seconds()
            return elapsed > 3600   # fire at most once per hour

    Attributes:
        last_fired_at: UTC datetime of the most recent successful invocation,
            or ``None`` if the agent has never been invoked by this schedule.
        fire_count: Number of times the agent has been invoked by this schedule.
        extra_state: The ``extra_state`` dict from the parent :class:`ScheduleConfig`.
    """

    last_fired_at: datetime | None
    fire_count: int
    extra_state: dict[str, Any]


@dataclass
class ScheduleConfig:
    """Describes when and how to auto-invoke an ADK agent.

    At least one of ``cron``, ``interval_seconds``, or ``condition`` must be set.
    ``cron`` and ``interval_seconds`` are mutually exclusive.  ``condition`` may
    be combined with ``cron`` or ``interval_seconds`` to act as a gate: the
    schedule determines *when* to check, the condition determines *whether* to fire.

    Args:
        agent: The ADK agent to invoke on schedule.
        app_name: A2A app name passed to the internal :class:`Runner`.
            Defaults to ``agent.name``.
        cron: Standard 5-field crontab expression, e.g. ``"0 9 * * 1-5"``.
        interval_seconds: Fixed interval in seconds.  Must be a positive integer.
        condition: Zero- or one-argument callable (sync or async).  When used
            alone it is polled every ``condition_poll_interval`` seconds and the
            agent fires on truthy results.  When combined with ``cron`` or
            ``interval_seconds`` it gates each tick — the agent only fires if the
            condition returns truthy on that tick.
            One-argument form receives a :class:`ConditionContext`.
        condition_poll_interval: How often (in seconds) to evaluate ``condition``
            when used standalone (without ``cron`` / ``interval_seconds``).
            Defaults to ``60``.
        fire_mode: Controls firing behaviour for standalone condition polling.

            * ``"every"`` *(default)* — fire on every truthy evaluation.
            * ``"once_until_reset"`` — fire only on the False→True transition;
              suppresses repeated fires while the condition stays truthy.

        condition_backoff_factor: Exponential back-off multiplier applied to
            ``condition_poll_interval`` after each consecutive falsy evaluation.
            ``1.0`` (default) disables back-off.  ``2.0`` doubles the wait after
            each false result.  Ignored unless ``condition`` is used standalone.
        condition_max_poll_interval: Upper bound (seconds) on the back-off delay.
            ``None`` (default) means no cap.
        trigger_text: Synthetic user message sent to the agent on each tick.
            The agent's instruction should distinguish this from real user input
            (e.g. ``"When the message is '__tick__' run the scheduled routine"``).
        user_id: User identity used for the scheduled session.
        session_service_uri: URI for the session backend, forwarded to ADK's
            ``create_session_service_from_options``.  Supports SQLAlchemy URIs
            (``sqlite:///./scheduler.db``, ``postgresql://…``), ``agentengine://``
            for Vertex AI, or ``memory://`` for in-memory.  When unset the
            scheduler uses the same default logic as ``get_fast_api_app``.
        session_db_kwargs: Extra keyword arguments passed to the session service
            constructor (e.g. pool settings for PostgreSQL).
        artifact_service_uri: URI for the artifact backend, forwarded to ADK's
            ``create_artifact_service_from_options``.  Supports ``gs://`` for
            GCS.  When unset defaults to local-file or in-memory storage.
        memory_service_uri: URI for the memory backend, forwarded to ADK's
            ``create_memory_service_from_options``.  Supports ``rag://`` for
            Vertex AI RAG or ``agentengine://`` for Memory Bank.  When unset
            defaults to in-memory.
        on_response: Optional callback invoked with the agent's final text after
            each scheduled invocation.
        on_error: Optional callback invoked with any exception raised during a
            scheduled invocation or condition evaluation.  If not set, errors
            are only logged.
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
    fire_mode: Literal["every", "once_until_reset"] = "every"
    condition_backoff_factor: float = 1.0
    condition_max_poll_interval: int | None = None
    trigger_text: str = "__tick__"
    user_id: str = "adk-scheduler"
    session_service_uri: str | None = None
    session_db_kwargs: dict[str, Any] | None = None
    artifact_service_uri: str | None = None
    memory_service_uri: str | None = None
    on_response: Callable[[str], Any] | None = None
    on_error: Callable[[Exception], Any] | None = None
    max_concurrent_runs: int = 1
    misfire_grace_time: int = 30
    extra_state: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        has_schedule = self.cron is not None or self.interval_seconds is not None
        has_condition = self.condition is not None
        if not has_schedule and not has_condition:
            raise ValueError(
                "ScheduleConfig requires at least one of: cron, interval_seconds, condition"
            )
        if self.cron is not None and self.interval_seconds is not None:
            raise ValueError("cron and interval_seconds are mutually exclusive")
        if self.interval_seconds is not None and self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be a positive integer")
        if self.condition_poll_interval <= 0:
            raise ValueError("condition_poll_interval must be a positive integer")
        if self.condition_backoff_factor < 1.0:
            raise ValueError("condition_backoff_factor must be >= 1.0")
        if self.condition_max_poll_interval is not None and self.condition_max_poll_interval <= 0:
            raise ValueError("condition_max_poll_interval must be a positive integer")
        if self.app_name is None:
            self.app_name = self.agent.name
