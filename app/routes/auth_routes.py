"""Login and logout routes."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app import limiter
from app.auth import verify_password
from app.sso_verify import verify_token

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_password(username, password):
            session["username"] = username
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop("username", None)
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
    return redirect(url_for("dashboard.index"))
