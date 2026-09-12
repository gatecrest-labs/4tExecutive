"""Weekly-brief scheduler registration -- app.collector._register_weekly_brief_job.

Separate test file (rather than extending tests/test_collector.py, whose
existing fixtures/tests belong to the collector/polling agent) covering the
new integration point this agent adds to app/collector.py.
"""

from unittest.mock import MagicMock

import pytest

import app.brief_schedule as brief_schedule_module
from app.collector import _register_weekly_brief_job


@pytest.fixture(autouse=True)
def tmp_schedule_config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_schedule_module, "SCHEDULE_CONFIG_PATH", tmp_path / "brief_schedule.json")


def test_job_not_registered_when_disabled():
    brief_schedule_module.save_brief_schedule_config(
        {"weekday": 0, "hour": 8, "recipients": "a@b.com", "enabled": False}
    )
    scheduler = MagicMock()

    _register_weekly_brief_job(scheduler, app=MagicMock())

    scheduler.add_job.assert_not_called()


def test_job_registered_with_cron_trigger_when_enabled():
    brief_schedule_module.save_brief_schedule_config(
        {"weekday": 3, "hour": 14, "recipients": "a@b.com", "enabled": True}
    )
    scheduler = MagicMock()

    _register_weekly_brief_job(scheduler, app=MagicMock())

    scheduler.add_job.assert_called_once()
    args, kwargs = scheduler.add_job.call_args
    trigger = args[1]
    assert kwargs["id"] == "weekly_brief"
    fields_by_name = {f.name: str(f) for f in trigger.fields}
    assert fields_by_name["hour"] == "14"
    assert fields_by_name["day_of_week"] == "3"


def test_job_not_registered_when_config_load_fails(monkeypatch):
    def _boom():
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(brief_schedule_module, "get_brief_schedule_config", _boom)
    scheduler = MagicMock()

    # Must not raise even if config loading blows up.
    _register_weekly_brief_job(scheduler, app=MagicMock())

    scheduler.add_job.assert_not_called()
