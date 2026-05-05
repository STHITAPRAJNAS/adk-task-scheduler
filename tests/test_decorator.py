"""Tests for the @scheduled decorator."""

from adk_task_scheduler.config import ScheduleConfig
from adk_task_scheduler.decorator import get_schedule_config, scheduled
from tests.conftest import EchoAgent


def make_agent(name: str = "a") -> EchoAgent:
    return EchoAgent(name=name, description="test")


def test_decorator_attaches_config():
    # Python decorator syntax only applies to def/class.
    # scheduled() is used as a regular callable: scheduled(...)(agent)
    agent = make_agent("hourly")
    decorated = scheduled(cron="0 * * * *")(agent)
    cfg = get_schedule_config(decorated)
    assert isinstance(cfg, ScheduleConfig)
    assert cfg.cron == "0 * * * *"
    assert cfg.agent is agent


def test_decorator_returns_same_agent_instance():
    agent = make_agent("same")
    result = scheduled(interval_seconds=30)(agent)
    assert result is agent


def test_decorator_sets_correct_trigger_text():
    agent = make_agent("tick")
    decorated = scheduled(interval_seconds=10, trigger_text="__refresh__")(agent)
    cfg = get_schedule_config(decorated)
    assert cfg.trigger_text == "__refresh__"


def test_decorator_with_condition():
    flag = {"active": True}
    agent = make_agent("conditional")
    decorated = scheduled(condition=lambda: flag["active"])(agent)
    cfg = get_schedule_config(decorated)
    assert cfg.condition() is True
    flag["active"] = False
    assert cfg.condition() is False


def test_get_schedule_config_undecorated_returns_none():
    agent = make_agent("plain")
    assert get_schedule_config(agent) is None


def test_decorator_overrides_previous_config():
    agent = make_agent("overwrite")
    scheduled(interval_seconds=10)(agent)
    scheduled(cron="*/5 * * * *")(agent)
    cfg = get_schedule_config(agent)
    assert cfg.cron == "*/5 * * * *"
    assert cfg.interval_seconds is None


def test_on_response_callback_stored():
    responses = []
    agent = make_agent("cb")
    decorated = scheduled(
        interval_seconds=5,
        on_response=responses.append,
    )(agent)
    cfg = get_schedule_config(decorated)
    cfg.on_response("hello")
    assert responses == ["hello"]
