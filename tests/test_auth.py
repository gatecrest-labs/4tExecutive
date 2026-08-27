import json

import pytest

from app.auth import create_user, delete_user, get_user, hash_password, verify_password


def test_get_user_returns_matching_user(tmp_users_file):
    user = get_user("alice")
    assert user is not None
    assert user["username"] == "alice"


def test_get_user_returns_none_for_unknown_user(tmp_users_file):
    assert get_user("bob") is None


def test_verify_password_accepts_correct_password(tmp_users_file):
    assert verify_password("alice", "correct-horse") is True


def test_verify_password_rejects_wrong_password(tmp_users_file):
    assert verify_password("alice", "wrong-password") is False


def test_verify_password_rejects_unknown_user(tmp_users_file):
    assert verify_password("nobody", "anything") is False


def test_verify_password_rejects_malformed_hash_instead_of_raising(tmp_path, monkeypatch):
    import app.auth as auth_module

    users_path = tmp_path / "users.json"
    users_path.write_text(
        json.dumps(
            {"users": [{"username": "bob", "password_hash": "REPLACE_WITH_BCRYPT_HASH"}]}
        )
    )
    monkeypatch.setattr(auth_module, "USERS_PATH", users_path)

    assert verify_password("bob", "anything") is False


def test_verify_password_rejects_oversized_password_instead_of_raising(tmp_users_file):
    assert verify_password("alice", "x" * 100) is False


def test_hash_password_produces_verifiable_hash():
    hashed = hash_password("new-password")
    import bcrypt

    assert bcrypt.checkpw(b"new-password", hashed.encode())


def test_create_user_adds_a_user(tmp_path, monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")
    import bcrypt

    create_user("alice", "secret")

    users = json.loads((tmp_path / "users.json").read_text())["users"]
    assert users[0]["username"] == "alice"
    assert bcrypt.checkpw(b"secret", users[0]["password_hash"].encode())


def test_create_user_rejects_duplicate_username(tmp_path, monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")

    create_user("alice", "secret")
    with pytest.raises(ValueError):
        create_user("alice", "other")


def test_delete_user_removes_user(tmp_path, monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")

    create_user("alice", "secret")
    delete_user("alice")

    assert json.loads((tmp_path / "users.json").read_text())["users"] == []


def test_delete_user_is_a_no_op_for_unknown_username(tmp_path, monkeypatch):
    import app.auth as auth_module

    monkeypatch.setattr(auth_module, "USERS_PATH", tmp_path / "users.json")

    delete_user("nobody")  # must not raise even though users.json doesn't exist yet
