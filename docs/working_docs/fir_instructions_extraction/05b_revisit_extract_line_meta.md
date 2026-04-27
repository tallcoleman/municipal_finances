# Task 05b: Revisit extract_line_meta.py for Cleaned Markdown Files

## Goal

Update `extract_line_meta.py` to use the cleaned markdown files in
`fir_instructions/source_files/2025/markdown_clean/` (instead of `markdown/`),
simplify the 74D double-heading workaround that is no longer needed, and add
support for the new S80 paired-line heading format introduced by the cleaning.

## Prerequisite

Task 05 complete — the extraction module and its test suite must already exist.

## Background

The FIR2025 instruction PDFs were converted to markdown twice:

- `markdown/` — original conversion; heading levels were inconsistent in places
- `markdown_clean/` — corrected version with verified heading hierarchies

`extract_schedule_meta.py` was already updated to use `markdown_clean/` as part of Task 04 revisit work. This task brings `extract_line_meta.py` in line.

### What changed in the cleaned files relevant to line extraction

| File | Original issue | Cleaned state |
|---|---|---|
| `FIR2025 S74.md` | Two `## **Schedule 74D**` headings (one in shared intro, one in content) | Exactly one `## **Schedule 74D**` heading |
| `FIR2025 S80.md` | (not affected; was already used as-is) | New `#### **Line X and Y - Name**` paired-heading format added by cleaning |

All other workarounds in the original code remain necessary:
- `_LINE_RANGE_SINGULAR_RE` — S60 still uses `Line 0895 to Line 0898 - Other`
- `_extract_inline_lines` — S53, S54, S60 still have inline `**Line XXXX**` patterns in body text
- Space-only separator in `_LINE_HEADING_RE` — still present in some schedules

## Changes Made

### 1. Updated default markdown directory

`_DEFAULT_MARKDOWN_DIR` changed from `markdown/` to `markdown_clean/`. The
module docstring usage example updated to match.

**File:** `src/municipal_finances/fir_instructions/extract_line_meta.py`

### 2. Removed the 74D double-heading workaround

The `_get_schedule_sections` special case for `code == "74D"` previously skipped
the first occurrence of `## **Schedule 74D**` and used the second, falling back
to the first if only one existed. With the cleaned file having exactly one
heading, the logic simplifies to the same pattern used for 74E.

**Before:**
```python
first = _find_section(sections, "Schedule 74D", exact=True)
if first is None:
    return []
idx = _find_section(sections, "Schedule 74D", exact=True, start=first + 1)
if idx is None:
    idx = first
end_idx = _find_section(sections, "Schedule 74E", exact=True)
return sections[idx:end_idx] if end_idx is not None else sections[idx:]
```

**After:**
```python
idx = _find_section(sections, "Schedule 74D", exact=True)
if idx is None:
    return []
end_idx = _find_section(sections, "Schedule 74E", exact=True)
return sections[idx:end_idx] if end_idx is not None else sections[idx:]
```

### 3. Added `_LINE_PAIRED_RE` and `_parse_paired_line_heading`

The cleaned `FIR2025 S80.md` uses a new heading format for lines that appear in
both the municipality section (0200-series) and the joint local board section
(0300-series):

```
#### **Line 0205 and 0305 - Administration**
#### **Line 0228 and 0328 Ambulance - Uniform**   ← space-only separator
```

26 headings follow this pattern. Without a specific handler, `_LINE_RANGE_RE`
would match `Line 0205 and 0305` and generate 101 records (0205 through 0305).

The fix adds:
- `_LINE_PAIRED_RE` — matches `Line? X and Y` with dash or space-only separator before the name
- `_parse_paired_line_heading(heading)` — returns `(id1, id2, name)` or `None`
- A `paired_parsed` branch in `_extract_per_schedule_lines` (checked before `range_parsed`)
  that emits two individual records sharing the same description, each with a
  `"Part of paired group Lines {id1} and {id2} — {name}."` note prepended.

### 4. Updated tests

- Removed `test_74d_two_headings_uses_second` (the workaround test).
- Renamed `test_74d_single_heading_uses_fallback` → `test_74d_single_heading`.
- Added `_parse_paired_line_heading` to imports.
- Added `TestPairedLineHeadings` class covering:
  - Dash-separated paired heading
  - Space-only-separated paired heading
  - Non-match for single-line and range headings
  - Two records emitted per paired heading stub
  - Both records share the same `line_name` and `description`

## Verification

```bash
# All tests pass
uv run pytest tests/fir_instructions/test_extract_line_meta.py -v

# S80 produces 52 paired-group rows (26 paired headings × 2 records)
uv run python -c "
from pathlib import Path
from municipal_finances.fir_instructions.extract_line_meta import _extract_per_schedule_lines
rows = _extract_per_schedule_lines(Path('fir_instructions/source_files/2025/markdown_clean'), '80')
print('S80 total:', len(rows))
print('Paired:', sum(1 for r in rows if 'paired group' in (r['description'] or '')))
"

# 74D finds sections correctly (first heading is 'Schedule 74D')
uv run python -c "
from pathlib import Path
from municipal_finances.fir_instructions.extract_line_meta import _get_schedule_sections
secs = _get_schedule_sections(Path('fir_instructions/source_files/2025/markdown_clean'), '74D')
print('74D sections:', len(secs))
print([s[0] for s in secs[:3]])
"
```

### Observed output

- `S80 total: 166`, `Paired: 52` (26 paired headings × 2 records)
- `74D sections: 14`, first heading `Schedule 74D`
