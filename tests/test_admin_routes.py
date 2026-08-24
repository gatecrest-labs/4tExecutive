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


def test_delete_source(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(id="s1", system="4thealth", name="A", base_url="https://a", token="t")

    response = client.post("/admin/sources/s1/delete", follow_redirects=False)

    assert response.status_code == 302
    assert sources_module.get_source("s1") is None


def test_refresh_source_triggers_poll_now(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    sources_module.add_source(id="s1", system="4thealth", name="A", base_url="https://a", token="t")

    with patch("app.routes.admin_routes.poll_now") as mock_poll_now:
        mock_poll_now.return_value = True
        response = client.post("/admin/sources/s1/refresh", follow_redirects=False)

    assert response.status_code == 302
    mock_poll_now.assert_called_once_with("s1")
