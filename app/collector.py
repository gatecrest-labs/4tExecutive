"""Scheduled polling of source systems into the local metrics cache."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import psutil
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.domains import DOMAINS, compute_domain, store_domain_scores
from app.events import (
    capture_rag_snapshot,
    detect_and_record,
    record_source_failed,
    record_source_recovered,
)
from app.metric_extract import apply_retention, extract_all
from app.metrics_db import (
    clear_poll_error,
    get_last_polled,
    get_latest,
    get_poll_error,
    insert_metric_points,
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


def _write_metric_points(source_id: str, payload: dict, collected_at: str) -> None:
    """Derive and store metric_points for a snapshot, best-effort.

    An extractor bug must never break polling — same swallow-and-log
    convention as _mark_polled.
    """
    try:
        insert_metric_points(source_id, collected_at, extract_all(payload))
    except Exception:
        logger.exception("Failed to extract metric points for source %s", source_id)


def _fail(source: dict, attempted_at: str, error: str, had_error: bool) -> bool:
    logger.warning("Poll failed for source %s: %s", source["id"], error)
    _mark_polled(source["id"], attempted_at)
    try:
        set_poll_error(source["id"], error, attempted_at)
        if not had_error:
            record_source_failed(source, error)
    except Exception:
        logger.exception("Failed to record poll error for source %s", source["id"])
    return False


def _domains_for_system(system: str) -> list[str]:
    return [name for name, spec in DOMAINS.items() if spec["system"] == system]


def _capture_domain_scores(system: str) -> dict:
    return {name: compute_domain(name)["score"] for name in _domains_for_system(system)}


def _record_change_events(source: dict, before_rag: dict, before_payload: dict | None, before_domain_scores: dict, after_payload: dict) -> None:
    """Compare the just-written poll against the state captured before it and
    record whatever changed. Best-effort — a detector bug must never affect
    polling, same convention as _write_metric_points."""
    try:
        after_rag = capture_rag_snapshot(source["id"], source["system"])
        after_domain_scores = _capture_domain_scores(source["system"])
        detect_and_record(
            source=source,
            before_rag=before_rag,
            after_rag=after_rag,
            before_payload=before_payload,
            after_payload=after_payload,
            before_domain_scores=before_domain_scores,
            after_domain_scores=after_domain_scores,
        )
    except Exception:
        logger.exception("Failed to detect change events for source %s", source["id"])


def poll_source(source: dict) -> bool:
    attempted_at = _now_iso()
    had_error = get_poll_error(source["id"]) is not None
    # Captured before the poll writes anything, so "before" reflects the
    # prior snapshot/metric_points state, not this poll's own data.
    before_rag = capture_rag_snapshot(source["id"], source["system"])
    before_latest = get_latest(source["id"], "summary")
    before_payload = before_latest["value"] if before_latest else None
    before_domain_scores = _capture_domain_scores(source["system"])
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
            return _fail(source, attempted_at, f"HTTP {response.status_code}", had_error)

        payload = response.json()
        write_snapshot(source["id"], "summary", payload, attempted_at)
        _write_metric_points(source["id"], payload, attempted_at)
        set_last_polled(source["id"], attempted_at)
        try:
            clear_poll_error(source["id"])
            if had_error:
                record_source_recovered(source)
        except Exception:
            logger.exception("Failed to clear poll error for source %s", source["id"])
        # No prior snapshot to compare against on a source's first-ever poll
        # — every RAG state would spuriously read as "changed from nothing".
        if before_payload is not None:
            _record_change_events(source, before_rag, before_payload, before_domain_scores, payload)
    except requests.RequestException as exc:
        return _fail(source, attempted_at, str(exc) or type(exc).__name__, had_error)
    except Exception as exc:
        return _fail(source, attempted_at, str(exc) or type(exc).__name__, had_error)

    return True


def poll_self() -> None:
    """Sample this host's own CPU/memory/disk and cache it as a synthetic
    "_self" source — never registered in sources.json/Admin, always present.
    Unlike poll_source, there's no network call and nothing to fail against,
    so no poll_errors/last_polled bookkeeping is needed here."""
    attempted_at = _now_iso()
    payload = {
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("/").percent,
    }
    write_snapshot("_self", "summary", payload, attempted_at)
    _write_metric_points("_self", payload, attempted_at)


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


def _run_retention() -> None:
    try:
        apply_retention()
    except Exception:
        logger.exception("Failed to apply metrics retention")


def _run_domain_scores() -> None:
    try:
        store_domain_scores()
    except Exception:
        logger.exception("Failed to compute domain scores")


def _run_weekly_brief(app) -> None:
    try:
        from app.brief_send import send_weekly_brief

        send_weekly_brief(app)
    except Exception:
        logger.exception("Failed to send weekly brief")


def _register_weekly_brief_job(scheduler: BackgroundScheduler, app) -> None:
    """Register the weekly brief send job, if enabled in config at
    scheduler-start time.

    Like every other job in this function, the schedule is read once at
    startup -- there is no hot-reload if an operator changes the weekday/
    hour/enabled fields in Admin > Reports afterwards; that takes effect on
    the next app restart, same as poll_all's fixed 1-minute interval or
    domain_scores' fixed 5-minute interval not being reconfigurable either.
    """
    try:
        from app.brief_schedule import get_brief_schedule_config

        schedule_cfg = get_brief_schedule_config()
    except Exception:
        logger.exception("Failed to load brief schedule config; weekly brief job not registered")
        return

    if not schedule_cfg.get("enabled"):
        return

    scheduler.add_job(
        lambda: _run_weekly_brief(app),
        CronTrigger(day_of_week=schedule_cfg.get("weekday", 0), hour=schedule_cfg.get("hour", 8)),
        id="weekly_brief",
    )


def init_scheduler(app) -> None:
    scheduler = BackgroundScheduler()
    scheduler.add_job(poll_all, "interval", minutes=1, id="poll_all")
    scheduler.add_job(poll_self, "interval", minutes=1, id="poll_self")
    scheduler.add_job(_run_retention, "interval", hours=24, id="metrics_retention")
    scheduler.add_job(_run_domain_scores, "interval", minutes=5, id="domain_scores")
    _register_weekly_brief_job(scheduler, app)
    scheduler.start()
    app.extensions["scheduler"] = scheduler
