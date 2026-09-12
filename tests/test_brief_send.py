from unittest.mock import patch

import pytest

import app.brief_schedule as brief_schedule_module
import app.brief_send as brief_send_module
import app.smtp_client as smtp_client_module
from app.brief_send import send_weekly_brief
from app.metrics_db import get_brief_sends
from app.smtp_client import save_smtp_config


@pytest.fixture(autouse=True)
def tmp_generated_dir(tmp_path, monkeypatch):
    generated = tmp_path / "generated" / "briefs"
    monkeypatch.setattr(brief_send_module, "GENERATED_DIR", generated)
    return generated


@pytest.fixture(autouse=True)
def tmp_smtp_and_schedule_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(smtp_client_module, "SMTP_CONFIG_PATH", tmp_path / "smtp.json")
    monkeypatch.setattr(brief_schedule_module, "SCHEDULE_CONFIG_PATH", tmp_path / "brief_schedule.json")


def _configure_smtp_enabled():
    save_smtp_config({"host": "smtp.example.com", "enabled": True, "from_address": "brief@example.com"})


def _configure_schedule(recipients="cio@example.com"):
    brief_schedule_module.save_brief_schedule_config(
        {"weekday": 0, "hour": 8, "recipients": recipients, "enabled": True}
    )


@patch("app.brief_send.render_pdf")
@patch("app.brief_send.send_email")
def test_send_weekly_brief_happy_path(mock_send_email, mock_render_pdf, app, tmp_generated_dir):
    _configure_smtp_enabled()
    _configure_schedule()
    mock_render_pdf.side_effect = lambda html_path, out_path, **kw: out_path.write_bytes(b"%PDF-1.4") or True

    result = send_weekly_brief(app)

    assert result["status"] == "sent"
    assert mock_send_email.call_count == 1
    to, subject, _html, kwargs = _call_args(mock_send_email)
    assert to == "cio@example.com"
    assert "Weekly Executive Brief" in subject
    assert len(kwargs["attachments"]) == 2  # html + pdf

    sends = get_brief_sends()
    assert len(sends) == 1
    assert sends[0]["status"] == "sent"
    assert sends[0]["error"] is None


def _call_args(mock):
    args, kwargs = mock.call_args
    to, subject, html = args[0], args[1], args[2]
    return to, subject, html, kwargs


@patch("app.brief_send.render_pdf", return_value=False)
@patch("app.brief_send.send_email")
def test_send_weekly_brief_degrades_when_pdf_generation_fails(mock_send_email, mock_render_pdf, app):
    _configure_smtp_enabled()
    _configure_schedule()

    result = send_weekly_brief(app)

    assert result["status"] == "partial"
    assert "PDF" in result["error"]
    _to, _subject, _html, kwargs = _call_args(mock_send_email)
    assert len(kwargs["attachments"]) == 1  # html only

    sends = get_brief_sends()
    assert sends[0]["status"] == "partial"


@patch("app.brief_send.render_pdf", return_value=False)
def test_send_weekly_brief_records_failure_when_smtp_disabled(mock_render_pdf, app):
    # SMTP left disabled (default), but a recipient IS configured so we get
    # past the "no recipients" short-circuit and into the real send_email
    # RuntimeError path.
    _configure_schedule()

    result = send_weekly_brief(app)

    assert result["status"] == "failed"
    sends = get_brief_sends()
    assert sends[0]["status"] == "failed"
    assert sends[0]["error"]


@patch("app.brief_send.render_pdf", return_value=False)
@patch("app.brief_send.send_email")
def test_send_weekly_brief_records_failure_when_no_recipients(mock_send_email, mock_render_pdf, app):
    _configure_smtp_enabled()
    _configure_schedule(recipients="")

    result = send_weekly_brief(app)

    assert result["status"] == "failed"
    mock_send_email.assert_not_called()
    sends = get_brief_sends()
    assert sends[0]["status"] == "failed"


@patch("app.brief_send.render_pdf")
@patch("app.brief_send.send_email", side_effect=RuntimeError("smtp exploded"))
def test_send_weekly_brief_records_failure_when_send_email_raises(mock_send_email, mock_render_pdf, app):
    _configure_smtp_enabled()
    _configure_schedule()
    mock_render_pdf.side_effect = lambda html_path, out_path, **kw: out_path.write_bytes(b"%PDF-1.4") or True

    result = send_weekly_brief(app)

    assert result["status"] == "failed"
    assert "smtp exploded" in result["error"]
    sends = get_brief_sends()
    assert sends[0]["status"] == "failed"
    assert "smtp exploded" in sends[0]["error"]


@patch("app.brief_send.render_pdf")
@patch("app.brief_send.send_email")
def test_send_weekly_brief_writes_html_file(mock_send_email, mock_render_pdf, app, tmp_generated_dir):
    _configure_smtp_enabled()
    _configure_schedule()
    mock_render_pdf.side_effect = lambda html_path, out_path, **kw: out_path.write_bytes(b"%PDF-1.4") or True

    result = send_weekly_brief(app)

    html_path = tmp_generated_dir / f"{result['week_key']}.html"
    assert html_path.exists()
    assert "Weekly Executive Brief" in html_path.read_text()
