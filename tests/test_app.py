"""Tests for build_scheduled_app and auto-discovery."""
from __future__ import annotations

import textwrap

from fastapi import FastAPI

from adk_task_scheduler.app import _discover_schedules, build_scheduled_app
from adk_task_scheduler.config import ScheduleConfig
from tests.conftest import EchoAgent


def make_agent(name: str) -> EchoAgent:
    return EchoAgent(name=name, description="test")


# ---------------------------------------------------------------------------
# build_scheduled_app returns a FastAPI instance
# ---------------------------------------------------------------------------

def test_build_scheduled_app_returns_fastapi(tmp_path):
    """build_scheduled_app returns a FastAPI app without errors."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    agent = make_agent("no_schedule")
    cfg = ScheduleConfig(agent=agent, interval_seconds=3600)

    app = build_scheduled_app(
        agents_dir=str(agents_dir),
        schedules=[cfg],
        auto_discover=False,
        web=False,
    )
    assert isinstance(app, FastAPI)


def test_build_scheduled_app_no_schedules_returns_fastapi(tmp_path):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    app = build_scheduled_app(
        agents_dir=str(agents_dir),
        schedules=[],
        auto_discover=False,
        web=False,
    )
    assert isinstance(app, FastAPI)


# ---------------------------------------------------------------------------
# Auto-discovery
# ---------------------------------------------------------------------------

def test_discover_schedules_finds_decorated_agent(tmp_path):
    """_discover_schedules picks up a root_agent with a schedule config attached."""
    pkg = tmp_path / "my_scheduled_agent"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    # scheduled() is called as a regular function (not @-syntax, which only
    # works on def/class statements).  The agent is wrapped in-place.
    (pkg / "agent.py").write_text(
        textwrap.dedent("""\
            from google.adk.agents import BaseAgent
            from google.adk.agents.invocation_context import InvocationContext
            from google.adk.events.event import Event
            from google.genai import types
            from adk_task_scheduler import scheduled
            from adk_task_scheduler.decorator import get_schedule_config

            class _Echo(BaseAgent):
                async def _run_async_impl(self, ctx):
                    yield Event(
                        invocation_id=ctx.invocation_id,
                        author=self.name,
                        content=types.Content(role="model", parts=[types.Part(text="hi")]),
                    )

            root_agent = scheduled(interval_seconds=60)(
                _Echo(name="discovered_agent", description="d")
            )
        """)
    )

    configs = _discover_schedules(str(tmp_path))
    assert len(configs) == 1
    assert configs[0].agent.name == "discovered_agent"


def test_discover_schedules_skips_undecorated_agent(tmp_path):
    pkg = tmp_path / "plain_agent"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "agent.py").write_text(
        textwrap.dedent("""\
            from google.adk.agents import BaseAgent
            from google.adk.agents.invocation_context import InvocationContext
            from google.adk.events.event import Event
            from google.genai import types

            class _Echo(BaseAgent):
                async def _run_async_impl(self, ctx):
                    yield Event(
                        invocation_id=ctx.invocation_id,
                        author=self.name,
                        content=types.Content(role="model", parts=[types.Part(text="hi")]),
                    )

            root_agent = _Echo(name="plain_agent", description="plain")
        """)
    )

    configs = _discover_schedules(str(tmp_path))
    assert configs == []


def test_discover_schedules_skips_missing_root_agent(tmp_path):
    pkg = tmp_path / "no_agent"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "agent.py").write_text("x = 1\n")

    configs = _discover_schedules(str(tmp_path))
    assert configs == []


def test_discover_schedules_handles_import_error_gracefully(tmp_path):
    pkg = tmp_path / "broken_agent"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "agent.py").write_text("raise RuntimeError('intentional failure')\n")

    # Should not raise — just skip the broken package
    configs = _discover_schedules(str(tmp_path))
    assert configs == []


# ---------------------------------------------------------------------------
# FastAPI routes not broken by scheduler
# ---------------------------------------------------------------------------

def test_list_apps_route_exists(tmp_path):
    """ADK's /list-apps route is still present after build_scheduled_app."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    agent = make_agent("route_test")
    cfg = ScheduleConfig(agent=agent, interval_seconds=3600)

    app = build_scheduled_app(
        agents_dir=str(agents_dir),
        schedules=[cfg],
        auto_discover=False,
        web=False,
    )

    # Verify /list-apps exists in the router table
    routes = [r.path for r in app.routes]
    assert "/list-apps" in routes


# ---------------------------------------------------------------------------
# Service URI propagation
# ---------------------------------------------------------------------------

def test_propagate_service_uris_fills_none_fields(tmp_path):
    """build_scheduled_app propagates service URIs into configs that lack them."""
    from adk_task_scheduler.app import _propagate_service_uris

    agent = make_agent("prop_test")
    cfg = ScheduleConfig(agent=agent, interval_seconds=10)
    assert cfg.session_service_uri is None
    assert cfg.artifact_service_uri is None

    kwargs = {
        "session_service_uri": "sqlite:///./sched.db",
        "artifact_service_uri": "gs://bucket/artifacts",
        "memory_service_uri": "memory://",
        "session_db_kwargs": {"pool_size": 2},
    }
    _propagate_service_uris([cfg], kwargs)

    assert cfg.session_service_uri == "sqlite:///./sched.db"
    assert cfg.artifact_service_uri == "gs://bucket/artifacts"
    assert cfg.memory_service_uri == "memory://"
    assert cfg.session_db_kwargs == {"pool_size": 2}


def test_propagate_service_uris_does_not_overwrite_explicit(tmp_path):
    """Configs with explicit URIs are not overwritten."""
    from adk_task_scheduler.app import _propagate_service_uris

    agent = make_agent("explicit_uri")
    cfg = ScheduleConfig(
        agent=agent,
        interval_seconds=10,
        session_service_uri="sqlite:///./custom.db",
    )

    _propagate_service_uris([cfg], {"session_service_uri": "sqlite:///./global.db"})

    assert cfg.session_service_uri == "sqlite:///./custom.db"
