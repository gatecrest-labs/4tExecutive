"""Route guards for login and tab-level access control."""

from __future__ import annotations

from functools import wraps

from flask import abort, current_app, redirect, session, url_for

from app.groups import user_has_tab


def _sso_session_ok() -> bool:
    login_at = session.get("sso_login_at")
    if login_at is None:
        return True  # local session: never subject to revocation
    checker = current_app.extensions.get("tsuite_session_checker")
    if checker is None:
        return True
    return bool(checker(session.get("username", ""), login_at))


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("auth.login"))
        if not _sso_session_ok():
            session.clear()
            return redirect(url_for("auth.login"))
        return fn(*args, **kwargs)

    return wrapper


def tab_required(tab: str):
    def decorator(fn):
        @wraps(fn)
        @login_required
        def wrapper(*args, **kwargs):
            if not user_has_tab(session["username"], tab):
                abort(403)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
