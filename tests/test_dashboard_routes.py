"""Tests for the saved-layout edit/save endpoints (/dashboard/edit, POST
/dashboard/layout). These no longer feed the Trend Board at GET /board (see
tests/test_board_routes.py and tests/test_board.py) — the board is now a
fixed, comprehensive view built from default_layout(), not per-user saved
layouts. get_layout/save_layout and this edit page remain functional but are
currently unused by any page."""

import json

import pytest

import app.groups as groups_module
import app.sources as sources_module


@pytest.fixture(autouse=True)
def tmp_sources_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")


def _login(client, username="alice"):
    with client.session_transaction() as sess:
        sess["username"] = username


def _allow_dashboard_tab(monkeypatch, tmp_path, username="alice"):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"executives": {"members": [username], "allowed_tabs": ["dashboard"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_edit_page_requires_login(client):
    response = client.get("/dashboard/edit", follow_redirects=False)
    assert response.status_code == 302


def test_edit_page_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/dashboard/edit")

    assert response.status_code == 403


def test_edit_page_lists_catalog(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/dashboard/edit")

    assert response.status_code == 200
    assert b"Hygiene Score" in response.data


def test_edit_page_shows_widget_labels_for_saved_layout(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )

    response = client.get("/dashboard/edit")

    assert response.status_code == 200
    assert response.data.count(b"Hygiene Score") >= 2


def test_post_layout_saves_and_can_be_read_back(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    payload = [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}]

    response = client.post("/dashboard/layout", json=payload)

    assert response.status_code == 204
    from app.layouts import get_layout

    assert get_layout("alice") == payload


def test_post_layout_rejects_unknown_widget_type(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.post("/dashboard/layout", json=[{"type": "bogus", "source_instance": "s1"}])

    assert response.status_code == 400


def test_post_layout_rejects_non_list_body(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.post("/dashboard/layout", json={"type": "4thealth.hygiene_score"})

    assert response.status_code == 400


def test_post_layout_rejects_list_items_missing_type(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.post("/dashboard/layout", json=[{"source_instance": "s1"}])

    assert response.status_code == 400


def test_post_layout_rejects_list_of_non_dict_items(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.post("/dashboard/layout", json=["not-a-widget"])

    assert response.status_code == 400
