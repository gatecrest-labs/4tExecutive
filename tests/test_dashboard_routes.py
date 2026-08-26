import json

import pytest

import app.groups as groups_module
import app.sources as sources_module
from app import metrics_db


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


def test_dashboard_falls_back_to_default_layout_when_none_saved(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    sources_module.add_source(
        id="s1", system="4thealth", name="East DC", base_url="https://a", token="t"
    )
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 88}, "2026-08-24T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"Hygiene Score" in response.data
    assert b"East DC" in response.data
    assert b"88" in response.data


def test_dashboard_empty_when_no_saved_layout_and_no_sources(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert b"No data yet" not in response.data  # no widgets rendered at all


def test_dashboard_prefers_saved_layout_over_default(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    sources_module.add_source(
        id="s1", system="4thealth", name="East DC", base_url="https://a", token="t"
    )
    from app.layouts import save_layout

    # Saved layout only picks one catalog entry, even though the default
    # would include every 4thealth widget for this source.
    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )

    response = client.get("/")

    assert response.data.count(b'class="widget widget-') == 1


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
