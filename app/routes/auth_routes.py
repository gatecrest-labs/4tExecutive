"""Login and logout routes."""

from __future__ import annotations

import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import limiter
from app.auth import verify_password
from app.groups import user_has_any_tab
from app.sso_verify import verify_token

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_password(username, password):
            session.pop("sso_login_at", None)  # a local session is never revocation-checked
            session["username"] = username
            if not user_has_any_tab(username):
                return redirect(url_for("auth.no_access"))
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@bp.route("/no-access")
def no_access():
    if "username" not in session:
        return redirect(url_for("auth.login"))
    return render_template("no_access.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop("username", None)
    session.pop("sso_login_at", None)
    return redirect(url_for("auth.login"))


@bp.route("/sso/login")
def sso_login():
    token = request.args.get("token", "")
    username = verify_token(token)
    if username is None:
        flash("SSO login failed or expired -- please log in directly.", "danger")
        return redirect(url_for("auth.login"))
    session.clear()  # fully re-derive -- never trust stale session state
    session["username"] = username
    session["sso_login_at"] = time.time()
    if not user_has_any_tab(username):
        return redirect(url_for("auth.no_access"))
    return redirect(url_for("dashboard.index"))


@bp.app_errorhandler(403)
def forbidden(error):
    """A signed-in user who has been granted no tabs at all sees why, instead
    of a bare 403 page. The status stays 403 and nothing becomes reachable."""
    wants_json = request.accept_mimetypes.best_match(["text/html", "application/json"]) == (
        "application/json"
    )
    if "username" in session and not wants_json and not user_has_any_tab(session["username"]):
        return render_template("no_access.html"), 403
    return error
