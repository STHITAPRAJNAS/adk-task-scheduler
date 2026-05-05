"""FastAPI entry point for the example ADK scheduler app.

Run::

    cd example
    uvicorn main:app --reload --log-level info

Routes (from ADK):
  POST /run              — ad-hoc agent invocation (JSON)
  POST /run_sse          — streaming SSE invocation
  GET  /list-apps        — list registered agent apps
  GET/POST /a2a/...      — A2A protocol endpoints (when a2a=True)

The ticker_agent will also fire automatically every 30 seconds, logged to
stdout via the on_response callback defined in agents/ticker_agent/agent.py.
"""
import logging

from adk_task_scheduler import build_scheduled_app

logging.basicConfig(level=logging.INFO)

app = build_scheduled_app(
    agents_dir="./agents",
    auto_discover=True,   # picks up @scheduled from ticker_agent/agent.py
    web=False,
    a2a=True,
)
