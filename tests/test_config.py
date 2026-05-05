"""Tests for ScheduleConfig validation."""
import pytest

from adk_task_scheduler.config import ScheduleConfig
from tests.conftest import EchoAgent


def make_agent(name: str = "a") -> EchoAgent:
    return EchoAgent(name=name, description="test")


def test_cron_config_defaults():
    agent = make_agent("summary")
    cfg = ScheduleConfig(agent=agent, cron="0 * * * *")
    assert cfg.app_name == "summary"
    assert cfg.trigger_text == "__tick__"
    assert cfg.user_id == "adk-scheduler"
    assert cfg.max_concurrent_runs == 1


def test_interval_config():
    agent = make_agent("poller")
    cfg = ScheduleConfig(agent=agent, interval_seconds=300)
    assert cfg.interval_seconds == 300
    assert cfg.app_name == "poller"


def test_condition_config():
    agent = make_agent("cond")
    cfg = ScheduleConfig(agent=agent, condition=lambda: True)
    assert cfg.condition is not None


def test_explicit_app_name_overrides_agent_name():
    agent = make_agent("original")
    cfg = ScheduleConfig(agent=agent, interval_seconds=10, app_name="override")
    assert cfg.app_name == "override"


def test_missing_trigger_raises():
    agent = make_agent("broken")
    with pytest.raises(ValueError, match="cron, interval_seconds, condition"):
        ScheduleConfig(agent=agent)


def test_extra_state_defaults_empty():
    agent = make_agent("clean")
    cfg = ScheduleConfig(agent=agent, cron="* * * * *")
    assert cfg.extra_state == {}


def test_interval_seconds_zero_raises():
    """interval_seconds=0 is not a valid positive interval."""
    agent = make_agent("zero")
    with pytest.raises(ValueError, match="positive integer"):
        ScheduleConfig(agent=agent, interval_seconds=0)


def test_condition_poll_interval_zero_raises():
    agent = make_agent("poll_zero")
    with pytest.raises(ValueError, match="positive integer"):
        ScheduleConfig(agent=agent, condition=lambda: True, condition_poll_interval=0)


def test_condition_poll_interval_custom():
    agent = make_agent("poll_custom")
    cfg = ScheduleConfig(agent=agent, condition=lambda: False, condition_poll_interval=30)
    assert cfg.condition_poll_interval == 30


def test_condition_poll_interval_default():
    agent = make_agent("poll_default")
    cfg = ScheduleConfig(agent=agent, condition=lambda: False)
    assert cfg.condition_poll_interval == 60
