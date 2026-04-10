# Task XX: Auth Production Hardening (DRAFT NOTES)

> **Status: Draft — unordered notes. Not a fully-formed task document.**
>
> These are steps that were intentionally deferred from Task 04a. They should be
> evaluated and prioritized before any public-facing or multi-user deployment.

---

## Keycloak Configuration

- **Switch to a persistent database**: replace `KC_DB=dev-mem` with a real PostgreSQL-backed Keycloak instance. The in-memory store loses all user data on container restart.
- **Restrict redirect URIs**: the dev realm uses `*`. Lock this down to the actual frontend origin(s).
- **Disable Direct Access Grants**: the `password` grant type (used for dev token fetching via curl) should be disabled in production — it exposes credentials directly to the client. Use authorization code flow with PKCE instead.
- **Set a strong admin password**: `KEYCLOAK_ADMIN_PASSWORD` should come from a secret manager, not a hardcoded env var.
- **Realm hardening**: review Keycloak's production hardening checklist (brute-force protection, password policies, session limits, email verification).
- **Run Keycloak in production mode**: replace `start-dev` with `start` in the container command. This enforces HTTPS and disables development-only features.
- **TLS**: Keycloak in production mode requires HTTPS. Put a reverse proxy (e.g., nginx, Caddy) in front.

## Token and Session Management

- **Consider refresh tokens** if interactive clients or long-running jobs are added (see notes in Task 04a).
- **Token introspection vs. offline validation**: Task 04a validates JWTs offline using JWKS. For higher-security scenarios (e.g., to support immediate token revocation), switch to token introspection (`/protocol/openid-connect/token/introspect`) at the cost of a network call per request.
- **Review token TTL**: 5 minutes is conservative and fine for API-only access. Adjust if a frontend is added.

## API Security

- **Rate limiting on auth-related endpoints**: protect the Keycloak token endpoint against brute-force with rate limiting at the proxy layer.
- **CORS configuration**: `api/main.py` currently has no CORS middleware. Add `CORSMiddleware` with explicit `allow_origins` before any browser-based client is added.
- **HTTPS on the API**: uvicorn currently serves HTTP. Terminate TLS at a reverse proxy in production.
- **Audit logging**: log authentication events (successful logins, 401/403 responses) with enough context (IP, user sub, endpoint) to support incident investigation.

## Secrets Management

- **`KEYCLOAK_*` env vars**: move to a secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault) rather than `.env` files in production.
- **Remove hardcoded dev credentials** from any committed files before deploying to a shared or public environment.

## Operational

- **Health check for Keycloak**: add a `healthcheck` to the Keycloak Docker Compose service so the api container waits for Keycloak to be ready before accepting requests.
- **JWKS cache invalidation**: the current module-level cache in `auth.py` is not invalidated on Keycloak key rotation. For production, consider a more robust cache with forced refresh on 401 from downstream or a scheduled refresh.
- **Keycloak version pinning**: pin the Keycloak image to a specific patch version (e.g., `keycloak:26.1.2`) rather than a minor version tag for reproducibility.
