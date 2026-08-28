"""Tests for the widget catalog and data lookup."""

from datetime import UTC, datetime, timedelta

import pytest

import app.sources as sources_module
from app import metrics_db
from app.metrics_db import init_db, write_snapshot
from app.widgets import (
    WIDGET_CATALOG,
    _downsample,
    default_layout,
    get_widget_series,
    get_widget_value,
)


def _iso(minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


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


def test_default_layout_only_host_widgets_when_no_sources():
    layout = default_layout()
    types = {w["type"] for w in layout}
    assert types == {"4texecutive.cpu_percent", "4texecutive.memory_percent", "4texecutive.disk_percent"}


def test_default_layout_one_widget_per_catalog_entry_per_matching_source():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")

    layout = default_layout()

    fourthealth_widgets = [w for w in layout if w["type"].startswith("4thealth.")]
    types = {w["type"] for w in fourthealth_widgets}
    expected = {
        t for t, e in WIDGET_CATALOG.items()
        if e["source_system"] == "4thealth" and t != "4thealth.ai_usage_24h"
    }
    assert types == expected
    assert all(w["source_instance"] == "4th-1" for w in fourthealth_widgets)


def test_default_layout_skips_disabled_sources():
    sources_module.add_source(
        id="4th-1", system="4thealth", name="A", base_url="https://a", token="t", enabled=False
    )

    layout = default_layout()
    types = {w["type"] for w in layout}
    assert types == {"4texecutive.cpu_percent", "4texecutive.memory_percent", "4texecutive.disk_percent"}


def test_default_layout_covers_multiple_source_instances():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")
    sources_module.add_source(id="4th-2", system="4thealth", name="B", base_url="https://b", token="t")

    layout = default_layout()

    instances = {w["source_instance"] for w in layout if w["type"].startswith("4thealth.")}
    assert instances == {"4th-1", "4th-2"}


def test_default_layout_ignores_source_whose_system_has_no_widgets():
    sources_module.add_source(id="x", system="unmapped-system", name="A", base_url="https://a", token="t")

    layout = default_layout()
    types = {w["type"] for w in layout}
    assert types == {"4texecutive.cpu_percent", "4texecutive.memory_percent", "4texecutive.disk_percent"}


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


def test_catalog_contains_ai_usage_widget():
    assert "4thealth.ai_usage_24h" in WIDGET_CATALOG
    assert WIDGET_CATALOG["4thealth.ai_usage_24h"]["field"] == "ai_usage_24h"


def test_default_layout_excludes_ai_widget_when_ai_not_enabled():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")
    write_snapshot("4th-1", "summary", {"hygiene_score": 92}, "2026-08-27T10:00:00Z")

    layout = default_layout()

    assert "4thealth.ai_usage_24h" not in {w["type"] for w in layout}


def test_default_layout_excludes_ai_widget_when_source_never_polled():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")

    layout = default_layout()

    assert "4thealth.ai_usage_24h" not in {w["type"] for w in layout}


def test_default_layout_includes_ai_widget_when_ai_enabled_true():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")
    write_snapshot(
        "4th-1", "summary",
        {"ai_enabled": True, "ai_connection_count_24h": 340, "ai_estimated_cost_24h_usd": 4.10},
        "2026-08-27T10:00:00Z",
    )

    layout = default_layout()

    ai_widgets = [w for w in layout if w["type"] == "4thealth.ai_usage_24h"]
    assert len(ai_widgets) == 1
    assert ai_widgets[0]["source_instance"] == "4th-1"


def test_catalog_contains_host_metric_widgets():
    assert "4texecutive.cpu_percent" in WIDGET_CATALOG
    assert "4texecutive.memory_percent" in WIDGET_CATALOG
    assert "4texecutive.disk_percent" in WIDGET_CATALOG
    assert WIDGET_CATALOG["4texecutive.cpu_percent"]["source_system"] == "4texecutive"


def test_default_layout_always_includes_host_metric_widgets_even_with_no_sources():
    layout = default_layout()

    types = {w["type"] for w in layout}
    assert "4texecutive.cpu_percent" in types
    assert "4texecutive.memory_percent" in types
    assert "4texecutive.disk_percent" in types
    host_widgets = [w for w in layout if w["type"].startswith("4texecutive.")]
    assert all(w["source_instance"] == "_self" for w in host_widgets)


def test_get_widget_value_for_host_cpu_percent():
    write_snapshot("_self", "summary", {"cpu_percent": 34.5, "memory_percent": 61.2, "disk_percent": 47.0}, "2026-08-27T10:00:00Z")
    widget = {"type": "4texecutive.cpu_percent", "source_instance": "_self"}

    assert get_widget_value(widget) == {"value": 34.5, "collected_at": "2026-08-27T10:00:00Z"}


def test_downsample_returns_points_unchanged_when_under_limit():
    points = [("t0", 1), ("t1", 2), ("t2", 3)]
    assert _downsample(points, max_points=80) == points


def test_downsample_returns_points_unchanged_when_exactly_at_limit():
    points = [(f"t{i}", i) for i in range(80)]
    assert _downsample(points, max_points=80) == points


def test_downsample_buckets_to_max_points_when_over_limit():
    points = [(f"t{i}", i) for i in range(100)]
    result = _downsample(points, max_points=10)
    assert len(result) == 10


def test_downsample_first_bucket_averages_and_rounds_int_inputs():
    points = [(f"t{i}", i) for i in range(100)]
    result = _downsample(points, max_points=10)
    assert result[0][0] == "t0"
    assert result[0][1] == round(sum(range(10)) / 10)


def test_downsample_keeps_float_precision_for_float_inputs():
    points = [(f"t{i}", i + 0.5) for i in range(20)]
    result = _downsample(points, max_points=5)
    assert len(result) == 5
    first_chunk_avg = sum(i + 0.5 for i in range(4)) / 4
    assert result[0][1] == round(first_chunk_avg, 2)


def test_downsample_empty_list_returns_empty_list():
    assert _downsample([], max_points=80) == []


def test_downsample_non_multiple_case_produces_exact_output_count():
    """Test non-multiple input size (n=100, max_points=80) produces exactly max_points buckets."""
    points = [(f"t{i}", i) for i in range(100)]
    result = _downsample(points, max_points=80)
    assert len(result) == 80


def test_catalog_marks_expected_widgets_with_chart_type():
    line_types = [
        "4thealth.firewall_online_count",
        "4thealth.firewall_managed_count",
        "4thealth.rule_count_total",
        "4thealth.adom_count",
        "4thealth.ai_usage_24h",
        "4texecutive.cpu_percent",
        "4texecutive.memory_percent",
        "4texecutive.disk_percent",
    ]
    for widget_type in line_types:
        assert WIDGET_CATALOG[widget_type]["chart_type"] == "line"
    assert WIDGET_CATALOG["4thealth.version_breakdown"]["chart_type"] == "bar"
    assert "chart_type" not in WIDGET_CATALOG["4thealth.hygiene_score"]
    assert "chart_type" not in WIDGET_CATALOG["4thealth.last_backup_status"]


def test_get_widget_series_delegates_to_get_widget_value_for_unflagged_widget():
    write_snapshot("s1", "summary", {"hygiene_score": 92}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result == {"value": 92, "collected_at": "2026-08-27T10:00:00Z"}
    assert "chart" not in result


def test_get_widget_series_line_builds_points_from_history_within_range():
    write_snapshot("s1", "summary", {"firewall_managed_count": 10}, _iso(600))
    write_snapshot("s1", "summary", {"firewall_managed_count": 20}, _iso(30))
    write_snapshot("s1", "summary", {"firewall_managed_count": 30}, _iso(5))
    widget = {"type": "4thealth.firewall_managed_count", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result["chart"] == "line"
    assert [v for _, v in result["points"]] == [10, 20, 30]
    assert result["min"] == 10
    assert result["max"] == 30
    assert result["collected_at"] is not None


def test_get_widget_series_line_excludes_snapshots_outside_range():
    write_snapshot("s1", "summary", {"firewall_managed_count": 999}, _iso(60 * 24 * 40))  # 40 days ago
    write_snapshot("s1", "summary", {"firewall_managed_count": 5}, _iso(10))
    widget = {"type": "4thealth.firewall_managed_count", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert [v for _, v in result["points"]] == [5]


def test_get_widget_series_line_no_history_returns_empty_chart():
    widget = {"type": "4thealth.firewall_managed_count", "source_instance": "unpolled"}

    result = get_widget_series(widget, "1d")

    assert result == {
        "chart": "line",
        "points": [],
        "min": None,
        "max": None,
        "extra_label": None,
        "collected_at": None,
    }


def test_get_widget_series_bar_uses_latest_snapshot_only_ignoring_range():
    write_snapshot(
        "s1", "summary",
        {"version_breakdown": {"7.4.5": 62, "7.2.9": 41}},
        _iso(5),
    )
    widget = {"type": "4thealth.version_breakdown", "source_instance": "s1"}

    result = get_widget_series(widget, "4h")

    assert result["chart"] == "bar"
    assert result["data"] == {"7.4.5": 62, "7.2.9": 41}
    assert result["collected_at"] is not None


def test_get_widget_series_bar_no_snapshot_returns_empty_chart():
    widget = {"type": "4thealth.version_breakdown", "source_instance": "unpolled"}

    result = get_widget_series(widget, "1d")

    assert result == {"chart": "bar", "data": {}, "collected_at": None}


def test_get_widget_series_ai_usage_charts_connection_count_and_carries_cost():
    write_snapshot(
        "s1", "summary",
        {"ai_usage_24h": {"ai_connection_count_24h": 100, "ai_estimated_cost_24h_usd": 1.5}},
        _iso(30),
    )
    write_snapshot(
        "s1", "summary",
        {"ai_usage_24h": {"ai_connection_count_24h": 340, "ai_estimated_cost_24h_usd": 4.1}},
        _iso(5),
    )
    widget = {"type": "4thealth.ai_usage_24h", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result["chart"] == "line"
    assert [v for _, v in result["points"]] == [100, 340]
    assert result["extra_label"] == "$4.10 est. cost (24h)"


def test_get_widget_series_downsamples_long_line_series():
    for i in range(200):
        write_snapshot("s1", "summary", {"cpu_percent": i % 100}, _iso(200 - i))
    widget = {"type": "4texecutive.cpu_percent", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert len(result["points"]) <= 80
