import json
from datetime import UTC, datetime, timedelta

import pytest

import app.groups as groups_module
import app.sources as sources_module
from app.metrics_db import insert_event, insert_metric_points
from app.sources import add_source


def _iso(minutes_ago: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _allow_dashboard_tab(monkeypatch, tmp_path, username="alice"):
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"executives": {"members": [username], "allowed_tabs": ["dashboard"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_scorecard_requires_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302


def test_scorecard_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/")

    assert response.status_code == 403


def test_scorecard_renders_with_no_sources(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert b"not yet measured" in response.data


def test_scorecard_renders_domain_cards_with_data(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    add_source(
        id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret"
    )
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 95.0, "firewall_managed_count": 100.0})

    response = client.get("/")

    assert response.status_code == 200
    assert b"Availability" in response.data
    assert b"95" in response.data


def test_scorecard_adom_filter_sets_cookie_and_scopes_score(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    add_source(id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret")
    insert_metric_points("s1", _iso(5), {
        "firewall_online_count": 100.0,
        "firewall_managed_count": 100.0,
        "by_adom.Corp.firewall_online_count": 5.0,
        "by_adom.Corp.firewalls_total": 10.0,
    })

    response = client.get("/?adom=Corp")

    assert response.status_code == 200
    assert b"Corp" in response.data
    set_cookies = "; ".join(response.headers.getlist("Set-Cookie"))
    assert "adom_filter=Corp" in set_cookies


def test_scorecard_adom_filter_unknown_ignored(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/?adom=NoSuchADOM")

    assert response.status_code == 200


def test_domain_detail_adom_filter_marks_scoped_member_row(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    add_source(id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret")
    insert_metric_points("s1", _iso(5), {
        "firewall_online_count": 100.0,
        "firewall_managed_count": 100.0,
        "by_adom.Corp.firewall_online_count": 5.0,
        "by_adom.Corp.firewalls_total": 10.0,
    })

    response = client.get("/domain/availability?adom=Corp")

    assert response.status_code == 200
    assert b"Corp" in response.data


def test_domain_detail_availability_shows_infrastructure_card(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    add_source(id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret")
    from app.metrics_db import write_snapshot

    write_snapshot("s1", "summary", {"infra": [
        {"role": "fortimanager", "label": "FMG-01", "hostname": "fmg1.local", "status": "green"},
    ]}, _iso(5))

    response = client.get("/domain/availability")

    assert response.status_code == 200
    assert b"Infrastructure" in response.data
    assert b"fmg1.local" in response.data


def test_domain_detail_non_availability_has_no_infrastructure_card(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/domain/posture")

    assert response.status_code == 200
    assert b"Infrastructure" not in response.data


def test_domain_detail_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/domain/availability")

    assert response.status_code == 403


def test_domain_detail_unknown_domain_is_404(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/domain/not-a-domain")

    assert response.status_code == 404


def test_domain_detail_renders_score_and_explanation(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    add_source(
        id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret"
    )
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 90.0, "firewall_managed_count": 100.0})

    response = client.get("/domain/availability")

    assert response.status_code == 200
    assert b"Availability" in response.data
    assert b"90" in response.data


def test_domain_detail_renders_event_tick_for_threshold_cross_in_window(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    add_source(
        id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret"
    )
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 80.0, "firewall_managed_count": 100.0})
    # domain_detail's chart reads stored domain-score history under "_fleet"
    # (written by the domain_scores scheduler job), not live-computed here.
    insert_metric_points("_fleet", _iso(60 * 24 * 5), {"domain.availability": 96.0})
    insert_metric_points("_fleet", _iso(5), {"domain.availability": 80.0})
    insert_event(
        ts=_iso(60 * 24 * 2),
        source_id=None,
        metric_key="domain.availability",
        kind="threshold_cross",
        severity="critical",
        title="Availability crossed its target",
        detail={"domain": "availability", "before": 96.0, "after": 80.0, "target": 95},
    )

    response = client.get("/domain/availability")

    assert response.status_code == 200
    assert b"chart-event-tick" in response.data
    assert b"Availability crossed its target" in response.data


def test_domain_detail_not_yet_measured(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/domain/vulnerability")

    assert response.status_code == 200
    assert b"not yet measured" in response.data


def test_domain_detail_accepts_window_query_param(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    add_source(
        id="s1", system="4thealth", name="East", base_url="https://example.internal", token="secret"
    )
    insert_metric_points("s1", _iso(5), {"firewall_online_count": 90.0, "firewall_managed_count": 100.0})

    response = client.get("/domain/availability?window=1y")

    assert response.status_code == 200


def test_scorecard_what_changed_panel_shows_recent_events(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    insert_event(
        ts=_iso(60),
        source_id="s1",
        metric_key="hygiene_score",
        kind="rag_change",
        severity="critical",
        title="Hygiene Score turned red",
        detail={"widget_type": "4thealth.hygiene_score", "before": "green", "after": "red"},
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"Hygiene Score turned red" in response.data
    assert b"/domain/posture" in response.data


def test_scorecard_what_changed_panel_empty_state(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert b"Nothing" in response.data


def test_scorecard_what_changed_excludes_events_older_than_7_days(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    insert_event(
        ts=_iso(60 * 24 * 10),
        source_id="s1",
        metric_key=None,
        kind="source_failed",
        severity="critical",
        title="too old to show",
        detail={},
    )

    response = client.get("/")

    assert response.status_code == 200
    assert b"too old to show" not in response.data


def test_events_requires_login(client):
    response = client.get("/events", follow_redirects=False)
    assert response.status_code == 302


def test_events_requires_dashboard_tab(client, tmp_path, monkeypatch):
    _login(client)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(json.dumps({}))
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)

    response = client.get("/events")

    assert response.status_code == 403


def test_events_returns_json_newest_first_within_window(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    insert_event(
        ts=_iso(60 * 24 * 40),  # 40 days ago
        source_id="s1",
        metric_key="hygiene_score",
        kind="rag_change",
        severity="critical",
        title="too old",
        detail={},
    )
    insert_event(
        ts=_iso(60),
        source_id="s1",
        metric_key="hygiene_score",
        kind="rag_change",
        severity="critical",
        title="older",
        detail={"before": "green", "after": "red"},
    )
    insert_event(
        ts=_iso(5),
        source_id="s1",
        metric_key="hygiene_score",
        kind="rag_change",
        severity="info",
        title="newer",
        detail={},
    )

    response = client.get("/events?days=30")

    assert response.status_code == 200
    payload = response.get_json()
    assert [e["title"] for e in payload] == ["newer", "older"]
    assert payload[1]["detail"] == {"before": "green", "after": "red"}


def test_events_default_days_is_30(client, tmp_path, monkeypatch):
    _login(client)
    _allow_dashboard_tab(monkeypatch, tmp_path)
    insert_event(
        ts=_iso(60 * 24 * 10),
        source_id="s1",
        metric_key=None,
        kind="source_failed",
        severity="critical",
        title="within default window",
        detail={},
    )

    response = client.get("/events")

    assert response.status_code == 200
    assert len(response.get_json()) == 1
