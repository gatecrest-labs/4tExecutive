"""Admin routes: source registry management and manual refresh."""

from __future__ import annotations

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from app.auth import create_user, delete_user, get_user
from app.collector import poll_now, poll_status
from app.decorators import tab_required
from app.groups import get_user_groups, list_group_names, set_user_groups
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


def _render_users(error: str | None = None):
    from app.atomic_io import read_json
    from app.auth import USERS_PATH

    usernames = [u["username"] for u in read_json(USERS_PATH, default={"users": []})["users"]]
    users = [{"username": name, "groups": get_user_groups(name)} for name in usernames]
    return render_template(
        "admin/users.html",
        users=users,
        all_groups=list_group_names(),
        error=error,
    )


@bp.route("/users", methods=["GET"])
@tab_required("admin")
def users():
    return _render_users()


@bp.route("/users", methods=["POST"])
@tab_required("admin")
def add_user_route():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    groups = request.form.getlist("groups")

    if not username:
        return _render_users(error="Username is required.")
    if get_user(username) is not None:
        return _render_users(error=f"user already exists: {username}")

    try:
        create_user(username, password)
    except ValueError as exc:
        return _render_users(error=str(exc))

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
