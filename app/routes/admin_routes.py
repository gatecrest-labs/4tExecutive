"""Admin routes: source registry management and manual refresh."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from app.collector import poll_now, poll_status
from app.decorators import tab_required
from app.sources import add_source, delete_source, list_sources

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _render_sources(error: str | None = None):
    sources = list_sources()
    statuses = {source["id"]: poll_status(source["id"]) for source in sources}
    return render_template(
        "admin/sources.html", sources=sources, statuses=statuses, error=error
    )


@bp.route("/sources", methods=["GET"])
@tab_required("admin")
def sources():
    return _render_sources()


@bp.route("/sources", methods=["POST"])
@tab_required("admin")
def add_source_route():
    base_url = request.form["base_url"]
    if not base_url.startswith("https://"):
        return _render_sources(
            error="Base URL must start with https:// (bearer token would otherwise be sent in cleartext)."
        )

    try:
        poll_interval_minutes = int(request.form.get("poll_interval_minutes", 15))
    except ValueError:
        return _render_sources(error="Poll interval (minutes) must be a whole number.")

    try:
        add_source(
            id=request.form["id"],
            system=request.form["system"],
            name=request.form["name"],
            base_url=base_url,
            token=request.form["token"],
            poll_interval_minutes=poll_interval_minutes,
            verify_tls=request.form.get("skip_tls_verify") != "on",
        )
    except ValueError as exc:
        return _render_sources(error=str(exc))

    return redirect(url_for("admin.sources"))


@bp.route("/sources/<source_id>/delete", methods=["POST"])
@tab_required("admin")
def delete_source_route(source_id):
    delete_source(source_id)
    return redirect(url_for("admin.sources"))


@bp.route("/sources/<source_id>/refresh", methods=["POST"])
@tab_required("admin")
def refresh_source_route(source_id):
    poll_now(source_id)
    return redirect(url_for("admin.sources"))
