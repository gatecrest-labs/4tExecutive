"""Admin routes: source registry management and manual refresh."""

from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.app_settings import get_setting, set_setting
from app.auth import create_user, delete_user, get_user
from app.brief_schedule import (
    get_brief_schedule_config,
    save_brief_schedule_config,
    validate_schedule_config,
)
from app.collector import poll_now, poll_status
from app.config_paths import GENERATED_DIR
from app.decorators import tab_required
from app.domains import get_scoring_config, save_scoring_config
from app.groups import get_user_groups, list_group_names, set_user_groups
from app.local_time import DEFAULT_TIMEZONE, is_valid_timezone
from app.metrics_db import get_brief_sends
from app.smtp_client import load_smtp_config, save_smtp_config, send_email
from app.sources import add_source, delete_source, list_sources
from app.widgets import DEFAULT_RANGE, RANGES, get_widget_series

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _render_admin(
    active_panel,
    sources_error=None,
    users_error=None,
    settings_error=None,
    scoring_error=None,
    reports_error=None,
    reports_message=None,
):
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
        scoring=get_scoring_config(),
        scoring_error=scoring_error,
        smtp_config=load_smtp_config(),
        schedule_config=get_brief_schedule_config(),
        brief_sends=get_brief_sends(),
        reports_error=reports_error,
        reports_message=reports_message,
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


@bp.route("/scoring", methods=["GET"])
@tab_required("admin")
def scoring():
    return _render_admin("scoring")


@bp.route("/scoring", methods=["POST"])
@tab_required("admin")
def update_scoring_route():
    config = get_scoring_config()

    def _parse(field_name):
        raw = request.form.get(field_name)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            raise ValueError(f'"{field_name}" must be a number, got "{raw}".') from None
        if value < 0:
            raise ValueError(f'"{field_name}" must not be negative.')
        return value

    try:
        for name in config["domain_weights"]:
            config["domain_weights"][name] = _parse(f"domain_weights.{name}")
        for name, params in config["domains"].items():
            for key in params:
                params[key] = _parse(f"domains.{name}.{key}")
    except ValueError as exc:
        return _render_admin("scoring", scoring_error=str(exc))

    save_scoring_config(config)
    return redirect(url_for("admin.scoring"))


@bp.route("/system", methods=["GET"])
@tab_required("admin")
def system():
    return _render_admin("system")


# ═══════════════════════  REPORTS PANEL (Executive Brief email/PDF)  ═══════════════════════


@bp.route("/reports", methods=["GET"])
@tab_required("admin")
def reports():
    return _render_admin("reports")


@bp.route("/reports/smtp", methods=["POST"])
@tab_required("admin")
def update_smtp_route():
    try:
        port = int(request.form.get("port", 25))
    except ValueError:
        return _render_admin("reports", reports_error="Port must be a whole number.")

    # The password field never round-trips the decrypted secret back into
    # the rendered <input> (see admin/index.html's placeholder="(unchanged)")
    # -- a blank submitted value means "keep whatever is already stored",
    # mirroring app.sources's "only overwrite the token if one was actually
    # submitted" behavior for the source token field.
    existing = load_smtp_config()
    submitted_password = request.form.get("password", "")
    password = submitted_password if submitted_password else existing.get("password", "")

    save_smtp_config(
        {
            "host": request.form.get("host", "").strip(),
            "port": port,
            "tls_mode": request.form.get("tls_mode", "none"),
            "username": request.form.get("username", "").strip(),
            "password": password,
            "from_address": request.form.get("from_address", "").strip(),
            "enabled": request.form.get("enabled") == "on",
        }
    )
    return redirect(url_for("admin.reports"))


@bp.route("/reports/schedule", methods=["POST"])
@tab_required("admin")
def update_brief_schedule_route():
    try:
        weekday = int(request.form.get("weekday", 0))
    except ValueError:
        weekday = -1  # forces a validation error below rather than a 500
    try:
        hour = int(request.form.get("hour", 8))
    except ValueError:
        hour = -1

    cfg = {
        "weekday": weekday,
        "hour": hour,
        "recipients": request.form.get("recipients", "").strip(),
        "enabled": request.form.get("enabled") == "on",
    }
    errors = validate_schedule_config(cfg)
    if errors:
        return _render_admin("reports", reports_error=" ".join(errors))

    save_brief_schedule_config(cfg)
    return redirect(url_for("admin.reports"))


@bp.route("/reports/test", methods=["POST"])
@tab_required("admin")
def send_test_brief_route():
    """Build today's real brief and email it to one test address, using
    send_email directly (not smtp_client.test_connection's canned message) --
    this is meant to prove the whole render+SMTP path works end to end, not
    just the SMTP connection."""
    from app.brief import build_brief

    to_address = request.form.get("to_address", "").strip()
    if not to_address or "@" not in to_address:
        return _render_admin("reports", reports_error="Enter a valid test recipient address.")

    try:
        from flask import current_app

        brief = build_brief()
        html = current_app.jinja_env.get_template("brief_email.html").render(brief=brief)
        send_email(to_address, "4tExecutive Weekly Brief -- test send", html)
    except Exception as exc:
        return _render_admin("reports", reports_error=f"Test send failed: {exc}")

    return _render_admin("reports", reports_message=f"Test brief sent to {to_address}.")


_DOWNLOAD_MIMETYPES = {"html": "text/html", "pdf": "application/pdf"}


@bp.route("/reports/sends/<int:send_id>/download.<ext>", methods=["GET"])
@tab_required("admin")
def download_brief_send_route(send_id, ext):
    if ext not in _DOWNLOAD_MIMETYPES:
        abort(404)

    send_row = next((s for s in get_brief_sends() if s["id"] == send_id), None)
    if send_row is None:
        abort(404)

    file_path = GENERATED_DIR / f"{send_row['week_key']}.{ext}"
    if not file_path.exists():
        abort(404)

    return send_file(file_path, mimetype=_DOWNLOAD_MIMETYPES[ext], as_attachment=True)


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
