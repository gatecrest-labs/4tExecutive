"""Tests for the devices drill-down module and routes."""

import json
from datetime import UTC, datetime, timedelta

import pytest

import app.groups as groups_module
import app.sources as sources_module
from app.devices import (
    DOMAIN_DEVICE_CSV_COLUMNS,
    FLEET_DEVICE_CSV_COLUMNS,
    devices_to_csv,
    get_domain_devices,
    get_fleet_devices,
)
from app.metrics_db import init_db, write_snapshot
from app.sources import add_source


def _iso(minutes_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    import app.metrics_db as metrics_db_module

    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    from app import config_paths

    monkeypatch.setattr(config_paths, "CONFIG_DIR", tmp_path / "config")
    init_db()


def _add_source(source_id, system, enabled=True):
    add_source(
        id=source_id,
        system=system,
        name=source_id,
        base_url="https://example.internal",
        token="secret",
        enabled=enabled,
    )


def _login(client, username="alice"):
    with client.session_transaction() as sess:
        sess["username"] = username


def _allow_dashboard_tab(monkeypatch, tmp_path, username="alice"):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"executives": {"members": [username], "allowed_tabs": ["dashboard"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


# ── get_domain_devices ──────────────────────────────────────────────────────


def test_get_domain_devices_posture_extracts_device_review_details():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {
            "device_review": {
                "details": [
                    {"device": "fw1", "adom": "Corp", "failed_checks": ["a", "b"], "worst_severity": "high"},
                ]
            }
        },
        _iso(5),
    )

    rows = get_domain_devices("posture")

    assert len(rows) == 1
    assert rows[0]["device"] == "fw1"
    assert rows[0]["adom"] == "Corp"
    assert rows[0]["source_name"] == "s1"
    assert rows[0]["detail_text"] == "2 failed checks (high)"


def test_get_domain_devices_hygiene_uses_package_field():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {"rule_hygiene": {"details": [{"package": "pkg1", "adom": "Corp", "findings": 3}]}},
        _iso(5),
    )

    rows = get_domain_devices("hygiene")

    assert rows[0]["device_label"] == "pkg1"
    assert rows[0]["detail_text"] == "3 findings"


def test_get_domain_devices_lifecycle_only_eol_versions():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {
            "version_breakdown": [
                {
                    "version": "7.0.1",
                    "count": 2,
                    "eol": True,
                    "devices": [{"device": "fw-old", "adom": "Corp", "version": "7.0.1"}],
                },
                {"version": "7.4.5", "count": 5, "eol": False},
            ]
        },
        _iso(5),
    )

    rows = get_domain_devices("lifecycle")

    assert len(rows) == 1
    assert rows[0]["device"] == "fw-old"
    assert rows[0]["detail_text"] == "7.0.1"


def test_get_domain_devices_lifecycle_missing_devices_list_yields_no_rows():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {"version_breakdown": [{"version": "7.0.1", "count": 2, "eol": True}]},
        _iso(5),
    )

    assert get_domain_devices("lifecycle") == []


def test_get_domain_devices_logging_reads_silent_devices():
    _add_source("s1", "4tlog")
    write_snapshot(
        "s1",
        "summary",
        {"silent_devices": [{"devid": "1", "devname": "fw-silent", "last_log_at": "2026-09-01T00:00:00Z"}]},
        _iso(5),
    )

    rows = get_domain_devices("logging")

    assert rows[0]["device_label"] == "fw-silent"
    assert "last log" in rows[0]["detail_text"]
    assert rows[0].get("adom") is None


def test_get_domain_devices_vulnerability_reads_top_advisory_devices():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {
            "psirt": {
                "top_advisory": {
                    "advisory_id": "FG-IR-24-001",
                    "devices": [{"device": "fw1", "adom": "Corp", "version": "7.0.1", "workaround_applied": True}],
                }
            }
        },
        _iso(5),
    )

    rows = get_domain_devices("vulnerability")

    assert rows[0]["detail_text"] == "FG-IR-24-001 (workaround applied)"


def test_get_domain_devices_vulnerability_no_workaround():
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {
            "psirt": {
                "top_advisory": {
                    "devices": [{"device": "fw1", "adom": "Corp", "workaround_applied": False}],
                }
            }
        },
        _iso(5),
    )

    rows = get_domain_devices("vulnerability")

    assert rows[0]["detail_text"] == "advisory (no workaround)"


def test_get_domain_devices_merges_across_multiple_sources():
    _add_source("s1", "4thealth")
    _add_source("s2", "4thealth")
    write_snapshot(
        "s1", "summary", {"device_review": {"details": [{"device": "a", "failed_checks": [], "worst_severity": "low"}]}}, _iso(5)
    )
    write_snapshot(
        "s2", "summary", {"device_review": {"details": [{"device": "b", "failed_checks": [], "worst_severity": "low"}]}}, _iso(5)
    )

    rows = get_domain_devices("posture")

    assert {r["device"] for r in rows} == {"a", "b"}


def test_get_domain_devices_excludes_disabled_sources():
    _add_source("s1", "4thealth", enabled=False)
    write_snapshot(
        "s1", "summary", {"device_review": {"details": [{"device": "a", "failed_checks": [], "worst_severity": "low"}]}}, _iso(5)
    )

    assert get_domain_devices("posture") == []


def test_get_domain_devices_availability_has_no_mapping():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {"device_review": {"details": [{"device": "a"}]}}, _iso(5))

    assert get_domain_devices("availability") == []


def test_get_domain_devices_empty_payload_no_crash():
    _add_source("s1", "4thealth")
    _add_source("s2", "4tlog")
    write_snapshot("s1", "summary", {}, _iso(5))
    write_snapshot("s2", "summary", {}, _iso(5))

    for name in ("posture", "hygiene", "lifecycle", "logging", "vulnerability", "availability"):
        assert get_domain_devices(name) == []


def test_get_domain_devices_no_snapshot_at_all_no_crash():
    _add_source("s1", "4thealth")

    for name in ("posture", "hygiene", "lifecycle", "logging", "vulnerability"):
        assert get_domain_devices(name) == []


# ── get_fleet_devices ────────────────────────────────────────────────────────


def test_get_fleet_devices_merges_multiple_categories_for_one_device_and_separate_for_another():
    _add_source("s1", "4thealth")
    _add_source("s2", "4tlog")
    write_snapshot(
        "s1",
        "summary",
        {
            "device_review": {
                "details": [{"device": "fw1", "adom": "Corp", "failed_checks": ["a"], "worst_severity": "high"}]
            },
            "rule_hygiene": {"details": [{"package": "fw1", "adom": "Corp", "findings": 4}]},
        },
        _iso(5),
    )
    write_snapshot(
        "s2",
        "summary",
        {"silent_devices": [{"devid": "9", "devname": "fw-silent", "last_log_at": "2026-09-01T00:00:00Z"}]},
        _iso(5),
    )

    rows = get_fleet_devices()

    assert len(rows) == 2
    fw1 = next(r for r in rows if r["device"] == "fw1")
    assert fw1["adom"] == "Corp"
    assert fw1["posture"] is not None
    assert fw1["hygiene"] is not None
    assert fw1["eol"] is None
    assert fw1["silent"] is None
    assert fw1["vulnerability"] is None

    silent = next(r for r in rows if r["device"] == "fw-silent")
    assert silent["adom"] is None
    assert silent["silent"] is not None
    assert silent["posture"] is None
    assert silent["hygiene"] is None


def test_get_fleet_devices_empty_when_nothing_present():
    _add_source("s1", "4thealth")
    write_snapshot("s1", "summary", {}, _iso(5))

    assert get_fleet_devices() == []


def test_get_fleet_devices_no_sources_at_all():
    assert get_fleet_devices() == []


# ── devices_to_csv ───────────────────────────────────────────────────────────


def test_devices_to_csv_shape():
    rows = [
        {"device": "fw1", "adom": "Corp", "posture": "2 failed checks (high)", "hygiene": None,
         "eol": None, "silent": None, "vulnerability": None},
    ]

    csv_text = devices_to_csv(rows, FLEET_DEVICE_CSV_COLUMNS)
    lines = csv_text.strip("\r\n").split("\r\n")

    assert lines[0] == "Device,ADOM,Posture,Hygiene,EOL,Silent,PSIRT"
    assert lines[1] == "fw1,Corp,2 failed checks (high),,,,"
    assert len(lines) == 2


def test_devices_to_csv_domain_columns_and_missing_key_renders_blank():
    rows = [{"device_label": "fw1", "detail_text": "3 findings", "source_name": "s1"}]

    csv_text = devices_to_csv(rows, DOMAIN_DEVICE_CSV_COLUMNS)
    lines = csv_text.strip("\r\n").split("\r\n")

    assert lines[0] == "Device,ADOM,Source,Detail"
    assert lines[1] == "fw1,,s1,3 findings"


def test_devices_to_csv_empty_rows_has_only_header():
    csv_text = devices_to_csv([], FLEET_DEVICE_CSV_COLUMNS)
    assert csv_text.strip("\r\n") == "Device,ADOM,Posture,Hygiene,EOL,Silent,PSIRT"


# ── Routes ───────────────────────────────────────────────────────────────────


def test_devices_route_requires_login(client):
    response = client.get("/devices", follow_redirects=False)
    assert response.status_code == 302


def test_devices_route_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/devices")

    assert response.status_code == 403


def test_devices_route_renders_fleet_table(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {"device_review": {"details": [{"device": "fw1", "adom": "Corp", "failed_checks": [], "worst_severity": "low"}]}},
        _iso(5),
    )

    response = client.get("/devices")

    assert response.status_code == 200
    assert b"fw1" in response.data
    assert b"Fleet Devices" in response.data


def test_devices_csv_route_returns_csv_content_type(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/devices.csv")

    assert response.status_code == 200
    assert response.content_type.startswith("text/csv")


def test_domain_devices_csv_route_returns_csv_content_type(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {"device_review": {"details": [{"device": "fw1", "adom": "Corp", "failed_checks": [], "worst_severity": "low"}]}},
        _iso(5),
    )

    response = client.get("/domain/posture/devices.csv")

    assert response.status_code == 200
    assert response.content_type.startswith("text/csv")
    assert b"fw1" in response.data


def test_domain_devices_csv_unknown_domain_is_404(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/domain/not-a-domain/devices.csv")

    assert response.status_code == 404


def test_domain_detail_renders_devices_section_when_present(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _add_source("s1", "4thealth")
    write_snapshot(
        "s1",
        "summary",
        {"device_review": {"details": [{"device": "fw1", "adom": "Corp", "failed_checks": ["a"], "worst_severity": "high"}]}},
        _iso(5),
    )

    response = client.get("/domain/posture")

    assert response.status_code == 200
    assert b"Devices" in response.data
    assert b"fw1" in response.data


def test_domain_detail_omits_devices_section_when_empty(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/domain/availability")

    assert response.status_code == 200
    assert b"devices-section" not in response.data
