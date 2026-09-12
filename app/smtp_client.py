"""SMTP email client for the weekly Executive Brief.

Mirrors (does NOT import) ~/code/github/ai/4thealth-plus/app/smtp_client.py's
shape (config load/save, send_email, test_connection), but follows this
repo's own conventions rather than that one's:

- Config lives under this repo's app.config_paths.CONFIG_DIR (that repo
  keeps a root-level smtp_config.json; this repo keeps everything under
  config/), via app.atomic_io.atomic_write_json/read_json.
- The SMTP password is encrypted at rest using app.crypto.encrypt_token/
  decrypt_token (already used for source bearer tokens in app.sources) --
  4thealth-plus's version stores the password in cleartext JSON, which is a
  gap this repo intentionally does not copy.
- No `run_history_days` setting -- this repo tracks brief send history in
  the `brief_sends` table (app.metrics_db.insert_brief_send/get_brief_sends)
  instead of a config-driven retention window.
"""

from __future__ import annotations

import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.atomic_io import atomic_write_json, read_json
from app.config_paths import CONFIG_DIR
from app.crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

SMTP_CONFIG_PATH = CONFIG_DIR / "smtp.json"

DEFAULTS: dict = {
    "host": "",
    "port": 25,
    "tls_mode": "none",  # "none" | "starttls" | "ssl"
    "username": "",
    "password": "",
    "from_address": "",
    "enabled": False,
}

CONNECT_TIMEOUT_SECONDS = 10


def load_smtp_config() -> dict:
    """Load SMTP config, decrypting the password. A missing/empty/blank
    stored password decrypts to "" rather than raising."""
    data = read_json(SMTP_CONFIG_PATH, default={})
    cfg = {**DEFAULTS, **data}
    password_enc = cfg.get("password") or ""
    if password_enc:
        try:
            cfg["password"] = decrypt_token(password_enc)
        except Exception:
            logger.exception("Failed to decrypt stored SMTP password; treating as unset")
            cfg["password"] = ""
    return cfg


def save_smtp_config(cfg: dict) -> None:
    """Persist SMTP config with the password encrypted at rest.

    Callers pass a plaintext password (or "" to keep whatever is already
    stored -- see the admin route, which mirrors app.sources's "blank field
    means unchanged" convention rather than round-tripping the decrypted
    secret back into a form).
    """
    merged = {**DEFAULTS, **cfg}
    password = merged.get("password") or ""
    merged["password"] = encrypt_token(password) if password else ""
    atomic_write_json(SMTP_CONFIG_PATH, merged)


def _parse_recipients(to: str) -> list[str]:
    return [addr.strip() for addr in to.split(",") if addr.strip()]


def _build_message(cfg: dict, to: str, subject: str, body_html: str, attachments: list[dict]) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = cfg.get("from_address") or cfg.get("host") or "4tExecutive"
    msg["To"] = ", ".join(_parse_recipients(to))
    msg.attach(MIMEText(body_html, "html"))
    for att in attachments:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(att["data"])
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=att["filename"])
        part.add_header("Content-Type", att.get("mimetype", "application/octet-stream"))
        msg.attach(part)
    return msg


def _connect(cfg: dict) -> smtplib.SMTP:
    tls_mode = cfg.get("tls_mode", "none")
    host = cfg["host"]
    port = int(cfg.get("port", 25))
    if tls_mode == "ssl":
        conn = smtplib.SMTP_SSL(host, port, timeout=CONNECT_TIMEOUT_SECONDS)
    else:
        conn = smtplib.SMTP(host, port, timeout=CONNECT_TIMEOUT_SECONDS)
        if tls_mode == "starttls":
            conn.starttls()
    username = cfg.get("username", "")
    password = cfg.get("password", "")
    if username:
        conn.login(username, password)
    return conn


def send_email(to: str, subject: str, body_html: str, attachments: list[dict] | None = None) -> None:
    """Send one email via the configured SMTP server. Raises RuntimeError if
    SMTP isn't enabled/configured, or whatever smtplib raises on a real
    connection/send failure -- callers (send_weekly_brief, the admin "send
    test" route) are responsible for catching and degrading gracefully."""
    cfg = load_smtp_config()
    if not cfg.get("enabled"):
        raise RuntimeError("SMTP is not enabled -- configure it in Admin > Reports.")
    if not cfg.get("host"):
        raise RuntimeError("SMTP host is not configured.")
    msg = _build_message(cfg, to, subject, body_html, attachments or [])
    conn = _connect(cfg)
    try:
        conn.sendmail(msg["From"], _parse_recipients(to), msg.as_string())
    finally:
        try:
            conn.quit()
        except Exception:
            logger.debug("Ignoring error while closing SMTP connection after send", exc_info=True)


def test_connection(to_address: str) -> dict:
    """Send a canned test message; returns {"ok": bool, "error": str|None}
    rather than raising, for a simple Admin UI result."""
    try:
        send_email(
            to_address,
            "4tExecutive SMTP test",
            "<p>SMTP connection test from 4tExecutive &mdash; if you received this, SMTP is working.</p>",
        )
        return {"ok": True, "error": None}
    except Exception as exc:
        return {"ok": False, "error": str(exc) or type(exc).__name__}
