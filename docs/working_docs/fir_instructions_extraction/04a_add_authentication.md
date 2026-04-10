# Task 04a: Add Authentication

## Goal

Add authentication to the FastAPI app using OAuth2 with Keycloak as the identity provider:

- Use Keycloak (via Docker Compose) to handle OAuth2 account management and token issuance
- The API validates Bearer JWT tokens issued by Keycloak on each request
- Three permission levels: Viewer, Editor, Administrator (see below)
- All existing endpoints are protected — unauthenticated requests return 401
- For development, the Keycloak container launches with a pre-configured realm, client, and default admin user (credentials documented below)
- Access tokens (short-lived) plus refresh tokens for session continuity
- No User table in the app database; user identity and roles are trusted entirely from JWT claims

**Permission levels:**

| Role | Capabilities |
|---|---|
| Viewer | Read-only access to all data endpoints; can manage their own Keycloak account |
| Editor | All Viewer privileges; can mutate data (write endpoints added in a later task) |
| Administrator | All Editor privileges; can manage users via Keycloak admin console |

## Prerequisites

- Docker Compose available (Keycloak runs as a container)
- Existing FastAPI app running (Tasks 01–10 are independent; this task is orthogonal)

## Task List

- [ ] Add `PyJWT[crypto]`, `cachetools`, and `httpx` (already a dev dep — promote to main) to dependencies; run `uv sync`
- [ ] Add Keycloak service to `docker-compose.yml`
- [ ] Create Keycloak realm initialization script (`keycloak/realm-export.json`) with realm, client, roles, and default dev admin user
- [ ] Create `src/municipal_finances/api/auth.py` — JWT validation and role-checking dependencies
- [ ] Apply auth dependencies to all existing routes (Viewer minimum on all read endpoints)
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### Dependencies

Add to `pyproject.toml` main dependencies:

```toml
"PyJWT[crypto]>=2.10"    # actively maintained; [crypto] pulls in cryptography for RS256
"cachetools>=5.5"        # TTL cache for JWKS
"httpx>=0.28"            # move from dev to main (needed for JWKS fetch)
```

### Docker Compose — Keycloak Service

Add to `docker-compose.yml`:

```yaml
  keycloak:
    image: quay.io/keycloak/keycloak:26
    command: start-dev --import-realm
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
      KC_DB: dev-mem          # in-memory; fine for dev, not production
    volumes:
      - ./keycloak:/opt/keycloak/data/import
    ports:
      - "8080:8080"
```

And add `depends_on: [keycloak]` to the `api` service.

### Keycloak Realm Initialization

Create `keycloak/realm-export.json` to configure the realm on first start. Key elements:

- **Realm name**: `municipal-finances`
- **Client**: `municipal-finances-api`
  - Client authentication: off (public client, for simplicity in dev)
  - Direct Access Grants: enabled (allows username/password token request for dev/testing)
  - Valid redirect URIs: `*` (dev only — restrict in production)
- **Roles**: `viewer`, `editor`, `administrator` (realm roles)
- **Default dev user**:
  - Username: `admin-dev`
  - Password: `changeme` (temporary, documented)
  - Roles assigned: `administrator`
- **Access token lifespan**: 300 seconds (5 minutes)
- **Refresh token lifespan**: 30 minutes (configurable in realm settings)

Generate the export JSON by standing up Keycloak manually once, configuring via the admin console, and exporting the realm. Commit the result as `keycloak/realm-export.json`. Document the manual export process briefly in a comment at the top of the file.

### Auth Module — `src/municipal_finances/api/auth.py`

This module is responsible for:

1. Fetching Keycloak's JWKS (public keys) to verify JWT signatures
2. Decoding and validating the Bearer token on each request
3. Extracting the user's realm roles from the token claims
4. Providing FastAPI dependency functions for each permission level

**Environment variables** (add to `.env.example`):

```
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=municipal-finances
KEYCLOAK_CLIENT_ID=municipal-finances-api
```

**JWKS URL** (derived at startup):
```
{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs
```

**Token validation flow:**

```python
import jwt                # PyJWT
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
)

def get_jwks_client() -> jwt.PyJWKClient:
    """Return a PyJWKClient pointed at Keycloak's JWKS endpoint."""
    ...

def decode_token(token: str) -> dict:
    """Validate the JWT signature and expiry; return the claims dict."""
    try:
        signing_key = get_jwks_client().get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=KEYCLOAK_CLIENT_ID,
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

def get_roles(claims: dict) -> list[str]:
    """Extract realm roles from Keycloak JWT claims."""
    return claims.get("realm_access", {}).get("roles", [])
```

**Role dependency functions:**

```python
def require_viewer(token: str = Depends(oauth2_scheme)) -> dict:
    claims = decode_token(token)
    roles = get_roles(claims)
    if not any(r in roles for r in ["viewer", "editor", "administrator"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return claims

def require_editor(token: str = Depends(oauth2_scheme)) -> dict:
    claims = decode_token(token)
    roles = get_roles(claims)
    if not any(r in roles for r in ["editor", "administrator"]):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return claims

def require_administrator(token: str = Depends(oauth2_scheme)) -> dict:
    claims = decode_token(token)
    roles = get_roles(claims)
    if "administrator" not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return claims
```

### Applying Auth to Existing Routes

Add `require_viewer` as a dependency to every route in:
- `api/routes/municipalities.py`
- `api/routes/fir_records.py`
- `api/routes/fir_sources.py`
- `api/routes/fir_instructions.py` (Task 10a, if complete)

Example:

```python
from municipal_finances.api.auth import require_viewer

@router.get("/", response_model=list[Municipality])
def list_municipalities(
    session: SessionDep,
    _claims: dict = Depends(require_viewer),
    ...
):
    ...
```

The `_claims` parameter is prefixed with `_` to indicate it's used only for its side effects (auth enforcement), not its value.

### JWKS Caching

`PyJWKClient` handles key fetching, but it re-fetches on every process startup and again on key rotation events. Wrap it in a module-level `cachetools.TTLCache` so the client instance (and its internally cached keys) is reused across requests within the TTL:

```python
from cachetools import TTLCache
from threading import Lock

_jwks_cache: TTLCache = TTLCache(maxsize=1, ttl=300)  # 5-minute TTL
_jwks_lock = Lock()

def get_jwks_client() -> jwt.PyJWKClient:
    """Return a cached PyJWKClient. Thread-safe via lock."""
    with _jwks_lock:
        if "client" not in _jwks_cache:
            _jwks_cache["client"] = jwt.PyJWKClient(JWKS_URL)
        return _jwks_cache["client"]
```

The lock ensures only one thread reconstructs the client on expiry. `PyJWKClient` itself also caches fetched keys internally and re-fetches automatically on a key-ID miss (i.e., after a Keycloak key rotation), so this two-layer approach avoids both thundering-herd on startup and stale-key issues after rotation.

### Refresh Tokens

Keycloak issues both an access token and a refresh token when a user authenticates. The API does not handle refresh tokens directly — the client is responsible for using the refresh token to obtain a new access token before expiry.

**Keycloak configuration** (in `realm-export.json`):
- Refresh token TTL: 1800 seconds (30 minutes)
- Refresh token rotation: enabled (each use issues a new refresh token and invalidates the old one)

**Client flow:**
1. Client POSTs credentials to Keycloak's token endpoint → receives `access_token` + `refresh_token`
2. Client includes `access_token` as `Authorization: Bearer <token>` on API calls
3. When the access token nears expiry, client POSTs to Keycloak's token endpoint with `grant_type=refresh_token&refresh_token=<token>` → receives new token pair
4. On logout, client POSTs to Keycloak's logout endpoint to revoke the refresh token

The API itself only validates access tokens and is unaware of refresh tokens.

## Tests

Auth logic in `tests/test_auth.py`, route enforcement in `tests/api/test_auth_enforcement.py`.

**Auth module (`tests/test_auth.py`):**

- [ ] Test `decode_token` with a valid JWT returns the expected claims
- [ ] Test `decode_token` with an expired JWT raises 401
- [ ] Test `decode_token` with a tampered signature raises 401
- [ ] Test `decode_token` with a missing/malformed Authorization header raises 401
- [ ] Test `get_roles` extracts realm roles correctly from a valid claims dict
- [ ] Test `get_roles` returns an empty list when `realm_access` is absent
- [ ] Test `require_viewer` passes for a token with the `viewer` role
- [ ] Test `require_viewer` passes for a token with `editor` or `administrator` role
- [ ] Test `require_viewer` raises 403 for a token with no recognized role
- [ ] Test `require_editor` passes for `editor` and `administrator`; raises 403 for `viewer`
- [ ] Test `require_administrator` passes only for `administrator`; raises 403 for others
- [ ] Test JWKS caching: a second call within TTL returns the same `PyJWKClient` instance without re-fetching
- [ ] Test JWKS caching: a call after TTL expiry constructs a new `PyJWKClient` instance

Use `pytest-mock` to mock `jwt.PyJWKClient` and construct test JWTs using `PyJWT` with a test RSA key pair (generated with `cryptography` in a session-scoped fixture).

**Route enforcement (`tests/api/test_auth_enforcement.py`):**

- [ ] Test that all existing `GET` endpoints return 401 when no token is provided
- [ ] Test that all existing `GET` endpoints return 403 when a token with no valid role is provided
- [ ] Test that all existing `GET` endpoints return 200 when a valid `viewer` token is provided

Parametrize across all route paths to avoid repetitive test code.

## Documentation Updates

- [ ] Update `CLAUDE.md` "Common commands" section — add Keycloak admin console URL and default dev credentials
- [ ] Update `CLAUDE.md` "Environment" section — document the three new `KEYCLOAK_*` env vars
- [ ] Update `CLAUDE.md` "Project structure" — add `keycloak/` directory and `api/auth.py`
- [ ] Update `.env.example` with the three new `KEYCLOAK_*` vars
- [ ] Update `docs/architecture.md` — document the auth design decisions (Keycloak, JWT-only, no app-side User table, role-claim approach)
- [ ] Update `README.md` — document how to obtain a token for API use (curl example against Keycloak's token endpoint)

## Success Criteria

- `docker compose up -d` starts Keycloak alongside the db and api containers without errors
- Keycloak admin console is accessible at `http://localhost:8080`
- The `municipal-finances` realm, `municipal-finances-api` client, and `admin-dev` user are pre-configured on first start
- A token can be obtained with:
  ```bash
  curl -s -X POST http://localhost:8080/realms/municipal-finances/protocol/openid-connect/token \
    -d "grant_type=password&client_id=municipal-finances-api&username=admin-dev&password=changeme" \
    | jq .access_token
  ```
- All `GET` endpoints return 401 without a token and 200 with a valid access token
- A refresh token is included in the token response alongside the access token
- All tests pass with 100% coverage on new code

## Verification

```bash
# Get a dev token
TOKEN=$(curl -s -X POST http://localhost:8080/realms/municipal-finances/protocol/openid-connect/token \
  -d "grant_type=password&client_id=municipal-finances-api&username=admin-dev&password=changeme" \
  | jq -r .access_token)

# Should return 200
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/municipalities/

# Should return 401
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/municipalities/
```
