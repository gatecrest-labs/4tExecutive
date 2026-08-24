import json

import app.groups as groups_module
import app.metrics_db as metrics_db


def _login(client, username="alice"):
    with client.session_transaction() as sess:
        sess["username"] = username


def _allow_dashboard_tab(monkeypatch, tmp_path, username="alice"):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"executives": {"members": [username], "allowed_tabs": ["dashboard"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_dashboard_requires_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302


def test_dashboard_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/")

    assert response.status_code == 403


def test_dashboard_renders_saved_widgets(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 88}, "2026-08-24T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"Hygiene Score" in response.data
    assert b"88" in response.data


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
