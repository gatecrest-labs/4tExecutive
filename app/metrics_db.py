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
            CREATE TABLE IF NOT EXISTS poll_errors (
                source_id TEXT PRIMARY KEY,
                error TEXT NOT NULL,
                attempted_at TEXT NOT NULL
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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metric_points (
                source_id TEXT NOT NULL,
                metric_key TEXT NOT NULL,
                ts TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY (source_id, metric_key, ts)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                source_id TEXT,
                metric_key TEXT,
                kind TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                detail TEXT NOT NULL
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


def set_poll_error(source_id: str, error: str, attempted_at: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO poll_errors (source_id, error, attempted_at) VALUES (?, ?, ?) "
            "ON CONFLICT(source_id) DO UPDATE SET error = excluded.error, "
            "attempted_at = excluded.attempted_at",
            (source_id, error, attempted_at),
        )


def clear_poll_error(source_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM poll_errors WHERE source_id = ?", (source_id,))


def get_poll_error(source_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT error, attempted_at FROM poll_errors WHERE source_id = ?", (source_id,)
        ).fetchone()
    return {"error": row[0], "attempted_at": row[1]} if row else None


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


def insert_metric_points(source_id: str, ts: str, points: dict[str, float | None]) -> None:
    """Upsert one derived metric point per (source_id, metric_key) at ts.

    None values are skipped (an extractor reporting "not applicable" for this
    payload shouldn't create a fabricated 0/null row). Re-inserting the same
    (source_id, metric_key, ts) replaces the prior value, so backfill is safe
    to re-run.
    """
    rows = [(source_id, key, ts, value) for key, value in points.items() if value is not None]
    if not rows:
        return
    with _connect() as conn:
        conn.executemany(
            "INSERT INTO metric_points (source_id, metric_key, ts, value) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(source_id, metric_key, ts) DO UPDATE SET value = excluded.value",
            rows,
        )


def iter_all_snapshots() -> list[dict]:
    """Every stored snapshot, oldest first, for one-time backfills."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT source_id, value_json, collected_at FROM snapshots ORDER BY collected_at ASC"
        ).fetchall()
    return [{"source_id": s, "value": json.loads(v), "collected_at": c} for s, v, c in rows]


def get_metric_series(source_id: str, metric_key: str, since: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT ts, value FROM metric_points "
            "WHERE source_id = ? AND metric_key = ? AND ts >= ? "
            "ORDER BY ts ASC",
            (source_id, metric_key, since),
        ).fetchall()
    return [{"ts": ts, "value": value} for ts, value in rows]


def get_metric_latest_at_or_before(source_id: str, metric_key: str, before: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT ts, value FROM metric_points "
            "WHERE source_id = ? AND metric_key = ? AND ts <= ? "
            "ORDER BY ts DESC LIMIT 1",
            (source_id, metric_key, before),
        ).fetchone()
    return {"ts": row[0], "value": row[1]} if row else None


def prune_snapshots_older_than(cutoff_iso: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM snapshots WHERE collected_at < ?", (cutoff_iso,))


def prune_metric_points_older_than(cutoff_iso: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM metric_points WHERE ts < ?", (cutoff_iso,))


def downsample_metric_points(cutoff_iso: str) -> None:
    """Collapse metric_points older than cutoff_iso to one mean point per calendar day.

    Groups by (source_id, metric_key, day) using the ts's date portion (ts is
    always UTC ISO-8601, so a string prefix is a safe day key). A group with
    only one point already is left untouched by the replace (same ts, same
    value). Runs as a single INSERT...SELECT + DELETE pass rather than
    row-by-row to keep the daily retention job cheap.
    """
    with _connect() as conn:
        conn.execute(
            """
            CREATE TEMP TABLE _daily AS
            SELECT source_id, metric_key, substr(ts, 1, 10) || 'T00:00:00Z' AS day_ts,
                   AVG(value) AS avg_value
            FROM metric_points
            WHERE ts < ?
            GROUP BY source_id, metric_key, substr(ts, 1, 10)
            """,
            (cutoff_iso,),
        )
        conn.execute("DELETE FROM metric_points WHERE ts < ?", (cutoff_iso,))
        conn.execute(
            "INSERT INTO metric_points (source_id, metric_key, ts, value) "
            "SELECT source_id, metric_key, day_ts, avg_value FROM _daily WHERE 1=1 "
            "ON CONFLICT(source_id, metric_key, ts) DO UPDATE SET value = excluded.value"
        )
        conn.execute("DROP TABLE _daily")


def insert_event(
    *,
    ts: str,
    source_id: str | None,
    metric_key: str | None,
    kind: str,
    severity: str,
    title: str,
    detail: dict,
) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT INTO events (ts, source_id, metric_key, kind, severity, title, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, source_id, metric_key, kind, severity, title, json.dumps(detail)),
        )
        return cursor.lastrowid


def get_events(since: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, ts, source_id, metric_key, kind, severity, title, detail "
            "FROM events WHERE ts >= ? ORDER BY ts DESC, id DESC",
            (since,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "ts": row[1],
            "source_id": row[2],
            "metric_key": row[3],
            "kind": row[4],
            "severity": row[5],
            "title": row[6],
            "detail": json.loads(row[7]),
        }
        for row in rows
    ]
