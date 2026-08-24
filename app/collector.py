"""Scheduled polling of source systems into the local metrics cache."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests
from apscheduler.schedulers.background import BackgroundScheduler

from app.metrics_db import get_last_polled, set_last_polled, write_snapshot
from app.sources import get_source, list_sources, source_headers

REQUEST_TIMEOUT_SECONDS = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def poll_source(source: dict) -> bool:
    url = f"{source['base_url']}/external/api/executive/summary"
    try:
        response = requests.get(
            url, headers=source_headers(source), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException:
        return False

    if response.status_code != 200:
        return False

    write_snapshot(source["id"], "summary", response.json(), _now_iso())
    set_last_polled(source["id"], _now_iso())
    return True


def _is_due(source: dict) -> bool:
    last_polled = get_last_polled(source["id"])
    if last_polled is None:
        return True
    last_dt = datetime.strptime(last_polled, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    interval = timedelta(minutes=source["poll_interval_minutes"])
    return datetime.now(timezone.utc) >= last_dt + interval


def poll_all() -> None:
    for source in list_sources():
        if not source.get("enabled", True):
            continue
        if not _is_due(source):
            continue
        poll_source(source)


def poll_now(source_id: str) -> bool:
    source = get_source(source_id)
    if source is None:
        return False
    return poll_source(source)


def init_scheduler(app) -> None:
    scheduler = BackgroundScheduler()
    scheduler.add_job(poll_all, "interval", minutes=1, id="poll_all")
    scheduler.start()
    app.extensions["scheduler"] = scheduler
