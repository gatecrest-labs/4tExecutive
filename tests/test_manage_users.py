
import pytest

import manage_users
from app.atomic_io import read_json


@pytest.fixture(autouse=True)
def tmp_users(tmp_path, monkeypatch):
    monkeypatch.setattr(manage_users, "USERS_PATH", tmp_path / "users.json")


def test_create_adds_a_user():
    manage_users.create_user("alice", "secret")
    users = read_json(manage_users.USERS_PATH)["users"]
    assert users[0]["username"] == "alice"
    import bcrypt

    assert bcrypt.checkpw(b"secret", users[0]["password_hash"].encode())


def test_create_rejects_duplicate_username():
    manage_users.create_user("alice", "secret")
    with pytest.raises(ValueError):
        manage_users.create_user("alice", "other")


def test_delete_removes_user():
    manage_users.create_user("alice", "secret")
    manage_users.delete_user("alice")
    assert read_json(manage_users.USERS_PATH)["users"] == []


def test_list_users_returns_usernames():
    manage_users.create_user("alice", "secret")
    manage_users.create_user("bob", "secret2")
    assert manage_users.list_users() == ["alice", "bob"]
