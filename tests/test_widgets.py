"""Tests for the widget catalog and data lookup."""

import pytest

import app.sources as sources_module
from app import metrics_db
from app.metrics_db import init_db, write_snapshot
from app.widgets import WIDGET_CATALOG, default_layout, get_widget_value


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
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


def test_default_layout_empty_when_no_sources():
    assert default_layout() == []


def test_default_layout_one_widget_per_catalog_entry_per_matching_source():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")

    layout = default_layout()

    types = {w["type"] for w in layout}
    assert types == {t for t, e in WIDGET_CATALOG.items() if e["source_system"] == "4thealth"}
    assert all(w["source_instance"] == "4th-1" for w in layout)


def test_default_layout_skips_disabled_sources():
    sources_module.add_source(
        id="4th-1", system="4thealth", name="A", base_url="https://a", token="t", enabled=False
    )

    assert default_layout() == []


def test_default_layout_covers_multiple_source_instances():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")
    sources_module.add_source(id="4th-2", system="4thealth", name="B", base_url="https://b", token="t")

    layout = default_layout()

    instances = {w["source_instance"] for w in layout}
    assert instances == {"4th-1", "4th-2"}


def test_default_layout_ignores_source_whose_system_has_no_widgets():
    sources_module.add_source(id="x", system="unmapped-system", name="A", base_url="https://a", token="t")

    assert default_layout() == []


def test_catalog_contains_firewall_rule_adom_widgets():
    assert "4thealth.firewall_managed_count" in WIDGET_CATALOG
    assert "4thealth.rule_count_total" in WIDGET_CATALOG
    assert "4thealth.adom_count" in WIDGET_CATALOG
    assert WIDGET_CATALOG["4thealth.firewall_managed_count"]["source_system"] == "4thealth"


def test_get_widget_value_for_firewall_managed_count():
    write_snapshot("4thealth-east", "summary", {"firewall_managed_count": 128}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.firewall_managed_count", "source_instance": "4thealth-east"}

    result = get_widget_value(widget)

    assert result == {"value": 128, "collected_at": "2026-08-27T10:00:00Z"}


def test_get_widget_value_for_rule_count_total():
    write_snapshot("4thealth-east", "summary", {"rule_count_total": 14200}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.rule_count_total", "source_instance": "4thealth-east"}

    assert get_widget_value(widget) == {"value": 14200, "collected_at": "2026-08-27T10:00:00Z"}


def test_get_widget_value_for_adom_count():
    write_snapshot("4thealth-east", "summary", {"adom_count": 9}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.adom_count", "source_instance": "4thealth-east"}

    assert get_widget_value(widget) == {"value": 9, "collected_at": "2026-08-27T10:00:00Z"}


def test_get_widget_value_for_version_breakdown_returns_dict_value():
    write_snapshot(
        "4thealth-east",
        "summary",
        {"version_breakdown": {"7.4.5": 62, "7.2.9": 41, "7.0.14": 25}},
        "2026-08-27T10:00:00Z",
    )
    widget = {"type": "4thealth.version_breakdown", "source_instance": "4thealth-east"}

    result = get_widget_value(widget)

    assert result == {
        "value": {"7.4.5": 62, "7.2.9": 41, "7.0.14": 25},
        "collected_at": "2026-08-27T10:00:00Z",
    }
