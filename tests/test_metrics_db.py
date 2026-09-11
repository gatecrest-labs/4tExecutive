import pytest

from app import metrics_db
from app.metrics_db import (
    clear_poll_error,
    downsample_metric_points,
    get_events,
    get_history,
    get_last_polled,
    get_latest,
    get_layout,
    get_metric_latest_at_or_before,
    get_metric_series,
    get_poll_error,
    init_db,
    insert_event,
    insert_metric_points,
    iter_all_snapshots,
    list_by_adom_names,
    prune_metric_points_older_than,
    prune_snapshots_older_than,
    save_layout,
    set_last_polled,
    set_poll_error,
    write_snapshot,
)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    init_db()


def test_write_snapshot_then_get_latest():
    write_snapshot("4thealth-east", "summary", {"hygiene_score": 92}, "2026-08-24T10:00:00Z")
    write_snapshot("4thealth-east", "summary", {"hygiene_score": 95}, "2026-08-24T10:15:00Z")

    latest = get_latest("4thealth-east", "summary")

    assert latest["value"] == {"hygiene_score": 95}
    assert latest["collected_at"] == "2026-08-24T10:15:00Z"


def test_get_latest_returns_none_when_no_data():
    assert get_latest("unknown-source", "summary") is None


def test_get_history_returns_snapshots_since_timestamp_ordered():
    write_snapshot("s1", "summary", {"v": 1}, "2026-08-24T08:00:00Z")
    write_snapshot("s1", "summary", {"v": 2}, "2026-08-24T09:00:00Z")
    write_snapshot("s1", "summary", {"v": 3}, "2026-08-24T10:00:00Z")

    history = get_history("s1", "summary", since="2026-08-24T08:30:00Z")

    assert [h["value"]["v"] for h in history] == [2, 3]


def test_last_polled_roundtrip():
    assert get_last_polled("s1") is None
    set_last_polled("s1", "2026-08-24T10:00:00Z")
    assert get_last_polled("s1") == "2026-08-24T10:00:00Z"


def test_layout_roundtrip():
    assert get_layout("alice") == []
    widgets = [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1"}]
    save_layout("alice", widgets)
    assert get_layout("alice") == widgets


def test_save_layout_overwrites_previous():
    save_layout("alice", [{"type": "a"}])
    save_layout("alice", [{"type": "b"}])
    assert get_layout("alice") == [{"type": "b"}]


def test_poll_error_roundtrip():
    assert get_poll_error("s1") is None
    set_poll_error("s1", "connection refused", "2026-08-24T10:00:00Z")
    assert get_poll_error("s1") == {"error": "connection refused", "attempted_at": "2026-08-24T10:00:00Z"}


def test_set_poll_error_overwrites_previous():
    set_poll_error("s1", "first error", "2026-08-24T10:00:00Z")
    set_poll_error("s1", "second error", "2026-08-24T10:15:00Z")
    assert get_poll_error("s1") == {"error": "second error", "attempted_at": "2026-08-24T10:15:00Z"}


def test_clear_poll_error_removes_it():
    set_poll_error("s1", "connection refused", "2026-08-24T10:00:00Z")
    clear_poll_error("s1")
    assert get_poll_error("s1") is None


def test_clear_poll_error_is_a_noop_when_none_exists():
    clear_poll_error("s1")  # should not raise
    assert get_poll_error("s1") is None


def test_insert_metric_points_then_get_series():
    insert_metric_points("s1", "2026-08-24T08:00:00Z", {"hygiene_score": 90.0})
    insert_metric_points("s1", "2026-08-24T09:00:00Z", {"hygiene_score": 92.0})

    series = get_metric_series("s1", "hygiene_score", since="2026-08-24T00:00:00Z")

    assert series == [
        {"ts": "2026-08-24T08:00:00Z", "value": 90.0},
        {"ts": "2026-08-24T09:00:00Z", "value": 92.0},
    ]


def test_get_metric_series_filters_by_since_and_metric_key():
    insert_metric_points("s1", "2026-08-24T08:00:00Z", {"hygiene_score": 90.0, "cpu_percent": 10.0})
    insert_metric_points("s1", "2026-08-25T08:00:00Z", {"hygiene_score": 91.0})

    series = get_metric_series("s1", "hygiene_score", since="2026-08-25T00:00:00Z")

    assert series == [{"ts": "2026-08-25T08:00:00Z", "value": 91.0}]


def test_insert_metric_points_upserts_on_same_source_key_ts():
    insert_metric_points("s1", "2026-08-24T08:00:00Z", {"hygiene_score": 90.0})
    insert_metric_points("s1", "2026-08-24T08:00:00Z", {"hygiene_score": 95.0})

    series = get_metric_series("s1", "hygiene_score", since="2026-08-24T00:00:00Z")

    assert series == [{"ts": "2026-08-24T08:00:00Z", "value": 95.0}]


def test_insert_metric_points_skips_none_values():
    insert_metric_points("s1", "2026-08-24T08:00:00Z", {"hygiene_score": None, "cpu_percent": 10.0})

    assert get_metric_series("s1", "hygiene_score", since="2026-08-24T00:00:00Z") == []
    assert get_metric_series("s1", "cpu_percent", since="2026-08-24T00:00:00Z") == [
        {"ts": "2026-08-24T08:00:00Z", "value": 10.0}
    ]


def test_get_metric_latest_at_or_before_returns_nearest_point():
    insert_metric_points("s1", "2026-08-20T08:00:00Z", {"hygiene_score": 88.0})
    insert_metric_points("s1", "2026-08-24T08:00:00Z", {"hygiene_score": 92.0})

    result = get_metric_latest_at_or_before("s1", "hygiene_score", "2026-08-22T00:00:00Z")

    assert result == {"ts": "2026-08-20T08:00:00Z", "value": 88.0}


def test_get_metric_latest_at_or_before_returns_none_when_no_point_precedes():
    insert_metric_points("s1", "2026-08-24T08:00:00Z", {"hygiene_score": 92.0})

    assert get_metric_latest_at_or_before("s1", "hygiene_score", "2026-08-20T00:00:00Z") is None


def test_prune_snapshots_older_than_removes_only_older_rows():
    write_snapshot("s1", "summary", {"v": 1}, "2026-08-01T00:00:00Z")
    write_snapshot("s1", "summary", {"v": 2}, "2026-08-25T00:00:00Z")

    prune_snapshots_older_than("2026-08-10T00:00:00Z")

    history = get_history("s1", "summary", since="2026-01-01T00:00:00Z")
    assert [h["value"]["v"] for h in history] == [2]


def test_prune_metric_points_older_than_removes_only_older_rows():
    insert_metric_points("s1", "2026-08-01T00:00:00Z", {"hygiene_score": 80.0})
    insert_metric_points("s1", "2026-08-25T00:00:00Z", {"hygiene_score": 90.0})

    prune_metric_points_older_than("2026-08-10T00:00:00Z")

    series = get_metric_series("s1", "hygiene_score", since="2026-01-01T00:00:00Z")
    assert series == [{"ts": "2026-08-25T00:00:00Z", "value": 90.0}]


def test_downsample_metric_points_collapses_same_day_points_to_daily_mean():
    insert_metric_points("s1", "2026-08-01T01:00:00Z", {"hygiene_score": 80.0})
    insert_metric_points("s1", "2026-08-01T13:00:00Z", {"hygiene_score": 90.0})
    insert_metric_points("s1", "2026-08-25T00:00:00Z", {"hygiene_score": 70.0})

    downsample_metric_points("2026-08-10T00:00:00Z")

    series = get_metric_series("s1", "hygiene_score", since="2026-01-01T00:00:00Z")

    assert series == [
        {"ts": "2026-08-01T00:00:00Z", "value": 85.0},
        {"ts": "2026-08-25T00:00:00Z", "value": 70.0},
    ]


def test_iter_all_snapshots_returns_every_row_oldest_first():
    write_snapshot("s1", "summary", {"v": 2}, "2026-08-24T09:00:00Z")
    write_snapshot("s2", "summary", {"v": 1}, "2026-08-24T08:00:00Z")

    rows = iter_all_snapshots()

    assert rows == [
        {"source_id": "s2", "value": {"v": 1}, "collected_at": "2026-08-24T08:00:00Z"},
        {"source_id": "s1", "value": {"v": 2}, "collected_at": "2026-08-24T09:00:00Z"},
    ]


def test_insert_event_then_get_events_returns_newest_first():
    insert_event(
        ts="2026-08-24T08:00:00Z",
        source_id="s1",
        metric_key="hygiene_score",
        kind="rag_change",
        severity="critical",
        title="Hygiene Score turned red",
        detail={"before": "green", "after": "red"},
    )
    insert_event(
        ts="2026-08-24T09:00:00Z",
        source_id="s1",
        metric_key="hygiene_score",
        kind="rag_change",
        severity="info",
        title="Hygiene Score turned green",
        detail={"before": "red", "after": "green"},
    )

    events = get_events(since="2026-01-01T00:00:00Z")

    assert [e["title"] for e in events] == [
        "Hygiene Score turned green",
        "Hygiene Score turned red",
    ]
    assert events[0]["detail"] == {"before": "red", "after": "green"}
    assert events[0]["source_id"] == "s1"
    assert events[0]["kind"] == "rag_change"
    assert events[0]["severity"] == "info"
    assert isinstance(events[0]["id"], int)


def test_get_events_filters_by_since():
    insert_event(
        ts="2026-08-01T00:00:00Z",
        source_id="s1",
        metric_key=None,
        kind="source_failed",
        severity="critical",
        title="s1 stopped responding",
        detail={},
    )
    insert_event(
        ts="2026-08-25T00:00:00Z",
        source_id="s1",
        metric_key=None,
        kind="source_recovered",
        severity="info",
        title="s1 recovered",
        detail={},
    )

    events = get_events(since="2026-08-10T00:00:00Z")

    assert [e["title"] for e in events] == ["s1 recovered"]


def test_get_events_with_no_events_returns_empty_list():
    assert get_events(since="2000-01-01T00:00:00Z") == []


def test_downsample_metric_points_leaves_already_daily_points_untouched():
    insert_metric_points("s1", "2026-08-01T00:00:00Z", {"hygiene_score": 80.0})

    downsample_metric_points("2026-08-10T00:00:00Z")

    series = get_metric_series("s1", "hygiene_score", since="2026-01-01T00:00:00Z")
    assert series == [{"ts": "2026-08-01T00:00:00Z", "value": 80.0}]


def test_list_by_adom_names_returns_distinct_sorted_names():
    insert_metric_points("s1", "2026-09-10T00:00:00Z", {
        "by_adom.Corp.firewalls_total": 10.0,
        "by_adom.Branch.firewalls_total": 3.0,
    })
    insert_metric_points("s2", "2026-09-10T00:00:00Z", {
        "by_adom.Corp.firewalls_total": 12.0,  # same adom, another source
    })

    assert list_by_adom_names() == ["Branch", "Corp"]


def test_list_by_adom_names_empty_when_none_present():
    insert_metric_points("s1", "2026-09-10T00:00:00Z", {"hygiene_score": 90.0})
    assert list_by_adom_names() == []
