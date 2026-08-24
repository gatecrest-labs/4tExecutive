"""Tests for the widget catalog and data lookup."""

import pytest

import app.metrics_db as metrics_db
from app.metrics_db import init_db, write_snapshot
from app.widgets import WIDGET_CATALOG, get_widget_value


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    init_db()


def test_catalog_contains_expected_widget_types():
    assert "4thealth.hygiene_score" in WIDGET_CATALOG
    assert "4thealth.version_compliance" in WIDGET_CATALOG
    assert "4tlog.log_volume_trend" in WIDGET_CATALOG
    entry = WIDGET_CATALOG["4thealth.hygiene_score"]
    assert entry["source_system"] == "4thealth"
    assert entry["metric_type"] == "summary"


def test_get_widget_value_returns_field_from_latest_snapshot():
    write_snapshot("4thealth-east", "summary", {"hygiene_score": 92}, "2026-08-24T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "4thealth-east"}

    result = get_widget_value(widget)

    assert result == {"value": 92, "collected_at": "2026-08-24T10:00:00Z"}


def test_get_widget_value_returns_none_when_no_snapshot_yet():
    widget = {"type": "4thealth.hygiene_score", "source_instance": "unpolled-source"}
    assert get_widget_value(widget) is None


def test_get_widget_value_raises_for_unknown_widget_type():
    widget = {"type": "not.a.real.widget", "source_instance": "x"}
    with pytest.raises(KeyError):
        get_widget_value(widget)
