"""Example ADK agent that self-wakes every 30 seconds.

Deploy with::

    cd example
    uvicorn main:app --reload

The agent will:
  - Respond to ad-hoc ``POST /run`` calls (standard ADK behaviour).
  - Auto-invoke itself every 30 seconds and print the response to stdout.
"""
import logging

from google.adk.agents import Agent

from adk_task_scheduler import scheduled

logger = logging.getLogger(__name__)


def _log_response(text: str) -> None:
    logger.info("[ticker_agent scheduled response] %s", text)


# scheduled() is called as a regular function wrapping the agent instance.
# Python @-decorator syntax only applies to def/class statements.
root_agent = scheduled(
    interval_seconds=30,
    trigger_text="__tick__",
    on_response=_log_response,
)(
    Agent(
        name="ticker_agent",
        model="gemini-2.0-flash",
        instruction="""
    You are a periodic ticker agent.

    When the user message is '__tick__' you are being called by the scheduler.
    Respond with a brief status message: current UTC time and the words "all systems nominal".

    For any other message, respond normally as a helpful assistant.
    """,
    )
)
