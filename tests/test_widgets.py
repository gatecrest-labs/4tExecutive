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

    assert result == {"value": 92, "collected_at": "2026-08-24T10:00:00Z", "rag": "green"}


def test_get_widget_value_rag_amber_between_thresholds():
    write_snapshot("s1", "summary", {"hygiene_score": 80}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    assert get_widget_value(widget)["rag"] == "amber"


def test_get_widget_value_rag_red_below_thresholds():
    write_snapshot("s1", "summary", {"hygiene_score": 40}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    assert get_widget_value(widget)["rag"] == "red"


def test_get_widget_value_no_rag_key_for_informational_widget():
    write_snapshot("s1", "summary", {"rule_count_total": 14200}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.rule_count_total", "source_instance": "s1"}

    result = get_widget_value(widget)

    assert "rag" not in result


def test_get_widget_value_rag_none_when_value_missing():
    write_snapshot("s1", "summary", {"some_other_field": 1}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    result = get_widget_value(widget)

    assert result["value"] is None
    assert result["rag"] is None


def test_get_widget_value_rag_lower_direction_for_pending_config_diffs():
    write_snapshot("s1", "summary", {"pending_config_diff_count": 0}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.pending_config_diffs", "source_instance": "s1"}
    assert get_widget_value(widget)["rag"] == "green"

    write_snapshot("s1", "summary", {"pending_config_diff_count": 3}, "2026-08-27T10:01:00Z")
    assert get_widget_value(widget)["rag"] == "amber"

    write_snapshot("s1", "summary", {"pending_config_diff_count": 9}, "2026-08-27T10:02:00Z")
    assert get_widget_value(widget)["rag"] == "red"


def test_get_widget_value_rag_string_ok_for_backup_status():
    write_snapshot("s1", "summary", {"last_backup_status": "ok"}, "2026-08-27T10:00:00Z")
    widget = {"type": "4thealth.last_backup_status", "source_instance": "s1"}
    assert get_widget_value(widget)["rag"] == "green"

    write_snapshot("s1", "summary", {"last_backup_status": "failed: disk full"}, "2026-08-27T10:01:00Z")
    assert get_widget_value(widget)["rag"] == "red"


def test_widget_catalog_backup_widget_relabeled():
    assert WIDGET_CATALOG["4thealth.last_backup_status"]["label"] == "App Config Backup"


def test_get_widget_value_returns_none_when_no_snapshot_yet():
    widget = {"type": "4thealth.hygiene_score", "source_instance": "unpolled-source"}
    assert get_widget_value(widget) is None


def test_get_widget_value_raises_for_unknown_widget_type():
    widget = {"type": "not.a.real.widget", "source_instance": "x"}
    with pytest.raises(KeyError):
        get_widget_value(widget)


def test_default_layout_empty_when_no_sources():
    layout = default_layout()
    assert layout == []


def test_default_layout_no_longer_includes_host_metrics():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")

    layout = default_layout()

    types = {w["type"] for w in layout}
    assert "4texecutive.cpu_percent" not in types
    assert "4texecutive.memory_percent" not in types
    assert "4texecutive.disk_percent" not in types


def test_default_layout_one_widget_per_catalog_entry_per_matching_source():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")

    layout = default_layout()

    fourthealth_widgets = [w for w in layout if w["type"].startswith("4thealth.")]
    types = {w["type"] for w in fourthealth_widgets}
    # ai_usage_24h, device_review_posture and rule_hygiene are only added to the
    # auto-generated default when the source's latest snapshot actually carries
    # the corresponding payload field — no snapshot here, so none of them appear.
    excluded = {
        "4thealth.ai_usage_24h",
        "4thealth.device_review_posture",
        "4thealth.rule_hygiene",
        "4thealth.firewall_online_count",
        "4thealth.firewall_managed_count",
    }
    expected = {
        t for t, e in WIDGET_CATALOG.items()
        if e["source_system"] == "4thealth" and t not in excluded
    }
    assert types == expected
    assert all(w["source_instance"] == "4th-1" for w in fourthealth_widgets)


def test_default_layout_skips_disabled_sources():
    sources_module.add_source(
        id="4th-1", system="4thealth", name="A", base_url="https://a", token="t", enabled=False
    )

    layout = default_layout()
    types = {w["type"] for w in layout}
    assert types == set()


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
    assert types == set()


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


def test_default_layout_excludes_tier2_widgets_when_source_has_no_rollups():
    """A 4thealth+ release without Tier 2 must not get two always-empty tiles."""
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")
    write_snapshot("4th-1", "summary", {"hygiene_score": 92}, "2026-08-27T10:00:00Z")

    types = {w["type"] for w in default_layout()}

    assert "4thealth.device_review_posture" not in types
    assert "4thealth.rule_hygiene" not in types


def test_default_layout_includes_device_review_posture_when_rollup_present():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")
    write_snapshot(
        "4th-1", "summary",
        {"device_review": {"devices_reviewed": 10, "devices_with_failures": 1}},
        "2026-08-27T10:00:00Z",
    )

    widgets = [w for w in default_layout() if w["type"] == "4thealth.device_review_posture"]

    assert len(widgets) == 1
    assert widgets[0]["source_instance"] == "4th-1"


def test_default_layout_includes_rule_hygiene_when_rollup_present():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")
    write_snapshot(
        "4th-1", "summary",
        {"rule_hygiene": {"rule_findings_total": 100, "rule_findings_by_type": {"shadow": 4}}},
        "2026-08-27T10:00:00Z",
    )

    widgets = [w for w in default_layout() if w["type"] == "4thealth.rule_hygiene"]

    assert len(widgets) == 1
    assert widgets[0]["source_instance"] == "4th-1"


def test_catalog_contains_host_metric_widgets():
    assert "4texecutive.cpu_percent" in WIDGET_CATALOG
    assert "4texecutive.memory_percent" in WIDGET_CATALOG
    assert "4texecutive.disk_percent" in WIDGET_CATALOG
    assert WIDGET_CATALOG["4texecutive.cpu_percent"]["source_system"] == "4texecutive"


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

    assert result == {"value": 92, "collected_at": "2026-08-27T10:00:00Z", "rag": "green"}
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
        "delta": None,
        "breakdown": None,
        "by_feature": None,
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

    assert result == {"chart": "bar", "data": {}, "eol_versions": [], "collected_at": None}


def test_get_widget_series_version_breakdown_handles_new_eol_shape():
    write_snapshot(
        "s1", "summary",
        {"version_breakdown": {"7.4.5": {"count": 12, "eol": False}, "6.4.2": {"count": 3, "eol": True}}},
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.version_breakdown", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {"7.4.5": 12, "6.4.2": 3}
    assert result["eol_versions"] == ["6.4.2"]


def test_get_widget_series_version_breakdown_handles_old_flat_shape():
    write_snapshot(
        "s1", "summary", {"version_breakdown": {"7.4.5": 12, "6.4.2": 3}}, "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.version_breakdown", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {"7.4.5": 12, "6.4.2": 3}
    assert result["eol_versions"] == []


def test_get_widget_series_version_breakdown_empty_when_no_data():
    widget = {"type": "4thealth.version_breakdown", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {}
    assert result["eol_versions"] == []


def test_catalog_has_device_review_posture_widget():
    entry = WIDGET_CATALOG["4thealth.device_review_posture"]
    assert entry["source_system"] == "4thealth"
    assert entry["chart_type"] == "bar"
    assert entry["default_size"] == "2x2"


def test_get_widget_series_device_review_posture_computes_pass_fail_and_rag():
    write_snapshot(
        "s1", "summary",
        {
            "device_review": {
                "devices_reviewed": 42,
                "devices_with_failures": 7,
                "findings_by_severity": {"critical": 1, "high": 3, "medium": 9, "low": 4},
                "top_failing_checks": [{"check": "default_admin", "count": 5}],
                "collected_at": "2026-08-28T06:00:00Z",
            }
        },
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.device_review_posture", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {"Passing": 35, "Failing": 7}
    assert result["top_failing_checks"] == [{"check": "default_admin", "count": 5}]
    assert result["collected_at"] == "2026-08-28T09:00:00Z"
    assert result["rollup_collected_at"] == "2026-08-28T06:00:00Z"
    assert result["rag"] == "red"


def test_get_widget_series_device_review_posture_collected_at_is_poll_time_not_rollup_time():
    """collected_at must stay the 4tExecutive poll time like every other widget.

    The device-review rollup carries its own (legitimately much older, up to
    48h) timestamp; exposing that as collected_at poisoned the dashboard
    posture strip's freshness aggregate, which compares collected_at against
    2 * poll_interval_minutes.
    """
    write_snapshot(
        "s1", "summary",
        {
            "device_review": {
                "devices_reviewed": 20,
                "devices_with_failures": 2,
                "findings_by_severity": {"critical": 0},
                "top_failing_checks": [],
                "collected_at": "2026-08-26T01:00:00Z",
            }
        },
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.device_review_posture", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["collected_at"] == "2026-08-28T09:00:00Z"
    assert result["rollup_collected_at"] == "2026-08-26T01:00:00Z"


def test_get_widget_series_device_review_posture_green_when_no_critical_findings():
    write_snapshot(
        "s1", "summary",
        {
            "device_review": {
                "devices_reviewed": 10, "devices_with_failures": 0,
                "findings_by_severity": {"critical": 0, "high": 0, "medium": 0, "low": 0},
                "top_failing_checks": [], "collected_at": "2026-08-28T06:00:00Z",
            }
        },
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.device_review_posture", "source_instance": "s1"}

    assert get_widget_series(widget, "30d")["rag"] == "green"


def test_get_widget_series_device_review_posture_no_data_when_rollup_absent():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-08-28T09:00:00Z")
    widget = {"type": "4thealth.device_review_posture", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert result["data"] == {}
    assert "rag" not in result


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


def test_catalog_has_fleet_availability_widget():
    entry = WIDGET_CATALOG["4thealth.fleet_availability"]
    assert entry["source_system"] == "4thealth"
    assert entry["chart_type"] == "line"
    assert entry["rag"] == {"direction": "ratio", "green": 100, "amber": 90}


def test_default_layout_includes_fleet_availability_not_the_aliased_pair():
    sources_module.add_source(id="4th-1", system="4thealth", name="A", base_url="https://a", token="t")

    layout = default_layout()

    types = {w["type"] for w in layout}
    assert "4thealth.fleet_availability" in types
    assert "4thealth.firewall_online_count" not in types
    assert "4thealth.firewall_managed_count" not in types


def test_get_widget_series_fleet_availability_computes_percentage_points():
    write_snapshot(
        "s1", "summary", {"firewall_online_count": 8, "firewall_managed_count": 10}, _iso(30)
    )
    write_snapshot(
        "s1", "summary", {"firewall_online_count": 10, "firewall_managed_count": 10}, _iso(5)
    )
    widget = {"type": "4thealth.fleet_availability", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result["chart"] == "line"
    assert [v for _, v in result["points"]] == [80.0, 100.0]
    assert result["extra_label"] == "10 / 10 (100%)"
    assert result["rag"] == "green"


def test_get_widget_series_fleet_availability_amber_and_red():
    write_snapshot("s1", "summary", {"firewall_online_count": 9, "firewall_managed_count": 10}, _iso(5))
    result = get_widget_series({"type": "4thealth.fleet_availability", "source_instance": "s1"}, "1d")
    assert result["rag"] == "amber"

    write_snapshot("s1", "summary", {"firewall_online_count": 5, "firewall_managed_count": 10}, _iso(1))
    result = get_widget_series({"type": "4thealth.fleet_availability", "source_instance": "s1"}, "1d")
    assert result["rag"] == "red"


def test_get_widget_series_fleet_availability_skips_snapshots_missing_a_side():
    write_snapshot("s1", "summary", {"firewall_online_count": 8}, _iso(10))
    write_snapshot("s1", "summary", {"firewall_online_count": 9, "firewall_managed_count": 10}, _iso(5))

    result = get_widget_series({"type": "4thealth.fleet_availability", "source_instance": "s1"}, "1d")

    assert len(result["points"]) == 1


def test_get_widget_series_fleet_availability_rag_uses_raw_latest_not_downsampled_average():
    for i in range(97):
        write_snapshot(
            "s1", "summary", {"firewall_online_count": 10, "firewall_managed_count": 10}, _iso(300 - i)
        )
    # A transient dip a few minutes ago, followed by a fully healthy latest reading. Once
    # bucket-averaged together by _downsample, this pair would drag the last bucket's average
    # down to 75% (red), even though the raw latest snapshot is 100% (green).
    write_snapshot("s1", "summary", {"firewall_online_count": 5, "firewall_managed_count": 10}, _iso(3))
    write_snapshot("s1", "summary", {"firewall_online_count": 10, "firewall_managed_count": 10}, _iso(1))

    result = get_widget_series({"type": "4thealth.fleet_availability", "source_instance": "s1"}, "30d")

    assert len(result["points"]) <= 80
    assert result["rag"] == "green"


def test_get_widget_series_fleet_availability_delta_rounded_for_float_values():
    write_snapshot("s1", "summary", {"firewall_online_count": 8, "firewall_managed_count": 10}, _iso(30))
    write_snapshot("s1", "summary", {"firewall_online_count": 5, "firewall_managed_count": 6}, _iso(5))

    result = get_widget_series({"type": "4thealth.fleet_availability", "source_instance": "s1"}, "1d")

    assert result["delta"] == 3.3


def test_get_widget_series_line_includes_delta_when_two_or_more_points():
    write_snapshot("s1", "summary", {"rule_count_total": 100}, _iso(600))
    write_snapshot("s1", "summary", {"rule_count_total": 130}, _iso(5))

    result = get_widget_series({"type": "4thealth.rule_count_total", "source_instance": "s1"}, "30d")

    assert result["delta"] == 30


def test_get_widget_series_line_delta_none_with_one_point():
    write_snapshot("s1", "summary", {"rule_count_total": 100}, _iso(5))

    result = get_widget_series({"type": "4thealth.rule_count_total", "source_instance": "s1"}, "1d")

    assert result["delta"] is None


def test_get_widget_series_line_delta_none_with_no_history():
    result = get_widget_series({"type": "4thealth.rule_count_total", "source_instance": "s1"}, "1d")

    assert result["delta"] is None


def test_catalog_has_rule_hygiene_widget_with_no_rag():
    entry = WIDGET_CATALOG["4thealth.rule_hygiene"]
    assert entry["source_system"] == "4thealth"
    assert entry["chart_type"] == "line"
    assert "rag" not in entry


def test_get_widget_series_rule_hygiene_line_points_and_breakdown():
    write_snapshot(
        "s1", "summary",
        {"rule_hygiene": {"rule_findings_total": 100, "rule_findings_by_type": {"shadow": 4, "unhit": 60}}},
        _iso(600),
    )
    write_snapshot(
        "s1", "summary",
        {"rule_hygiene": {"rule_findings_total": 118, "rule_findings_by_type": {"shadow": 5, "unhit": 65}}},
        _iso(5),
    )
    widget = {"type": "4thealth.rule_hygiene", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert [v for _, v in result["points"]] == [100, 118]
    assert result["breakdown"] == {"shadow": 5, "unhit": 65}
    assert result["delta"] == 18
    assert "rag" not in result


def test_get_widget_series_rule_hygiene_skips_snapshots_without_rollup():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, _iso(10))
    write_snapshot(
        "s1", "summary",
        {"rule_hygiene": {"rule_findings_total": 118, "rule_findings_by_type": {}}},
        _iso(5),
    )
    widget = {"type": "4thealth.rule_hygiene", "source_instance": "s1"}

    result = get_widget_series(widget, "30d")

    assert len(result["points"]) == 1


def test_get_widget_series_ai_usage_includes_by_feature_breakdown_when_present():
    write_snapshot(
        "s1", "summary",
        {
            "ai_usage_24h": {"ai_connection_count_24h": 12, "ai_estimated_cost_24h_usd": 0.41},
            "ai_usage_by_feature": {"device_review_summary": {"calls": 5, "cost_usd": 0.2, "failures": 0}},
        },
        _iso(5),
    )
    widget = {"type": "4thealth.ai_usage_24h", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result["by_feature"] == {"device_review_summary": {"calls": 5, "cost_usd": 0.2, "failures": 0}}


def test_get_widget_series_ai_usage_by_feature_absent_when_not_in_payload():
    write_snapshot(
        "s1", "summary",
        {"ai_usage_24h": {"ai_connection_count_24h": 12, "ai_estimated_cost_24h_usd": 0.41}},
        _iso(5),
    )
    widget = {"type": "4thealth.ai_usage_24h", "source_instance": "s1"}

    result = get_widget_series(widget, "1d")

    assert result["by_feature"] is None


def test_get_widget_value_stale_true_when_field_group_collected_at_old():
    old_ts = (datetime.now(UTC) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_snapshot(
        "s1", "summary",
        {"hygiene_score": 90, "hygiene_sweep_collected_at": old_ts},
        "2026-08-28T09:00:00Z",  # poll-time collected_at is fresh; field-group collected_at is stale
    )
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    result = get_widget_value(widget)

    assert result["stale"] is True


def test_get_widget_value_stale_false_when_field_group_collected_at_recent():
    recent_ts = (datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_snapshot(
        "s1", "summary",
        {"hygiene_score": 90, "hygiene_sweep_collected_at": recent_ts},
        "2026-08-28T09:00:00Z",
    )
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    assert get_widget_value(widget)["stale"] is False


def test_get_widget_value_no_stale_key_when_field_group_collected_at_absent():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-08-28T09:00:00Z")
    widget = {"type": "4thealth.hygiene_score", "source_instance": "s1"}

    assert "stale" not in get_widget_value(widget)


def test_get_widget_value_no_stale_key_for_widget_type_without_a_field_group():
    write_snapshot("s1", "summary", {"adom_count": 4}, "2026-08-28T09:00:00Z")
    widget = {"type": "4thealth.adom_count", "source_instance": "s1"}

    assert "stale" not in get_widget_value(widget)
