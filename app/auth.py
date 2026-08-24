"""Local user store and bcrypt password verification."""

from __future__ import annotations

import bcrypt

from app.atomic_io import read_json
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
    return bcrypt.checkpw(password.encode(), user["password_hash"].encode())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
