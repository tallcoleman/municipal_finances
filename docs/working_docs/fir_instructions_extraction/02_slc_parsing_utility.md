# Task 02: SLC Parsing Utility

## Goal

Create a utility module for parsing the `slc` field from `firrecord` into its component parts (schedule, line, column), and for converting between the database format and the PDF reference format. This utility is foundational — it's needed by the API join logic, the data inference step, and the audit checks.

## Task List

- [ ] Create `src/municipal_finances/slc.py` with parsing functions
- [ ] Write comprehensive tests
- [ ] Verify against real SLC values in the database (if accessible) or against known examples

## Implementation Details

### Functions to Implement

```python
def parse_slc(slc: str) -> dict:
    """Parse a database SLC string into components.

    Input format: 'slc.{schedule_code}.L{line_4digits}.C{column_2digits}.{sub}'
    Example: 'slc.10.L9930.C01.' -> {'schedule': '10', 'line_id': '9930', 'column_id': '01', 'sub': ''}

    Returns dict with keys: schedule, line_id, column_id, sub
    (schedule maps to fir_schedule_meta.schedule, not the serial schedule_id FK)
    Raises ValueError if format doesn't match.
    """

def slc_to_pdf_format(schedule: str, line_id: str, column_id: str) -> str:
    """Convert components to PDF reference format.

    Example: ('10', '9930', '01') -> 'SLC 10 9930 01'
    """

def pdf_slc_to_components(pdf_slc: str) -> dict:
    """Parse a PDF-format SLC reference into components.

    Input format: 'SLC 10 9930 01' or '10 9930 01' (with or without 'SLC' prefix)
    Also handles wildcard patterns like '40 xxxx 05'.

    Returns dict with keys: schedule, line_id, column_id
    (schedule maps to fir_schedule_meta.schedule, not the serial schedule_id FK)
    Values may be None if wildcarded (e.g., 'xxxx').
    """
```

### Edge Cases to Handle

- Schedule codes with letters: `"51A"`, `"51B"`, `"22A"`, `"74E"`
- SLC strings with empty `sub` field (trailing dot): `"slc.10.L9930.C01."`
- SLC strings with non-empty `sub` field (if any exist in the data)
- PDF SLC patterns with wildcards: `"40 xxxx 05"` means "all lines in Schedule 40, Column 05"
- Malformed inputs should raise `ValueError` with a clear message

### Regex Pattern

The database SLC format can be parsed with:
```python
import re
SLC_PATTERN = re.compile(r'^slc\.([^.]+)\.L(\d{4})\.C(\d{2})\.(.*)$')
```

## Tests

- [ ] Test `parse_slc` with standard SLC: `"slc.10.L9930.C01."`
- [ ] Test `parse_slc` with lettered schedule: `"slc.51A.L0410.C01."`
- [ ] Test `parse_slc` with non-empty sub field (if applicable)
- [ ] Test `parse_slc` raises ValueError on malformed input
- [ ] Test `slc_to_pdf_format` produces correct output
- [ ] Test `pdf_slc_to_components` with standard format
- [ ] Test `pdf_slc_to_components` with wildcard patterns
- [ ] Test `pdf_slc_to_components` with and without "SLC" prefix
- [ ] Test round-trip: parse_slc -> slc_to_pdf_format -> pdf_slc_to_components produces consistent results

## Documentation Updates

- [ ] Update `CLAUDE.md` "Project structure" to mention `slc.py`

## Success Criteria

- All parsing functions handle the known SLC formats correctly
- Edge cases (lettered schedules, wildcards, malformed input) are covered
- All tests pass with 100% coverage on the new module

## Questions

1. Are there SLC values in the database with a non-empty `sub` field? If so, what values does it take? This affects the parser. Verify by querying: `SELECT DISTINCT substring(slc from '[^.]+$') FROM firrecord WHERE slc IS NOT NULL LIMIT 100;`
2. Are there SLC formats beyond the documented pattern? Verify by querying: `SELECT slc FROM firrecord WHERE slc NOT LIKE 'slc.%.L%.C%.%' LIMIT 10;`
3. Should the parser be strict (reject anything not matching the pattern) or lenient (best-effort extraction)? Recommend strict with clear error messages, since bad SLC values indicate data issues that should be surfaced.
