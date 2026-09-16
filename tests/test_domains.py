"""Tests for domain scoring: aggregation, formulas, grades, overall rollup."""

from datetime import UTC, datetime, timedelta

import pytest

import app.sources as sources_module
from app import metrics_db
from app.domains import (
    DOMAINS,
    compute_domain,
    compute_overall,
    domain_member_table,
    get_infra_devices,
    get_scoring_config,
    grade_for,
    rag_for_grade,
    save_scoring_config,
    store_domain_scores,
)
from app.metrics_db import get_metric_series, init_db, insert_metric_points, write_snapshot
from app.sources import add_source


def _iso(minutes_ago: int = 0, at: datetime | None = None) -> str:
    base = at or datetime.now(UTC)
    return (base - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db, "DB_PATH", tmp_path / "metrics.db")
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    from app import config_paths

    config_dir = tmp_path / "config"
    monkeypatch.setattr(config_paths, "CONFIG_DIR", config_dir)
    import app.domains as domains_module

    monkeypatch.setattr(domains_module, "SCORING_PATH", config_dir / "scoring.json")
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


def test_grade_for_boundaries():
    assert grade_for(95) == "A"
    assert grade_for(90) == "A"
    assert grade_for(89.9) == "B"
    assert grade_for(80) == "B"
    assert grade_for(79.9) == "C"
    assert grade_for(70) == "C"
    assert grade_for(69.9) == "D"
    assert grade_for(60) == "D"
    assert grade_for(59.9) == "F"
    assert grade_for(None) is None


def test_rag_for_grade():
    assert rag_for_grade("A") == "green"
    assert rag_for_grade("B") == "green"
    assert rag_for_grade("C") == "amber"
    assert rag_for_grade("D") == "amber"
    assert rag_for_grade("F") == "red"
    assert rag_for_grade(None) is None


def test_compute_domain_availability_from_single_source():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 9.0, "firewall_managed_count": 10.0})

    result = compute_domain("availability")

    assert result["score"] == 90.0
    assert result["grade"] == "A"
    assert result["rag"] == "green"
    assert "9" in result["why"] and "10" in result["why"]


def test_compute_domain_availability_sums_across_multiple_sources():
    _add_source("s1", "4thealth")
    _add_source("s2", "4thealth")
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 60.0, "firewall_managed_count": 60.0})
    insert_metric_points("s2", _iso(5), {"firewall_online_count": 90.0, "firewall_managed_count": 100.0})

    result = compute_domain("availability")

    # (60+90)/(60+100) = 150/160 = 93.75, rounded to 1 decimal
    assert result["score"] == pytest.approx(93.8, abs=0.01)


def test_compute_domain_adom_filter_reads_by_adom_availability():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {
        "firewall_online_count": 100.0,
        "firewall_managed_count": 100.0,
        "by_adom.Corp.firewall_online_count": 5.0,
        "by_adom.Corp.firewalls_total": 10.0,
    })

    fleet = compute_domain("availability")
    corp = compute_domain("availability", adom="Corp")

    assert fleet["score"] == 100.0
    assert corp["score"] == 50.0  # 5/10 online for Corp specifically
    assert corp["inputs"]["firewall_online_count"] == 5.0
    assert corp["inputs"]["firewall_managed_count"] == 10.0


def test_domain_member_table_adom_filter_marks_scoped_rows():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {
        "firewall_online_count": 100.0,
        "firewall_managed_count": 100.0,
        "by_adom.Corp.firewall_online_count": 5.0,
        "by_adom.Corp.firewalls_total": 10.0,
    })

    rows = domain_member_table("availability", adom="Corp")

    online_row = next(r for r in rows if r["key"] == "firewall_online_count")
    assert online_row["now"] == 5.0
    assert online_row["adom_scoped"] is True

    admin_row = next(r for r in rows if r["key"] == "change_control.admin_changes_24h")
    assert admin_row["adom_scoped"] is False  # no by_adom breakdown for this field


def test_compute_domain_lifecycle_percentage_components_unaffected_by_adom_filter():
    """devices_on_eol_version/devices_hw_eos have no per-ADOM breakdown, so
    their percentage-of-fleet components must stay fleet-wide even when an
    ADOM filter is active — scoping only the denominator would corrupt the
    ratio."""
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {
        "version_compliance_pct": 100.0,
        "devices_on_eol_version": 10.0,
        "lifecycle.devices_hw_eos": 0.0,
        "firewall_managed_count": 100.0,
        "by_adom.Corp.version_compliance_pct": 100.0,
        "by_adom.Corp.firewalls_total": 5.0,
    })

    fleet = compute_domain("lifecycle")
    corp = compute_domain("lifecycle", adom="Corp")

    # Same firewall_managed_count denominator (100, fleet-wide) in both
    # cases -- if Corp's smaller device count (5) leaked in as the
    # denominator, the eol percentage would balloon to 10/5=200%+.
    assert fleet["score"] == corp["score"]


def test_compute_domain_availability_excludes_disabled_sources():
    _add_source("s1", "4thealth")
    _add_source("s2", "4thealth", enabled=False)
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 10.0, "firewall_managed_count": 10.0})
    insert_metric_points("s2", _iso(5), {"firewall_online_count": 0.0, "firewall_managed_count": 999.0})

    result = compute_domain("availability")

    assert result["score"] == 100.0


def test_compute_domain_not_measured_when_no_sources():
    result = compute_domain("availability")

    assert result["score"] is None
    assert result["grade"] is None
    assert result["rag"] is None


def test_compute_domain_lifecycle_not_measured_without_data():
    assert compute_domain("lifecycle")["score"] is None


def test_compute_domain_returns_not_measured_for_a_domain_with_no_system(monkeypatch):
    """The system-is-None short-circuit in compute_domain/domain_member_table
    is now dead code against the real DOMAINS table (every domain has a
    real system as of the lifecycle wiring) but is kept as a defensive
    guard for any future domain added ahead of its data source landing —
    exercise it directly rather than dropping the coverage."""
    import app.domains as domains_module

    monkeypatch.setitem(domains_module.DOMAINS, "future_domain", {"label": "Future", "system": None})
    monkeypatch.setitem(domains_module.MEMBER_METRICS, "future_domain", [{"key": "x", "label": "X"}])

    result = compute_domain("future_domain")
    assert result["score"] is None
    assert result["grade"] is None
    assert result["rag"] is None
    assert domain_member_table("future_domain") == []


def test_compute_domain_vulnerability_not_measured_without_psirt_data():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 100.0, "firewall_managed_count": 100.0})

    assert compute_domain("vulnerability")["score"] is None


def test_compute_domain_vulnerability_scoring():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "psirt.devices_critical": 2.0,
            "psirt.devices_high": 1.0,
            "psirt.devices_medium": 1.0,
            "psirt.kev_exposed_devices": 0.0,
        },
    )

    result = compute_domain("vulnerability")

    # top(critical=2, kev=0) = 2 -> penalty min(2*20, 60) = 40
    # high 1*3 = 3; medium 1*1 = 1
    # score = 100 - 40 - 3 - 1 = 56
    assert result["score"] == 56.0
    assert result["grade"] == "F"  # 56 < 60 on the normal scale too


def test_compute_domain_vulnerability_penalty_is_capped():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "psirt.devices_critical": 100.0,
            "psirt.devices_high": 100.0,
            "psirt.devices_medium": 100.0,
            "psirt.kev_exposed_devices": 0.0,
        },
    )

    result = compute_domain("vulnerability")

    assert result["score"] == 0.0  # 100 - 60 - 30 - 10


def test_compute_domain_vulnerability_grade_floors_to_f_on_any_kev_exposure():
    """Even a score that would otherwise be a passing letter grade must
    floor to F the moment any device is KEV-exposed — a single KEV hit is
    an escalation event, not something a good average should mask."""
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "psirt.devices_critical": 0.0,
            "psirt.devices_high": 0.0,
            "psirt.devices_medium": 0.0,
            "psirt.kev_exposed_devices": 1.0,
        },
    )

    result = compute_domain("vulnerability")

    # top(critical=0, kev=1) = 1 -> penalty 20 -> score 80, which alone
    # would be grade B — the KEV override must still floor it to F.
    assert result["score"] == 80.0
    assert result["grade"] == "F"
    assert result["rag"] == "red"


def test_compute_domain_vulnerability_no_kev_no_forced_grade():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "psirt.devices_critical": 0.0,
            "psirt.devices_high": 0.0,
            "psirt.devices_medium": 0.0,
            "psirt.kev_exposed_devices": 0.0,
        },
    )

    result = compute_domain("vulnerability")

    assert result["score"] == 100.0
    assert result["grade"] == "A"


def test_compute_domain_lifecycle_perfect_fleet():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "version_compliance_pct": 100.0,
            "devices_on_eol_version": 0.0,
            "lifecycle.devices_hw_eos": 0.0,
            "firewall_managed_count": 100.0,
        },
    )

    result = compute_domain("lifecycle")

    assert result["score"] == 100.0
    assert result["grade"] == "A"


def test_compute_domain_lifecycle_weighted_components():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "version_compliance_pct": 80.0,
            "devices_on_eol_version": 20.0,
            "lifecycle.devices_hw_eos": 10.0,
            "firewall_managed_count": 100.0,
        },
    )

    result = compute_domain("lifecycle")

    # firmware: 80 * 0.5 = 40
    # software-EOL component: (100 - 20) * 0.25 = 20
    # hardware-EOS component: (100 - 10) * 0.25 = 22.5
    # total = 82.5
    assert result["score"] == pytest.approx(82.5, abs=0.01)


def test_compute_domain_lifecycle_missing_component_defaults_to_optimistic_100():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {"version_compliance_pct": 60.0})

    result = compute_domain("lifecycle")

    # firmware: 60*0.5=30; software-EOL and hardware-EOS default to the
    # optimistic 100 component each (no data => not penalized).
    assert result["score"] == pytest.approx(30.0 + 25.0 + 25.0, abs=0.01)


def test_compute_domain_lifecycle_no_denominator_treats_percentages_as_zero():
    """Without firewall_managed_count there's no denominator for the
    percentage components — they must default to the fully-healthy 100
    rather than raising or fabricating a rate."""
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "version_compliance_pct": 90.0,
            "devices_on_eol_version": 5.0,
            "lifecycle.devices_hw_eos": 5.0,
        },
    )

    result = compute_domain("lifecycle")

    assert result["score"] == pytest.approx(90.0 * 0.5 + 25.0 + 25.0, abs=0.01)


def test_compute_domain_posture_weighted_average_and_failure_penalty():
    _add_source("s1", "4thealth")
    _add_source("s2", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {"hygiene_score": 80.0, "version_compliance_pct": 90.0, "firewall_managed_count": 100.0},
    )
    insert_metric_points(
        "s2",
        _iso(5),
        {"hygiene_score": 100.0, "version_compliance_pct": 100.0, "firewall_managed_count": 100.0},
    )
    insert_metric_points("s1", _iso(5), {"device_review.devices_with_failures": 3.0})

    result = compute_domain("posture")

    # weighted avg hygiene = (80*100 + 100*100) / 200 = 90
    # weighted avg compliance = (90*100 + 100*100) / 200 = 95
    # score = 100 - (100-90)*0.5 - (100-95)*0.3 - min(3*1, 20)
    #       = 100 - 5 - 1.5 - 3 = 90.5
    assert result["score"] == pytest.approx(90.5, abs=0.01)


def test_compute_domain_hygiene_findings_rate():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1", _iso(5), {"rule_hygiene.rule_findings_total": 10.0, "rule_count_total": 1000.0}
    )

    result = compute_domain("hygiene")

    # rate = 10/1000*1000 = 10 findings/1000 rules; penalty = 10*0.5 = 5
    assert result["score"] == pytest.approx(95.0, abs=0.01)


def test_compute_domain_hygiene_penalty_is_capped():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1", _iso(5), {"rule_hygiene.rule_findings_total": 10000.0, "rule_count_total": 100.0}
    )

    result = compute_domain("hygiene")

    assert result["score"] == 60.0  # 100 - cap(40)


def test_compute_domain_logging_silent_and_disk_penalty():
    _add_source("s1", "4tlog")
    _add_source("s2", "4tlog")
    insert_metric_points("s1", _iso(5), {"devices_silent": 2.0, "faz_disk_used_pct": 55.0})
    insert_metric_points("s2", _iso(5), {"devices_silent": 3.0, "faz_disk_used_pct": 80.0})

    result = compute_domain("logging")

    # silent total = 5 -> penalty min(5*3, 40) = 15
    # disk max = 80 -> penalty max(0, 80-70)*1 = 10
    # score = 100 - 15 - 10 = 75
    assert result["score"] == 75.0


def test_compute_domain_delta_against_baseline():
    _add_source("s1", "4thealth")
    eight_days_ago = datetime.now(UTC) - timedelta(days=8)
    insert_metric_points(
        "s1", _iso(at=eight_days_ago), {"firewall_online_count": 80.0, "firewall_managed_count": 100.0}
    )
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 95.0, "firewall_managed_count": 100.0})

    result = compute_domain("availability", compare_to="7d")

    assert result["score"] == 95.0
    assert result["delta"] == pytest.approx(15.0, abs=0.01)


def test_compute_domain_delta_is_none_without_baseline_data():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 95.0, "firewall_managed_count": 100.0})

    result = compute_domain("availability", compare_to="7d")

    assert result["delta"] is None


def test_compute_overall_weighted_mean_excludes_unmeasured_domains():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 100.0, "firewall_managed_count": 100.0})

    overall = compute_overall()

    config = get_scoring_config()
    assert overall["domains"]["vulnerability"]["score"] is None
    assert overall["domains"]["availability"]["score"] == 100.0
    # Every domain can be measured given the right metric_points, but only
    # availability has any here, so overall == availability's score exactly.
    assert overall["score"] == 100.0
    assert config["domain_weights"]["availability"] > 0


def test_compute_overall_is_none_when_nothing_measured():
    overall = compute_overall()

    assert overall["score"] is None
    assert overall["grade"] is None
    assert overall["rag"] is None


def test_compute_overall_rag_is_worst_of_measured_domains():
    _add_source("s1", "4thealth")
    _add_source("s2", "4tlog")
    # availability: perfect -> green
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 100.0, "firewall_managed_count": 100.0})
    # logging: heavy silent devices + full disk -> should push score into F/red
    insert_metric_points("s2", _iso(5), {"devices_silent": 100.0, "faz_disk_used_pct": 100.0})

    overall = compute_overall()

    assert overall["domains"]["logging"]["rag"] == "red"
    assert overall["domains"]["availability"]["rag"] == "green"
    assert overall["rag"] == "red"


def test_get_scoring_config_returns_sane_defaults_and_is_deep_merge_overridable():
    config = get_scoring_config()
    assert set(config["domain_weights"]) == set(DOMAINS)
    assert all(w >= 0 for w in config["domain_weights"].values())

    config["domain_weights"]["availability"] = 999
    config["domains"]["posture"]["hygiene_weight"] = 0.9
    save_scoring_config(config)

    reloaded = get_scoring_config()
    assert reloaded["domain_weights"]["availability"] == 999
    assert reloaded["domains"]["posture"]["hygiene_weight"] == 0.9
    # unrelated defaults survive the merge
    assert reloaded["domains"]["hygiene"]["points_per_1000_findings"] > 0


def test_store_domain_scores_writes_to_fleet_metric_points():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 90.0, "firewall_managed_count": 100.0})

    store_domain_scores()

    series = get_metric_series("_fleet", "domain.availability", since="2000-01-01T00:00:00Z")
    assert len(series) == 1
    assert series[0]["value"] == 90.0


def test_store_domain_scores_skips_unmeasured_domains():
    store_domain_scores()

    assert get_metric_series("_fleet", "domain.vulnerability", since="2000-01-01T00:00:00Z") == []


def test_domain_member_table_includes_now_delta_and_rag():
    _add_source("s1", "4thealth")
    eight_days_ago = datetime.now(UTC) - timedelta(days=8)
    insert_metric_points("s1", _iso(at=eight_days_ago), {"hygiene_score": 70.0})
    insert_metric_points("s1", _iso(5), {"hygiene_score": 95.0})

    rows = domain_member_table("posture", compare_to="7d")

    hygiene_row = next(r for r in rows if r["key"] == "hygiene_score")
    assert hygiene_row["now"] == 95.0
    assert hygiene_row["delta"] == pytest.approx(25.0, abs=0.01)
    assert hygiene_row["rag"] == "green"


def test_domain_member_table_includes_change_control_rows_with_rag():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "firewall_online_count": 100.0,
            "firewall_managed_count": 100.0,
            "change_control.devices_out_of_sync": 5.0,
            "change_control.admin_changes_24h": 12.0,
        },
    )

    rows = domain_member_table("availability")

    out_of_sync_row = next(r for r in rows if r["key"] == "change_control.devices_out_of_sync")
    assert out_of_sync_row["now"] == 5.0
    assert out_of_sync_row["rag"] == "red"  # lower/green0/amber3 -> 5 is red

    admin_changes_row = next(r for r in rows if r["key"] == "change_control.admin_changes_24h")
    assert admin_changes_row["now"] == 12.0
    # direction "none", no rag threshold configured -> informational only
    assert admin_changes_row["rag"] is None


def test_score_availability_ignores_change_control_inputs():
    """P8 only adds these as display rows on the domain member table — the
    Availability score formula itself must stay online/managed only."""
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "firewall_online_count": 100.0,
            "firewall_managed_count": 100.0,
            "change_control.devices_out_of_sync": 999.0,
            "change_control.admin_changes_24h": 999.0,
        },
    )

    result = compute_domain("availability")

    assert result["score"] == 100.0


def test_domain_member_table_empty_for_domain_with_no_system(monkeypatch):
    import app.domains as domains_module

    monkeypatch.setitem(domains_module.DOMAINS, "future_domain", {"label": "Future", "system": None})
    monkeypatch.setitem(domains_module.MEMBER_METRICS, "future_domain", [{"key": "x", "label": "X"}])

    assert domain_member_table("future_domain") == []


def test_domain_member_table_includes_license_status_rows():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "license_status.devices_expired": 2.0,
            "license_status.devices_unknown": 1.0,
        },
    )

    rows = domain_member_table("lifecycle")

    expired_row = next(r for r in rows if r["key"] == "license_status.devices_expired")
    assert expired_row["now"] == 2.0
    # Matches the license_status Board widget's catalog entry -> gets a real RAG, same as change_control.devices_out_of_sync's pattern elsewhere in this file
    assert expired_row["rag"] == "red"

    unknown_row = next(r for r in rows if r["key"] == "license_status.devices_unknown")
    assert unknown_row["now"] == 1.0


def test_domain_member_table_license_status_rows_absent_when_no_data():
    _add_source("s1", "4thealth")
    insert_metric_points("s1", _iso(5), {"version_compliance_pct": 90.0})

    rows = domain_member_table("lifecycle")

    expired_row = next(r for r in rows if r["key"] == "license_status.devices_expired")
    assert expired_row["now"] is None


def test_domain_member_table_includes_license_expiring_soon_rows():
    _add_source("s1", "4thealth")
    insert_metric_points(
        "s1",
        _iso(5),
        {
            "license_status.devices_expiring_30": 3.0,
            "license_status.devices_expiring_60": 5.0,
            "license_status.devices_expiring_90": 8.0,
        },
    )

    rows = domain_member_table("lifecycle")

    row_30 = next(r for r in rows if r["key"] == "license_status.devices_expiring_30")
    row_60 = next(r for r in rows if r["key"] == "license_status.devices_expiring_60")
    row_90 = next(r for r in rows if r["key"] == "license_status.devices_expiring_90")
    assert row_30["now"] == 3.0
    assert row_60["now"] == 5.0
    assert row_90["now"] == 8.0
    # devices_expiring_30 matches the 4thealth.license_expiring_soon widget's
    # metric_key (green=0, amber=3) -- 3.0 lands exactly on the amber
    # threshold, same rag_state() "lower" semantics as every other badge.
    assert row_30["rag"] == "amber"
    # devices_expiring_60/90 have no matching widget -- informational only,
    # same as devices_expired's sibling devices_unknown row.
    assert row_60["rag"] is None
    assert row_90["rag"] is None


# ── get_infra_devices ─────────────────────────────────────────────────────────

def test_get_infra_devices_merges_across_sources_and_normalizes_disk_field():
    _add_source("s1", "4thealth")
    _add_source("s2", "4tlog")
    write_snapshot("s1", "summary", {"infra": [
        {"role": "fortimanager", "label": "FMG-01", "hostname": "fmg1.local",
         "cpu": 12.0, "mem": 25.0, "disk_pct": 33.0, "ha_role": "master", "status": "green"},
    ]}, "2026-09-10T00:00:00Z")
    write_snapshot("s2", "summary", {"infra": [
        {"role": "fortianalyzer", "label": "FAZ-01", "hostname": "faz1.local", "version": "v7.4.5",
         "cpu": 10.0, "mem": 20.0, "disk_used_pct": 60.0, "ha_role": None, "status": "green"},
    ]}, "2026-09-10T00:00:00Z")

    devices = get_infra_devices()

    assert len(devices) == 2
    fmg = next(d for d in devices if d["role"] == "fortimanager")
    faz = next(d for d in devices if d["role"] == "fortianalyzer")
    assert fmg["disk_pct"] == 33.0
    assert faz["disk_pct"] == 60.0  # normalized from disk_used_pct
    assert "disk_used_pct" not in faz
    assert fmg["source_name"] == "s1"


def test_get_infra_devices_excludes_disabled_sources():
    _add_source("s1", "4thealth", enabled=False)
    write_snapshot("s1", "summary", {"infra": [{"role": "fortimanager", "label": "FMG-01"}]}, "2026-09-10T00:00:00Z")

    assert get_infra_devices() == []


def test_get_infra_devices_empty_when_no_snapshot_yet():
    _add_source("s1", "4thealth")
    assert get_infra_devices() == []


def test_get_infra_devices_ignores_sources_with_no_infra_key():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 90}, "2026-09-10T00:00:00Z")
    assert get_infra_devices() == []


def test_get_infra_devices_normalizes_yellow_status_to_amber():
    _add_source("s1", "4tlog")
    write_snapshot("s1", "summary", {"infra": [
        {"role": "fortianalyzer", "label": "FAZ-01", "status": "yellow"},
    ]}, "2026-09-10T00:00:00Z")

    devices = get_infra_devices()

    assert devices[0]["status"] == "amber"
