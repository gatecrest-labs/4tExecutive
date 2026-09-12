import json
from unittest.mock import MagicMock, patch

import pytest

import app.smtp_client as smtp_client_module
from app.smtp_client import DEFAULTS, load_smtp_config, save_smtp_config, send_email
from app.smtp_client import test_connection as smtp_test_connection


@pytest.fixture(autouse=True)
def tmp_smtp_config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(smtp_client_module, "SMTP_CONFIG_PATH", tmp_path / "smtp.json")
    return tmp_path / "smtp.json"


def test_load_defaults_when_no_file():
    assert load_smtp_config() == DEFAULTS


def test_save_then_load_round_trip():
    save_smtp_config(
        {
            "host": "smtp.example.com",
            "port": 587,
            "tls_mode": "starttls",
            "username": "bot@example.com",
            "password": "hunter2",
            "from_address": "bot@example.com",
            "enabled": True,
        }
    )

    cfg = load_smtp_config()

    assert cfg["host"] == "smtp.example.com"
    assert cfg["port"] == 587
    assert cfg["tls_mode"] == "starttls"
    assert cfg["password"] == "hunter2"
    assert cfg["enabled"] is True


def test_password_encrypted_at_rest(tmp_smtp_config_path):
    save_smtp_config({"host": "smtp.example.com", "password": "hunter2", "enabled": True})

    raw = json.loads(tmp_smtp_config_path.read_text())

    assert "hunter2" not in json.dumps(raw)
    assert raw["password"] != "hunter2"
    assert raw["password"] != ""


def test_blank_password_saved_as_blank_not_error():
    save_smtp_config({"host": "smtp.example.com", "password": "", "enabled": False})

    cfg = load_smtp_config()

    assert cfg["password"] == ""


def test_send_email_raises_when_disabled():
    save_smtp_config({"host": "smtp.example.com", "enabled": False})

    with pytest.raises(RuntimeError):
        send_email("a@b.com", "subject", "<p>hi</p>")


def test_send_email_raises_when_no_host():
    save_smtp_config({"host": "", "enabled": True})

    with pytest.raises(RuntimeError):
        send_email("a@b.com", "subject", "<p>hi</p>")


@patch("smtplib.SMTP")
def test_send_email_uses_plain_smtp_and_calls_sendmail(mock_smtp_cls):
    save_smtp_config(
        {
            "host": "smtp.example.com",
            "port": 25,
            "tls_mode": "none",
            "from_address": "brief@example.com",
            "enabled": True,
        }
    )
    mock_conn = MagicMock()
    mock_smtp_cls.return_value = mock_conn

    send_email("a@b.com,c@d.com", "Weekly Brief", "<p>body</p>")

    mock_smtp_cls.assert_called_once_with("smtp.example.com", 25, timeout=10)
    mock_conn.starttls.assert_not_called()
    assert mock_conn.sendmail.call_count == 1
    from_addr, to_addrs, message = mock_conn.sendmail.call_args[0]
    assert from_addr == "brief@example.com"
    assert to_addrs == ["a@b.com", "c@d.com"]
    assert "Weekly Brief" in message
    mock_conn.quit.assert_called_once()


@patch("smtplib.SMTP")
def test_send_email_starttls_mode_calls_starttls(mock_smtp_cls):
    save_smtp_config(
        {"host": "smtp.example.com", "port": 587, "tls_mode": "starttls", "enabled": True}
    )
    mock_conn = MagicMock()
    mock_smtp_cls.return_value = mock_conn

    send_email("a@b.com", "subject", "<p>hi</p>")

    mock_conn.starttls.assert_called_once()


@patch("smtplib.SMTP_SSL")
def test_send_email_ssl_mode_uses_smtp_ssl(mock_smtp_ssl_cls):
    save_smtp_config({"host": "smtp.example.com", "port": 465, "tls_mode": "ssl", "enabled": True})
    mock_conn = MagicMock()
    mock_smtp_ssl_cls.return_value = mock_conn

    send_email("a@b.com", "subject", "<p>hi</p>")

    mock_smtp_ssl_cls.assert_called_once_with("smtp.example.com", 465, timeout=10)
    mock_conn.sendmail.assert_called_once()


@patch("smtplib.SMTP")
def test_send_email_logs_in_when_username_present(mock_smtp_cls):
    save_smtp_config(
        {
            "host": "smtp.example.com",
            "username": "bot@example.com",
            "password": "hunter2",
            "enabled": True,
        }
    )
    mock_conn = MagicMock()
    mock_smtp_cls.return_value = mock_conn

    send_email("a@b.com", "subject", "<p>hi</p>")

    mock_conn.login.assert_called_once_with("bot@example.com", "hunter2")


@patch("smtplib.SMTP")
def test_send_email_with_attachments(mock_smtp_cls):
    save_smtp_config({"host": "smtp.example.com", "enabled": True})
    mock_conn = MagicMock()
    mock_smtp_cls.return_value = mock_conn

    send_email(
        "a@b.com",
        "subject",
        "<p>hi</p>",
        attachments=[{"filename": "brief.pdf", "mimetype": "application/pdf", "data": b"%PDF-1.4"}],
    )

    message = mock_conn.sendmail.call_args[0][2]
    assert "brief.pdf" in message


@patch("smtplib.SMTP")
def test_test_connection_ok(mock_smtp_cls):
    save_smtp_config({"host": "smtp.example.com", "enabled": True})
    mock_smtp_cls.return_value = MagicMock()

    result = smtp_test_connection("a@b.com")

    assert result == {"ok": True, "error": None}


def test_test_connection_failure_returns_error_not_raise():
    save_smtp_config({"host": "", "enabled": False})

    result = smtp_test_connection("a@b.com")

    assert result["ok"] is False
    assert result["error"]
