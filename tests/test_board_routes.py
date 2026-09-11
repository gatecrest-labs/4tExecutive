import json
from datetime import UTC, datetime, timedelta

import pytest

import app.groups as groups_module
import app.sources as sources_module
from app.metrics_db import insert_event, insert_metric_points, write_snapshot
from app.sources import add_source


def _iso(minutes_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def tmp_state(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    from app import config_paths

    monkeypatch.setattr(config_paths, "CONFIG_DIR", tmp_path / "config")
    import app.domains as domains_module

    monkeypatch.setattr(domains_module, "SCORING_PATH", tmp_path / "config" / "scoring.json")


def _login(client, username="alice"):
    with client.session_transaction() as sess:
        sess["username"] = username


def _allow_dashboard_tab(monkeypatch, tmp_path, username="alice"):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"executives": {"members": [username], "allowed_tabs": ["dashboard"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def _seed(source_id="s1", system="4thealth"):
    add_source(
        id=source_id, system=system, name=source_id, base_url="https://example.internal", token="secret"
    )


def test_board_requires_login(client):
    response = client.get("/board", follow_redirects=False)
    assert response.status_code == 302


def test_board_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/board")

    assert response.status_code == 403


def test_board_renders_rows_grouped_by_domain(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed()
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    insert_metric_points("s1", _iso(5), {"hygiene_score": 88.0})

    response = client.get("/board")

    assert response.status_code == 200
    assert b"Hygiene Score" in response.data
    assert b"Config Posture" in response.data


def test_board_legend_line_present(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/board")

    assert response.status_code == 200
    assert b"better" in response.data.lower()


def test_board_domain_filter_query_param_sets_cookie_and_filters(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed("s1", "4thealth")
    _seed("s2", "4tlog")
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    write_snapshot("s2", "summary", {"devices_silent": 1, "devices_logging": 10}, _iso(5))

    response = client.get("/board?domain=logging")

    assert response.status_code == 200
    assert b"Hygiene Score" not in response.data
    assert b"Silent devices" in response.data or b"Silent Devices" in response.data
    set_cookies = "; ".join(response.headers.getlist("Set-Cookie"))
    assert "domain_filter=logging" in set_cookies


def test_board_source_filter_query_param_sets_cookie_and_filters(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed("s1", "4thealth")
    _seed("s2", "4thealth")
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    write_snapshot("s2", "summary", {"hygiene_score": 70}, _iso(5))

    response = client.get("/board?source=s1")

    assert response.status_code == 200
    set_cookies = "; ".join(response.headers.getlist("Set-Cookie"))
    assert "source_filter=s1" in set_cookies


def test_board_adom_filter_query_param_sets_cookie_and_scopes_value(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed("s1", "4thealth")
    write_snapshot("s1", "summary", {"pending_config_diff_count": 100}, _iso(5))
    insert_metric_points("s1", _iso(5), {
        "pending_config_diff_count": 100.0,
        "by_adom.Corp.pending_config_diff_count": 3.0,
    })

    response = client.get("/board?adom=Corp")

    assert response.status_code == 200
    assert b"Corp" in response.data
    set_cookies = "; ".join(response.headers.getlist("Set-Cookie"))
    assert "adom_filter=Corp" in set_cookies


def test_board_adom_filter_unknown_adom_ignored(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed("s1", "4thealth")
    write_snapshot("s1", "summary", {"pending_config_diff_count": 100}, _iso(5))
    insert_metric_points("s1", _iso(5), {"pending_config_diff_count": 100.0})

    response = client.get("/board?adom=NoSuchADOM")

    assert response.status_code == 200  # falls back to fleet-wide, no error


def test_board_adom_filter_all_clears_cookie(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    client.set_cookie("adom_filter", "Corp")

    response = client.get("/board?adom=")

    set_cookies = "; ".join(response.headers.getlist("Set-Cookie"))
    assert "adom_filter=Corp" not in set_cookies


def test_board_sort_query_param(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed()
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))

    response = client.get("/board?sort=name")

    assert response.status_code == 200


def test_board_invalid_sort_falls_back_to_default(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/board?sort=bogus")

    assert response.status_code == 200


def test_board_csv_export(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed()
    write_snapshot("s1", "summary", {"hygiene_score": 88}, _iso(5))
    insert_metric_points("s1", _iso(5), {"hygiene_score": 88.0})

    response = client.get("/board.csv")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert b"Hygiene Score" in response.data


def test_board_csv_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/board.csv")

    assert response.status_code == 403


def test_board_stale_row_gets_stale_indicator(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed()
    write_snapshot(
        "s1",
        "summary",
        {"hygiene_score": 92, "hygiene_sweep_status": "ok", "hygiene_sweep_collected_at": _iso(200)},
        _iso(5),
    )
    insert_metric_points("s1", _iso(5), {"hygiene_score": 92.0})

    response = client.get("/board")

    assert response.status_code == 200
    assert b"board-row-stale" in response.data


def test_board_row_renders_event_tick_for_matching_rag_change(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    _seed()
    write_snapshot("s1", "summary", {"hygiene_score": 40}, _iso(5))
    insert_metric_points("s1", _iso(60 * 25), {"hygiene_score": 92.0})
    insert_metric_points("s1", _iso(5), {"hygiene_score": 40.0})
    insert_event(
        ts=_iso(60),
        source_id="s1",
        metric_key="hygiene_score",
        kind="rag_change",
        severity="critical",
        title="Hygiene Score turned red",
        detail={"widget_type": "4thealth.hygiene_score", "before": "green", "after": "red"},
    )

    response = client.get("/board")

    assert response.status_code == 200
    assert b"chart-event-tick" in response.data
    assert b"Hygiene Score turned red" in response.data
