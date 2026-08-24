"""Tests for the create_app factory's SECRET_KEY / cookie hardening."""

import pytest

from app import _resolve_cookie_secure, create_app


def test_create_app_raises_when_secret_key_unset(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError):
        create_app(testing=False)


def test_create_app_raises_when_secret_key_is_placeholder(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "change-me-to-a-random-value")

    with pytest.raises(RuntimeError):
        create_app(testing=False)


def test_create_app_testing_mode_does_not_require_secret_key(monkeypatch, tmp_config_dir, tmp_path):
    import app.metrics_db as metrics_db_module

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")

    flask_app = create_app(testing=True)

    assert flask_app.secret_key == "dev-only-change-me"


def test_create_app_sets_samesite_cookie_config(monkeypatch, tmp_config_dir, tmp_path):
    import app.metrics_db as metrics_db_module

    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setattr(metrics_db_module, "DB_PATH", tmp_path / "metrics.db")

    flask_app = create_app(testing=True)

    assert flask_app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_resolve_cookie_secure_true_when_certs_present_and_auto(monkeypatch, tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake cert")
    key.write_text("fake key")
    monkeypatch.setenv("SSL_CERT", str(cert))
    monkeypatch.setenv("SSL_KEY", str(key))
    monkeypatch.delenv("COOKIE_SECURE", raising=False)

    assert _resolve_cookie_secure() is True


def test_resolve_cookie_secure_false_when_certs_missing_and_auto(monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT", str(tmp_path / "missing-cert.pem"))
    monkeypatch.setenv("SSL_KEY", str(tmp_path / "missing-key.pem"))
    monkeypatch.delenv("COOKIE_SECURE", raising=False)

    assert _resolve_cookie_secure() is False


def test_resolve_cookie_secure_forced_true_overrides_missing_certs(monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT", str(tmp_path / "missing-cert.pem"))
    monkeypatch.setenv("SSL_KEY", str(tmp_path / "missing-key.pem"))
    monkeypatch.setenv("COOKIE_SECURE", "true")

    assert _resolve_cookie_secure() is True


def test_resolve_cookie_secure_forced_false_overrides_present_certs(monkeypatch, tmp_path):
    cert = tmp_path / "cert.pem"
    key = tmp_path / "key.pem"
    cert.write_text("fake cert")
    key.write_text("fake key")
    monkeypatch.setenv("SSL_CERT", str(cert))
    monkeypatch.setenv("SSL_KEY", str(key))
    monkeypatch.setenv("COOKIE_SECURE", "false")

    assert _resolve_cookie_secure() is False
