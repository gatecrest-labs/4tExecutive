import datetime

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.sso_verify as sso_verify_module


def _write_test_keypair(tmp_path, monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_path = tmp_path / "sso_public_key.pem"
    public_key_path.write_bytes(public_pem)
    monkeypatch.setattr(sso_verify_module, "PUBLIC_KEY_PATH", public_key_path)
    return private_key


def _sso_token(private_key, **overrides):
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "alice",
        "aud": "4texecutive",
        "iss": "4tsuite",
        "iat": now,
        "nbf": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="EdDSA")


def test_sso_login_records_login_time(client, tmp_path, monkeypatch, tmp_groups_file):
    key = _write_test_keypair(tmp_path, monkeypatch)
    client.get(f"/sso/login?token={_sso_token(key)}")
    with client.session_transaction() as sess:
        assert isinstance(sess["sso_login_at"], float)


def test_sso_session_is_dropped_when_checker_says_revoked(
    app, client, tmp_path, monkeypatch, tmp_groups_file
):
    key = _write_test_keypair(tmp_path, monkeypatch)
    state = {"valid": True}
    app.extensions["tsuite_session_checker"] = lambda username, login_at: state["valid"]
    client.get(f"/sso/login?token={_sso_token(key)}")
    assert client.get("/board", follow_redirects=False).status_code == 200
    state["valid"] = False
    response = client.get("/board", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    with client.session_transaction() as sess:
        assert "username" not in sess


def test_checker_receives_username_and_login_time(
    app, client, tmp_path, monkeypatch, tmp_groups_file
):
    key = _write_test_keypair(tmp_path, monkeypatch)
    seen = []
    app.extensions["tsuite_session_checker"] = lambda u, t: seen.append((u, t)) or True
    client.get(f"/sso/login?token={_sso_token(key)}")
    client.get("/board")
    assert seen and seen[0][0] == "alice" and isinstance(seen[0][1], float)


def test_local_login_session_is_never_checked(app, client, tmp_groups_file):
    def explode(username, login_at):
        raise AssertionError("checker must not run for local sessions")

    app.extensions["tsuite_session_checker"] = explode
    with client.session_transaction() as sess:
        sess["username"] = "alice"  # no sso_login_at: a local session
    assert client.get("/board").status_code == 200


def test_no_checker_configured_leaves_sso_sessions_alone(
    app, client, tmp_path, monkeypatch, tmp_groups_file
):
    key = _write_test_keypair(tmp_path, monkeypatch)
    app.extensions["tsuite_session_checker"] = None
    client.get(f"/sso/login?token={_sso_token(key)}")
    assert client.get("/board").status_code == 200


def test_factory_builds_checker_from_env(tmp_config_dir, tmp_path, monkeypatch):
    import app.metrics_db as metrics_db_module
    from app import create_app

    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")
    monkeypatch.setenv("TSUITE_REVOCATIONS_URL", "https://suite.invalid:8400")
    monkeypatch.setenv("TSUITE_REVOCATIONS_TOKEN", "t")
    configured = create_app(testing=True)
    assert callable(configured.extensions["tsuite_session_checker"])
    monkeypatch.delenv("TSUITE_REVOCATIONS_URL")
    unconfigured = create_app(testing=True)
    assert unconfigured.extensions["tsuite_session_checker"] is None
