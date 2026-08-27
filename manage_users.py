#!/usr/bin/env python3
"""CLI for managing config/users.json — create, delete, list users."""

from __future__ import annotations

import argparse
import sys

from app.atomic_io import atomic_write_json, read_json
from app.auth import USERS_PATH, create_user, delete_user, hash_password


def _load() -> list[dict]:
    return read_json(USERS_PATH, default={"users": []}).get("users", [])


def _save(users: list[dict]) -> None:
    atomic_write_json(USERS_PATH, {"users": users})


def set_password(username: str, password: str) -> None:
    users = _load()
    for user in users:
        if user["username"] == username:
            user["password_hash"] = hash_password(password)
            _save(users)
            return
    raise ValueError(f"no such user: {username}")


def list_users() -> list[str]:
    return [u["username"] for u in _load()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage 4tExecutive users")
    sub = parser.add_subparsers(dest="command", required=True)

    create_parser = sub.add_parser("create")
    create_parser.add_argument("username")
    create_parser.add_argument("password")

    set_password_parser = sub.add_parser("set-password")
    set_password_parser.add_argument("username")
    set_password_parser.add_argument("password")

    delete_parser = sub.add_parser("delete")
    delete_parser.add_argument("username")

    sub.add_parser("list")

    args = parser.parse_args()

    if args.command == "create":
        create_user(args.username, args.password)
        print(f"Created user: {args.username}")
    elif args.command == "set-password":
        set_password(args.username, args.password)
        print(f"Updated password for user: {args.username}")
    elif args.command == "delete":
        delete_user(args.username)
        print(f"Deleted user: {args.username}")
    elif args.command == "list":
        for username in list_users():
            print(username)


if __name__ == "__main__":
    sys.exit(main())
