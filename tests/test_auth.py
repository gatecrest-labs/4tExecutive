import json

from app.auth import get_user, hash_password, verify_password


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
