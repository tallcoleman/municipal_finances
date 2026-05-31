"""Route-level auth enforcement tests.

Verifies that all GET endpoints return 401 without a token, 403 with a
token that carries no recognized role, and 200 with a valid viewer token.
Uses its own test client that does NOT bypass require_viewer, so the
enforcement is exercised for real.
"""

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

import municipal_finances.api.auth as auth_module
from municipal_finances.api.main import app
from municipal_finances.database import get_session

ALL_GET_ROUTES = [
    "/municipalities/",
    "/municipalities/DOESNOTEXIST",
    "/records/",
    "/sources/",
    "/sources/9999",
]


@pytest.fixture(scope="module")
def enforcement_rsa_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def enforcement_private_key_pem(enforcement_rsa_key_pair):
    private_key, _ = enforcement_rsa_key_pair
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture(scope="module")
def enforcement_public_key(enforcement_rsa_key_pair):
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    _, public_key = enforcement_rsa_key_pair
    pem = public_key.public_bytes(encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo)
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    return load_pem_public_key(pem)


def _make_token(private_key_pem, roles):
    now = int(time.time())
    payload = {
        "sub": "test-user",
        "aud": "municipal-finances-api",
        "iat": now,
        "exp": now + 900,
        "realm_access": {"roles": roles},
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


@pytest.fixture()
def enforcement_client(session, enforcement_private_key_pem, enforcement_public_key, mocker):
    """TestClient that enforces auth (no require_viewer bypass).

    Patches get_jwks_client so JWT validation uses the test key pair
    rather than hitting a real Keycloak instance.
    """
    mock_client = mocker.MagicMock()
    mock_signing_key = mocker.MagicMock()
    mock_signing_key.key = enforcement_public_key
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    mocker.patch.object(auth_module, "get_jwks_client", return_value=mock_client)

    def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session
    # Intentionally do NOT override require_viewer — enforcement is the point.
    with TestClient(app, follow_redirects=False) as c:
        yield c, enforcement_private_key_pem
    app.dependency_overrides.pop(get_session, None)


@pytest.mark.parametrize("path", ALL_GET_ROUTES)
def test_no_token_returns_401(enforcement_client, path):
    client, _ = enforcement_client
    response = client.get(path)
    assert response.status_code == 401


@pytest.mark.parametrize("path", ALL_GET_ROUTES)
def test_no_valid_role_returns_403(enforcement_client, path):
    client, private_key_pem = enforcement_client
    token = _make_token(private_key_pem, roles=[])
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


@pytest.mark.parametrize("path", ALL_GET_ROUTES)
def test_viewer_token_returns_200(enforcement_client, path):
    client, private_key_pem = enforcement_client
    token = _make_token(private_key_pem, roles=["viewer"])
    response = client.get(path, headers={"Authorization": f"Bearer {token}"})
    # 200 or 404 (for routes that look up a specific resource that doesn't exist)
    assert response.status_code in (200, 404)
