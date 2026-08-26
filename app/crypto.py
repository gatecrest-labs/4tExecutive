"""Symmetric encryption for secrets at rest (source bearer tokens).

Runs outside any Flask app/request context too (the collector's scheduled
poll job is a background thread with no app context), so the key is derived
straight from the environment rather than `flask.current_app`. `create_app`
already refuses to start outside test mode unless SECRET_KEY is set to a
real value, so by the time this runs in production the env var is
guaranteed present; the literal fallback exists only to match the fixed
`dev-only-change-me` secret `create_app(testing=True)` uses.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet

_TESTING_SECRET_KEY = "dev-only-change-me"


def _fernet() -> Fernet:
    secret_key = os.environ.get("SECRET_KEY") or _TESTING_SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token_enc: str) -> str:
    return _fernet().decrypt(token_enc.encode()).decode()
