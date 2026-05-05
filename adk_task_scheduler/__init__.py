"""adk-task-scheduler — auto-scheduling for Google ADK agents.

Quick start::

    from adk_task_scheduler import scheduled, build_scheduled_app

    @scheduled(cron="0 * * * *")
    root_agent = Agent(name="my_agent", model="gemini-2.5-flash", ...)

    app = build_scheduled_app(agents_dir="./agents", web=False, a2a=True)
    # uvicorn main:app
"""

from .app import build_scheduled_app
from .config import ScheduleConfig
from .decorator import get_schedule_config, scheduled, with_schedule

__all__ = [
    "scheduled",
    "with_schedule",
    "get_schedule_config",
    "ScheduleConfig",
    "build_scheduled_app",
]
