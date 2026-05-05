from __future__ import annotations

import importlib
import logging
import pathlib
import sys
from typing import Any

from fastapi import FastAPI
from google.adk.cli.fast_api import get_fast_api_app

from .config import ScheduleConfig
from .decorator import get_schedule_config
from .lifespan import build_scheduler_lifespan

logger = logging.getLogger(__name__)


def build_scheduled_app(
    *,
    agents_dir: str,
    schedules: list[ScheduleConfig] | None = None,
    auto_discover: bool = True,
    web: bool = False,
    **fastapi_kwargs: Any,
) -> FastAPI:
    """Drop-in replacement for ``get_fast_api_app`` that adds auto-scheduling.

    Internally this function:

    1. Collects all :class:`~adk_task_scheduler.ScheduleConfig` objects from
       the explicit ``schedules`` list and (optionally) from any ``root_agent``
       decorated with :func:`~adk_task_scheduler.scheduled` found under
       ``agents_dir``.
    2. Builds a lifespan context manager that starts an
       ``AsyncIOScheduler`` on FastAPI startup and shuts it down cleanly.
    3. Passes that lifespan to ``get_fast_api_app`` via its ``lifespan=``
       parameter — **no monkey-patching required**.

    All keyword arguments beyond ``schedules`` and ``auto_discover`` are
    forwarded verbatim to ``get_fast_api_app``, so the full ADK feature set
    (A2A endpoints, ``/run``, ``/run_sse``, session services, etc.) is
    preserved unmodified.

    Ad-hoc triggers via the ADK chat UI or ``POST /run`` continue to use
    ADK's internal ``runner_dict`` and are completely unaffected by the
    scheduler's separate ``RunnerPool``.

    Args:
        agents_dir: Path to the ADK agents directory (same as ``get_fast_api_app``).
        schedules: Explicit list of :class:`~adk_task_scheduler.ScheduleConfig`.
        auto_discover: If ``True``, scan ``agents_dir`` for ``root_agent``
            objects decorated with :func:`~adk_task_scheduler.scheduled` and
            add them automatically.
        web: Passed to ``get_fast_api_app``.
        **fastapi_kwargs: Any remaining kwargs forwarded to ``get_fast_api_app``.

    Returns:
        A :class:`fastapi.FastAPI` instance with the scheduler baked in.
    """
    all_schedules: list[ScheduleConfig] = list(schedules or [])

    if auto_discover:
        discovered = _discover_schedules(agents_dir)
        logger.info(
            "adk-task-scheduler: auto-discovered %d schedule(s) under '%s'",
            len(discovered),
            agents_dir,
        )
        all_schedules.extend(discovered)

    # Propagate service URIs from fastapi_kwargs into any schedule that hasn't
    # set them explicitly — users configure once in build_scheduled_app, not
    # on every individual ScheduleConfig.
    _propagate_service_uris(all_schedules, fastapi_kwargs)

    lifespan = (
        build_scheduler_lifespan(all_schedules, base_dir=agents_dir)
        if all_schedules
        else None
    )

    if not all_schedules:
        logger.warning(
            "adk-task-scheduler: no schedules found; returning plain get_fast_api_app"
        )

    return get_fast_api_app(
        agents_dir=agents_dir,
        web=web,
        lifespan=lifespan,
        **fastapi_kwargs,
    )


def _discover_schedules(agents_dir: str) -> list[ScheduleConfig]:
    """Scan *agents_dir* for ADK agent packages that carry a schedule config.

    Each sub-directory that contains an ``agent.py`` with a ``root_agent``
    module-level variable is inspected. If that variable has a
    :class:`~adk_task_scheduler.config.ScheduleConfig` attached (via the
    :func:`~adk_task_scheduler.decorator.scheduled` decorator), it is included.
    """
    configs: list[ScheduleConfig] = []
    base = pathlib.Path(agents_dir).resolve()

    if str(base) not in sys.path:
        sys.path.insert(0, str(base))

    for agent_dir in sorted(base.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_module_path = agent_dir / "agent.py"
        if not agent_module_path.exists():
            continue

        module_name = f"{agent_dir.name}.agent"
        try:
            mod = importlib.import_module(module_name)
        except Exception as exc:
            logger.warning(
                "adk-task-scheduler: failed to import '%s': %s", module_name, exc
            )
            continue

        agent = getattr(mod, "root_agent", None)
        if agent is None:
            continue

        cfg = get_schedule_config(agent)
        if cfg is not None:
            logger.debug(
                "adk-task-scheduler: found schedule on agent '%s'", agent.name
            )
            configs.append(cfg)

    return configs


_SERVICE_URI_FIELDS = (
    "session_service_uri",
    "session_db_kwargs",
    "artifact_service_uri",
    "memory_service_uri",
)


def _propagate_service_uris(
    schedules: list[ScheduleConfig],
    fastapi_kwargs: dict[str, Any],
) -> None:
    """Copy service URI kwargs into any ScheduleConfig that hasn't set them.

    Allows callers to configure once at ``build_scheduled_app`` level rather
    than repeating the same URIs on every individual ``ScheduleConfig``.
    Only fields that are ``None`` on the config are overwritten.
    """
    overrides = {k: fastapi_kwargs[k] for k in _SERVICE_URI_FIELDS if k in fastapi_kwargs}
    if not overrides:
        return
    for cfg in schedules:
        for field_name, value in overrides.items():
            if getattr(cfg, field_name) is None:
                object.__setattr__(cfg, field_name, value)
