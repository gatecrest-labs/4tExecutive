"""Tests for the create_app factory's SECRET_KEY / cookie hardening."""

import pytest

from app import create_app


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
