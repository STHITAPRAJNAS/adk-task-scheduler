# adk-task-scheduler

[![PyPI version](https://img.shields.io/pypi/v/adk-task-scheduler.svg)](https://pypi.org/project/adk-task-scheduler/)
[![Python](https://img.shields.io/pypi/pyversions/adk-task-scheduler.svg)](https://pypi.org/project/adk-task-scheduler/)
[![CI](https://github.com/STHITAPRAJNAS/adk-task-scheduler/actions/workflows/ci.yml/badge.svg)](https://github.com/STHITAPRAJNAS/adk-task-scheduler/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Auto-scheduling for [Google ADK](https://google.github.io/adk-docs/) agents.  
Bake **cron**, **interval**, or **condition-based** triggers directly into your agent definitions so they self-wake — no separate orchestrator, no cloud scheduler, no code changes to ADK.

---

## Why

ADK agents are purely invocation-driven. Out of the box an agent only runs when a user or external system sends a message. `adk-task-scheduler` adds a **self-wake** capability that coexists with the standard ad-hoc `POST /run` interface:

```
Without this library                  With this library
─────────────────────────────         ──────────────────────────────────────────
User/system → POST /run → agent       User/system → POST /run → agent (unchanged)
                                      APScheduler tick → agent (new)
```

---

## How it works

`get_fast_api_app` (the ADK function that powers `adk api_server`) accepts a `lifespan=` parameter. This library builds an [APScheduler](https://apscheduler.readthedocs.io/) `AsyncIOScheduler` lifespan and passes it in — **no monkey-patching, no ADK fork required**. ADK's own `runner_dict` handles all ad-hoc calls; the scheduler maintains a separate `RunnerPool` so the two paths never interfere.

```
┌──────────────────────────────────────────────────────────────┐
│  FastAPI app  (returned by build_scheduled_app)              │
│                                                              │
│  ┌─────────────────────────┐  ┌──────────────────────────┐  │
│  │  ADK runner_dict        │  │  Scheduler RunnerPool    │  │
│  │  POST /run              │  │  cron / interval /       │  │
│  │  POST /run_sse          │  │  condition triggers      │  │
│  │  WebSocket /run_live    │  │                          │  │
│  │  GET/POST /a2a/...      │  │  Separate Runner per     │  │
│  └─────────────────────────┘  │  app_name — no overlap   │  │
│                                └──────────────────────────┘  │
│        ADK lifespan ── scheduler lifespan (composed)         │
└──────────────────────────────────────────────────────────────┘
```

---

## Installation

```bash
pip install adk-task-scheduler
```

**Requirements:** Python ≥ 3.10, `google-adk ≥ 1.7.0`

---

## Quick start

### 1. Attach a schedule to `root_agent`

> **Note:** Python's `@decorator` syntax only applies to `def`/`class` statements,
> not variable assignments. Use `with_schedule()` (the recommended API) or the
> `scheduled()(agent)` call form.

```python
# agents/ticker_agent/agent.py
from google.adk.agents import Agent
from adk_task_scheduler import with_schedule

root_agent = with_schedule(
    Agent(
        name="ticker_agent",
        model="gemini-2.0-flash",
        instruction="""
        You are a periodic monitoring agent.

        When the user message is exactly '__tick__', you are being invoked by
        the scheduler (not a real user). Run your monitoring routine and report
        status. Do NOT ask clarifying questions.

        For any other message, respond normally as a helpful assistant.
        """,
    ),
    interval_seconds=60,
    trigger_text="__tick__",
    on_response=lambda text: print(f"[monitor] {text}"),
)
```

### 2. Build the app

```python
# main.py
from adk_task_scheduler import build_scheduled_app

app = build_scheduled_app(
    agents_dir="./agents",
    auto_discover=True,   # picks up with_schedule() agents automatically
    web=False,
    a2a=True,
)
```

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The agent now:
- Responds to ad-hoc `POST /run` calls (standard ADK — unchanged).
- Self-wakes every 60 seconds and logs its response.

---

## Examples

### Cron-triggered daily briefing agent

```python
# agents/briefing_agent/agent.py
import logging
from google.adk.agents import Agent
from adk_task_scheduler import with_schedule

logger = logging.getLogger(__name__)

root_agent = with_schedule(
    Agent(
        name="briefing_agent",
        model="gemini-2.0-flash",
        instruction="""
        You are a morning briefing assistant.

        When the user message is '__morning__', produce a concise daily briefing:
        - Key tasks for the day (you may fabricate plausible examples)
        - Weather summary for London
        - One motivational note

        For other messages, respond normally.
        """,
    ),
    cron="0 8 * * 1-5",          # 08:00 every weekday
    trigger_text="__morning__",
    user_id="briefing-system",
    session_service_uri="sqlite:///./briefing.db",   # persist sessions
    on_response=lambda text: logger.info("Daily briefing:\n%s", text),
    on_error=lambda exc: logger.error("Briefing failed: %s", exc),
)
```

---

### Condition-triggered market monitor

```python
# agents/market_monitor/agent.py
import logging
from datetime import datetime, timezone
from google.adk.agents import Agent
from adk_task_scheduler import with_schedule

logger = logging.getLogger(__name__)


def is_market_open() -> bool:
    """True during NYSE trading hours Mon-Fri 14:30-21:00 UTC."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:          # weekend
        return False
    return 14 <= now.hour < 21


root_agent = with_schedule(
    Agent(
        name="market_monitor",
        model="gemini-2.0-flash",
        instruction="""
        You are a market monitoring agent.

        When the user message is '__market_check__', analyse current market
        conditions (simulate with plausible data) and flag any anomalies.
        Keep the response under 3 bullet points.

        For other messages respond normally.
        """,
    ),
    condition=is_market_open,          # evaluated every 5 minutes
    condition_poll_interval=300,
    trigger_text="__market_check__",
    max_concurrent_runs=1,             # never overlap
    on_response=lambda text: logger.info("[market] %s", text),
)
```

---

### Multi-agent: mix scheduled and ad-hoc in one app

```
agents/
├── briefing_agent/
│   ├── __init__.py
│   └── agent.py        ← with_schedule(cron="0 8 * * 1-5")
├── market_monitor/
│   ├── __init__.py
│   └── agent.py        ← with_schedule(condition=is_market_open)
└── assistant/
    ├── __init__.py
    └── agent.py        ← plain Agent, no schedule (ad-hoc only)
```

```python
# main.py
from adk_task_scheduler import build_scheduled_app

app = build_scheduled_app(
    agents_dir="./agents",
    auto_discover=True,          # discovers all three agents
    web=False,
    a2a=True,
    session_service_uri="sqlite:///./sessions.db",
)
```

`auto_discover=True` (default) scans `agents_dir` for any `root_agent` that
carries a schedule config. Agents without a schedule are registered in ADK's
router as usual and remain fully available for ad-hoc calls.

---

### Explicit `ScheduleConfig` (wiring outside `agent.py`)

Useful when the schedule is environment-specific (e.g. different cron for
staging vs. production) and you don't want it hard-coded in the agent file:

```python
# main.py
import os
from adk_task_scheduler import ScheduleConfig, build_scheduled_app
from agents.reporter.agent import root_agent   # plain Agent, no schedule

cfg = ScheduleConfig(
    agent=root_agent,
    cron=os.environ["REPORT_CRON"],            # e.g. "0 6 * * *"
    trigger_text="__generate_report__",
    user_id="report-system",
    session_service_uri=os.environ["DB_URI"],
    on_response=lambda text: publish_to_slack(text),
    on_error=lambda exc: alert_oncall(exc),
    max_concurrent_runs=1,
    misfire_grace_time=120,
)

app = build_scheduled_app(
    agents_dir="./agents",
    schedules=[cfg],
    auto_discover=False,   # opt out of scanning when configs are explicit
    web=False,
    a2a=True,
)
```

---

## Trigger types

| Parameter | Type | Description |
|---|---|---|
| `cron="0 8 * * 1-5"` | `str` | Standard 5-field crontab (APScheduler `CronTrigger`). |
| `interval_seconds=300` | `int` | Fixed interval. Must be ≥ 1. |
| `condition=fn` | `Callable[[], Any]` | Polled every `condition_poll_interval` seconds (default 60). Agent fires when `fn()` is truthy. Supports both sync and `async` callables. |

---

## API reference

### `with_schedule(agent, *, ...)` ← recommended

```python
from adk_task_scheduler import with_schedule

root_agent = with_schedule(
    Agent(name="my_agent", ...),
    cron="0 * * * *",
    trigger_text="__tick__",
    session_service_uri="sqlite:///./sessions.db",
    on_response=lambda text: print(text),
    on_error=lambda exc: print(f"Error: {exc}"),
)
```

| Parameter | Type | Default | Description |
|---|---|---|---|
| `cron` | `str` | — | Crontab expression |
| `interval_seconds` | `int` | — | Seconds between runs (≥ 1) |
| `condition` | `Callable[[], Any]` | — | Condition function |
| `condition_poll_interval` | `int` | `60` | How often (s) to evaluate `condition` |
| `trigger_text` | `str` | `"__tick__"` | Synthetic user message |
| `user_id` | `str` | `"adk-scheduler"` | Session user identity |
| `session_service_uri` | `str` | — | SQLAlchemy URI; defaults to in-memory |
| `on_response` | `Callable[[str], Any]` | — | Called with the agent's final text |
| `on_error` | `Callable[[Exception], Any]` | — | Called on invocation failure |
| `max_concurrent_runs` | `int` | `1` | Max overlapping invocations |
| `misfire_grace_time` | `int` | `30` | APScheduler misfire grace (seconds) |

### `scheduled(**kwargs)` → `Callable[[BaseAgent], BaseAgent]`

Equivalent to `with_schedule` but curried:

```python
from adk_task_scheduler import scheduled

root_agent = scheduled(interval_seconds=30)(Agent(...))
```

All parameters identical to `with_schedule`.

### `build_scheduled_app(*, agents_dir, ...)` → `FastAPI`

Drop-in for `get_fast_api_app`. All `get_fast_api_app` keyword arguments
(`a2a`, `session_service_uri`, `allow_origins`, `trace_to_cloud`, etc.) are
forwarded verbatim.

| Extra parameter | Type | Default | Description |
|---|---|---|---|
| `schedules` | `list[ScheduleConfig]` | `[]` | Explicit schedule configs |
| `auto_discover` | `bool` | `True` | Scan `agents_dir` for scheduled agents |
| `web` | `bool` | `False` | Passed to `get_fast_api_app` |

### `ScheduleConfig`

Dataclass holding all scheduling metadata. Construct directly when you need
environment-specific configuration that shouldn't live in `agent.py`.

---

## Session strategy

Each scheduled invocation creates a **fresh session** by default, so runs are
fully isolated. To retain state across ticks (e.g. accumulate context over
time), pass a `session_service_uri` pointing to a persistent store and manage
session IDs yourself via `extra_state` or the `on_response` callback.

```python
ScheduleConfig(
    agent=root_agent,
    interval_seconds=3600,
    session_service_uri="sqlite:///./scheduler.db",
    extra_state={"environment": "production", "tenant": "acme"},
)
```

---

## Development

```bash
git clone https://github.com/STHITAPRAJNAS/adk-task-scheduler.git
cd adk-task-scheduler

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
```

### Running the example

```bash
cd example
pip install -e "..[dev]"   # install from parent
uvicorn main:app --reload --log-level info
```

The `ticker_agent` will fire every 30 seconds and log its response. You can
also call it ad-hoc:

```bash
curl -s -X POST http://localhost:8000/run \
  -H "Content-Type: application/json" \
  -d '{
    "app_name": "ticker_agent",
    "user_id": "me",
    "session_id": "test-1",
    "new_message": {"role": "user", "parts": [{"text": "What time is it?"}]}
  }' | python -m json.tool
```

---

## Releasing

This project uses **PyPI Trusted Publishing** (OIDC) — no API token needed.

**Steps:**

1. Bump the version in `pyproject.toml` and `adk_task_scheduler/__init__.py`.
2. Add a section to `CHANGELOG.md`.
3. Commit and push to `main`.
4. Tag the release:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
5. The [publish workflow](.github/workflows/publish.yml) triggers automatically on `v*.*.*` tags, runs the full test suite, then uploads to PyPI via `pypa/gh-action-pypi-publish`.

**One-time setup (first release only):**  
Add a *Trusted Publisher* entry on [pypi.org/manage/account/publishing/](https://pypi.org/manage/account/publishing/) pointing to `STHITAPRAJNAS/adk-task-scheduler`, workflow `publish.yml`, and environment `pypi`.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).
