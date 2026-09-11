"""Tests for the Trend Board's row-building, target/progress, sort, filter, and CSV logic."""

import csv
import io
from datetime import UTC, datetime, timedelta

import pytest

import app.sources as sources_module
from app import metrics_db
from app.board import DOMAIN_ORDER, WIDGET_DOMAIN, build_rows, rows_to_csv
from app.metrics_db import init_db, insert_metric_points, write_snapshot
from app.sources import add_source
from app.widgets import WIDGET_CATALOG


def _iso(minutes_ago: int = 0, at: datetime | None = None) -> str:
    base = at or datetime.now(UTC)
    return (base - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    init_db()


def _add_source(source_id, system, **overrides):
    base = {"id": source_id, "system": system, "name": source_id, "enabled": True}
    base.update(overrides)
    add_source(
        id=base["id"],
        system=base["system"],
        name=base["name"],
        base_url="https://example.internal",
        token="secret",
        enabled=base["enabled"],
    )


def test_every_non_host_catalog_entry_is_mapped_to_a_domain():
    for widget_type, entry in WIDGET_CATALOG.items():
        if entry["source_system"] == "4texecutive":
            continue
        assert widget_type in WIDGET_DOMAIN, widget_type
        assert WIDGET_DOMAIN[widget_type] in DOMAIN_ORDER


def test_build_rows_basic_fields():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    insert_metric_points("s1", _iso(5), {"hygiene_score": 88.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d")

    row = next(r for r in rows if r["widget_type"] == "4thealth.hygiene_score")
    assert row["now"] == 88.0
    assert row["source_instance"] == "s1"
    assert row["domain"] == "posture"
    assert row["unit"] is None


def test_build_rows_adom_filter_reads_by_adom_value():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"pending_config_diff_count": 100}, _iso(5))
    insert_metric_points("s1", _iso(5), {
        "pending_config_diff_count": 100.0,
        "by_adom.Corp.pending_config_diff_count": 42.0,
    })

    fleet_rows = build_rows(compare_to="yesterday", sparkline="30d")
    corp_rows = build_rows(compare_to="yesterday", sparkline="30d", adom="Corp")

    fleet_row = next(r for r in fleet_rows if r["widget_type"] == "4thealth.pending_config_diffs")
    corp_row = next(r for r in corp_rows if r["widget_type"] == "4thealth.pending_config_diffs")
    assert fleet_row["now"] == 100.0
    assert fleet_row["adom_scoped"] is False
    assert corp_row["now"] == 42.0
    assert corp_row["adom_scoped"] is True


def test_build_rows_adom_filter_leaves_unmapped_metrics_at_fleet_value():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    insert_metric_points("s1", _iso(5), {"hygiene_score": 88.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d", adom="Corp")

    row = next(r for r in rows if r["widget_type"] == "4thealth.hygiene_score")
    assert row["now"] == 88.0  # no by_adom breakdown for hygiene_score -> unaffected
    assert row["adom_scoped"] is False


def test_build_rows_adom_filter_none_when_adom_has_no_data():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"pending_config_diff_count": 100}, _iso(5))
    insert_metric_points("s1", _iso(5), {"pending_config_diff_count": 100.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d", adom="NoDataADOM")

    row = next(r for r in rows if r["widget_type"] == "4thealth.pending_config_diffs")
    assert row["now"] is None


def test_build_rows_percent_unit_for_pct_metric():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1", "summary", {"firewall_online_count": 9, "firewall_managed_count": 10}, _iso(5)
    )
    insert_metric_points(
        "s1", _iso(5), {"firewall_online_count": 9.0, "firewall_managed_count": 10.0, "fleet_availability_pct": 90.0}
    )

    rows = build_rows(compare_to="yesterday", sparkline="30d")

    row = next(r for r in rows if r["widget_type"] == "4thealth.fleet_availability")
    assert row["unit"] == "%"
    assert row["now"] == 90.0


def test_build_rows_delta_vs_30d_independent_of_compare_to():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 95}, _iso(5))
    insert_metric_points("s1", _iso(60 * 24 * 40), {"hygiene_score": 60.0})  # 40 days ago
    insert_metric_points("s1", _iso(60 * 24 * 8), {"hygiene_score": 70.0})  # 8 days ago
    insert_metric_points("s1", _iso(5), {"hygiene_score": 95.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d")

    row = next(r for r in rows if r["widget_type"] == "4thealth.hygiene_score")
    # vs 30d baseline (~60.0, the closest point at-or-before 30d ago)
    assert row["delta_30d"] == pytest.approx(35.0, abs=0.01)
    assert row["better_30d"] is True


def test_build_rows_target_and_progress_for_higher_direction():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 45}, _iso(5))
    insert_metric_points("s1", _iso(5), {"hygiene_score": 45.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d")

    row = next(r for r in rows if r["widget_type"] == "4thealth.hygiene_score")
    assert row["target"] == 90  # green threshold
    assert row["progress"] == pytest.approx(0.5, abs=0.01)  # 45/90


def test_build_rows_target_and_progress_for_lower_direction():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"pending_config_diff_count": 4}, _iso(5))
    insert_metric_points("s1", _iso(5), {"pending_config_diff_count": 4.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d")

    row = next(r for r in rows if r["widget_type"] == "4thealth.pending_config_diffs")
    assert row["target"] == 0  # green threshold
    assert row["progress"] == pytest.approx(0.2, abs=0.01)  # 1 - 4/5 (amber=5)


def test_build_rows_no_meter_for_informational_widget():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"rule_count_total": 4000}, _iso(5))
    insert_metric_points("s1", _iso(5), {"rule_count_total": 4000.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d")

    row = next(r for r in rows if r["widget_type"] == "4thealth.rule_count_total")
    assert row["target"] is None
    assert row["progress"] is None
    assert row["status"] == "gray"


def test_build_rows_no_meter_when_threshold_is_degenerate_zero():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {"device_review": {"devices_reviewed": 10, "devices_with_failures": 2}},
        _iso(5),
    )
    insert_metric_points("s1", _iso(5), {"device_review.devices_with_failures": 2.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d")

    row = next(r for r in rows if r["widget_type"] == "4thealth.device_review_posture")
    # amber threshold is 0 (degenerate) -> guarded, no divide-by-zero, no meter
    assert row["progress"] is None


def test_build_rows_filters_by_domain():
    _add_source("s1", "4thealth")
    _add_source("s2", "4tlog")
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    write_snapshot("s2", "summary", {"devices_silent": 2, "devices_logging": 10}, _iso(5))

    rows = build_rows(compare_to="yesterday", sparkline="30d", domain_filter="logging")

    assert rows
    assert all(r["domain"] == "logging" for r in rows)


def test_build_rows_filters_by_source():
    _add_source("s1", "4thealth")
    _add_source("s2", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    write_snapshot("s2", "summary", {"hygiene_score": 70}, _iso(5))

    rows = build_rows(compare_to="yesterday", sparkline="30d", source_filter="s1")

    assert rows
    assert all(r["source_instance"] == "s1" for r in rows)


def test_build_rows_sorted_by_status_severity_within_domain_order():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {"hygiene_score": 40, "version_compliance_pct": 99, "pending_config_diff_count": 0},
        _iso(5),
    )
    insert_metric_points(
        "s1", _iso(5), {"hygiene_score": 40.0, "version_compliance_pct": 99.0, "pending_config_diff_count": 0.0}
    )

    rows = build_rows(compare_to="yesterday", sparkline="30d", sort="status")

    statuses = [r["status"] for r in rows if r["domain"] == "posture"]
    order = {"red": 0, "amber": 1, "green": 2, "gray": 3, None: 4}
    assert statuses == sorted(statuses, key=lambda s: order[s])


def test_build_rows_sorted_by_name():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 88, "adom_count": 3}, _iso(5))

    rows = build_rows(compare_to="yesterday", sparkline="30d", sort="name")

    availability_names = [r["label"] for r in rows if r["domain"] == "availability"]
    # build_rows sorts by r["label"].lower() (case-insensitive) — compare
    # against that same key, not a bare case-sensitive sort.
    assert availability_names == sorted(availability_names, key=str.lower)


def test_build_rows_sorted_by_delta_largest_absolute_first():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1", "summary", {"hygiene_score": 95, "version_compliance_pct": 91}, _iso(5)
    )
    insert_metric_points("s1", _iso(60 * 25), {"hygiene_score": 50.0, "version_compliance_pct": 90.0})
    insert_metric_points("s1", _iso(5), {"hygiene_score": 95.0, "version_compliance_pct": 91.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d", sort="delta")

    posture_rows = [r for r in rows if r["domain"] == "posture" and r["delta_compare_to"] is not None]
    deltas = [abs(r["delta_compare_to"]) for r in posture_rows]
    assert deltas == sorted(deltas, reverse=True)


def test_build_rows_stale_flag_present_from_annotate():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {"hygiene_score": 92, "hygiene_sweep_status": "ok", "hygiene_sweep_collected_at": _iso(200)},
        _iso(5),
    )
    insert_metric_points("s1", _iso(5), {"hygiene_score": 92.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d")

    row = next(r for r in rows if r["widget_type"] == "4thealth.hygiene_score")
    assert row["stale"] is True


def test_rows_to_csv_includes_header_and_values():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    insert_metric_points("s1", _iso(5), {"hygiene_score": 88.0})

    rows = build_rows(compare_to="yesterday", sparkline="30d")
    csv_text = rows_to_csv(rows)

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = reader.fieldnames
    assert "Metric" in fieldnames
    assert "Now" in fieldnames
    body = list(reader)
    hygiene_row = next(r for r in body if r["Metric"] == "Hygiene Score")
    assert hygiene_row["Now"] == "88.0"
