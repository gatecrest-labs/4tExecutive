"""Integration tests: two consecutive poll_source() calls emitting a known
event list, and a no-change pair emitting none (see app/events.py for the
detector unit tests)."""

from unittest.mock import patch

import pytest

import app.sources as sources_module
from app import metrics_db
from app.collector import poll_source
from app.crypto import encrypt_token
from app.metrics_db import get_events, init_db
from app.sources import add_source


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    from app import config_paths

    monkeypatch.setattr(config_paths, "CONFIG_DIR", tmp_path / "config")
    import app.domains as domains_module
    import app.events as events_module

    monkeypatch.setattr(domains_module, "SCORING_PATH", tmp_path / "config" / "scoring.json")
    monkeypatch.setattr(events_module, "EVENTS_CONFIG_PATH", tmp_path / "config" / "events.json")
    init_db()


def _source(**overrides):
    base = {
        "id": "4thealth-east",
        "system": "4thealth",
        "name": "East DC",
        "base_url": "https://4thealth-east.internal:8100",
        "token": encrypt_token("secret"),
        "poll_interval_minutes": 15,
        "enabled": True,
    }
    base.update(overrides)
    # domains.py's fleet aggregation (used for threshold_cross detection)
    # reads the source registry, not just the dict passed into poll_source.
    add_source(
        id=base["id"],
        system=base["system"],
        name=base["name"],
        base_url=base["base_url"],
        token="secret",
        poll_interval_minutes=base["poll_interval_minutes"],
        enabled=base["enabled"],
    )
    return base


def _poll(source, payload, status_code=200):
    with patch("app.collector.requests.get") as mock_get:
        mock_get.return_value.status_code = status_code
        mock_get.return_value.json.return_value = payload
        return poll_source(source)


def test_two_consecutive_snapshots_produce_known_events():
    source = _source()
    _poll(
        source,
        {
            "hygiene_score": 92,
            "hygiene_sweep_status": "ok",
            "firewall_online_count": 100,
            "firewall_managed_count": 100,
            "devices_silent": 0,
            "pending_config_diff_count": 0,
        },
    )

    _poll(
        source,
        {
            "hygiene_score": 40,  # green -> red: rag_change
            "hygiene_sweep_status": "ok",
            "firewall_online_count": 60,  # 100% -> 60%: availability crosses its 95 target
            "firewall_managed_count": 100,
            "devices_silent": 0,
            "pending_config_diff_count": 10,  # +10 vs threshold 3: rollup_delta
        },
    )

    events = get_events(since="2000-01-01T00:00:00Z")
    # hygiene_score dropping 92->40 also crosses Config Posture's own target
    # (90), alongside Availability's (95) from the online-count drop — both
    # are genuine threshold_cross events, not duplicates of one another.
    kinds = sorted(e["kind"] for e in events)
    assert kinds == ["rag_change", "rollup_delta", "threshold_cross", "threshold_cross"]

    rag_event = next(e for e in events if e["kind"] == "rag_change")
    assert rag_event["detail"]["before"] == "green"
    assert rag_event["detail"]["after"] == "red"

    rollup_event = next(e for e in events if e["kind"] == "rollup_delta")
    assert rollup_event["metric_key"] == "pending_config_diff_count"
    assert rollup_event["detail"]["delta"] == 10.0

    threshold_domains = {e["detail"]["domain"] for e in events if e["kind"] == "threshold_cross"}
    assert threshold_domains == {"availability", "posture"}


def test_identical_consecutive_snapshots_produce_no_events():
    source = _source()
    payload = {
        "hygiene_score": 92,
        "hygiene_sweep_status": "ok",
        "firewall_online_count": 100,
        "firewall_managed_count": 100,
        "devices_silent": 0,
        "pending_config_diff_count": 0,
    }

    _poll(source, payload)
    _poll(source, dict(payload))

    assert get_events(since="2000-01-01T00:00:00Z") == []


def test_first_ever_poll_produces_no_events():
    source = _source()
    _poll(source, {"hygiene_score": 40, "hygiene_sweep_status": "ok"})

    assert get_events(since="2000-01-01T00:00:00Z") == []


def test_poll_failure_then_recovery_emits_source_events():
    source = _source()
    _poll(source, {"hygiene_score": 92, "hygiene_sweep_status": "ok"})

    _poll(source, {}, status_code=503)

    events = get_events(since="2000-01-01T00:00:00Z")
    assert [e["kind"] for e in events] == ["source_failed"]

    _poll(source, {"hygiene_score": 92, "hygiene_sweep_status": "ok"})

    events = get_events(since="2000-01-01T00:00:00Z")
    kinds = [e["kind"] for e in events]
    assert "source_recovered" in kinds


def test_repeated_failures_only_emit_source_failed_once():
    source = _source()
    _poll(source, {}, status_code=503)
    _poll(source, {}, status_code=503)
    _poll(source, {}, status_code=503)

    events = get_events(since="2000-01-01T00:00:00Z")
    assert len([e for e in events if e["kind"] == "source_failed"]) == 1
