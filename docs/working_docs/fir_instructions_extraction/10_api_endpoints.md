# Task 10: API Endpoints for Instruction Metadata

## Goal

Expose the instruction metadata tables via the FastAPI API so users can query schedule, line, and column metadata alongside FIR record data.

## Prerequisites

- Task 01 (database models) complete
- Task 02 (SLC parsing) complete
- Some data in metadata tables for testing

## Task List

- [ ] Create `src/municipal_finances/api/routes/fir_instructions.py` with new endpoints
- [ ] Register the new router in `api/main.py`
- [ ] Write tests
- [ ] Update documentation

## Implementation Details

### Endpoints

**Schedule metadata:**
- `GET /instructions/schedules/` — List all schedules, optionally filtered by year
  - Query params: `year` (int, optional — filters to schedules valid in that year), `category` (str, optional), `offset`, `limit`
- `GET /instructions/schedules/{schedule}` — Get a specific schedule's metadata
  - Query params: `year` (int, optional — returns the version valid in that year)

**Line metadata:**
- `GET /instructions/lines/` — List lines, filtered by schedule and/or year
  - Query params: `schedule` (required), `year` (int, optional), `section` (str, optional), `offset`, `limit`
- `GET /instructions/lines/{schedule}/{line_id}` — Get a specific line's metadata
  - Query params: `year` (int, optional)

**Column metadata:**
- `GET /instructions/columns/` — List columns for a schedule
  - Query params: `schedule` (required), `year` (int, optional), `offset`, `limit`
- `GET /instructions/columns/{schedule}/{column_id}` — Get a specific column's metadata
  - Query params: `year` (int, optional)

**Changelog:**
- `GET /instructions/changelog/` — List changelog entries
  - Query params: `year` (int, optional), `schedule` (str, optional), `source` (str, optional), `change_type` (str, optional), `offset`, `limit`

**Enriched record lookup:**
- `GET /instructions/lookup/` — Given an SLC string and year, return the matching schedule, line, and column metadata
  - Query params: `slc` (str, required — database format), `year` (int, required)
  - Returns combined metadata from all three tables

### Year Filtering Logic

When `year` is provided, filter with the versioning query:
```python
query = query.where(
    (model.valid_from_year.is_(None) | (model.valid_from_year <= year)),
    (model.valid_to_year.is_(None) | (model.valid_to_year >= year))
)
```

### Lookup Endpoint

The `/instructions/lookup/` endpoint is the primary integration point. It:
1. Parses the SLC string using `parse_slc()` from Task 02
2. Queries `fir_schedule_meta`, `fir_line_meta`, and `fir_column_meta` for the matching year
3. Returns a combined response

```python
@router.get("/instructions/lookup/")
def lookup_instruction(slc: str, year: int, session: Session = Depends(get_session)):
    parsed = parse_slc(slc)
    schedule = get_schedule_for_year(session, parsed["schedule"], year)
    line = get_line_for_year(session, parsed["schedule"], parsed["line_id"], year)
    column = get_column_for_year(session, parsed["schedule"], parsed["column_id"], year)
    return {"schedule": schedule, "line": line, "column": column}
```

### Router Registration

In `api/main.py`:
```python
from municipal_finances.api.routes.fir_instructions import router as instructions_router
app.include_router(instructions_router)
```

## Tests

Follow the pattern in `test_api.py`:

- [ ] Add `seed_schedule_meta()`, `seed_line_meta()`, `seed_column_meta()`, `seed_changelog_entry()` helpers
- [ ] Test `GET /instructions/schedules/` returns all schedules
- [ ] Test `GET /instructions/schedules/` with `year` filter returns only valid schedules
- [ ] Test `GET /instructions/schedules/{schedule}` returns correct schedule
- [ ] Test `GET /instructions/schedules/{schedule}` with invalid schedule returns 404
- [ ] Test `GET /instructions/lines/` requires `schedule`
- [ ] Test `GET /instructions/lines/` with year filtering
- [ ] Test `GET /instructions/lines/{schedule}/{line_id}` returns correct line
- [ ] Test `GET /instructions/columns/` with schedule filter
- [ ] Test `GET /instructions/changelog/` with various filters
- [ ] Test `GET /instructions/lookup/` with valid SLC and year
- [ ] Test `GET /instructions/lookup/` with invalid SLC returns 422
- [ ] Test `GET /instructions/lookup/` where no metadata exists returns appropriate response
- [ ] Test pagination (offset/limit) on list endpoints

## Documentation Updates

- [ ] Update `CLAUDE.md` "API" section to mention new endpoints
- [ ] Update `CLAUDE.md` "Project structure" to mention new route file
- [ ] Update `docs/architecture.md` if API design decisions are documented there

## Success Criteria

- All endpoints return correct data with proper year filtering
- `/instructions/lookup/` correctly parses SLC and returns combined metadata
- Pagination works consistently across all list endpoints
- 404 responses for missing resources, 422 for invalid input
- All tests pass with 100% coverage on new code
- API docs at `/docs` show the new endpoints with proper descriptions

## Questions

1. Should the lookup endpoint return 404 if any of the three metadata types is missing for the given SLC/year, or should it return partial results (with nulls for missing parts)?
2. Should there be an endpoint that enriches `firrecord` results with instruction metadata inline? E.g., `GET /records/?include_instructions=true`. This would be convenient but could be expensive. Alternative: let the client make a separate lookup call.
3. Should the changelog endpoint support filtering by `severity`?
4. Rate limiting considerations — the lookup endpoint could be called frequently. Any caching strategy needed?
