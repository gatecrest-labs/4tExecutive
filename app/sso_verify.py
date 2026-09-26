"""Verify a 4tSuite-issued SSO JWT and map it to a username.

This is the entire trust boundary between 4texecutive and 4tSuite --
kept intentionally tiny and stable, so a future change to the claims
shape stays a small, trackable patch rather than a redesign. See
4tSuite's Docs/superpowers/specs/2026-09-26-phase2-sso-trust-hook-design.md
for the full token contract this implements.
"""

from __future__ import annotations

import jwt

from app.config_paths import CONFIG_DIR

PUBLIC_KEY_PATH = CONFIG_DIR / "sso_public_key.pem"
APP_ID = "4texecutive"


def verify_token(token: str) -> str | None:
    """Returns the username claim on success, None on any verification failure."""
    if not PUBLIC_KEY_PATH.exists():
        return None
    try:
        claims = jwt.decode(
            token,
            PUBLIC_KEY_PATH.read_bytes(),
            algorithms=["EdDSA"],
            audience=APP_ID,
            issuer="4tsuite",
            leeway=30,
            options={"require": ["exp", "iat", "nbf", "sub", "aud", "iss"]},
        )
    except jwt.InvalidTokenError:
        return None
    return claims.get("sub") or None
