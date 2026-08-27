"""Scheduled polling of source systems into the local metrics cache."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import psutil
import requests
from apscheduler.schedulers.background import BackgroundScheduler

from app.metrics_db import (
    clear_poll_error,
    get_last_polled,
    get_latest,
    get_poll_error,
    set_last_polled,
    set_poll_error,
    write_snapshot,
)
from app.sources import get_source, list_sources, source_headers

logger = logging.getLogger(__name__)
REQUEST_TIMEOUT_SECONDS = 10


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def _fail(source_id: str, attempted_at: str, error: str) -> bool:
    logger.warning("Poll failed for source %s: %s", source_id, error)
    _mark_polled(source_id, attempted_at)
    try:
        set_poll_error(source_id, error, attempted_at)
    except Exception:
        logger.exception("Failed to record poll error for source %s", source_id)
    return False


def poll_source(source: dict) -> bool:
    attempted_at = _now_iso()
    try:
        url = f"{source['base_url']}/external/api/executive/summary"
        response = requests.get(
            url,
            headers=source_headers(source),
            timeout=REQUEST_TIMEOUT_SECONDS,
            # Off only for sources explicitly marked as self-signed/internal
            # certs in Admin — see the verify_tls note in app/sources.py.
            verify=source.get("verify_tls", True),
        )
        if response.status_code != 200:
            return _fail(source["id"], attempted_at, f"HTTP {response.status_code}")

        write_snapshot(source["id"], "summary", response.json(), attempted_at)
        set_last_polled(source["id"], attempted_at)
        try:
            clear_poll_error(source["id"])
        except Exception:
            logger.exception("Failed to clear poll error for source %s", source["id"])
    except requests.RequestException as exc:
        return _fail(source["id"], attempted_at, str(exc) or type(exc).__name__)
    except Exception as exc:
        return _fail(source["id"], attempted_at, str(exc) or type(exc).__name__)

    return True


def poll_self() -> None:
    """Sample this host's own CPU/memory/disk and cache it as a synthetic
    "_self" source — never registered in sources.json/Admin, always present.
    Unlike poll_source, there's no network call and nothing to fail against,
    so no poll_errors/last_polled bookkeeping is needed here."""
    write_snapshot(
        "_self",
        "summary",
        {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage("/").percent,
        },
        _now_iso(),
    )


def poll_status(source_id: str) -> dict:
    """Best-known state of a source's polling for display in Admin.

    Distinct from `_is_due`: this describes outcome (ok/failed/pending) for a
    human, not scheduling. `error` is only set to a live poll_errors row —
    it's cleared on the first success after a failure, so a "failed" status
    always reflects the most recent attempt, never a stale one that was
    later superseded by a success.
    """
    error = get_poll_error(source_id)
    if error is not None:
        return {"status": "failed", "detail": error["error"], "at": error["attempted_at"]}
    latest = get_latest(source_id, "summary")
    if latest is not None:
        return {"status": "ok", "detail": None, "at": latest["collected_at"]}
    return {"status": "pending", "detail": None, "at": None}


def _is_due(source: dict) -> bool:
    last_polled = get_last_polled(source["id"])
    if last_polled is None:
        return True
    last_dt = datetime.strptime(last_polled, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    interval = timedelta(minutes=source["poll_interval_minutes"])
    return datetime.now(UTC) >= last_dt + interval


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
    scheduler.add_job(poll_self, "interval", minutes=1, id="poll_self")
    scheduler.start()
    app.extensions["scheduler"] = scheduler
