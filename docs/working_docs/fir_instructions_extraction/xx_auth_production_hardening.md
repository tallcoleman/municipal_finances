# Task XX: Auth Production Hardening (DRAFT NOTES)

> **Status: Draft — unordered notes. Not a fully-formed task document.**
>
> These are steps that were intentionally deferred from Task 04a. They should be
> evaluated and prioritized before any public-facing or multi-user deployment.

---

## Keycloak Configuration

- **Switch to a persistent database**: replace `KC_DB=dev-mem` with a real PostgreSQL-backed Keycloak instance. The in-memory store loses all user data on container restart.
- **Restrict redirect URIs**: the dev realm uses `*`. Lock this down to the actual frontend origin(s). For the Coolify-hosted editor (Task 10b), add the production Coolify domain to the `municipal-finances-api` client's `redirectUris` and `webOrigins` in `keycloak/realm-export.json` before the first production deploy — or set them via the Keycloak admin console and re-export the realm.
- **Disable Direct Access Grants**: the `password` grant type (used for dev token fetching via curl) should be disabled in production — it exposes credentials directly to the client. Use authorization code flow with PKCE instead.
- **Set a strong admin password**: `KEYCLOAK_ADMIN_PASSWORD` should come from a secret manager, not a hardcoded env var.
- **Realm hardening**: review Keycloak's production hardening checklist (brute-force protection, password policies, session limits, email verification).
- **Run Keycloak in production mode**: replace `start-dev` with `start` in the container command. This enforces HTTPS and disables development-only features.
- **TLS**: Keycloak in production mode requires HTTPS. Put a reverse proxy (e.g., nginx, Caddy) in front.

## Token and Session Management

- **Token introspection vs. offline validation**: Task 04a validates JWTs offline using JWKS. For higher-security scenarios (e.g., to support immediate token revocation), switch to token introspection (`/protocol/openid-connect/token/introspect`) at the cost of a network call per request.
- **Review token TTLs**: access token (5 min) and refresh token (30 min) lifespans were chosen conservatively. Adjust if a frontend with longer idle sessions is added.
- **Refresh token absolute expiry**: Keycloak supports a `ssoSessionMaxLifespan` that caps the total refresh chain regardless of activity. Set this to a reasonable value (e.g., 8 hours) to limit the window of a stolen refresh token.

## API Security

- **Rate limiting on auth-related endpoints**: protect the Keycloak token endpoint against brute-force with rate limiting at the proxy layer.
- **CORS configuration**: Task 10b adds `CORSMiddleware` to `api/main.py` with origins read from `CORS_ALLOWED_ORIGINS`. Set this env var to the production Coolify frontend URL (e.g., `https://editor.example.com`) — do not leave it at the dev default (`http://localhost:5173`) in production.
- **HTTPS on the API**: uvicorn currently serves HTTP. Terminate TLS at a reverse proxy in production.
- **Audit logging**: log authentication events (successful logins, 401/403 responses) with enough context (IP, user sub, endpoint) to support incident investigation.

## Secrets Management

- **`KEYCLOAK_*` env vars**: move to a secrets manager (e.g., AWS Secrets Manager, HashiCorp Vault) rather than `.env` files in production.
- **Remove hardcoded dev credentials** from any committed files before deploying to a shared or public environment.

## Operational

- **Health check for Keycloak**: add a `healthcheck` to the Keycloak Docker Compose service so the api container waits for Keycloak to be ready before accepting requests.
- **JWKS cache invalidation**: the current module-level cache in `auth.py` is not invalidated on Keycloak key rotation. For production, consider a more robust cache with forced refresh on 401 from downstream or a scheduled refresh.
- **Keycloak version pinning**: pin the Keycloak image to a specific patch version (e.g., `keycloak:26.1.2`) rather than a minor version tag for reproducibility.
