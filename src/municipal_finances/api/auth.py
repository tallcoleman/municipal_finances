"""JWT authentication and role-checking dependencies for the FastAPI app.

Validates Bearer tokens issued by Keycloak, extracts realm roles from claims,
and provides FastAPI dependency functions for each permission level.
"""

import os
from threading import Lock

import jwt
from cachetools import TTLCache
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "municipal-finances")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "municipal-finances-api")

JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"
_TOKEN_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=_TOKEN_URL)

_jwks_cache: TTLCache = TTLCache(maxsize=1, ttl=300)
_jwks_lock = Lock()


def get_jwks_client() -> jwt.PyJWKClient:
    """Return a cached PyJWKClient pointed at Keycloak's JWKS endpoint.

    Thread-safe: only one thread constructs the client on cache expiry.
    PyJWKClient itself caches fetched keys and re-fetches on key-ID miss
    (i.e., after Keycloak key rotation), so this avoids thundering-herd
    on startup without risking stale keys post-rotation.
    """
    with _jwks_lock:
        if "client" not in _jwks_cache:
            _jwks_cache["client"] = jwt.PyJWKClient(JWKS_URL)
        return _jwks_cache["client"]


def decode_token(token: str) -> dict:
    """Validate the JWT signature and expiry; return the claims dict.

    Raises HTTP 401 on any validation failure (expired, bad signature,
    wrong audience, malformed).
    """
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=KEYCLOAK_CLIENT_ID,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_roles(claims: dict) -> list[str]:
    """Extract realm roles from Keycloak JWT claims.

    Returns an empty list when realm_access is absent (e.g., service
    accounts or tokens without realm role claims).
    """
    return claims.get("realm_access", {}).get("roles", [])


def require_viewer(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: require viewer, editor, or administrator role."""
    claims = decode_token(token)
    roles = get_roles(claims)
    if not any(r in roles for r in ["viewer", "editor", "administrator"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return claims


def require_editor(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: require editor or administrator role."""
    claims = decode_token(token)
    roles = get_roles(claims)
    if not any(r in roles for r in ["editor", "administrator"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return claims


def require_administrator(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: require administrator role."""
    claims = decode_token(token)
    roles = get_roles(claims)
    if "administrator" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return claims
