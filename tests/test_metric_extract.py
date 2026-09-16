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


def test_extract_all_covers_psirt_fields():
    payload = {
        "psirt": {
            "open_advisories": 3,
            "devices_critical": 5,
            "devices_high": 2,
            "devices_medium": 1,
            "devices_critical_mitigated": 1.0,
            "kev_exposed_devices": 2,
            "mean_days_to_remediate_90d": 12.5,
            "top_advisory": {"advisory_id": "FG-IR-24-001", "cvss": 9.8, "kev": True, "devices": 5},
        }
    }
    points = extract_all(payload)
    assert points["psirt.open_advisories"] == 3.0
    assert points["psirt.devices_critical"] == 5.0
    assert points["psirt.devices_high"] == 2.0
    assert points["psirt.devices_medium"] == 1.0
    assert points["psirt.devices_critical_mitigated"] == 1.0
    assert points["psirt.kev_exposed_devices"] == 2.0
    assert points["psirt.mean_days_to_remediate_90d"] == 12.5
    assert "psirt" not in points
    assert "psirt.top_advisory" not in points


def test_extract_all_omits_psirt_keys_when_absent():
    points = extract_all({"hygiene_score": 92})
    assert "psirt.devices_critical" not in points
    assert "psirt.kev_exposed_devices" not in points


def test_extract_all_covers_change_control_fields():
    payload = {
        "change_control": {
            "devices_out_of_sync": 4,
            "admin_changes_24h": 12,
            "admin_changes_by_user": [{"user": "alice", "count": 8}],
            "collected_at": "2026-09-10T01:00:00Z",
        }
    }
    points = extract_all(payload)
    assert points["change_control.devices_out_of_sync"] == 4.0
    assert points["change_control.admin_changes_24h"] == 12.0
    assert "change_control" not in points
    assert "change_control.admin_changes_by_user" not in points


def test_extract_all_omits_change_control_keys_when_absent():
    points = extract_all({"hygiene_score": 92})
    assert "change_control.devices_out_of_sync" not in points
    assert "change_control.admin_changes_24h" not in points


def test_extract_all_covers_lifecycle_fields():
    payload = {
        "lifecycle": {
            "devices_hw_eos": 3,
            "devices_hw_eos_12m": 5,
            "models_unknown": ["FortiGate-Unicorn"],
            "collected_at": "2026-09-10T00:00:00Z",
        }
    }
    points = extract_all(payload)
    assert points["lifecycle.devices_hw_eos"] == 3.0
    assert points["lifecycle.devices_hw_eos_12m"] == 5.0
    assert "lifecycle" not in points
    assert "lifecycle.models_unknown" not in points


def test_extract_all_omits_lifecycle_keys_when_absent():
    points = extract_all({"hygiene_score": 92})
    assert "lifecycle.devices_hw_eos" not in points
    assert "lifecycle.devices_hw_eos_12m" not in points


def test_extract_all_computes_devices_on_eol_version():
    payload = {
        "version_breakdown": {
            "v7.4.5": {"count": 10, "eol": False},
            "v6.4.2": {"count": 3, "eol": True},
            "v6.0.5": {"count": 2, "eol": True},
        }
    }
    points = extract_all(payload)
    assert points["devices_on_eol_version"] == 5.0


def test_extract_all_devices_on_eol_version_none_when_no_breakdown():
    assert "devices_on_eol_version" not in extract_all({"hygiene_score": 92})


def test_extract_all_covers_by_adom_fields():
    from app.metric_extract import by_adom_metric_key

    payload = {
        "by_adom": {
            "Corp": {
                "firewalls_total": 10,
                "firewall_online_count": 9,
                "version_compliance_pct": 90.0,
                "pending_config_diff_count": 1,
                "devices_with_failures": 2,
            },
            "Branch": {"firewalls_total": 3, "firewall_online_count": 3},
        }
    }
    points = extract_all(payload)
    assert points["by_adom.Corp.firewalls_total"] == 10.0
    assert points["by_adom.Corp.devices_with_failures"] == 2.0
    assert points["by_adom.Branch.firewall_online_count"] == 3.0
    assert "by_adom.Branch.devices_with_failures" not in points
    assert "by_adom" not in points

    assert by_adom_metric_key("firewall_managed_count", "Corp") == "by_adom.Corp.firewalls_total"
    assert by_adom_metric_key("firewall_online_count", "Corp") == "by_adom.Corp.firewall_online_count"
    assert by_adom_metric_key("hygiene_score", "Corp") is None


def test_extract_all_omits_by_adom_when_absent():
    points = extract_all({"hygiene_score": 92})
    assert not any(k.startswith("by_adom.") for k in points)


def test_extract_all_devices_on_eol_version_zero_when_none_are_eol():
    payload = {"version_breakdown": {"v7.4.5": {"count": 10, "eol": False}}}
    assert extract_all(payload)["devices_on_eol_version"] == 0.0


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


def test_extract_all_covers_license_status_fields():
    payload = {
        "license_status": {
            "devices_licensed": 40,
            "devices_expired": 2,
            "devices_unknown": 1,
            "details": [{"device": "fw-a", "adom": "Corp", "status": "expired", "expires": None}],
            "devices_expiring_30": 3,
            "devices_expiring_60": 5,
            "devices_expiring_90": 8,
            "expiring_soon": [
                {"device": "fw-b", "adom": "Corp", "expires": "2026-10-01", "days_until": 15}
            ],
            "collected_at": "2026-09-16T03:00:00Z",
        }
    }
    points = extract_all(payload)
    assert points["license_status.devices_licensed"] == 40.0
    assert points["license_status.devices_expired"] == 2.0
    assert points["license_status.devices_unknown"] == 1.0
    assert points["license_status.devices_expiring_30"] == 3.0
    assert points["license_status.devices_expiring_60"] == 5.0
    assert points["license_status.devices_expiring_90"] == 8.0
    assert "license_status" not in points
    assert "license_status.details" not in points
    assert "license_status.expiring_soon" not in points


def test_extract_all_omits_license_status_keys_when_absent():
    points = extract_all({"hygiene_score": 92})
    assert "license_status.devices_licensed" not in points
    assert "license_status.devices_expired" not in points
    assert "license_status.devices_unknown" not in points
    assert "license_status.devices_expiring_30" not in points
    assert "license_status.devices_expiring_60" not in points
    assert "license_status.devices_expiring_90" not in points
