"""Tests for change-detection event building (app/events.py)."""


import pytest

import app.sources as sources_module
from app import metrics_db
from app.events import (
    build_rag_change_events,
    build_rollup_delta_events,
    build_threshold_cross_events,
    capture_rag_snapshot,
    detect_and_record,
    event_domain,
    get_events_config,
    positioned_ticks,
    record_source_failed,
    record_source_recovered,
    save_events_config,
)
from app.metrics_db import get_events, init_db, write_snapshot
from app.sources import add_source


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    from app import config_paths

    monkeypatch.setattr(config_paths, "CONFIG_DIR", tmp_path / "config")
    import app.events as events_module

    monkeypatch.setattr(events_module, "EVENTS_CONFIG_PATH", tmp_path / "config" / "events.json")
    init_db()


def _source(source_id="s1", system="4thealth", name="East"):
    add_source(id=source_id, system=system, name=name, base_url="https://x.internal", token="t")
    return {"id": source_id, "system": system, "name": name}


def test_build_rag_change_events_detects_transition():
    source = _source()
    before = {"4thealth.hygiene_score": "green"}
    after = {"4thealth.hygiene_score": "red"}

    events = build_rag_change_events(source, before, after)

    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "rag_change"
    assert event["severity"] == "critical"
    assert event["source_id"] == "s1"
    assert "red" in event["title"]
    assert event["detail"] == {"widget_type": "4thealth.hygiene_score", "before": "green", "after": "red"}


def test_build_rag_change_events_no_change_produces_nothing():
    source = _source()
    before = {"4thealth.hygiene_score": "green"}
    after = {"4thealth.hygiene_score": "green"}

    assert build_rag_change_events(source, before, after) == []


def test_build_rag_change_events_severity_by_new_state():
    source = _source()
    key = "4thealth.hygiene_score"
    assert build_rag_change_events(source, {key: "green"}, {key: "amber"})[0]["severity"] == "warning"
    assert build_rag_change_events(source, {key: "amber"}, {key: "green"})[0]["severity"] == "info"


def test_capture_rag_snapshot_reads_current_latest():
    _source()
    write_snapshot("s1", "summary", {"hygiene_score": 92, "hygiene_sweep_status": "ok"}, "2026-08-27T10:00:00Z")

    snapshot = capture_rag_snapshot("s1", "4thealth")

    assert snapshot["4thealth.hygiene_score"] == "green"


def test_build_rollup_delta_events_detects_increase_beyond_threshold():
    source = _source()
    before_payload = {"devices_silent": 1}
    after_payload = {"devices_silent": 5}

    events = build_rollup_delta_events(source, before_payload, after_payload)

    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "rollup_delta"
    assert event["metric_key"] == "devices_silent"
    assert event["severity"] == "warning"
    assert event["detail"] == {"before": 1.0, "after": 5.0, "delta": 4.0, "threshold": 3}


def test_build_rollup_delta_events_within_threshold_produces_nothing():
    source = _source()
    events = build_rollup_delta_events(source, {"devices_silent": 1}, {"devices_silent": 3})
    assert events == []


def test_build_rollup_delta_events_critical_findings_any_change_triggers():
    source = _source()
    before_payload = {"device_review": {"findings_by_severity": {"critical": 0}}}
    after_payload = {"device_review": {"findings_by_severity": {"critical": 1}}}

    events = build_rollup_delta_events(source, before_payload, after_payload)

    assert len(events) == 1
    assert events[0]["metric_key"] == "device_review.findings_by_severity.critical"
    assert events[0]["severity"] == "warning"


def test_build_rollup_delta_events_decrease_is_info_severity():
    source = _source()
    events = build_rollup_delta_events(source, {"devices_silent": 10}, {"devices_silent": 2})
    assert events[0]["severity"] == "info"


def test_build_rollup_delta_events_missing_data_is_skipped():
    source = _source()
    assert build_rollup_delta_events(source, None, {"devices_silent": 5}) == []
    assert build_rollup_delta_events(source, {"devices_silent": 1}, {}) == []


def test_build_rollup_delta_events_respects_config_override():
    save_events_config({"rollup_thresholds": {"devices_silent": 100}})
    source = _source()

    events = build_rollup_delta_events(source, {"devices_silent": 1}, {"devices_silent": 5})

    assert events == []


def test_get_events_config_has_sane_defaults():
    config = get_events_config()
    assert config["rollup_thresholds"]["devices_silent"] == 3
    assert config["rollup_thresholds"]["device_review.findings_by_severity.critical"] == 0
    assert config["rollup_thresholds"]["pending_config_diff_count"] == 3


def test_build_threshold_cross_events_detects_crossing_below_target():
    before_scores = {"availability": 96.0}
    after_scores = {"availability": 80.0}

    events = build_threshold_cross_events(before_scores, after_scores)

    assert len(events) == 1
    event = events[0]
    assert event["kind"] == "threshold_cross"
    assert event["severity"] == "critical"
    assert event["source_id"] is None
    assert event["detail"]["domain"] == "availability"
    assert event["detail"]["target"] == 95


def test_build_threshold_cross_events_detects_crossing_above_target_as_info():
    events = build_threshold_cross_events({"availability": 80.0}, {"availability": 96.0})
    assert events[0]["severity"] == "info"


def test_build_threshold_cross_events_no_crossing_produces_nothing():
    events = build_threshold_cross_events({"availability": 96.0}, {"availability": 97.0})
    assert events == []


def test_build_threshold_cross_events_domain_without_target_is_skipped():
    # vulnerability/lifecycle have no target configured by default
    events = build_threshold_cross_events({"vulnerability": 50.0}, {"vulnerability": 10.0})
    assert events == []


def test_detect_and_record_inserts_events_and_returns_them():
    source = _source()

    events = detect_and_record(
        source=source,
        before_rag={"4thealth.hygiene_score": "green"},
        after_rag={"4thealth.hygiene_score": "red"},
        before_payload={"devices_silent": 1},
        after_payload={"devices_silent": 10},
        before_domain_scores={"availability": 96.0},
        after_domain_scores={"availability": 80.0},
    )

    assert len(events) == 3  # rag_change + rollup_delta + threshold_cross
    stored = get_events(since="2000-01-01T00:00:00Z")
    assert len(stored) == 3


def test_detect_and_record_no_change_produces_no_events():
    source = _source()

    events = detect_and_record(
        source=source,
        before_rag={"4thealth.hygiene_score": "green"},
        after_rag={"4thealth.hygiene_score": "green"},
        before_payload={"devices_silent": 1},
        after_payload={"devices_silent": 1},
        before_domain_scores={"availability": 96.0},
        after_domain_scores={"availability": 96.0},
    )

    assert events == []
    assert get_events(since="2000-01-01T00:00:00Z") == []


def test_record_source_failed_and_recovered():
    source = _source()

    record_source_failed(source, "connection refused")
    record_source_recovered(source)

    events = get_events(since="2000-01-01T00:00:00Z")
    kinds = {e["kind"] for e in events}
    assert kinds == {"source_failed", "source_recovered"}
    failed = next(e for e in events if e["kind"] == "source_failed")
    assert failed["severity"] == "critical"
    assert failed["detail"] == {"error": "connection refused"}
    recovered = next(e for e in events if e["kind"] == "source_recovered")
    assert recovered["severity"] == "info"


def test_event_domain_for_threshold_cross():
    event = {"kind": "threshold_cross", "detail": {"domain": "hygiene"}, "metric_key": "domain.hygiene"}
    assert event_domain(event) == "hygiene"


def test_event_domain_for_rag_change():
    event = {
        "kind": "rag_change",
        "detail": {"widget_type": "4thealth.hygiene_score", "before": "green", "after": "red"},
        "metric_key": "hygiene_score",
    }
    assert event_domain(event) == "posture"


def test_event_domain_for_rollup_delta():
    event = {"kind": "rollup_delta", "metric_key": "devices_silent", "detail": {}}
    assert event_domain(event) == "logging"


def test_event_domain_for_source_events_is_none():
    assert event_domain({"kind": "source_failed", "metric_key": None, "detail": {}}) is None
    assert event_domain({"kind": "source_recovered", "metric_key": None, "detail": {}}) is None


def test_positioned_ticks_maps_event_time_onto_chart_width():
    points = [
        {"ts": "2026-08-01T00:00:00Z", "value": 1},
        {"ts": "2026-08-11T00:00:00Z", "value": 2},
    ]
    events = [{"ts": "2026-08-06T00:00:00Z", "title": "halfway"}]

    ticks = positioned_ticks(points, events, width=240)

    assert ticks == [{"x": 120.0, "title": "halfway"}]


def test_positioned_ticks_excludes_events_outside_series_range():
    points = [
        {"ts": "2026-08-01T00:00:00Z", "value": 1},
        {"ts": "2026-08-11T00:00:00Z", "value": 2},
    ]
    events = [{"ts": "2026-07-01T00:00:00Z", "title": "too early"}]

    assert positioned_ticks(points, events, width=240) == []


def test_positioned_ticks_with_fewer_than_two_points_is_empty():
    assert positioned_ticks([{"ts": "2026-08-01T00:00:00Z", "value": 1}], [{"ts": "2026-08-01T00:00:00Z", "title": "x"}], 240) == []
    assert positioned_ticks([], [], 240) == []
