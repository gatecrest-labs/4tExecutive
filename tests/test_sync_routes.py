import datetime

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import app.groups as groups_module
import app.sso_verify as sso_verify_module
from app import create_app


@pytest.fixture
def service_keypair(tmp_path, monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_key_path = tmp_path / "sso_public_key.pem"
    public_key_path.write_bytes(public_pem)
    monkeypatch.setattr(sso_verify_module, "PUBLIC_KEY_PATH", public_key_path)
    return private_key


def _service_token(private_key, **overrides):
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


def test_receive_group_push_rejects_missing_token(client):
    response = client.post(
        "/4tsuite/groups", json={"username": "dave", "group": "administrators", "member": True}
    )

    assert response.status_code == 403


def test_receive_group_push_rejects_wrong_scope_token(client, service_keypair):
    token = _service_token(service_keypair, scope="something_else")

    response = client.post(
        "/4tsuite/groups",
        json={"username": "dave", "group": "administrators", "member": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_receive_group_push_adds_member(client, service_keypair, tmp_groups_file):
    token = _service_token(service_keypair)

    response = client.post(
        "/4tsuite/groups",
        json={"username": "dave", "group": "developers", "member": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204
    assert "developers" in groups_module.get_user_groups("dave")


def test_receive_group_push_removes_member(client, service_keypair, tmp_groups_file):
    token = _service_token(service_keypair)

    response = client.post(
        "/4tsuite/groups",
        json={"username": "alice", "group": "administrators", "member": False},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204
    assert "administrators" not in groups_module.get_user_groups("alice")


def test_receive_group_push_rejects_unknown_group(client, service_keypair, tmp_groups_file):
    token = _service_token(service_keypair)

    response = client.post(
        "/4tsuite/groups",
        json={"username": "dave", "group": "nonexistent", "member": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400


def test_receive_group_push_works_with_csrf_protection_turned_on(service_keypair, tmp_groups_file):
    csrf_app = create_app(testing=True, enable_csrf=True)
    csrf_client = csrf_app.test_client()
    token = _service_token(service_keypair)

    response = csrf_client.post(
        "/4tsuite/groups",
        json={"username": "dave", "group": "developers", "member": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 204
