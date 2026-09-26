import datetime

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.sso_verify as sso_verify_module
from app.sso_verify import verify_token


@pytest.fixture
def keypair(tmp_path, monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_path = tmp_path / "sso_public_key.pem"
    public_key_path.write_bytes(public_pem)
    monkeypatch.setattr(sso_verify_module, "PUBLIC_KEY_PATH", public_key_path)
    return private_key


def _make_token(private_key, **overrides):
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "alice",
        "aud": "4texecutive",
        "iss": "4tsuite",
        "iat": now,
        "nbf": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="EdDSA")


def test_verify_token_accepts_a_validly_signed_unexpired_token(keypair):
    token = _make_token(keypair)

    assert verify_token(token) == "alice"


def test_verify_token_accepts_a_token_with_reasonable_clock_skew(keypair):
    # Simulates the minting host's clock running 20 seconds ahead -- must
    # still verify given the 30-second leeway (design doc section 4).
    skewed_now = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=20)
    token = _make_token(
        keypair,
        iat=skewed_now,
        nbf=skewed_now,
        exp=skewed_now + datetime.timedelta(minutes=5),
    )

    assert verify_token(token) == "alice"


def test_verify_token_rejects_an_expired_token(keypair):
    now = datetime.datetime.now(datetime.UTC)
    token = _make_token(
        keypair,
        iat=now - datetime.timedelta(minutes=10),
        nbf=now - datetime.timedelta(minutes=10),
        exp=now - datetime.timedelta(minutes=5),
    )

    assert verify_token(token) is None


def test_verify_token_rejects_wrong_audience(keypair):
    token = _make_token(keypair, aud="4tlog")

    assert verify_token(token) is None


def test_verify_token_rejects_wrong_issuer(keypair):
    token = _make_token(keypair, iss="not-4tsuite")

    assert verify_token(token) is None


def test_verify_token_rejects_a_malformed_token(keypair):
    assert verify_token("not-a-real-token") is None


def test_verify_token_rejects_a_token_signed_by_a_different_keypair(keypair):
    other_private_key = Ed25519PrivateKey.generate()
    token = _make_token(other_private_key)

    assert verify_token(token) is None


def test_verify_token_rejects_when_public_key_file_is_missing(keypair, tmp_path, monkeypatch):
    monkeypatch.setattr(sso_verify_module, "PUBLIC_KEY_PATH", tmp_path / "does-not-exist.pem")
    token = _make_token(keypair)

    assert verify_token(token) is None


def test_verify_token_rejects_a_token_missing_exp_claim(keypair):
    # Finding 1: PyJWT only validates exp if it's present, so a token
    # missing exp entirely would verify as valid and never expire.
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "alice",
        "aud": "4texecutive",
        "iss": "4tsuite",
        "iat": now,
        "nbf": now,
        # exp intentionally omitted
    }
    token = jwt.encode(claims, keypair, algorithm="EdDSA")

    assert verify_token(token) is None


def test_verify_token_rejects_a_token_with_empty_sub_claim(keypair):
    # Finding 2: An empty string sub claim should be treated as missing
    token = _make_token(keypair, sub="")

    assert verify_token(token) is None
