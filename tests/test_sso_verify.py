import datetime

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.sso_verify as sso_verify_module
from app import sso_verify
from app.sso_verify import verify_service_token, verify_token


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


def _make_service_token(private_key, **overrides):
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "_service:4tsuite",
        "aud": "4texecutive",
        "iss": "4tsuite",
        "scope": "groups_push",
        "iat": now,
        "nbf": now,
        "exp": now + datetime.timedelta(minutes=5),
    }
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="EdDSA")


def test_verify_service_token_accepts_a_validly_signed_matching_scope_token(keypair):
    token = _make_service_token(keypair)

    claims = verify_service_token(token, expected_scope="groups_push")

    assert claims is not None
    assert claims["scope"] == "groups_push"


def test_verify_service_token_rejects_wrong_scope(keypair):
    token = _make_service_token(keypair, scope="something_else")

    assert verify_service_token(token, expected_scope="groups_push") is None


def test_verify_service_token_rejects_missing_scope_claim(keypair):
    now = datetime.datetime.now(datetime.UTC)
    claims = {
        "sub": "_service:4tsuite",
        "aud": "4texecutive",
        "iss": "4tsuite",
        "iat": now,
        "nbf": now,
        "exp": now + datetime.timedelta(minutes=5),
        # scope intentionally omitted
    }
    token = jwt.encode(claims, keypair, algorithm="EdDSA")

    assert verify_service_token(token, expected_scope="groups_push") is None


def test_verify_service_token_rejects_an_expired_token(keypair):
    now = datetime.datetime.now(datetime.UTC)
    token = _make_service_token(
        keypair,
        iat=now - datetime.timedelta(minutes=10),
        nbf=now - datetime.timedelta(minutes=10),
        exp=now - datetime.timedelta(minutes=5),
    )

    assert verify_service_token(token, expected_scope="groups_push") is None


def test_verify_service_token_rejects_a_login_token_lacking_scope(keypair):
    # A real login token (from _make_token) has no scope claim at all --
    # must never be usable against the groups-push verification path.
    token = _make_token(keypair)

    assert verify_service_token(token, expected_scope="groups_push") is None


def test_verify_token_rejects_a_service_token_with_a_scope_claim(keypair):
    # A validly-signed service (groups_push) token must never be usable
    # to log in via verify_token, even though its sub claim is non-empty.
    token = _make_service_token(keypair)

    assert verify_token(token) is None


def _new_key():
    private = Ed25519PrivateKey.generate()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public_pem


def _token(private, sub="alice"):
    now = datetime.datetime.now(datetime.UTC)
    return jwt.encode(
        {
            "sub": sub,
            "aud": sso_verify.APP_ID,
            "iss": "4tsuite",
            "iat": now,
            "nbf": now,
            "exp": now + datetime.timedelta(minutes=5),
        },
        private,
        algorithm="EdDSA",
    )


def test_bundle_verifies_a_token_signed_by_either_key(tmp_path, monkeypatch):
    (k1, p1), (k2, p2) = _new_key(), _new_key()
    bundle = tmp_path / "sso_public_key.pem"
    bundle.write_bytes(p1 + p2)
    monkeypatch.setattr(sso_verify, "PUBLIC_KEY_PATH", bundle)
    assert sso_verify.verify_token(_token(k1)) == "alice"
    assert sso_verify.verify_token(_token(k2)) == "alice"


def test_token_from_a_key_not_in_the_file_fails(tmp_path, monkeypatch):
    (_, p1), (k2, _) = _new_key(), _new_key()
    only_first = tmp_path / "sso_public_key.pem"
    only_first.write_bytes(p1)
    monkeypatch.setattr(sso_verify, "PUBLIC_KEY_PATH", only_first)
    assert sso_verify.verify_token(_token(k2)) is None


def test_single_pem_file_still_works(tmp_path, monkeypatch):
    k, p = _new_key()
    single = tmp_path / "sso_public_key.pem"
    single.write_bytes(p)
    monkeypatch.setattr(sso_verify, "PUBLIC_KEY_PATH", single)
    assert sso_verify.verify_token(_token(k)) == "alice"


def test_empty_or_missing_key_file_fails_closed(tmp_path, monkeypatch):
    k, _ = _new_key()
    empty = tmp_path / "empty.pem"
    empty.write_bytes(b"")
    for path in (empty, tmp_path / "missing.pem"):
        monkeypatch.setattr(sso_verify, "PUBLIC_KEY_PATH", path)
        assert sso_verify.verify_token(_token(k)) is None


def test_garbage_key_file_fails_closed(tmp_path, monkeypatch):
    k, _ = _new_key()
    junk = tmp_path / "junk.pem"
    junk.write_bytes(b"-----BEGIN PUBLIC KEY-----\nnot a key\n-----END PUBLIC KEY-----\n")
    monkeypatch.setattr(sso_verify, "PUBLIC_KEY_PATH", junk)
    assert sso_verify.verify_token(_token(k)) is None


def test_directory_at_key_path_fails_closed(tmp_path, monkeypatch):
    # Docker bind-mounts an empty directory when the host file is absent.
    k, _ = _new_key()
    directory = tmp_path / "sso_public_key.pem"
    directory.mkdir()
    monkeypatch.setattr(sso_verify, "PUBLIC_KEY_PATH", directory)
    assert sso_verify.verify_token(_token(k)) is None
