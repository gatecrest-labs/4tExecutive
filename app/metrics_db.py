"""SQLite-backed cache for collected metrics, poll state, and dashboard layouts."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "metrics.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                source_id TEXT NOT NULL,
                metric_type TEXT NOT NULL,
                value_json TEXT NOT NULL,
                collected_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS last_polled (
                source_id TEXT PRIMARY KEY,
                collected_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS layouts (
                username TEXT PRIMARY KEY,
                widgets_json TEXT NOT NULL
            )
            """
        )


def write_snapshot(source_id: str, metric_type: str, value: dict, collected_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO snapshots (source_id, metric_type, value_json, collected_at) "
            "VALUES (?, ?, ?, ?)",
            (source_id, metric_type, json.dumps(value), collected_at),
        )


def get_latest(source_id: str, metric_type: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT value_json, collected_at FROM snapshots "
            "WHERE source_id = ? AND metric_type = ? "
            "ORDER BY collected_at DESC LIMIT 1",
            (source_id, metric_type),
        ).fetchone()
    if row is None:
        return None
    return {"value": json.loads(row[0]), "collected_at": row[1]}


def get_history(source_id: str, metric_type: str, since: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT value_json, collected_at FROM snapshots "
            "WHERE source_id = ? AND metric_type = ? AND collected_at >= ? "
            "ORDER BY collected_at ASC",
            (source_id, metric_type, since),
        ).fetchall()
    return [{"value": json.loads(v), "collected_at": c} for v, c in rows]


def set_last_polled(source_id: str, collected_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO last_polled (source_id, collected_at) VALUES (?, ?) "
            "ON CONFLICT(source_id) DO UPDATE SET collected_at = excluded.collected_at",
            (source_id, collected_at),
        )


def get_last_polled(source_id: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT collected_at FROM last_polled WHERE source_id = ?", (source_id,)
        ).fetchone()
    return row[0] if row else None


def get_layout(username: str) -> list[dict]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT widgets_json FROM layouts WHERE username = ?", (username,)
        ).fetchone()
    return json.loads(row[0]) if row else []


def save_layout(username: str, widgets: list[dict]) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO layouts (username, widgets_json) VALUES (?, ?) "
            "ON CONFLICT(username) DO UPDATE SET widgets_json = excluded.widgets_json",
            (username, json.dumps(widgets)),
        )
