import json
from unittest.mock import patch

import pytest

import app.brief_schedule as brief_schedule_module
import app.groups as groups_module
import app.routes.admin_routes as admin_routes_module
import app.smtp_client as smtp_client_module
import app.sources as sources_module
from app.metrics_db import insert_brief_send


@pytest.fixture(autouse=True)
def tmp_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(sources_module, "SOURCES_PATH", tmp_path / "sources.json")
    monkeypatch.setattr(smtp_client_module, "SMTP_CONFIG_PATH", tmp_path / "smtp.json")
    monkeypatch.setattr(brief_schedule_module, "SCHEDULE_CONFIG_PATH", tmp_path / "brief_schedule.json")
    monkeypatch.setattr(admin_routes_module, "GENERATED_DIR", tmp_path / "generated" / "briefs")


def _login_as_admin(client, tmp_path, monkeypatch, username="carol"):
    with client.session_transaction() as sess:
        sess["username"] = username
    groups_path = tmp_path / "groups.json"
    groups_path.write_text(
        json.dumps({"administrators": {"members": [username], "allowed_tabs": ["admin"]}})
    )
    monkeypatch.setattr(groups_module, "GROUPS_PATH", groups_path)


def test_reports_page_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/reports")
    assert response.status_code == 403


def test_reports_page_renders(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.get("/admin/reports")

    assert response.status_code == 200
    assert b"SMTP settings" in response.data
    assert b"Weekly send schedule" in response.data


def test_update_smtp_settings_saves_config(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/reports/smtp",
        data={
            "host": "smtp.example.com",
            "port": "587",
            "tls_mode": "starttls",
            "username": "bot",
            "password": "hunter2",
            "from_address": "brief@example.com",
            "enabled": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    cfg = smtp_client_module.load_smtp_config()
    assert cfg["host"] == "smtp.example.com"
    assert cfg["password"] == "hunter2"
    assert cfg["enabled"] is True


def test_update_smtp_settings_blank_password_keeps_existing(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    smtp_client_module.save_smtp_config({"host": "old.example.com", "password": "keepme", "enabled": True})

    client.post(
        "/admin/reports/smtp",
        data={"host": "new.example.com", "port": "25", "tls_mode": "none", "password": ""},
        follow_redirects=False,
    )

    cfg = smtp_client_module.load_smtp_config()
    assert cfg["host"] == "new.example.com"
    assert cfg["password"] == "keepme"


def test_update_smtp_settings_invalid_port_shows_error(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post("/admin/reports/smtp", data={"host": "x", "port": "not-a-number"})

    assert response.status_code == 200
    assert b"Port" in response.data


def test_update_schedule_saves_config(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/reports/schedule",
        data={"weekday": "2", "hour": "9", "recipients": "a@b.com", "enabled": "on"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    cfg = brief_schedule_module.get_brief_schedule_config()
    assert cfg["weekday"] == 2
    assert cfg["hour"] == 9
    assert cfg["enabled"] is True


def test_update_schedule_validation_error_shown(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/reports/schedule",
        data={"weekday": "9", "hour": "9", "recipients": "a@b.com", "enabled": "on"},
    )

    assert response.status_code == 200
    assert b"weekday" in response.data


@patch("app.routes.admin_routes.send_email")
def test_send_test_route_calls_send_email(mock_send_email, client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post(
        "/admin/reports/test", data={"to_address": "me@example.com"}, follow_redirects=False
    )

    assert response.status_code == 200
    mock_send_email.assert_called_once()
    to_address = mock_send_email.call_args[0][0]
    assert to_address == "me@example.com"
    assert b"sent to me@example.com" in response.data


def test_send_test_route_rejects_invalid_address(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post("/admin/reports/test", data={"to_address": "not-an-email"})

    assert response.status_code == 200
    assert b"valid test recipient" in response.data


@patch("app.routes.admin_routes.send_email", side_effect=RuntimeError("smtp down"))
def test_send_test_route_shows_error_on_failure(mock_send_email, client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.post("/admin/reports/test", data={"to_address": "me@example.com"})

    assert response.status_code == 200
    assert b"Test send failed" in response.data


def test_download_route_requires_admin_tab(client):
    with client.session_transaction() as sess:
        sess["username"] = "alice"
    response = client.get("/admin/reports/sends/1/download.html")
    assert response.status_code == 403


def test_download_route_404s_for_unknown_send_id(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)

    response = client.get("/admin/reports/sends/999/download.html")

    assert response.status_code == 404


def test_download_route_404s_for_bad_extension(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    send_id = insert_brief_send("2026-W10", "2026-03-02T08:00:00Z", "a@b.com", "sent")

    response = client.get(f"/admin/reports/sends/{send_id}/download.txt")

    assert response.status_code == 404


def test_download_route_404s_when_pdf_generation_failed(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    send_id = insert_brief_send(
        "2026-W10", "2026-03-02T08:00:00Z", "a@b.com", "partial", error="PDF generation failed"
    )

    response = client.get(f"/admin/reports/sends/{send_id}/download.pdf")

    assert response.status_code == 404


def test_download_route_serves_stored_html_file(client, tmp_path, monkeypatch):
    _login_as_admin(client, tmp_path, monkeypatch)
    send_id = insert_brief_send("2026-W10", "2026-03-02T08:00:00Z", "a@b.com", "sent")
    generated_dir = tmp_path / "generated" / "briefs"
    generated_dir.mkdir(parents=True)
    (generated_dir / "2026-W10.html").write_text("<html>hi</html>")

    response = client.get(f"/admin/reports/sends/{send_id}/download.html")

    assert response.status_code == 200
    assert response.data == b"<html>hi</html>"
