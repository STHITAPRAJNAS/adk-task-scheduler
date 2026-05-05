# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2025-05-05

### Added

- `ScheduleConfig` dataclass — declarative schedule definition with cron,
  interval, or condition triggers.
- `scheduled()` — callable wrapper that attaches a `ScheduleConfig` to any
  ADK `BaseAgent` instance.
- `with_schedule()` — ergonomic one-liner alternative to `scheduled()(agent)`.
- `build_scheduled_app()` — drop-in for `get_fast_api_app` that injects an
  `APScheduler AsyncIOScheduler` via the `lifespan=` parameter without
  patching ADK internals.
- `RunnerPool` — shared, lazily-created `Runner` pool (one per `app_name`)
  for scheduled invocations, isolated from ADK's own `runner_dict`.
- Auto-discovery: `build_scheduled_app(auto_discover=True)` scans `agents_dir`
  for `root_agent` instances that carry a schedule config.
- Support for cron, fixed-interval, and polled-condition triggers.
- `on_response` / `on_error` callbacks per schedule.
- Persistent session support via `session_service_uri` (SQLAlchemy URI).
- 39 tests covering config, decorator, invoker, lifespan, and app layers.
