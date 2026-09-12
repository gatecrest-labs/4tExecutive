import pytest

import app.brief_schedule as brief_schedule_module
from app.brief_schedule import (
    DEFAULTS,
    get_brief_schedule_config,
    save_brief_schedule_config,
    validate_schedule_config,
)


@pytest.fixture(autouse=True)
def tmp_schedule_config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(brief_schedule_module, "SCHEDULE_CONFIG_PATH", tmp_path / "brief_schedule.json")


def test_defaults_when_no_file():
    assert get_brief_schedule_config() == DEFAULTS


def test_save_then_load_round_trip():
    save_brief_schedule_config(
        {"weekday": 4, "hour": 17, "recipients": "cio@example.com, ciso@example.com", "enabled": True}
    )

    cfg = get_brief_schedule_config()

    assert cfg["weekday"] == 4
    assert cfg["hour"] == 17
    assert cfg["recipients"] == "cio@example.com, ciso@example.com"
    assert cfg["enabled"] is True


def test_valid_config_passes():
    cfg = {"weekday": 0, "hour": 8, "recipients": "a@b.com", "enabled": True}
    assert validate_schedule_config(cfg) == []


def test_disabled_config_with_no_recipients_is_valid():
    cfg = {"weekday": 0, "hour": 8, "recipients": "", "enabled": False}
    assert validate_schedule_config(cfg) == []


@pytest.mark.parametrize("weekday", [-1, 7, "not-a-number"])
def test_invalid_weekday_rejected(weekday):
    cfg = {"weekday": weekday, "hour": 8, "recipients": "a@b.com", "enabled": True}
    errors = validate_schedule_config(cfg)
    assert errors
    assert any("weekday" in e for e in errors)


@pytest.mark.parametrize("hour", [-1, 24, "not-a-number"])
def test_invalid_hour_rejected(hour):
    cfg = {"weekday": 0, "hour": hour, "recipients": "a@b.com", "enabled": True}
    errors = validate_schedule_config(cfg)
    assert errors
    assert any("hour" in e for e in errors)


def test_malformed_recipient_rejected():
    cfg = {"weekday": 0, "hour": 8, "recipients": "not-an-email", "enabled": True}
    errors = validate_schedule_config(cfg)
    assert errors
    assert any("Malformed" in e for e in errors)


def test_empty_entries_in_recipient_list_silently_dropped():
    # a@b.com,,c@d.com -- the empty entry between the two commas is dropped
    # rather than treated as a malformed address (see the comment in
    # app.brief_schedule._parse_recipients for the rationale).
    cfg = {"weekday": 0, "hour": 8, "recipients": "a@b.com,,c@d.com", "enabled": True}
    assert validate_schedule_config(cfg) == []


def test_enabled_with_no_recipients_rejected():
    cfg = {"weekday": 0, "hour": 8, "recipients": "", "enabled": True}
    errors = validate_schedule_config(cfg)
    assert errors
    assert any("recipient" in e.lower() for e in errors)
