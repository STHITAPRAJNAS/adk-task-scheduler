"""adk-task-scheduler — auto-scheduling for Google ADK agents.

Quick start::

    from google.adk.agents import Agent
    from adk_task_scheduler import with_schedule, build_scheduled_app

    root_agent = with_schedule(
        Agent(name="my_agent", model="gemini-2.0-flash", instruction="..."),
        cron="0 * * * *",
    )

    app = build_scheduled_app(agents_dir="./agents", web=False, a2a=True)
    # uvicorn main:app
"""

__version__ = "0.2.0"

from .app import build_scheduled_app
from .config import ConditionContext, ScheduleConfig
from .decorator import get_schedule_config, scheduled, with_schedule

__all__ = [
    "__version__",
    "ConditionContext",
    "ScheduleConfig",
    "build_scheduled_app",
    "get_schedule_config",
    "scheduled",
    "with_schedule",
]
