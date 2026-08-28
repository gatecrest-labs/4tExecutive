import json
from unittest.mock import patch

import pytest

import app.groups as groups_module
import app.sources as sources_module


@pytest.fixture(autouse=True)
def tmp_sources_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")


def _login_as_admin(client, tmp_path, monkeypatch, username="carol"):
    with client.session_transaction() as sess:
        sess["username"] = username
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"administrators": {"members": [username], "allowed_tabs": ["admin"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_admin_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/sources")
    assert response.status_code == 403


def test_admin_sources_page_lists_sources(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(
        id="4thealth-east", system="4thealth", name="East DC",
        base_url="https://a", token="t",
    )

    response = client.get("/admin/sources")

    assert response.status_code == 200
    assert b"East DC" in response.data


def test_add_source_via_post(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/sources",
        data={
            "id": "4tlog-main",
            "system": "4tlog",
            "name": "Main FAZ",
            "base_url": "https://4tlog.internal",
            "token": "secret",
            "poll_interval_minutes": "20",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert sources_module.get_source("4tlog-main")["name"] == "Main FAZ"
    assert sources_module.get_source("4tlog-main")["verify_tls"] is True


def test_add_source_with_skip_tls_verify_checkbox_disables_verification(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/sources",
        data={
            "id": "self-signed",
            "system": "4thealth",
            "name": "Self-signed instance",
            "base_url": "https://internal.example",
            "token": "secret",
            "poll_interval_minutes": "15",
            "skip_tls_verify": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert sources_module.get_source("self-signed")["verify_tls"] is False


def test_admin_sources_page_shows_status_marker(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(
        id="s1", system="4thealth", name="A", base_url="https://a", token="t"
    )

    response = client.get("/admin/sources")

    assert response.status_code == 200
    assert b"Not yet polled" in response.data


def test_delete_source(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(id="s1", system="4thealth", name="A", base_url="https://a", token="t")

    response = client.post("/admin/sources/s1/delete", follow_redirects=False)

    assert response.status_code == 302
    assert sources_module.get_source("s1") is None


def test_add_source_duplicate_id_shows_error_instead_of_500(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(id="dup", system="4thealth", name="A", base_url="https://a", token="t")

    response = client.post(
        "/admin/sources",
        data={
            "id": "dup",
            "system": "4thealth",
            "name": "B",
            "base_url": "https://b",
            "token": "secret",
            "poll_interval_minutes": "15",
        },
    )

    assert response.status_code == 200
    assert b"source id already exists" in response.data


def test_add_source_non_numeric_poll_interval_shows_error_instead_of_500(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/sources",
        data={
            "id": "s1",
            "system": "4thealth",
            "name": "A",
            "base_url": "https://a",
            "token": "secret",
            "poll_interval_minutes": "not-a-number",
        },
    )

    assert response.status_code == 200
    assert b"error" in response.data.lower()
    assert sources_module.get_source("s1") is None


def test_add_source_rejects_non_https_base_url(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/sources",
        data={
            "id": "s1",
            "system": "4thealth",
            "name": "A",
            "base_url": "http://insecure.internal",
            "token": "secret",
            "poll_interval_minutes": "15",
        },
    )

    assert response.status_code == 200
    assert b"https" in response.data.lower()
    assert sources_module.get_source("s1") is None


def test_refresh_source_triggers_poll_now(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(id="s1", system="4thealth", name="A", base_url="https://a", token="t")

    with patch("app.routes.admin_routes.poll_now") as mock_poll_now:
        mock_poll_now.return_value = True
        response = client.post("/admin/sources/s1/refresh", follow_redirects=False)

    assert response.status_code == 302
    mock_poll_now.assert_called_once_with("s1")


def test_admin_system_page_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/system")
    assert response.status_code == 403


def test_admin_system_page_renders_host_metrics(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    from app import metrics_db

    metrics_db.init_db()
    metrics_db.write_snapshot(
        "_self", "summary", {"cpu_percent": 12.5, "memory_percent": 40, "disk_percent": 55}, "2026-08-27T10:00:00Z"
    )

    response = client.get("/admin/system")

    assert response.status_code == 200
    assert b"Host CPU" in response.data
    assert b"Host Memory" in response.data
    assert b"Host Disk" in response.data
