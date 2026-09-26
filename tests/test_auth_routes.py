import json

import app.auth as auth_module


def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"4tExecutive" in response.data


def test_login_page_uses_login_card_layout(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'class="login-card"' in response.data


def test_login_with_valid_credentials_redirects_and_sets_session(client, tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    users_path.write_text(
        json.dumps(
            {"users": [{"username": "alice", "password_hash": _hash("secret")}]}
        )
    )
    monkeypatch.setattr(auth_module, "USERS_PATH", users_path)

    response = client.post(
        "/login", data={"username": "alice", "password": "secret"}, follow_redirects=False
    )

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["username"] == "alice"


def test_login_with_invalid_credentials_shows_error(client, tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    users_path.write_text(
        json.dumps({"users": [{"username": "alice", "password_hash": _hash("secret")}]})
    )
    monkeypatch.setattr(auth_module, "USERS_PATH", users_path)

    response = client.post("/login", data={"username": "alice", "password": "wrong"})

    assert response.status_code == 200
    assert b"Invalid" in response.data


def test_logout_via_post_clears_session(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "username" not in sess


def _hash(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


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


def test_sso_login_with_valid_token_sets_session_and_redirects(client, tmp_path, monkeypatch):
    private_key = _write_test_keypair(tmp_path, monkeypatch)

    token = _sso_token(private_key)
    response = client.get(f"/sso/login?token={token}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/board"
    with client.session_transaction() as sess:
        assert sess["username"] == "alice"


def test_sso_login_with_invalid_token_falls_back_to_login_page(client):
    response = client.get("/sso/login?token=not-a-real-token", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    with client.session_transaction() as sess:
        assert "username" not in sess


def test_sso_login_clears_a_stale_session_before_applying_new_claims(client, tmp_path, monkeypatch):
    private_key = _write_test_keypair(tmp_path, monkeypatch)

    with client.session_transaction() as sess:
        sess["username"] = "stale-user"
        sess["some_other_stale_key"] = "leftover"

    token = _sso_token(private_key)
    client.get(f"/sso/login?token={token}", follow_redirects=False)

    with client.session_transaction() as sess:
        assert sess["username"] == "alice"
        assert "some_other_stale_key" not in sess


def test_sso_authenticated_user_with_no_local_group_membership_gets_403_on_admin_tabs(
    client, tmp_path, monkeypatch, tmp_groups_file
):
    private_key = _write_test_keypair(tmp_path, monkeypatch)

    # "nobody-in-groups" has no entry at all in tmp_groups_file's canned
    # groups.json -- SSO login must still succeed (it only verifies the
    # token), but authorization must still come from local groups.json,
    # never be implied by a successful SSO login.
    token = _sso_token(private_key, sub="nobody-in-groups")
    client.get(f"/sso/login?token={token}", follow_redirects=False)

    response = client.get("/admin/sources")

    assert response.status_code == 403
