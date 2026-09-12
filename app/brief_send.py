"""Weekly Executive Brief send job: render -> (optional) PDF -> email ->
record the outcome.

Lives in its own module (not app/brief.py, which is pure data/string logic
owned by the brief-core agent) since this is the integration-heavy piece:
Flask app context, filesystem writes, subprocess, SMTP, DB writes. Called
both from the APScheduler job app.collector.init_scheduler registers, and
from the Admin > Reports "Send test" route -- both run inside `app`, per
this repo's existing scheduler convention (app.collector's own jobs are
plain functions closed over module state; this one needs the Flask app
passed in explicitly since it must render a template and call
app.metrics_db from outside a request).

Every sub-step is best-effort/log-and-degrade, matching
app.collector._run_retention/_run_domain_scores's convention: a failure in
PDF generation must not skip sending the HTML-only email, and a failure in
email sending must not crash the scheduler thread or leave brief_sends
un-updated.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from app.brief import build_brief, week_key_for
from app.brief_pdf import render_pdf
from app.brief_schedule import get_brief_schedule_config
from app.config_paths import GENERATED_DIR
from app.metrics_db import insert_brief_send
from app.smtp_client import send_email

logger = logging.getLogger(__name__)


def _render_brief_html(app, brief: dict) -> str:
    """Render brief_email.html (a self-contained, non-base.html template --
    see its docstring) to a string, outside any HTTP request."""
    template = app.jinja_env.get_template("brief_email.html")
    return template.render(brief=brief)


def _write_html_file(html: str, week_key: str) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(GENERATED_DIR) / f"{week_key}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def send_weekly_brief(app, now: datetime | None = None) -> dict:
    """Build, render, (try to) PDF-ify, and email this week's brief.

    Returns a small result dict for callers that want it (the admin "send
    test" route does); always also records the outcome via
    insert_brief_send. Never raises -- every failure path is caught, logged,
    and turned into a "failed"/"partial" brief_sends row instead.
    """
    with app.app_context():
        week_key = week_key_for(now)
        sent_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        schedule_cfg = get_brief_schedule_config()
        recipients = schedule_cfg.get("recipients") or ""

        try:
            brief = build_brief(now=now)
        except Exception:
            logger.exception("Failed to build weekly brief for %s", week_key)
            insert_brief_send(week_key, sent_at, recipients, "failed", error="build_brief failed")
            return {"status": "failed", "week_key": week_key, "error": "build_brief failed"}

        try:
            html = _render_brief_html(app, brief)
            html_path = _write_html_file(html, week_key)
        except Exception:
            logger.exception("Failed to render/write brief HTML for %s", week_key)
            insert_brief_send(week_key, sent_at, recipients, "failed", error="render_brief_html failed")
            return {"status": "failed", "week_key": week_key, "error": "render_brief_html failed"}

        pdf_path = GENERATED_DIR / f"{week_key}.pdf"
        pdf_ok = False
        try:
            pdf_ok = render_pdf(str(html_path), pdf_path)
        except Exception:
            # render_pdf already catches its own errors and returns False --
            # this is an extra belt-and-suspenders guard in case of a bug in
            # it, since a PDF failure must never take down the send.
            logger.exception("Unexpected error generating brief PDF for %s", week_key)
            pdf_ok = False

        attachments = [
            {"filename": f"{week_key}.html", "mimetype": "text/html", "data": html.encode("utf-8")}
        ]
        if pdf_ok:
            attachments.append(
                {
                    "filename": f"{week_key}.pdf",
                    "mimetype": "application/pdf",
                    "data": pdf_path.read_bytes(),
                }
            )

        if not recipients.strip():
            logger.warning("No recipients configured for weekly brief send (%s); skipping email.", week_key)
            insert_brief_send(week_key, sent_at, recipients, "failed", error="no recipients configured")
            return {"status": "failed", "week_key": week_key, "error": "no recipients configured"}

        try:
            send_email(
                recipients,
                f"Weekly Executive Brief -- {brief['week_start']} to {brief['week_end']}",
                html,
                attachments=attachments,
            )
        except Exception as exc:
            logger.exception("Failed to email weekly brief for %s", week_key)
            insert_brief_send(week_key, sent_at, recipients, "failed", error=str(exc) or type(exc).__name__)
            return {"status": "failed", "week_key": week_key, "error": str(exc)}

        status = "sent" if pdf_ok else "partial"
        error = None if pdf_ok else "PDF generation failed; sent HTML only"
        insert_brief_send(week_key, sent_at, recipients, status, error=error)
        return {"status": status, "week_key": week_key, "error": error}
