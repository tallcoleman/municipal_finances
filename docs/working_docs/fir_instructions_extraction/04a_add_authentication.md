# Task 04a: Add Authentication

## Goal

Add authentication to the FastAPI app using OAuth2 with Keycloak as the identity provider:

- Use Keycloak (via Docker Compose) to handle OAuth2 account management and token issuance
- The API validates Bearer JWT tokens issued by Keycloak on each request
- Three permission levels: Viewer, Editor, Administrator (see below)
- All existing endpoints are protected — unauthenticated requests return 401
- For development, the Keycloak container launches with a pre-configured realm, client, and default admin user (credentials documented below)
- Short-lived access tokens only (no refresh token support in this task — see notes in Implementation Details)
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

- [ ] Add `python-jose[cryptography]` and `httpx` (already a dev dep — promote to main) to dependencies; run `uv sync`
- [ ] Add Keycloak service to `docker-compose.yml`
- [ ] Create Keycloak realm initialization script (`keycloak/realm-export.json`) with realm, client, roles, and default dev admin user
- [ ] Create `src/municipal_finances/api/auth.py` — JWT validation and role-checking dependencies
- [ ] Apply auth dependencies to all existing routes (Viewer minimum on all read endpoints)
- [ ] Write tests
- [ ] Create `docs/working_docs/fir_instructions_extraction/xx_auth_production_hardening.md` (draft notes)
- [ ] Update documentation

## Implementation Details

### Dependencies

Add to `pyproject.toml` main dependencies:

```toml
"python-jose[cryptography]>=3.3"
"httpx>=0.28"          # move from dev to main (needed for JWKS fetch)
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
- **Token lifespan**: 300 seconds (5 minutes) — short-lived, no refresh tokens issued to keep scope limited

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
from jose import jwt, JWTError
import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
)

def get_jwks() -> dict:
    """Fetch JWKS from Keycloak. Cache the result (e.g., with functools.lru_cache or a module-level variable)."""
    ...

def decode_token(token: str) -> dict:
    """Validate the JWT signature and expiry; return the claims dict."""
    jwks = get_jwks()
    try:
        return jwt.decode(token, jwks, algorithms=["RS256"], audience=KEYCLOAK_CLIENT_ID)
    except JWTError:
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
- `api/routes/fir_instructions.py` (Task 10, if complete)

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

Fetching JWKS on every request is expensive and fragile. Cache the JWKS response at module level with a short TTL (e.g., 5 minutes). A simple approach:

```python
import time

_jwks_cache: dict | None = None
_jwks_fetched_at: float = 0.0
_JWKS_TTL = 300  # seconds

def get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    if _jwks_cache is None or time.time() - _jwks_fetched_at > _JWKS_TTL:
        response = httpx.get(JWKS_URL)
        response.raise_for_status()
        _jwks_cache = response.json()
        _jwks_fetched_at = time.time()
    return _jwks_cache
```

### Notes on Refresh Tokens

This task issues short-lived access tokens only (5-minute TTL). Refresh token support is deferred. It would be warranted if:

- **Interactive web clients** need to maintain a session without re-prompting for credentials — access tokens expiring every 5 minutes would cause frequent logouts
- **Long-running batch jobs** need API access across token expiry boundaries
- **Mobile clients** are added, where re-authentication UX is disruptive

Keycloak supports refresh tokens natively; enabling them is primarily a client and realm configuration change. The API itself would not need to change — the client handles the refresh flow and presents a fresh access token.

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
- [ ] Test JWKS caching: a second call within TTL does not re-fetch from Keycloak

Use `pytest-mock` to mock `httpx.get` for JWKS responses and construct test JWTs using `python-jose` with a test RSA key pair.

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
- All `GET` endpoints return 401 without a token and 200 with a valid token
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
