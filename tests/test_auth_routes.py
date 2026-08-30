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
