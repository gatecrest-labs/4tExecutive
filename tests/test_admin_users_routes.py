import json

import app.auth as auth_module
import app.groups as groups_module


def _login_as_admin(client, tmp_path, monkeypatch, username="carol"):
    with client.session_transaction() as sess:
        sess["username"] = username
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps(
            {
                "administrators": {"members": [username], "allowed_tabs": ["admin"]},
                "executives": {"members": [], "allowed_tabs": ["dashboard"]},
            }
        )
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_admin_users_page_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/users")
    assert response.status_code == 403


def test_admin_users_page_lists_users(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")
    auth_module.create_user("dave", "secret")

    response = client.get("/admin/users")

    assert response.status_code == 200
    assert b"dave" in response.data


def test_add_user_via_post(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")

    response = client.post(
        "/admin/users",
        data={"username": "dave", "password": "secret", "groups": ["executives"]},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert auth_module.get_user("dave") is not None
    assert groups_module.get_user_groups("dave") == ["executives"]


def test_add_user_duplicate_username_shows_error_instead_of_500(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")
    auth_module.create_user("dave", "secret")

    response = client.post(
        "/admin/users",
        data={"username": "dave", "password": "other", "groups": []},
    )

    assert response.status_code == 200
    assert b"already exists" in response.data


def test_delete_user(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")
    auth_module.create_user("dave", "secret")

    response = client.post("/admin/users/dave/delete", follow_redirects=False)

    assert response.status_code == 302
    assert auth_module.get_user("dave") is None


def test_delete_user_refuses_to_delete_self(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch, username="carol")
    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")
    auth_module.create_user("carol", "secret")

    response = client.post("/admin/users/carol/delete", follow_redirects=False)

    assert response.status_code == 400
    assert auth_module.get_user("carol") is not None
