import json
from datetime import UTC, datetime

import pytest

import app.groups as groups_module
import app.sources as sources_module
from app.metrics_db import get_brief_asks, write_snapshot
from app.sources import add_source


@pytest.fixture(autouse=True)
def tmp_sources_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    from app import config_paths

    monkeypatch.setattr(config_paths, "CONFIG_DIR", tmp_path / "config")
    import app.domains as domains_module

    monkeypatch.setattr(domains_module, "SCORING_PATH", tmp_path / "config" / "scoring.json")


def _login(client, username="alice"):
    with client.session_transaction() as sess:
        sess["username"] = username


def _allow_tabs(monkeypatch, tmp_path, tabs, username="alice"):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({"executives": {"members": [username], "allowed_tabs": tabs}}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_brief_requires_login(client):
    response = client.get("/brief", follow_redirects=False)
    assert response.status_code == 302


def test_brief_403_without_brief_tab(client, tmp_path, monkeypatch):
    _login(client)
    _allow_tabs(monkeypatch, tmp_path, ["dashboard"])

    response = client.get("/brief")

    assert response.status_code == 403


def test_brief_200_with_brief_tab(client, tmp_path, monkeypatch):
    _login(client)
    _allow_tabs(monkeypatch, tmp_path, ["brief"])

    response = client.get("/brief")

    assert response.status_code == 200
    assert b"Weekly Executive Brief" in response.data


def test_brief_read_only_asks_without_brief_edit_tab(client, tmp_path, monkeypatch):
    _login(client)
    _allow_tabs(monkeypatch, tmp_path, ["brief"])

    response = client.get("/brief")

    assert response.status_code == 200
    assert b"briefAsksForm" not in response.data


def test_brief_asks_post_403_without_brief_edit_tab(client, tmp_path, monkeypatch):
    _login(client)
    _allow_tabs(monkeypatch, tmp_path, ["brief"])

    response = client.post("/brief/asks", data={"week_key": "2026-W37", "ask": ["Approve budget"]})

    assert response.status_code == 403


def test_brief_asks_post_saves_and_round_trips(client, tmp_path, monkeypatch):
    _login(client)
    _allow_tabs(monkeypatch, tmp_path, ["brief", "brief_edit"])

    response = client.post(
        "/brief/asks",
        data={"week_key": "2026-W37", "ask": ["Approve budget", "", "Confirm ownership"]},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert get_brief_asks("2026-W37") == ["Approve budget", "Confirm ownership"]


def test_brief_page_shows_edit_form_with_brief_edit_tab(client, tmp_path, monkeypatch):
    _login(client)
    _allow_tabs(monkeypatch, tmp_path, ["brief", "brief_edit"])

    response = client.get("/brief")

    assert response.status_code == 200
    assert b"briefAsksForm" in response.data


def test_brief_renders_with_full_posture_panels_populated(client, tmp_path, monkeypatch):
    _login(client)
    _allow_tabs(monkeypatch, tmp_path, ["brief", "brief_edit"])
    add_source(id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret")
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_snapshot(
        "s1",
        "summary",
        {
            "device_review": {
                "devices_reviewed": 103,
                "devices_with_failures": 8,
                "top_failing_checks": [{"name": "Admin MFA not enforced", "count": 4}],
            },
            "version_compliance_pct": 91.0,
            "version_breakdown": {"7.4.6": {"count": 56, "eol": False}, "7.0.14": {"count": 3, "eol": True}},
            "change_control": {"devices_out_of_sync": 1, "admin_changes_24h": 27},
        },
        now_iso,
    )

    response = client.get("/brief")

    assert response.status_code == 200
    assert b"Admin MFA not enforced" in response.data
    assert b"EOL" in response.data
