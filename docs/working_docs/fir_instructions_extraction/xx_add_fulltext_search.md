# Task XX: Add Full-Text Search (DRAFT)

> **Status: Draft — open questions listed below before this is finalized.**

## Goal

Add full-text search over the FIR instruction metadata tables so users can find relevant schedules, lines, and columns via a front-end website. Search results must support filtering by FIR year so users see only the metadata version that was valid in the year they care about.

## Prerequisites

- Task 01 (database models) complete
- Task 10a (API endpoints) complete — year filtering logic already established
- Some baseline data in the metadata tables for testing

## Approach

Use **PostgreSQL full-text search** (tsvector / GIN indexes). This requires no new infrastructure — search is handled by the existing PostgreSQL instance via new API endpoints. Results are always in sync with the database; no rebuild step is needed.

## Task List

- [ ] Write Alembic migration to add `search_vector` generated columns and GIN indexes
- [ ] Update SQLModel models if needed to accommodate the new columns
- [ ] Create `src/municipal_finances/api/routes/search.py` with search endpoints
- [ ] Register the new router in `api/main.py`
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### Database: Generated Columns and GIN Indexes

Add a `GENERATED ALWAYS AS ... STORED` tsvector column to each metadata table. The database auto-updates this column whenever text fields change — no application-level sync required.

**Tables and fields to index:**

| Table | Fields |
|---|---|
| `fir_schedule_meta` | `schedule_name`, `category`, `description` |
| `fir_line_meta` | `line_name`, `section`, `description`, `includes`, `excludes`, `applicability` |
| `fir_column_meta` | `column_name`, `description` |
| `fir_instruction_changelog` | `heading`, `description` |
| `municipality` | `municipality_desc` |

Example for `fir_line_meta` (repeat pattern for each table):

```sql
ALTER TABLE fir_line_meta
  ADD COLUMN search_vector tsvector
  GENERATED ALWAYS AS (
    to_tsvector('english',
      coalesce(line_name, '') || ' ' ||
      coalesce(section, '') || ' ' ||
      coalesce(description, '') || ' ' ||
      coalesce(includes, '') || ' ' ||
      coalesce(excludes, '') || ' ' ||
      coalesce(applicability, '')
    )
  ) STORED;

CREATE INDEX ix_fir_line_meta_search ON fir_line_meta USING GIN(search_vector);
```

SQLModel does not natively model PostgreSQL generated columns. Options:
- Declare the column with `sa_column=Column(TSVECTOR, server_default=...)` using SQLAlchemy types directly
- Or exclude it from the model and query using raw SQL / `text()` for search queries only

### API: Search Endpoints

Create `src/municipal_finances/api/routes/search.py`.

**Proposed endpoints:**

- `GET /search?q=...&year=...` — unified search across all metadata tables; returns results grouped by type (`schedule`, `line`, `column`, `changelog`)
- `GET /search/lines?q=...&year=...&schedule=...` — lines only; `schedule` is an optional narrowing filter
- `GET /search/schedules?q=...&year=...` — schedules only
- `GET /search/municipalities?q=...` — municipality name lookup (no year filter)

**Query pattern** (lines example):

```python
ts_query = func.plainto_tsquery("english", q)
stmt = (
    select(FIRLineMeta)
    .where(
        FIRLineMeta.search_vector.op("@@")(ts_query),
        FIRLineMeta.valid_from_year <= year,
        or_(FIRLineMeta.valid_to_year.is_(None), FIRLineMeta.valid_to_year >= year),
    )
    .order_by(func.ts_rank(FIRLineMeta.search_vector, ts_query).desc())
    .offset(offset)
    .limit(limit)
)
```

Use `plainto_tsquery` (not `to_tsquery`) — it safely handles user input without requiring the user to know PostgreSQL query syntax.

**Year filter default:** if `year` is omitted, default to the most recent FIR year with data. Expose this as a documented default in the API response so clients know what year was used.

**Response shape** for `GET /search`:

```json
{
  "query": "police protection",
  "year": 2024,
  "results": {
    "schedules": [...],
    "lines": [...],
    "columns": [...],
    "changelog": [...]
  }
}
```

Each result item should include the matched entity's key identifiers (schedule, line_id, etc.) plus a short excerpt of the matched text (can be generated with `ts_headline()`).

### Router Registration

In `api/main.py`:

```python
from municipal_finances.api.routes.search import router as search_router
app.include_router(search_router, prefix="/search", tags=["search"])
```

## Tests

Follow the pattern in `test_api.py`.

- [ ] Add seed helpers for each metadata table if not already present from Task 10a
- [ ] Test `GET /search?q=...&year=...` returns results from all table types
- [ ] Test `GET /search/lines?q=...&year=...` returns matching lines, ranked by relevance
- [ ] Test year filtering: a query with `year=2019` excludes rows with `valid_from_year > 2019`
- [ ] Test year filtering: a query with `year=2024` excludes rows where `valid_to_year < 2024`
- [ ] Test `year` omitted: defaults to most recent FIR year
- [ ] Test `GET /search/municipalities?q=...` returns matching municipalities
- [ ] Test empty query returns 422 or empty results (decide behaviour)
- [ ] Test query with no matches returns empty results (not 404)
- [ ] Test `schedule` filter on `/search/lines` correctly narrows results
- [ ] Test `ts_rank` ordering: higher-relevance matches appear first
- [ ] Test pagination (`offset`, `limit`) on all list endpoints
- [ ] Test special characters in query don't cause errors (`plainto_tsquery` sanitises input)

## Documentation Updates

- [ ] Update `CLAUDE.md` "API" section to mention the `/search` endpoints
- [ ] Update `CLAUDE.md` "Project structure" to mention the new route file
- [ ] Update `docs/architecture.md` with the FTS design decision (choice of PostgreSQL FTS over external search services)

## Success Criteria

- All search endpoints return results ranked by `ts_rank`
- Year filtering correctly applies version boundaries from `valid_from_year` / `valid_to_year`
- GIN indexes are confirmed used in `EXPLAIN ANALYZE` output (no sequential scans)
- Special characters and multi-word queries handled safely by `plainto_tsquery`
- All tests pass
- API docs at `/docs` describe the new endpoints with parameter descriptions

## Open Questions

1. **Which tables are in scope?** Is searching `fir_instruction_changelog` useful to front-end users, or is it primarily an admin/internal table? It may add noise to unified search results.

2. **Default year behaviour:** when `year` is omitted, default to the latest FIR year with data, or show results across all years (with duplicates)? Defaulting to the latest year seems safest for UX but may surprise users looking for historical data.

3. **Unified vs. per-type endpoints:** is the `GET /search` unified endpoint needed, or will front-end code always call the per-type endpoints (`/search/lines`, `/search/schedules`)? The unified endpoint is convenient for a global search box but more complex to implement and test.

4. **`ts_headline` excerpts:** should the API return a short highlighted snippet of matched text in each result? `ts_headline()` generates this automatically in PostgreSQL, but adds some query overhead. Worth it for UX, or leave excerpting to the front end?

5. **Weighted fields:** PostgreSQL tsvector supports field weighting (A–D) to boost matches in more important fields (e.g., `line_name` > `description`). Worth adding, or start without weights?

6. **Municipality search scope:** should municipality search be part of the unified `/search` endpoint, or kept separate since it has no year dimension and is a different kind of lookup?

7. **Result limit and pagination strategy:** what are the appropriate `limit` defaults and maximums for search results? Unlike list endpoints, users typically want only the top 10–20 results — consider a lower default limit than the standard list endpoints.

8. **SQLModel model changes:** how to handle the `search_vector` column in SQLModel? Options are (a) include it as a non-nullable `Any` field excluded from API responses, (b) use raw SQL for search queries and keep models unchanged, or (c) use SQLAlchemy `Column(TSVECTOR)` directly. This affects how clean the model and query code look.

9. **Authentication:** should search endpoints require authentication (matching Task 04a) or be public? FIR instruction metadata is public information, so unauthenticated access seems reasonable.
