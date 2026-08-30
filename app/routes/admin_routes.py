"""Admin routes: source registry management and manual refresh."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for

from app.app_settings import get_setting, set_setting
from app.auth import create_user, delete_user, get_user
from app.collector import poll_now, poll_status
from app.decorators import tab_required
from app.groups import get_user_groups, list_group_names, set_user_groups
from app.local_time import DEFAULT_TIMEZONE, is_valid_timezone
from app.sources import add_source, delete_source, list_sources
from app.widgets import DEFAULT_RANGE, RANGES, get_widget_series

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _render_admin(active_panel, sources_error=None, users_error=None, settings_error=None):
    from app.atomic_io import read_json
    from app.auth import USERS_PATH

    sources = list_sources()
    statuses = {source["id"]: poll_status(source["id"]) for source in sources}
    usernames = [u["username"] for u in read_json(USERS_PATH, default={"users": []})["users"]]
    users = [{"username": name, "groups": get_user_groups(name)} for name in usernames]

    return render_template(
        "admin/index.html",
        active_panel=active_panel,
        sources=sources,
        statuses=statuses,
        sources_error=sources_error,
        users=users,
        all_groups=list_group_names(),
        users_error=users_error,
        timezone=get_setting("timezone", DEFAULT_TIMEZONE),
        settings_error=settings_error,
    )


@bp.route("/sources", methods=["GET"])
@tab_required("admin")
def sources():
    return _render_admin("sources")


@bp.route("/sources", methods=["POST"])
@tab_required("admin")
def add_source_route():
    base_url = request.form["base_url"]
    if not base_url.startswith("https://"):
        return _render_admin(
            "sources",
            sources_error="Base URL must start with https:// (bearer token would otherwise be sent in cleartext).",
        )

    try:
        poll_interval_minutes = int(request.form.get("poll_interval_minutes", 15))
    except ValueError:
        return _render_admin("sources", sources_error="Poll interval (minutes) must be a whole number.")

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
        return _render_admin("sources", sources_error=str(exc))

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


@bp.route("/users", methods=["GET"])
@tab_required("admin")
def users():
    return _render_admin("users")


@bp.route("/users", methods=["POST"])
@tab_required("admin")
def add_user_route():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    groups = request.form.getlist("groups")

    if not username:
        return _render_admin("users", users_error="Username is required.")
    if get_user(username) is not None:
        return _render_admin("users", users_error=f"user already exists: {username}")

    try:
        create_user(username, password)
    except ValueError as exc:
        return _render_admin("users", users_error=str(exc))

    set_user_groups(username, groups)
    return redirect(url_for("admin.users"))


@bp.route("/users/<username>/delete", methods=["POST"])
@tab_required("admin")
def delete_user_route(username):
    if username == session["username"]:
        abort(400)
    delete_user(username)
    set_user_groups(username, [])
    return redirect(url_for("admin.users"))


@bp.route("/settings", methods=["GET"])
@tab_required("admin")
def settings():
    return _render_admin("settings")


@bp.route("/settings", methods=["POST"])
@tab_required("admin")
def update_settings_route():
    tz = request.form.get("timezone", "").strip()
    if not is_valid_timezone(tz):
        return _render_admin(
            "settings",
            settings_error=f'"{tz}" is not a recognized IANA timezone name (e.g. "America/Chicago", "UTC").',
        )
    set_setting("timezone", tz)
    return redirect(url_for("admin.settings"))


@bp.route("/system", methods=["GET"])
@tab_required("admin")
def system():
    return _render_admin("system")


_HOST_METRICS_KEYS = {
    "4texecutive.cpu_percent": "cpu",
    "4texecutive.memory_percent": "mem",
    "4texecutive.disk_percent": "disk",
}


@bp.route("/api/host-metrics", methods=["GET"])
@tab_required("admin")
def host_metrics_api():
    range_key = request.args.get("range", DEFAULT_RANGE)
    if range_key not in RANGES:
        range_key = DEFAULT_RANGE

    result = {}
    for widget_type, short_key in _HOST_METRICS_KEYS.items():
        series = get_widget_series({"type": widget_type, "source_instance": "_self"}, range_key)
        points = (series or {}).get("points") or []
        result[short_key] = [
            {"ts": int(datetime.fromisoformat(ts).timestamp()), "v": v}
            for ts, v in points
        ]
    return jsonify(result)
