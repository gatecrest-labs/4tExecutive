import pytest

from app import metrics_db
from app.metrics_db import (
    clear_poll_error,
    get_history,
    get_last_polled,
    get_latest,
    get_layout,
    get_poll_error,
    init_db,
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
