import json

import pytest

import app.groups as groups_module
import app.sources as sources_module
from app.domains import get_scoring_config


@pytest.fixture(autouse=True)
def tmp_sources_file(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    from app import config_paths

    monkeypatch.setattr(config_paths, "CONFIG_DIR", tmp_path / "config")
    import app.domains as domains_module

    monkeypatch.setattr(domains_module, "SCORING_PATH", tmp_path / "config" / "scoring.json")


def _login_as_admin(client, tmp_path, monkeypatch, username="carol"):
    with client.session_transaction() as sess:
        sess["username"] = username
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"administrators": {"members": [username], "allowed_tabs": ["admin"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_scoring_page_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/scoring")
    assert response.status_code == 403


def test_scoring_page_shows_current_defaults(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.get("/admin/scoring")

    assert response.status_code == 200
    assert b"availability" in response.data.lower()
    assert b"posture" in response.data.lower()


def test_scoring_update_saves_weights_and_params(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    config = get_scoring_config()
    form = {}
    for name, weight in config["domain_weights"].items():
        form[f"domain_weights.{name}"] = str(weight)
    for name, params in config["domains"].items():
        for key, value in params.items():
            form[f"domains.{name}.{key}"] = str(value)
    form["domain_weights.availability"] = "42"
    form["domains.posture.hygiene_weight"] = "0.9"

    response = client.post("/admin/scoring", data=form, follow_redirects=False)

    assert response.status_code == 302
    saved = get_scoring_config()
    assert saved["domain_weights"]["availability"] == 42.0
    assert saved["domains"]["posture"]["hygiene_weight"] == 0.9


def test_scoring_update_rejects_non_numeric_value(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    config = get_scoring_config()
    form = {}
    for name, weight in config["domain_weights"].items():
        form[f"domain_weights.{name}"] = str(weight)
    for name, params in config["domains"].items():
        for key, value in params.items():
            form[f"domains.{name}.{key}"] = str(value)
    form["domain_weights.availability"] = "not-a-number"

    response = client.post("/admin/scoring", data=form)

    assert response.status_code == 200
    assert b"must be a number" in response.data.lower()
    # unchanged
    assert get_scoring_config()["domain_weights"]["availability"] != "not-a-number"


def test_scoring_update_rejects_negative_value(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    config = get_scoring_config()
    form = {}
    for name, weight in config["domain_weights"].items():
        form[f"domain_weights.{name}"] = str(weight)
    for name, params in config["domains"].items():
        for key, value in params.items():
            form[f"domains.{name}.{key}"] = str(value)
    form["domain_weights.availability"] = "-5"

    response = client.post("/admin/scoring", data=form)

    assert response.status_code == 200
    assert b"must not be negative" in response.data.lower()
