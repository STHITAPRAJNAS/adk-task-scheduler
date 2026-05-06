# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-05-05

### Added

- `fire_mode` field on `ScheduleConfig` — `"every"` (default, existing behaviour)
  or `"once_until_reset"` which fires only on a False→True condition transition,
  suppressing re-fires while the condition stays truthy.
- `ConditionContext` dataclass passed to one-argument condition callables;
  carries `last_fired_at`, `fire_count`, and `extra_state` so conditions can
  make time-aware or count-aware decisions.  Zero-argument callables still work
  unchanged.
- `condition_backoff_factor` — exponential back-off multiplier applied to
  `condition_poll_interval` after each consecutive falsy evaluation.  Reduces
  unnecessary API calls for slow-changing conditions.
- `condition_max_poll_interval` — upper bound (seconds) on the back-off delay.
- `condition` may now be combined with `cron` or `interval_seconds` to act as a
  gate: the schedule controls *when* to check, the condition controls *whether*
  to fire.  Previously these were mutually exclusive.
- Condition evaluation exceptions are now caught and routed to `on_error`;
  previously they propagated silently through APScheduler.
- `ConditionContext` exported from the top-level package.
- 29 new tests covering all condition improvements.

### Changed

- `ScheduleConfig` validation: `cron` and `interval_seconds` are now mutually
  exclusive (raises `ValueError`); previously mixing them was silently ignored.

## [0.1.2] - 2026-05-05

### Changed

- PyPI metadata: richer keyword set (`a2a`, `genai`, `agent`, `agentic`, `llm-agent`,
  `vertex-ai`, `google-cloud`, `generative-ai`, `background-tasks`, `task-scheduler`)
  aligned with ADK ecosystem search terms.
- Classifiers: added `Environment :: Web Environment`, `Framework :: AsyncIO`,
  `Natural Language :: English`, `Programming Language :: Python :: 3 :: Only`,
  `Topic :: Internet :: WWW/HTTP`, `Typing :: Typed`.
- License field upgraded to SPDX expression (`Apache-2.0`) per PEP 639.
- Added `Documentation` URL to project metadata.

## [0.1.1] - 2026-05-05

### Added

- `ScheduleConfig` now accepts `artifact_service_uri`, `memory_service_uri`,
  and `session_db_kwargs` — matching the full parameter surface of
  `get_fast_api_app`.
- `RunnerPool` delegates to ADK's `create_*_service_from_options` helpers so
  service construction is always consistent with the ad-hoc runner.
- `RunnerPool` now injects `InMemoryCredentialService` so agents that use
  OAuth tools work correctly in scheduled invocations.
- `RunnerPool` accepts a `base_dir` parameter (forwarded automatically from
  `build_scheduled_app` as `agents_dir`).
- `build_scheduled_app` propagates service URIs from its kwargs into any
  `ScheduleConfig` that hasn't set them explicitly — configure once at app
  level, not per-schedule.
- `py.typed` marker for PEP 561 compliance (mypy consumers see full types).

### Fixed

- Test isolation: autouse `_isolated_cwd` fixture in conftest now sets cwd
  to a temporary directory for every test, preventing ADK's local-SQLite
  fallback from creating session-storage directories in the project root.
- `_propagate_service_uris` now uses plain `setattr` instead of
  `object.__setattr__` — `ScheduleConfig` is a plain dataclass, not Pydantic.

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
