# adk-task-scheduler

Auto-scheduling for [Google ADK](https://google.github.io/adk-docs/) agents.  
Bake cron, interval, or condition-based triggers directly into your agent definitions — no separate orchestrator required.

## Why

ADK agents are invocation-driven. Out of the box they only run when a user or external system sends a message. `adk-task-scheduler` adds a **self-wake** capability so agents can fire on a schedule, alongside the existing ad-hoc `POST /run` interface, with zero changes to ADK internals.

## How it works

`get_fast_api_app` (the ADK function that powers `adk api_server`) accepts an optional `lifespan=` parameter. This library builds an [APScheduler](https://apscheduler.readthedocs.io/) `AsyncIOScheduler` lifespan and passes it in — **no monkey-patching required**. ADK's own `runner_dict` handles ad-hoc calls; the scheduler uses a separate `RunnerPool` so the two never interfere.

```
┌────────────────────────────────────────────────────────┐
│  FastAPI app (from build_scheduled_app)                │
│                                                        │
│  ┌──────────────────────┐  ┌─────────────────────────┐ │
│  │  ADK runner_dict     │  │  Scheduler RunnerPool   │ │
│  │  (ad-hoc /run calls) │  │  (cron / interval jobs) │ │
│  └──────────────────────┘  └─────────────────────────┘ │
└────────────────────────────────────────────────────────┘
```

## Installation

```bash
pip install adk-task-scheduler
```

Requires Python ≥ 3.10, `google-adk ≥ 1.7.0`.

## Quick start

### 1. Attach a schedule to your `root_agent`

Python's `@decorator` syntax only works on `def`/`class` statements. Use
`with_schedule()` (recommended) or call `scheduled()(agent)` directly:

```python
# agents/ticker_agent/agent.py
from google.adk.agents import Agent
from adk_task_scheduler import with_schedule

root_agent = with_schedule(
    Agent(
        name="ticker_agent",
        model="gemini-2.0-flash",
        instruction="""
    When the message is '__tick__' you are called by the scheduler.
    Report current UTC time and status.
    For all other messages respond normally.
    """,
    ),
    interval_seconds=30,
    trigger_text="__tick__",
)
```

Or equivalently with `scheduled()`:

```python
from adk_task_scheduler import scheduled

root_agent = scheduled(interval_seconds=30, trigger_text="__tick__")(
    Agent(name="ticker_agent", model="gemini-2.0-flash", instruction="...")
)
```

### 2. Build the app

```python
# main.py
from adk_task_scheduler import build_scheduled_app

app = build_scheduled_app(
    agents_dir="./agents",
    auto_discover=True,   # picks up @scheduled decorators automatically
    web=False,
    a2a=True,
)
```

```bash
uvicorn main:app --reload
```

The agent now:
- Responds to `POST /run` ad-hoc calls (standard ADK).
- Self-wakes every 30 seconds via the scheduler.

### 3. Explicit `ScheduleConfig` (no decorator)

```python
from adk_task_scheduler import ScheduleConfig, build_scheduled_app
from my_agents.reporter.agent import root_agent

cfg = ScheduleConfig(
    agent=root_agent,
    cron="0 9 * * 1-5",          # 9 AM weekdays
    trigger_text="__morning__",
    session_service_uri="sqlite:///./scheduler.db",
    on_response=lambda text: print(f"Agent said: {text}"),
    on_error=lambda exc: print(f"Error: {exc}"),
)

app = build_scheduled_app(
    agents_dir="./agents",
    schedules=[cfg],
    auto_discover=False,
    web=False,
)
```

## Trigger types

| Parameter | Description |
|---|---|
| `cron="0 * * * *"` | Standard 5-field crontab expression (APScheduler `CronTrigger`) |
| `interval_seconds=300` | Fixed interval in seconds |
| `condition=lambda: is_market_open()` | Polled every 60 s; fires when truthy (sync or async) |

## API reference

### `@scheduled(...)`

Decorator that attaches a `ScheduleConfig` to a `root_agent` instance.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `cron` | `str` | — | Crontab expression |
| `interval_seconds` | `int` | — | Interval in seconds |
| `condition` | `Callable` | — | Condition function |
| `trigger_text` | `str` | `"__tick__"` | Synthetic user message |
| `user_id` | `str` | `"adk-scheduler"` | Session user identity |
| `session_service_uri` | `str` | — | SQLAlchemy URI (default: in-memory) |
| `on_response` | `Callable[[str], Any]` | — | Called with the agent's final text |
| `on_error` | `Callable[[Exception], Any]` | — | Called on invocation failure |
| `max_concurrent_runs` | `int` | `1` | Max overlapping invocations |
| `misfire_grace_time` | `int` | `30` | APScheduler misfire grace seconds |

### `build_scheduled_app(...)`

Drop-in for `get_fast_api_app`. All `get_fast_api_app` kwargs are forwarded verbatim.

| Extra parameter | Type | Default | Description |
|---|---|---|---|
| `schedules` | `list[ScheduleConfig]` | `[]` | Explicit schedule configs |
| `auto_discover` | `bool` | `True` | Scan `agents_dir` for `@scheduled` agents |

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check .
```

## License

Apache 2.0
