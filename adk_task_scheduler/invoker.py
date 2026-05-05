from __future__ import annotations

import contextlib
import inspect
import logging

from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from .config import ScheduleConfig

logger = logging.getLogger(__name__)


class RunnerPool:
    """Maintains one reusable :class:`Runner` per ``app_name``.

    Runners are created lazily on first use and shared across all scheduled
    invocations. This matches the pattern used by ``get_fast_api_app`` for its
    own ``runner_dict`` — ADK's ``Runner`` is safe to reuse across invocations.

    The pool is intentionally separate from ADK's internal ``runner_dict`` so
    that ad-hoc triggers served by the FastAPI app are completely unaffected.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Runner, BaseSessionService]] = {}

    def get_or_create(self, cfg: ScheduleConfig) -> tuple[Runner, BaseSessionService]:
        key = cfg.app_name
        if key not in self._entries:
            if cfg.session_service_uri:
                from google.adk.sessions.database_session_service import (
                    DatabaseSessionService,
                )
                svc: BaseSessionService = DatabaseSessionService(
                    db_url=cfg.session_service_uri
                )
            else:
                svc = InMemorySessionService()

            runner = Runner(
                app_name=cfg.app_name,
                agent=cfg.agent,
                session_service=svc,
            )
            self._entries[key] = (runner, svc)

        return self._entries[key]

    async def close_all(self) -> None:
        for runner, _ in self._entries.values():
            with contextlib.suppress(Exception):
                await runner.close()
        self._entries.clear()


async def invoke_agent(cfg: ScheduleConfig, pool: RunnerPool) -> None:
    """Create a session, send the trigger message, and collect the response.

    A *new* session is created for every invocation so that scheduled runs
    start with clean state. Persistent history across ticks can be achieved
    by passing a fixed ``session_service_uri`` and managing session IDs in
    ``extra_state`` or the ``on_response`` callback.
    """
    runner, svc = pool.get_or_create(cfg)
    try:
        session = await svc.create_session(
            app_name=cfg.app_name,
            user_id=cfg.user_id,
            state=cfg.extra_state or {},
        )
        message = types.Content(
            role="user",
            parts=[types.Part(text=cfg.trigger_text)],
        )
        async for event in runner.run_async(
            user_id=cfg.user_id,
            session_id=session.id,
            new_message=message,
        ):
            if event.is_final_response() and cfg.on_response:
                text = _extract_text(event)
                cfg.on_response(text)
    except Exception as exc:
        logger.exception("Scheduled invocation failed for app_name=%s", cfg.app_name)
        if cfg.on_error:
            cfg.on_error(exc)


def make_apscheduler_job(cfg: ScheduleConfig, pool: RunnerPool):
    """Return an async callable for APScheduler 3.x ``AsyncIOScheduler``.

    ``AsyncIOScheduler`` detects coroutine functions and runs them via its
    ``AsyncIOExecutor``, which schedules them on the running event loop using
    ``asyncio.ensure_future`` — no explicit ``create_task`` needed.
    """

    async def _job() -> None:
        await invoke_agent(cfg, pool)

    return _job


async def evaluate_condition(cfg: ScheduleConfig) -> bool:
    """Evaluate a condition callback that may be sync or async."""
    if cfg.condition is None:
        return False
    result = cfg.condition()
    if inspect.isawaitable(result):
        result = await result
    return bool(result)


def _extract_text(event) -> str:
    """Pull plain text from the final response event, empty string if none."""
    if event.content and event.content.parts:
        return "".join(
            part.text for part in event.content.parts if hasattr(part, "text") and part.text
        )
    return ""
