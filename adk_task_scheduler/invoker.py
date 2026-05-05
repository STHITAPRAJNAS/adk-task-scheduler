from __future__ import annotations

import contextlib
import inspect
import logging

from google.adk.runners import Runner
from google.adk.sessions.base_session_service import BaseSessionService
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

    Args:
        base_dir: Base directory passed to ADK's service factory helpers
            (used for local-file fallback storage).  Defaults to ``"."``.
    """

    def __init__(self, base_dir: str = ".") -> None:
        self._base_dir = base_dir
        self._entries: dict[str, tuple[Runner, BaseSessionService]] = {}

    def get_or_create(self, cfg: ScheduleConfig) -> tuple[Runner, BaseSessionService]:
        key = cfg.app_name
        if key not in self._entries:
            from google.adk.auth.credential_service.in_memory_credential_service import (
                InMemoryCredentialService,
            )
            from google.adk.cli.fast_api import (
                create_artifact_service_from_options,
                create_memory_service_from_options,
                create_session_service_from_options,
            )

            svc = create_session_service_from_options(
                base_dir=self._base_dir,
                session_service_uri=cfg.session_service_uri,
                session_db_kwargs=cfg.session_db_kwargs,
            )
            artifact_service = create_artifact_service_from_options(
                base_dir=self._base_dir,
                artifact_service_uri=cfg.artifact_service_uri,
            )
            memory_service = create_memory_service_from_options(
                base_dir=self._base_dir,
                memory_service_uri=cfg.memory_service_uri,
            )

            runner = Runner(
                app_name=cfg.app_name,
                agent=cfg.agent,
                session_service=svc,
                artifact_service=artifact_service,
                memory_service=memory_service,
                credential_service=InMemoryCredentialService(),
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
        # part.text is a field on the Pydantic model so hasattr is always True;
        # check for None/empty explicitly.
        return "".join(part.text for part in event.content.parts if part.text)
    return ""
