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


def test_dashboard_shows_only_host_widgets_when_no_saved_layout_and_no_sources(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert response.data.count(b'class="widget widget-') == 3
    assert b"Host CPU" in response.data


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


def test_dashboard_renders_version_breakdown_as_bar_chart(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.version_breakdown", "source_instance": "s1", "size": "2x2", "date_range": "30d"}],
    )
    metrics_db.write_snapshot(
        "s1", "summary", {"version_breakdown": {"7.4.5": 62, "7.2.9": 41}}, "2026-08-27T10:00:00Z"
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"chart-bar" in response.data
    assert b"7.4.5" in response.data
    assert b"62" in response.data


def test_dashboard_handles_version_breakdown_missing_field_gracefully(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.version_breakdown", "source_instance": "s1", "size": "2x2", "date_range": "30d"}],
    )
    # Snapshot without version_breakdown field - only has hygiene_score
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 92}, "2026-08-27T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"FortiOS Versions" in response.data
    assert b"widget-2x2" in response.data
    assert b"No data yet" in response.data


def test_dashboard_renders_ai_usage_widget_as_line_chart(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.ai_usage_24h", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot(
        "s1",
        "summary",
        {"ai_usage_24h": {"ai_connection_count_24h": 340, "ai_estimated_cost_24h_usd": 4.1}},
        "2026-08-27T10:00:00Z",
    )

    response = client.get("/?range=30d")

    assert response.status_code == 200
    assert b"chart-line" in response.data
    assert b"340" in response.data
    assert b"est. cost" in response.data


def test_dashboard_renders_zero_value_instead_of_no_data(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.pending_config_diffs", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot(
        "s1", "summary", {"pending_config_diff_count": 0}, "2026-08-27T10:00:00Z"
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"No data yet" not in response.data
    assert b">0<" in response.data


def test_dashboard_defaults_to_1d_range(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert b'class="range-btn active">1d<' in response.data


def test_dashboard_range_query_param_sets_cookie(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/?range=7d")

    assert response.status_code == 200
    assert response.headers.get("Set-Cookie", "").find("range=7d") != -1


def test_dashboard_invalid_range_falls_back_to_default(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/?range=bogus")

    assert response.status_code == 200
    assert b'class="range-btn active">1d<' in response.data


def test_dashboard_uses_range_cookie_when_no_query_param(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    client.set_cookie("range", "30d")

    response = client.get("/")

    assert response.status_code == 200
    assert b'class="range-btn active">30d<' in response.data


def test_dashboard_renders_firewall_managed_count_as_line_chart(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.firewall_managed_count", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"firewall_managed_count": 128}, "2026-08-27T10:00:00Z")

    response = client.get("/?range=30d")

    assert response.status_code == 200
    assert b"chart-line" in response.data
    assert b"128" in response.data


def test_dashboard_renders_rag_class_on_widget_card(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.hygiene_score", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"hygiene_score": 40}, "2026-08-27T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"rag-red" in response.data


def test_dashboard_no_rag_class_for_informational_widget(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    from app.layouts import save_layout

    save_layout(
        "alice",
        [{"type": "4thealth.rule_count_total", "source_instance": "s1", "size": "1x1", "date_range": "30d"}],
    )
    metrics_db.write_snapshot("s1", "summary", {"rule_count_total": 14200}, "2026-08-27T10:00:00Z")

    response = client.get("/")

    assert response.status_code == 200
    assert b"rag-" not in response.data
