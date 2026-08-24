"""Scheduled polling of source systems into the local metrics cache."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests
from apscheduler.schedulers.background import BackgroundScheduler

from app.metrics_db import get_last_polled, set_last_polled, write_snapshot
from app.sources import get_source, list_sources, source_headers

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 10


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mark_polled(source_id: str, attempted_at: str) -> None:
    """Record a poll attempt (success or failure), best-effort.

    Called on both success and failure paths so a down source is retried on
    its configured poll_interval_minutes instead of every scheduler tick.
    Swallows its own errors so a failure here (e.g. during error handling)
    never masks/replaces the original failure being reported.
    """
    try:
        set_last_polled(source_id, attempted_at)
    except Exception:
        logger.exception("Failed to record last_polled for source %s", source_id)


def poll_source(source: dict) -> bool:
    attempted_at = _now_iso()
    try:
        url = f"{source['base_url']}/external/api/executive/summary"
        response = requests.get(
            url, headers=source_headers(source), timeout=REQUEST_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            logger.warning("Poll failed for source %s: HTTP %s", source["id"], response.status_code)
            _mark_polled(source["id"], attempted_at)
            return False

        write_snapshot(source["id"], "summary", response.json(), attempted_at)
        set_last_polled(source["id"], attempted_at)
    except requests.RequestException as exc:
        logger.warning("Poll failed for source %s: %s", source["id"], exc)
        _mark_polled(source["id"], attempted_at)
        return False
    except Exception as exc:
        logger.warning("Poll failed for source %s: %s", source["id"], exc)
        _mark_polled(source["id"], attempted_at)
        return False

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
        try:
            if not source.get("enabled", True):
                continue
            if not _is_due(source):
                continue
            poll_source(source)
        except Exception:
            logger.exception(
                "Unexpected error polling source %s; continuing with remaining sources",
                source.get("id", "<unknown>"),
            )


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
