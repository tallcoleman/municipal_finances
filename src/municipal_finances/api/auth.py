"""Keycloak token introspection and role-checking dependencies for the FastAPI app.

Validates Bearer tokens by calling Keycloak's introspection endpoint on every request,
extracts realm roles from the introspection response claims, and provides FastAPI
dependency functions for each permission level.
"""

import os

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "municipal-finances")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "municipal-finances-api")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", "")
# Public URL used only for the Swagger UI token form — must be reachable from the browser.
# Defaults to localhost:8080; override if Keycloak is behind a proxy.
_KEYCLOAK_PUBLIC_URL = os.getenv("KEYCLOAK_PUBLIC_URL", "http://localhost:8080")

INTROSPECTION_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token/introspect"
_TOKEN_URL = f"{_KEYCLOAK_PUBLIC_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=_TOKEN_URL)


def introspect_token(token: str) -> dict:
    """Validate a Bearer token via Keycloak's introspection endpoint; return claims.

    POSTs to Keycloak with client credentials and the token. Returns the full
    claims dict (including realm_access.roles) when active. Raises HTTP 401 if
    Keycloak marks the token inactive, if the HTTP call fails, or if Keycloak
    returns a non-2xx response.
    """
    try:
        response = httpx.post(
            INTROSPECTION_URL,
            data={
                "token": token,
                "client_id": KEYCLOAK_CLIENT_ID,
                "client_secret": KEYCLOAK_CLIENT_SECRET,
            },
        )
        response.raise_for_status()
        claims = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if not claims.get("active"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


def get_roles(claims: dict) -> list[str]:
    """Extract realm roles from Keycloak introspection response claims.

    Returns an empty list when realm_access is absent (e.g., service
    accounts or tokens without realm role claims).
    """
    return claims.get("realm_access", {}).get("roles", [])


def require_viewer(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: require viewer, editor, or administrator role."""
    claims = introspect_token(token)
    roles = get_roles(claims)
    if not any(r in roles for r in ["viewer", "editor", "administrator"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return claims


def require_editor(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: require editor or administrator role."""
    claims = introspect_token(token)
    roles = get_roles(claims)
    if not any(r in roles for r in ["editor", "administrator"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return claims


def require_administrator(token: str = Depends(oauth2_scheme)) -> dict:
    """FastAPI dependency: require administrator role."""
    claims = introspect_token(token)
    roles = get_roles(claims)
    if "administrator" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return claims
