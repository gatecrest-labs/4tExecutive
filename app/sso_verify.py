"""Verify a 4tSuite-issued JWT and map it to a username or a service scope.

This is the entire trust boundary between 4texecutive and 4tSuite --
kept intentionally tiny and stable, so a future change to the claims
shape stays a small, trackable patch rather than a redesign. See
4tSuite's Docs/superpowers/specs/2026-09-26-phase2-sso-trust-hook-design.md
for the login token contract, and
Docs/superpowers/specs/2026-09-26-groupsync-health-restart-design.md
(same 4tSuite repo) for the service-token (scope-based) contract
verify_service_token checks.
"""

from __future__ import annotations

import hashlib
import re

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization

from app.config_paths import CONFIG_DIR

PUBLIC_KEY_PATH = CONFIG_DIR / "sso_public_key.pem"
APP_ID = "4texecutive"


_PEM_RE = re.compile(rb"-----BEGIN PUBLIC KEY-----.+?-----END PUBLIC KEY-----", re.DOTALL)


def _load_keys() -> dict[str, bytes]:
    """Map kid -> PEM for every public key in PUBLIC_KEY_PATH.

    The file may hold one PEM (legacy) or several concatenated PEMs (a
    rotation bundle). kid is the first 16 hex chars of SHA-256 of the raw
    public key bytes. Read on every call so a rotated file takes effect
    without a restart. Missing, empty, garbage or non-file -> {}.
    """
    if not PUBLIC_KEY_PATH.exists():
        return {}
    try:
        data = PUBLIC_KEY_PATH.read_bytes()
    except OSError:
        return {}
    found: dict[str, bytes] = {}
    for block in _PEM_RE.findall(data):
        try:
            raw = serialization.load_pem_public_key(block).public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        except (ValueError, TypeError, UnsupportedAlgorithm):
            continue
        found[hashlib.sha256(raw).hexdigest()[:16]] = block
    return found


def _decode(token: str) -> dict | None:
    keys = _load_keys()
    if not keys:
        return None
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.InvalidTokenError:
        return None
    # Only a string kid can select a key; any other type is treated as absent.
    candidates = [keys[kid]] if isinstance(kid, str) and kid in keys else list(keys.values())
    for pem in candidates:
        try:
            return jwt.decode(
                token,
                pem,
                algorithms=["EdDSA"],
                audience=APP_ID,
                issuer="4tsuite",
                leeway=30,
                options={"require": ["exp", "iat", "nbf", "sub", "aud", "iss"]},
            )
        except jwt.InvalidSignatureError:
            continue
        except jwt.PyJWTError:
            return None
    return None


def verify_token(token: str) -> str | None:
    """Returns the username claim on success, None on any verification failure."""
    claims = _decode(token)
    if claims is None or "scope" in claims:
        return None
    return claims.get("sub") or None


def verify_service_token(token: str, expected_scope: str) -> dict | None:
    """Returns the verified claims on success, None on any verification
    failure (including a scope mismatch). Never returns a username for
    session purposes -- this token never logs anyone in."""
    claims = _decode(token)
    if claims is None or claims.get("scope") != expected_scope:
        return None
    return claims
