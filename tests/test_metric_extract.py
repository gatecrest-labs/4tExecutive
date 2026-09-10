"""Tests for the derived metric-point extractor registry and backfill/retention."""

import pytest

from app import metrics_db
from app.metric_extract import (
    EXTRACTORS,
    apply_retention,
    backfill,
    extract_all,
)
from app.metrics_db import get_metric_series, init_db, write_snapshot
from app.widgets import WIDGET_CATALOG


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    init_db()


def test_every_catalog_field_has_an_extractor():
    catalog_fields = {entry["field"] for entry in WIDGET_CATALOG.values()}
    for field in catalog_fields:
        assert field in EXTRACTORS, f"missing extractor for catalog field {field!r}"


def test_extract_all_covers_required_nested_and_derived_keys():
    payload = {
        "hygiene_score": 92,
        "firewall_online_count": 8,
        "firewall_managed_count": 10,
        "devices_silent": 2,
        "faz_disk_used_pct": 55,
        "device_review": {
            "devices_with_failures": 3,
            "findings_by_severity": {"critical": 1, "high": 2, "medium": 3, "low": 4},
        },
        "rule_hygiene": {
            "rule_findings_total": 7,
            "rule_findings_by_type": {"shadowed_rule": 4, "unhit_rule": 3},
        },
    }

    points = extract_all(payload)

    assert points["hygiene_score"] == 92.0
    assert points["fleet_availability_pct"] == 80.0
    assert points["devices_silent"] == 2.0
    assert points["faz_disk_used_pct"] == 55.0
    assert points["device_review.devices_with_failures"] == 3.0
    assert points["device_review.findings_by_severity.critical"] == 1.0
    assert points["device_review.findings_by_severity.high"] == 2.0
    assert points["device_review.findings_by_severity.medium"] == 3.0
    assert points["device_review.findings_by_severity.low"] == 4.0
    assert points["rule_hygiene.rule_findings_total"] == 7.0
    assert points["rule_hygiene.rule_findings_by_type.shadowed_rule"] == 4.0
    assert points["rule_hygiene.rule_findings_by_type.unhit_rule"] == 3.0


def test_extract_all_encodes_last_backup_status_as_1_or_0():
    assert extract_all({"last_backup_status": "ok"})["last_backup_status"] == 1.0
    assert extract_all({"last_backup_status": "error: timeout"})["last_backup_status"] == 0.0


def test_extract_all_omits_keys_it_cannot_derive():
    points = extract_all({"hygiene_score": 92})
    assert "fleet_availability_pct" not in points
    assert "device_review.devices_with_failures" not in points


def test_extract_all_skips_composite_dict_fields_with_no_single_scalar():
    points = extract_all({"version_breakdown": {"7.0": 5, "7.2": 10}})
    assert "version_breakdown" not in points


def test_backfill_walks_existing_snapshots_into_metric_points():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-08-24T08:00:00Z")
    write_snapshot("s1", "summary", {"hygiene_score": 95}, "2026-08-24T09:00:00Z")

    backfill()

    series = get_metric_series("s1", "hygiene_score", since="2026-01-01T00:00:00Z")
    assert series == [
        {"ts": "2026-08-24T08:00:00Z", "value": 90.0},
        {"ts": "2026-08-24T09:00:00Z", "value": 95.0},
    ]


def test_backfill_is_idempotent():
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-08-24T08:00:00Z")

    backfill()
    backfill()

    series = get_metric_series("s1", "hygiene_score", since="2026-01-01T00:00:00Z")
    assert series == [{"ts": "2026-08-24T08:00:00Z", "value": 90.0}]


def test_apply_retention_prunes_and_downsamples(monkeypatch):
    from datetime import UTC, datetime

    import app.metric_extract as metric_extract_module
    from app.metrics_db import get_history, insert_metric_points

    write_snapshot("s1", "summary", {"v": 1}, "2020-01-01T00:00:00Z")
    # Older than the 90-day snapshot/downsample cutoff but newer than the
    # 13-month metric_points cutoff: should downsample to one daily point.
    insert_metric_points("s1", "2026-01-01T01:00:00Z", {"hygiene_score": 80.0})
    insert_metric_points("s1", "2026-01-01T13:00:00Z", {"hygiene_score": 90.0})
    # Older than the 13-month cutoff entirely: should be pruned.
    insert_metric_points("s1", "2010-01-01T00:00:00Z", {"hygiene_score": 50.0})

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 10, tzinfo=UTC)

    monkeypatch.setattr(metric_extract_module, "datetime", _FixedDatetime)

    apply_retention()

    assert get_history("s1", "summary", since="2000-01-01T00:00:00Z") == []
    series = get_metric_series("s1", "hygiene_score", since="2000-01-01T00:00:00Z")
    assert series == [{"ts": "2026-01-01T00:00:00Z", "value": 85.0}]
