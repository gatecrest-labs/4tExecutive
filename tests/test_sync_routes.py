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


def test_receive_group_push_rejects_service_sentinel_username(
    client, service_keypair, tmp_groups_file
):
    # Even with a valid groups_push token, the payload must never be able
    # to grant group membership to the "_service:4tsuite" sentinel -- that
    # would let a replayed push token also authenticate as that sentinel
    # via /sso/login (verify_token rejects scoped tokens, but this closes
    # the second half of the escalation chain independently).
    token = _service_token(service_keypair)

    response = client.post(
        "/4tsuite/groups",
        json={"username": "_service:4tsuite", "group": "administrators", "member": True},
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


def test_manifest_requires_manifest_read_scope(client, service_keypair):
    wrong = _service_token(service_keypair, scope="groups_push")

    assert client.get("/4tsuite/manifest").status_code == 403
    response = client.get("/4tsuite/manifest", headers={"Authorization": f"Bearer {wrong}"})
    assert response.status_code == 403


def test_manifest_describes_app(client, service_keypair, tmp_groups_file):
    token = _service_token(service_keypair, scope="manifest_read")

    response = client.get("/4tsuite/manifest", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["app_id"] == "4texecutive"
    assert body["protocol_version"] == 1
    assert body["tabs"] == ["admin", "brief", "brief_edit", "dashboard"]
    assert "administrators" in body["groups"]


def test_receive_group_push_rejects_malformed_body_with_400(
    client, service_keypair, tmp_groups_file
):
    token = _service_token(service_keypair)

    response = client.post(
        "/4tsuite/groups",
        json={"group": "developers"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 400
