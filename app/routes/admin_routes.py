"""Admin routes: source registry management and manual refresh."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from app.collector import poll_now
from app.decorators import tab_required
from app.sources import add_source, delete_source, list_sources

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/sources", methods=["GET"])
@tab_required("admin")
def sources():
    return render_template("admin/sources.html", sources=list_sources())


@bp.route("/sources", methods=["POST"])
@tab_required("admin")
def add_source_route():
    add_source(
        id=request.form["id"],
        system=request.form["system"],
        name=request.form["name"],
        base_url=request.form["base_url"],
        token=request.form["token"],
        poll_interval_minutes=int(request.form.get("poll_interval_minutes", 15)),
    )
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
