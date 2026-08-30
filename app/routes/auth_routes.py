"""Login and logout routes."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from app import limiter
from app.auth import verify_password

bp = Blueprint("auth", __name__)


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if verify_password(username, password):
            session["username"] = username
            return redirect(url_for("dashboard.index"))
        error = "Invalid username or password."
    return render_template("login.html", error=error)


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.pop("username", None)
    return redirect(url_for("auth.login"))
