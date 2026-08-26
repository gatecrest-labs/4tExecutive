"""CSRF is disabled for the shared `app`/`client` fixtures (testing=True) so
every other test file can POST without a token. These tests force it back on
against a throwaway app instance to verify the protection actually works.
"""

import json

import app.groups as groups_module
from app import create_app


def _csrf_app(tmp_config_dir, tmp_path, monkeypatch):
    import app.metrics_db as metrics_db_module

    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")
    return create_app(testing=True, enable_csrf=True)


def test_post_without_csrf_token_is_rejected(tmp_config_dir, tmp_path, monkeypatch):
    flask_app = _csrf_app(tmp_config_dir, tmp_path, monkeypatch)
    client = flask_app.test_client()

    response = client.post("/login", data={"username": "alice", "password": "wrong"})

    assert response.status_code == 400


def test_post_with_valid_csrf_token_is_accepted(tmp_config_dir, tmp_path, monkeypatch):
    flask_app = _csrf_app(tmp_config_dir, tmp_path, monkeypatch)
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"executives": {"members": ["alice"], "allowed_tabs": ["dashboard"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)
    client = flask_app.test_client()

    login_page = client.get("/login")
    token = login_page.data.decode().split('name="csrf_token" value="')[1].split('"')[0]

    response = client.post(
        "/login",
        data={"username": "alice", "password": "wrong", "csrf_token": token},
    )

    # Wrong password, but the CSRF check itself passed (would be 400 otherwise).
    assert response.status_code == 200
    assert b"Invalid" in response.data
