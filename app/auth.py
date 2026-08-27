"""Local user store and bcrypt password verification."""

from __future__ import annotations

import bcrypt

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR

USERS_PATH = CONFIG_DIR / "users.json"


def _load_users() -> list[dict]:
    return read_json(USERS_PATH, default={"users": []}).get("users", [])


def get_user(username: str) -> dict | None:
    for user in _load_users():
        if user.get("username") == username:
            return user
    return None


def verify_password(username: str, password: str) -> bool:
    user = get_user(username)
    if user is None:
        return False
    try:
        return bcrypt.checkpw(password.encode(), user["password_hash"].encode())
    except ValueError:
        # Raised by bcrypt for a malformed/invalid hash (e.g. an unbootstrapped
        # "REPLACE_WITH_BCRYPT_HASH" placeholder) or an over-long password.
        # Treat both as a failed login rather than a 500.
        return False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _save_users(users: list[dict]) -> None:
    atomic_write_json(USERS_PATH, {"users": users})


def create_user(username: str, password: str) -> None:
    users = _load_users()
    if any(user["username"] == username for user in users):
        raise ValueError(f"user already exists: {username}")
    users.append({"username": username, "password_hash": hash_password(password)})
    _save_users(users)


def delete_user(username: str) -> None:
    users = [user for user in _load_users() if user["username"] != username]
    _save_users(users)
