"""Flask app factory for 4tExecutive."""

from __future__ import annotations

import os

from flask import Flask
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect

from app.config_paths import bootstrap_config
from app.groups import user_has_tab

# Matches the placeholder value shipped in .env.example — if an operator copies
# .env.example to .env without changing it, we must refuse to boot rather than
# sign session cookies with a publicly known key.
_PLACEHOLDER_SECRET_KEY = "change-me-to-a-random-value"

csrf = CSRFProtect()
# In-memory storage, scoped to this process — matches the Dockerfile's
# single-gunicorn-worker deployment. Scaling to multiple workers/instances
# needs a shared backend (e.g. Redis) or each process enforces its own
# independent limit.
limiter = Limiter(key_func=get_remote_address)


def _resolve_cookie_secure() -> bool:
    """Mirror 4thealth's convention: auto-enable Secure cookies when TLS cert
    files are present, override with COOKIE_SECURE=true|false."""
    cert = os.environ.get("SSL_CERT", "certs/cert.pem")
    key = os.environ.get("SSL_KEY", "certs/key.pem")
    ssl_active = os.path.exists(cert) and os.path.exists(key)
    setting = os.environ.get("COOKIE_SECURE", "auto").lower()
    return setting == "true" or (setting == "auto" and ssl_active)


def create_app(
    testing: bool = False,
    *,
    enable_csrf: bool | None = None,
    enable_rate_limit: bool | None = None,
) -> Flask:
    flask_app = Flask(__name__)

    if testing:
        flask_app.secret_key = "dev-only-change-me"
    else:
        secret_key = os.environ.get("SECRET_KEY")
        if not secret_key or secret_key == _PLACEHOLDER_SECRET_KEY:
            raise RuntimeError(
                "SECRET_KEY environment variable must be set to a real secret "
                "value (not the .env.example placeholder) before starting the "
                "app outside of testing mode."
            )
        flask_app.secret_key = secret_key

    # Flask's default cookie name ("session") collides with any other Flask
    # app on the same hostname — cookies are scoped by domain+path, not
    # port, so e.g. 4thealth-plus on :8100 and 4tExecutive on :8200, both at
    # "localhost", would silently overwrite each other's session cookie in
    # the browser. A unique name makes that impossible regardless of what
    # else is running alongside it.
    flask_app.config["SESSION_COOKIE_NAME"] = "4texecutive_session"
    flask_app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    flask_app.config["SESSION_COOKIE_SECURE"] = _resolve_cookie_secure()
    flask_app.testing = testing

    # Both default to disabled in test mode so route tests can POST without a
    # CSRF token and aren't throttled by shared per-process rate-limit state.
    # tests/test_csrf.py and tests/test_rate_limit.py pass the enable_* kwargs
    # to exercise the real behavior against a throwaway app instance instead.
    flask_app.config["WTF_CSRF_ENABLED"] = (not testing) if enable_csrf is None else enable_csrf
    flask_app.config["RATELIMIT_ENABLED"] = (
        (not testing) if enable_rate_limit is None else enable_rate_limit
    )
    csrf.init_app(flask_app)
    limiter.init_app(flask_app)

    if not testing:
        bootstrap_config()

    from app.metrics_db import init_db

    init_db()

    from app.routes.auth_routes import bp as auth_bp

    flask_app.register_blueprint(auth_bp)

    from app.routes.dashboard_routes import bp as dashboard_bp

    flask_app.register_blueprint(dashboard_bp)

    from app.routes.admin_routes import bp as admin_bp

    flask_app.register_blueprint(admin_bp)

    from app.routes.theme_routes import bp as theme_bp

    flask_app.register_blueprint(theme_bp)

    flask_app.jinja_env.globals["user_has_tab"] = user_has_tab

    from app.app_settings import get_setting
    from app.local_time import DEFAULT_TIMEZONE, format_local

    flask_app.jinja_env.filters["local_time"] = lambda iso_ts: format_local(
        iso_ts, get_setting("timezone", DEFAULT_TIMEZONE)
    )

    if not testing:
        from app.collector import init_scheduler

        init_scheduler(flask_app)

    return flask_app
