#!/usr/bin/env python3
"""Populate config/ and metrics.db with fake data for visual QA.

Run with: python seed_demo_data.py
Then: docker compose up --build, and log in at http://localhost:8200
with DEMO_USERNAME / DEMO_PASSWORD (printed below).

Writes metrics snapshots directly — no network calls, no real source
systems required.
"""

from __future__ import annotations

from datetime import UTC, datetime

import app.groups as groups_module
import app.sources as sources_module
import manage_users
from app.atomic_io import atomic_write_json
from app.config_paths import bootstrap_config
from app.layouts import save_layout
from app.metrics_db import init_db, write_snapshot
from app.widgets import WIDGET_CATALOG

DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo-password-123"

_DEMO_SOURCES = [
    {
        "id": "demo-4thealth",
        "system": "4thealth",
        "name": "Demo — 4thealth (HQ)",
        "base_url": "https://demo-4thealth.invalid:8100",
    },
    {
        "id": "demo-4tlog",
        "system": "4tlog",
        "name": "Demo — 4tlog (HQ)",
        "base_url": "https://demo-4tlog.invalid:8100",
    },
]

_DEMO_SNAPSHOT_VALUES = {
    "demo-4thealth": {
        "hygiene_score": 94,
        "version_compliance_pct": 88,
        "pending_config_diff_count": 3,
        "last_backup_status": "OK — 2026-08-23T02:00:00Z",
        "firewall_online_count": 12,
    },
    "demo-4tlog": {
        "faz_health": "Healthy (2 of 2 targets up)",
        "log_volume_trend": "12.4M events/day (+3% week over week)",
    },
}

_SIZE_CYCLE = ["1x1", "2x1", "2x2"]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed() -> None:
    bootstrap_config()
    init_db()

    if DEMO_USERNAME not in manage_users.list_users():
        manage_users.create_user(DEMO_USERNAME, DEMO_PASSWORD)

    atomic_write_json(
        groups_module.GROUPS_PATH,
        {
            "demo": {
                "members": [DEMO_USERNAME],
                "allowed_tabs": ["dashboard", "admin"],
            }
        },
    )

    for demo_source in _DEMO_SOURCES:
        if sources_module.get_source(demo_source["id"]) is None:
            sources_module.add_source(
                id=demo_source["id"],
                system=demo_source["system"],
                name=demo_source["name"],
                base_url=demo_source["base_url"],
                token="demo-token-not-a-real-secret",
                enabled=False,  # demo hosts don't exist; avoid noisy failed polls
            )
        write_snapshot(
            demo_source["id"], "summary", _DEMO_SNAPSHOT_VALUES[demo_source["id"]], _now_iso()
        )

    layout = []
    for index, (widget_type, entry) in enumerate(WIDGET_CATALOG.items()):
        source_id = "demo-4thealth" if entry["source_system"] == "4thealth" else "demo-4tlog"
        layout.append(
            {
                "type": widget_type,
                "source_instance": source_id,
                "size": _SIZE_CYCLE[index % len(_SIZE_CYCLE)],
                "date_range": "30d",
            }
        )
    save_layout(DEMO_USERNAME, layout)

    print(f"Seeded demo data. Log in with username={DEMO_USERNAME!r} password={DEMO_PASSWORD!r}")


if __name__ == "__main__":
    seed()
