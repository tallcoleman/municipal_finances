
# Task 10b: Create Metadata Descriptions Editor

## Goal

Create a React front-end application and corresponding API endpoints that allow an authenticated Editor or Administrator user to view and edit the following Markdown text fields in the metadata tables:

- `fir_schedule_meta.description`
- `fir_schedule_meta.change_notes`
- `fir_line_meta.description`
- `fir_line_meta.includes`
- `fir_line_meta.excludes`
- `fir_line_meta.applicability`
- `fir_line_meta.change_notes`
- `fir_column_meta.description`
- `fir_column_meta.change_notes`

Edits are in-place updates to existing rows — the intent is to clean up and enhance text extracted from source PDFs, not to change version ranges or create new versioned rows. The UI mirrors the Schedule → Line / Column hierarchy of the data. When a record has multiple historical versions, the editor allows navigating between them and displays the adjacent version's content read-only alongside the editor for reference.

**Architecture:**

- Front-end: Vite + React + TypeScript, deployed as a static site on Coolify via Docker + nginx
- Markdown editor: `@uiw/react-md-editor` with `rehype-sanitize` (XSS protection on preview output)
- Auth: Keycloak Authorization Code + PKCE flow (extends the client from Task 04a to support the SPA)
- Backend additions: three `PATCH` endpoints added to the FastAPI app; read access via Task 10a GET endpoints
- State management: TanStack Query for server state; local React state for in-progress edits

## Prerequisites

- Task 04a (authentication) complete — Keycloak is running, JWT validation is in place, and the `municipal-finances-api` Keycloak client exists
- Task 10a (API endpoints) complete, or at minimum the GET list and detail endpoints for schedules, lines, and columns are implemented

## Task List

**Backend:**

- [ ] Add CORS middleware to `api/main.py`
- [ ] Extend `keycloak/realm-export.json` to enable Standard Flow (Authorization Code + PKCE) on the existing `municipal-finances-api` client; add frontend redirect URIs
- [ ] Add `PATCH /instructions/schedules/{id}` endpoint with `require_editor` auth
- [ ] Add `PATCH /instructions/lines/{id}` endpoint with `require_editor` auth
- [ ] Add `PATCH /instructions/columns/{id}` endpoint with `require_editor` auth
- [ ] Add `line_id` filter param to `GET /instructions/lines/` and `column_id` filter param to `GET /instructions/columns/` (needed to fetch all versions of a specific line or column without a year filter)
- [ ] Write backend tests for the PATCH endpoints and updated list endpoint filters

**Frontend:**

- [ ] Initialize Vite + React + TypeScript project in `frontend/`
- [ ] Add runtime dependencies: `@uiw/react-md-editor`, `rehype-sanitize`, `@tanstack/react-query`, `keycloak-js`, `@react-keycloak/web`, `react-router-dom`
- [ ] Add dev dependencies: `vitest`, `@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`, `jsdom`, `msw`
- [ ] Implement Keycloak auth integration (login-required, PKCE, token refresh on API calls)
- [ ] Implement API client with automatic Bearer token injection
- [ ] Build `MarkdownField` — `@uiw/react-md-editor` wrapper with `rehype-sanitize` and read-only mode
- [ ] Build `VersionNavigator` — version tab/prev–next control; shows adjacent version content read-only alongside the active editor
- [ ] Build `ScheduleSelector` — lists all schedules, selectable to enter the editor
- [ ] Build `ScheduleEditor` — edits `description` and `change_notes` on a selected schedule version
- [ ] Build `LineEditor` — edits all five line fields on a selected line version
- [ ] Build `ColumnEditor` — edits `description` and `change_notes` on a selected column version
- [ ] Compose `EditorPage` — full page layout linking selector, version navigator, and editors
- [ ] Add `frontend/Dockerfile` (multi-stage, nginx) and `frontend/nginx.conf`
- [ ] Write frontend tests (Vitest + React Testing Library + MSW)
- [ ] Update documentation

## Implementation Details

### Backend: CORS

Add `CORSMiddleware` to `api/main.py`. Read allowed origins from an environment variable so the production value can differ from the dev default:

```python
from fastapi.middleware.cors import CORSMiddleware
import os

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["GET", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

Add `CORS_ALLOWED_ORIGINS` to `.env.example`. In production, set this to the Coolify frontend URL (e.g., `https://editor.example.com`).

### Backend: Keycloak — Enable SPA Flow

The existing `municipal-finances-api` client was created in Task 04a with Direct Access Grants for dev/test use. Extend it in `keycloak/realm-export.json` to also support the Authorization Code + PKCE flow used by the SPA:

- Set `standardFlowEnabled: true` on the `municipal-finances-api` client
- Add to `redirectUris`: `http://localhost:5173/*` (dev) and a placeholder for the production Coolify URL (e.g., `https://editor.example.com/*`)
- Add to `webOrigins`: `http://localhost:5173` and the production origin (for Keycloak's CORS handling)

Using the same client for both the API (Direct Access Grants in dev) and the SPA (Standard Flow) avoids an audience mismatch in JWT validation — the API already validates tokens with `audience=municipal-finances-api`.

### Backend: PATCH Endpoints

Add to `src/municipal_finances/api/routes/fir_instructions.py` alongside the Task 10a read endpoints. All three endpoints require `require_editor`, accept a partial-update body, return the full updated record, and return 404 for an unknown id.

**Pydantic update models:**

```python
class ScheduleMetaUpdate(SQLModel):
    description: str | None = None
    change_notes: str | None = None

class LineMetaUpdate(SQLModel):
    description: str | None = None
    includes: str | None = None
    excludes: str | None = None
    applicability: str | None = None
    change_notes: str | None = None

class ColumnMetaUpdate(SQLModel):
    description: str | None = None
    change_notes: str | None = None
```

**Implementation pattern** (apply identically to lines and columns):

```python
@router.patch("/instructions/schedules/{id}", response_model=FIRScheduleMeta)
def update_schedule_meta(
    id: int,
    update: ScheduleMetaUpdate,
    session: SessionDep,
    _claims: dict = Depends(require_editor),
):
    """Update editable description fields on a schedule metadata row."""
    row = session.get(FIRScheduleMeta, id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
```

`exclude_unset=True` ensures only explicitly provided fields are written — a PATCH body of `{"description": "new text"}` leaves `change_notes` unchanged.

### Backend: List Endpoint Filters

Version navigation requires fetching all version rows for a specific (schedule, line_id) or (schedule, column_id) pair. Add optional filter params to the existing list endpoints:

- `GET /instructions/lines/?schedule={s}&line_id={l}` — when `line_id` is provided, filter to rows matching that exact `line_id`. Combine with omitting `year` to return all versions.
- `GET /instructions/columns/?schedule={s}&column_id={c}` — same pattern.

These are additive changes to the Task 10a endpoint signatures.

### Frontend: Project Setup

Initialize the project at `frontend/` in the repository root:

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install @uiw/react-md-editor rehype-sanitize @tanstack/react-query \
            keycloak-js @react-keycloak/web react-router-dom
npm install -D vitest @testing-library/react @testing-library/user-event \
               @testing-library/jest-dom jsdom msw
```

**Project structure:**

```
frontend/
  src/
    auth/
      keycloak.ts         # Keycloak instance
      AuthProvider.tsx    # ReactKeycloakProvider wrapper
    api/
      client.ts           # fetch wrapper with Bearer token injection
      schedules.ts        # API calls for fir_schedule_meta
      lines.ts            # API calls for fir_line_meta
      columns.ts          # API calls for fir_column_meta
    components/
      MarkdownField.tsx   # @uiw/react-md-editor + rehype-sanitize
      VersionNavigator.tsx
      ScheduleSelector.tsx
      ScheduleEditor.tsx
      LineEditor.tsx
      ColumnEditor.tsx
    pages/
      EditorPage.tsx
    App.tsx
    main.tsx
  __tests__/
    MarkdownField.test.tsx
    VersionNavigator.test.tsx
    ScheduleEditor.test.tsx
    LineEditor.test.tsx
    ColumnEditor.test.tsx
    auth.test.tsx
  Dockerfile
  nginx.conf
  vite.config.ts
  vitest.config.ts
  .env.example
```

**`frontend/.env.example`:**

```
VITE_API_URL=http://localhost:8000
VITE_KEYCLOAK_URL=http://localhost:8080
VITE_KEYCLOAK_REALM=municipal-finances
VITE_KEYCLOAK_CLIENT_ID=municipal-finances-api
```

Add the same four variables to the root `.env.example` with a comment indicating they are consumed by the frontend build.

> **Note:** Vite bakes env vars into the static bundle at build time. The correct production values for `VITE_API_URL` and `VITE_KEYCLOAK_URL` must be set before building the Docker image (e.g., as build args in Coolify). They are not read at runtime by nginx.

### Frontend: Keycloak Auth

`src/auth/keycloak.ts`:

```typescript
import Keycloak from 'keycloak-js';

const keycloak = new Keycloak({
  url: import.meta.env.VITE_KEYCLOAK_URL,
  realm: import.meta.env.VITE_KEYCLOAK_REALM,
  clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID,
});

export default keycloak;
```

`src/auth/AuthProvider.tsx`:

```typescript
import { ReactKeycloakProvider } from '@react-keycloak/web';
import keycloak from './keycloak';

export function AuthProvider({ children }: { children: React.ReactNode }) {
  return (
    <ReactKeycloakProvider
      authClient={keycloak}
      initOptions={{ onLoad: 'login-required', pkceMethod: 'S256' }}
    >
      {children}
    </ReactKeycloakProvider>
  );
}
```

`onLoad: 'login-required'` redirects unauthenticated visitors to Keycloak immediately. `pkceMethod: 'S256'` enables PKCE.

### Frontend: API Client

`src/api/client.ts`:

```typescript
import keycloak from '../auth/keycloak';

const BASE_URL = import.meta.env.VITE_API_URL;

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  await keycloak.updateToken(30); // refresh if expiring within 30 s
  return fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${keycloak.token}`,
      ...options.headers,
    },
  });
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

export async function apiPatch<T>(path: string, body: object): Promise<T> {
  const res = await apiFetch(path, { method: 'PATCH', body: JSON.stringify(body) });
  if (!res.ok) throw new Error(`PATCH ${path} failed: ${res.status}`);
  return res.json();
}
```

### Frontend: MarkdownField

`src/components/MarkdownField.tsx`:

```typescript
import MDEditor from '@uiw/react-md-editor';
import rehypeSanitize from 'rehype-sanitize';

interface MarkdownFieldProps {
  label: string;
  value: string | null;
  onChange: (value: string) => void;
  readOnly?: boolean;
}

export function MarkdownField({ label, value, onChange, readOnly = false }: MarkdownFieldProps) {
  return (
    <div>
      <label>{label}</label>
      <MDEditor
        value={value ?? ''}
        onChange={(val) => onChange(val ?? '')}
        previewOptions={{ rehypePlugins: [[rehypeSanitize]] }}
        preview={readOnly ? 'preview' : 'live'}
        readOnly={readOnly}
      />
    </div>
  );
}
```

`rehypeSanitize` is applied only to the preview pane. It strips unsafe HTML that could result from Markdown rendering (e.g., `<script>` tags, inline event handlers), following the default sanitization schema.

### Frontend: Version Navigation

Each metadata row is uniquely identified by its database `id`. Multiple rows can share the same natural key (schedule, line_id) with different `valid_from_year`/`valid_to_year` ranges. The `VersionNavigator` component:

1. Receives the full list of versions for the selected record, sorted by `valid_from_year` ascending (nulls first)
2. Tracks the index of the currently selected version
3. Renders prev / next controls and a label showing the year range of each version
4. When the selected version has a neighbour, renders that neighbour's fields read-only alongside the active editor

**Year range label helper:**

```typescript
function versionLabel(validFromYear: number | null, validToYear: number | null): string {
  const from = validFromYear === null ? 'before 2019' : String(validFromYear);
  const to   = validToYear   === null ? 'present'     : String(validToYear);
  return `${from} – ${to}`;
}
```

**Fetching all versions for a line:**

```
GET /instructions/lines/?schedule=40&line_id=0410
```

Omitting the `year` parameter and including `line_id` returns every version row for that line. The same pattern applies to columns (`column_id` filter) and schedules (filter the full schedule list by `schedule` code client-side, since there are only ~26 schedules).

### Frontend: Editor Layout

`EditorPage.tsx` composes the full editing experience:

```
┌─────────────────────────────────────────────────────┐
│  Schedule: [selector]                               │
├─────────────────────────────┬───────────────────────┤
│  Schedule Metadata          │  Versions:            │
│  ── description ──          │  ← 2022 | 2023–present│
│  [MarkdownField]            │                       │
│  ── change_notes ──         │  Prior version        │
│  [MarkdownField]            │  (read-only preview)  │
│  [Save]                     │                       │
├─────────────────┬───────────┴───────────────────────┤
│  Lines          │  Columns                          │
│  [line list]    │  [column list]                    │
│  → [LineEditor] │  → [ColumnEditor]                 │
└─────────────────┴───────────────────────────────────┘
```

Use TanStack Query mutations for saves so the query cache is automatically invalidated and the UI reflects the saved values without a manual refresh.

### Frontend: Deployment

`frontend/Dockerfile`:

```dockerfile
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

`frontend/nginx.conf` (handles client-side routing):

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

In Coolify, point the service at `frontend/Dockerfile` within the repository. Set `VITE_API_URL`, `VITE_KEYCLOAK_URL`, `VITE_KEYCLOAK_REALM`, and `VITE_KEYCLOAK_CLIENT_ID` as build-time environment variables in Coolify's service configuration. Also update the `municipal-finances-api` Keycloak client's `redirectUris` and `webOrigins` to include the production Coolify domain before the first production deploy.

## Tests

### Backend (`tests/api/test_instructions_editor.py`)

- [ ] `PATCH /instructions/schedules/{id}` with valid editor token returns 200 and updated row
- [ ] `PATCH /instructions/schedules/{id}` with partial body updates only the specified fields; unspecified fields are unchanged
- [ ] `PATCH /instructions/schedules/{id}` with viewer token returns 403
- [ ] `PATCH /instructions/schedules/{id}` without token returns 401
- [ ] `PATCH /instructions/schedules/{id}` with unknown id returns 404
- [ ] Repeat the above five assertions for `PATCH /instructions/lines/{id}`
- [ ] Repeat the above five assertions for `PATCH /instructions/columns/{id}`
- [ ] `GET /instructions/lines/?schedule=X&line_id=Y` (no year) returns all version rows for that line
- [ ] `GET /instructions/columns/?schedule=X&column_id=Y` (no year) returns all version rows for that column
- [ ] CORS preflight (`OPTIONS /instructions/schedules/{id}`) returns correct `Access-Control-Allow-*` headers

### Frontend (`frontend/__tests__/`)

Use Vitest + React Testing Library. Mock API calls with MSW (`msw/node` in tests).

- [ ] `MarkdownField`: renders the label; updates value on change; applies read-only mode (preview only, no toolbar)
- [ ] `MarkdownField`: preview pane strips `<script>` tags via `rehype-sanitize`
- [ ] `VersionNavigator`: renders correct version count; prev button disabled on first version; next button disabled on last version
- [ ] `VersionNavigator`: selecting next version emits correct index and displays adjacent version content read-only
- [ ] `ScheduleEditor`: renders field values from MSW-mocked API; calls `PATCH` on save with only changed fields; shows save success state
- [ ] `ScheduleEditor`: save button is disabled while the mutation is in-flight
- [ ] `LineEditor`: renders all five fields; calls `PATCH` with correct payload
- [ ] `ColumnEditor`: renders both fields; calls `PATCH` on save
- [ ] `AuthProvider`: when `keycloak.authenticated` is false, the protected page is not rendered (redirect occurs)

## Documentation Updates

- [ ] Update `CLAUDE.md` "Project structure" — add `frontend/` directory with key subdirectories
- [ ] Update `CLAUDE.md` "Environment" — document `CORS_ALLOWED_ORIGINS`
- [ ] Update `CLAUDE.md` "Common commands" — add `npm run dev` (start frontend dev server) and `npm run build` (build static site) under a new "Frontend" subsection
- [ ] Update root `.env.example` — add `CORS_ALLOWED_ORIGINS` and the four `VITE_*` build vars with comments
- [ ] Add `frontend/.env.example` with the four `VITE_*` variables
- [ ] Update `docs/architecture.md` — document the editor front-end, the decision to extend the existing Keycloak client for PKCE rather than create a separate SPA client, and the Vite + nginx deployment model
- [ ] Update `README.md` — describe the editor app (purpose, how to run locally, how authentication works, note on build-time env vars)

## Success Criteria

- Authenticated editors can log in via Keycloak, select a schedule, and save edits to all listed Markdown fields
- Unauthenticated visitors are redirected to Keycloak login; only users with `editor` or `administrator` roles can save changes
- Viewer-role users receive 403 on any PATCH request
- When a record has multiple versions, the navigator shows all versions, the adjacent version's text is visible read-only for reference, and each version can be independently edited and saved
- Markdown preview output is sanitized via `rehype-sanitize`; `<script>` tags are stripped
- PATCH requests update only submitted fields; unsubmitted fields are unchanged in the database
- All backend tests pass at 100% coverage on new code
- All frontend tests pass
- The Docker image builds cleanly; the static site is served correctly by nginx (including client-side routing fallback to `index.html`)

## Verification

```bash
# Get a dev token using the API client's Direct Access Grant (for CLI testing)
TOKEN=$(curl -s -X POST http://localhost:8080/realms/municipal-finances/protocol/openid-connect/token \
  -d "grant_type=password&client_id=municipal-finances-api&username=admin-dev&password=changeme" \
  | jq -r .access_token)

# Patch a schedule description (replace 1 with a valid id)
curl -s -X PATCH http://localhost:8000/instructions/schedules/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Updated description."}' | jq .description

# Confirm partial update: change_notes should be unchanged
curl -s http://localhost:8000/instructions/schedules/1 \
  -H "Authorization: Bearer $TOKEN" | jq .change_notes

# Confirm 403 for viewer role (issue a viewer token first, then):
curl -s -o /dev/null -w "%{http_code}" -X PATCH http://localhost:8000/instructions/schedules/1 \
  -H "Authorization: Bearer $VIEWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Should be rejected."}'
# Expected: 403

# Start the frontend dev server
cd frontend && npm run dev
# Open http://localhost:5173 — should redirect to Keycloak login,
# then land on the editor after authenticating as admin-dev
```
