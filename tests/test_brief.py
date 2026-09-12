from datetime import UTC, datetime, timedelta

import pytest

import app.domains as domains_module
import app.metrics_db as metrics_db_module
import app.sources as sources_module
from app.brief import build_brief, build_status_sentence, week_key_for
from app.metrics_db import init_db, insert_event, insert_metric_points
from app.sources import add_source


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def tmp_db_and_config(tmp_path, monkeypatch):
    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")
    init_db()
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    monkeypatch.setattr(domains_module, "SCORING_PATH", tmp_path / "scoring.json")


# ── build_status_sentence ───────────────────────────────────────────────


def test_status_sentence_all_clear_when_nothing_notable():
    sentence = build_status_sentence([], {"availability": None, "posture": 0.0})

    assert sentence == (
        "All monitored domains are within target and no new critical or "
        "attention items were recorded this week."
    )


def test_status_sentence_never_empty_on_empty_inputs():
    assert build_status_sentence([], {}) != ""
    assert build_status_sentence([], {}) is not None


def test_status_sentence_critical_only():
    events = [{"severity": "critical", "title": "Fortinet advisory FG-IR-26-118"}]

    sentence = build_status_sentence(events, {})

    assert "1 new critical item" in sentence
    assert "Fortinet advisory FG-IR-26-118" in sentence
    assert "attention item" not in sentence


def test_status_sentence_warning_only():
    events = [
        {"severity": "warning", "title": "Silent devices increased"},
        {"severity": "warning", "title": "Pending diffs increased"},
    ]

    sentence = build_status_sentence(events, {})

    assert "2 attention items" in sentence
    assert "critical item" not in sentence


def test_status_sentence_mixed_improving_and_degrading():
    sentence = build_status_sentence(
        [],
        {"availability": 2.0, "posture": -1.5, "hygiene": None},
    )

    assert "improving" in sentence
    assert "degrading" in sentence
    assert "Availability & Change" in sentence
    assert "Config Posture" in sentence


def test_status_sentence_criticals_and_degrading_combined():
    events = [{"severity": "critical", "title": "KEV advisory"}]
    domain_deltas = {"vulnerability": -5.0}

    sentence = build_status_sentence(events, domain_deltas)

    assert "1 new critical item" in sentence
    assert "KEV advisory" in sentence
    assert "degrading" in sentence
    assert "Vulnerability" in sentence


def test_status_sentence_never_raises_on_malformed_inputs():
    # No severity key, no title key -- must degrade gracefully, never raise.
    build_status_sentence([{"severity": "critical"}], None)
    build_status_sentence(None, None)


# ── build_brief ──────────────────────────────────────────────────────────


def test_build_brief_on_empty_db_does_not_crash():
    brief = build_brief(now=datetime(2026, 9, 12, tzinfo=UTC))

    assert brief["overall"]["score"] is None
    assert brief["decisions"] == []
    assert brief["asks"] == []
    assert brief["status_sentence"]
    assert brief["status_word"] == "Not yet measured"
    for tile in brief["tiles"]:
        assert tile["series"] == []
    panels = brief["posture_panels"]
    assert panels["device_review"] is None
    assert panels["firmware"] is None
    assert panels["change_control"] is None
    assert brief["trends"]["posture"]["points"] == []
    assert brief["trends"]["logging"]["points"] == []


def test_build_brief_with_populated_fixture_db():
    now = datetime(2026, 9, 12, tzinfo=UTC)
    add_source(id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret")
    add_source(id="l1", system="4tlog", name="Log East", base_url="https://logs.internal", token="secret")

    insert_metric_points(
        "s1",
        _iso(now - timedelta(days=1)),
        {
            "firewall_online_count": 95.0,
            "firewall_managed_count": 100.0,
            "hygiene_score": 90.0,
            "version_compliance_pct": 92.0,
            "psirt.devices_critical": 1.0,
            "psirt.kev_exposed_devices": 1.0,
            "rule_hygiene.rule_findings_total": 118.0,
            "rule_count_total": 4800.0,
        },
    )
    insert_metric_points("l1", _iso(now - timedelta(days=1)), {"devices_silent": 8.0})
    insert_metric_points("_fleet", _iso(now - timedelta(days=1)), {"domain.posture": 79.0, "domain.logging": 88.0})

    insert_event(
        ts=_iso(now - timedelta(days=1)),
        source_id="s1",
        metric_key="psirt.devices_critical",
        kind="rag_change",
        severity="critical",
        title="Fortinet advisory FG-IR-26-118 affects 3 firewalls",
        detail={"cvss": 9.8},
    )

    brief = build_brief(now=now)

    assert brief["overall"]["score"] is not None
    assert len(brief["decisions"]) == 1
    assert brief["decisions"][0]["title"] == "Fortinet advisory FG-IR-26-118 affects 3 firewalls"
    assert brief["decisions"][0]["source_name"] == "East"
    tile_labels = [t["label"] for t in brief["tiles"]]
    assert tile_labels == [
        "Availability",
        "Posture score",
        "Vulnerable devices",
        "Silent devices",
        "Hygiene findings",
    ]
    vuln_tile = brief["tiles"][2]
    assert vuln_tile["value"] == 1
    silent_tile = brief["tiles"][3]
    assert silent_tile["value"] == 8.0
    assert "1 new critical item" in brief["status_sentence"]


def test_week_key_for_matches_isocalendar():
    now = datetime(2026, 9, 12, tzinfo=UTC)
    iso = now.isocalendar()

    assert week_key_for(now) == f"{iso.year}-W{iso.week:02d}"
