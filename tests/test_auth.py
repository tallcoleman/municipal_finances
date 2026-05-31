"""Unit tests for src/municipal_finances/api/auth.py."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

import municipal_finances.api.auth as auth_module
from municipal_finances.api.auth import decode_token, get_jwks_client, get_roles, require_administrator, require_editor, require_viewer


@pytest.fixture(scope="session")
def rsa_key_pair():
    """Generate a throwaway RSA key pair for signing test JWTs."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture(scope="session")
def private_key_pem(rsa_key_pair):
    private_key, _ = rsa_key_pair
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )


@pytest.fixture(scope="session")
def public_key_pem(rsa_key_pair):
    _, public_key = rsa_key_pair
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def make_token(private_key_pem, *, roles=None, expired=False, audience="municipal-finances-api"):
    """Build a signed JWT with the given roles and expiry."""
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "aud": audience,
        "iat": now,
        "exp": now - 60 if expired else now + 900,
        "realm_access": {"roles": roles or []},
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


def mock_jwks_client(mocker, public_key_pem):
    """Patch get_jwks_client to return a mock that signs with our test public key."""
    mock_client = mocker.MagicMock()
    mock_signing_key = mocker.MagicMock()
    mock_signing_key.key = jwt.algorithms.RSAAlgorithm.from_jwk(  # type: ignore[attr-defined]
        jwt.algorithms.RSAAlgorithm.to_jwk(  # type: ignore[attr-defined]
            jwt.PyJWKClient("http://unused")._get_keys  # won't be called
        )
    ) if False else _load_public_key(public_key_pem)
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key
    mocker.patch.object(auth_module, "get_jwks_client", return_value=mock_client)
    return mock_client


def _load_public_key(public_key_pem):
    """Return a key object that PyJWT can use for RS256 verification."""
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    return load_pem_public_key(public_key_pem)


# ---------------------------------------------------------------------------
# decode_token
# ---------------------------------------------------------------------------


def test_decode_token_valid(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["viewer"])
    claims = decode_token(token)
    assert claims["sub"] == "user-123"
    assert claims["realm_access"]["roles"] == ["viewer"]


def test_decode_token_expired(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, expired=True)
    with pytest.raises(HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


def test_decode_token_tampered_signature(mocker, public_key_pem):
    """A token with a forged signature must raise 401."""
    mock_jwks_client(mocker, public_key_pem)
    # Build a valid-looking token then corrupt the signature
    other_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_pem = other_private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    token = make_token(other_pem, roles=["viewer"])
    with pytest.raises(HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


def test_decode_token_malformed(mocker, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    with pytest.raises(HTTPException) as exc_info:
        decode_token("not.a.token")
    assert exc_info.value.status_code == 401


def test_decode_token_wrong_audience(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, audience="wrong-client")
    with pytest.raises(HTTPException) as exc_info:
        decode_token(token)
    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# get_roles
# ---------------------------------------------------------------------------


def test_get_roles_extracts_roles():
    claims = {"realm_access": {"roles": ["viewer", "offline_access"]}}
    assert get_roles(claims) == ["viewer", "offline_access"]


def test_get_roles_missing_realm_access():
    assert get_roles({}) == []


def test_get_roles_empty_roles():
    assert get_roles({"realm_access": {"roles": []}}) == []


# ---------------------------------------------------------------------------
# require_viewer
# ---------------------------------------------------------------------------


def test_require_viewer_passes_for_viewer(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["viewer"])
    claims = require_viewer(token=token)
    assert claims["sub"] == "user-123"


def test_require_viewer_passes_for_editor(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["editor"])
    claims = require_viewer(token=token)
    assert claims["sub"] == "user-123"


def test_require_viewer_passes_for_administrator(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["administrator"])
    claims = require_viewer(token=token)
    assert claims["sub"] == "user-123"


def test_require_viewer_raises_403_for_no_role(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=[])
    with pytest.raises(HTTPException) as exc_info:
        require_viewer(token=token)
    assert exc_info.value.status_code == 403


def test_require_viewer_raises_403_for_unknown_role(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["some_other_role"])
    with pytest.raises(HTTPException) as exc_info:
        require_viewer(token=token)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_editor
# ---------------------------------------------------------------------------


def test_require_editor_passes_for_editor(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["editor"])
    claims = require_editor(token=token)
    assert claims["sub"] == "user-123"


def test_require_editor_passes_for_administrator(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["administrator"])
    claims = require_editor(token=token)
    assert claims["sub"] == "user-123"


def test_require_editor_raises_403_for_viewer(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["viewer"])
    with pytest.raises(HTTPException) as exc_info:
        require_editor(token=token)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_administrator
# ---------------------------------------------------------------------------


def test_require_administrator_passes_for_administrator(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["administrator"])
    claims = require_administrator(token=token)
    assert claims["sub"] == "user-123"


def test_require_administrator_raises_403_for_editor(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["editor"])
    with pytest.raises(HTTPException) as exc_info:
        require_administrator(token=token)
    assert exc_info.value.status_code == 403


def test_require_administrator_raises_403_for_viewer(mocker, private_key_pem, public_key_pem):
    mock_jwks_client(mocker, public_key_pem)
    token = make_token(private_key_pem, roles=["viewer"])
    with pytest.raises(HTTPException) as exc_info:
        require_administrator(token=token)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# JWKS caching
# ---------------------------------------------------------------------------


def test_jwks_cache_returns_same_instance_within_ttl(mocker):
    """Two calls within TTL must return the same PyJWKClient instance."""
    mock_constructor = mocker.patch("municipal_finances.api.auth.jwt.PyJWKClient")

    # Clear the module-level cache so this test starts fresh
    auth_module._jwks_cache.clear()

    client1 = get_jwks_client()
    client2 = get_jwks_client()

    assert client1 is client2
    mock_constructor.assert_called_once()


def test_jwks_cache_constructs_new_instance_after_expiry(mocker):
    """A call after TTL expiry must construct a new PyJWKClient."""
    from unittest.mock import MagicMock

    instance1 = MagicMock(name="client-1")
    instance2 = MagicMock(name="client-2")
    mock_constructor = mocker.patch(
        "municipal_finances.api.auth.jwt.PyJWKClient", side_effect=[instance1, instance2]
    )

    auth_module._jwks_cache.clear()

    client1 = get_jwks_client()
    # Simulate cache expiry by clearing it
    auth_module._jwks_cache.clear()
    client2 = get_jwks_client()

    assert mock_constructor.call_count == 2
    assert client1 is not client2
