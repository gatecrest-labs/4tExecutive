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
    get_scoring_config,
    grade_for,
    rag_for_grade,
    save_scoring_config,
    store_domain_scores,
)
from app.metrics_db import get_metric_series, init_db, insert_metric_points
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


def test_compute_domain_vulnerability_and_lifecycle_always_not_measured():
    assert compute_domain("vulnerability")["score"] is None
    assert compute_domain("lifecycle")["score"] is None


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
    # Only availability, posture, hygiene, logging can ever be measured here;
    # only availability has data, so overall == availability's score exactly.
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


def test_domain_member_table_empty_for_unmeasured_domain():
    assert domain_member_table("vulnerability") == []
