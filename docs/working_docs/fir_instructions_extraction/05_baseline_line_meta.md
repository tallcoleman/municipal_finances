# Task 05: Extract FIR2025 Baseline — Line Metadata (Phase 1b)

## Goal

Extract line-level metadata for all schedules from the FIR2025 Instructions PDF. This is the largest extraction task, covering both the Functional Classifications attachment and the schedule-by-schedule instruction sections.

## Prerequisites

- Task 01 (database models) complete
- Task 02 (SLC parsing) complete
- Task 04 (schedule metadata) complete — need `fir_schedule_meta` rows (for the `schedule_id` FK and `schedule` text values), and the PDF-to-text conversion and offset maps from Task 04's prerequisite step must already exist (`fir_instructions/source_files/FIR2025 Instructions.txt` and `FIR2025 Instructions.offsets.json`)

## Task List

- [ ] Extract Functional Classifications from `FIR2025 Instructions.txt` using the offset map (section between Introduction and Schedule 02)
  - [ ] Schedule 12 lines (Grants/User Fees)
  - [ ] Schedule 40 lines (Expenses)
  - [ ] Schedule 51 lines (Tangible Capital Assets)
- [ ] Extract line descriptions from each schedule's instruction section (~26 schedules)
  - [ ] Revenue schedules: 10, 12
  - [ ] Taxation schedules: 20, 22, 22A, 22B, 22C, 24, 26, 28, 72
  - [ ] Expense schedules: 40, 42
  - [ ] TCA schedules: 51A, 51B
  - [ ] Other schedules: 53, 54, 60, 61A, 61B, 62, 70, 71, 74, 74E, 76, 77, 80, 81, 83
- [ ] Merge Functional Classifications data with schedule instruction data for overlapping schedules (12, 40, 51)
- [ ] Set all rows to `valid_from_year = NULL`, `valid_to_year = NULL`
- [ ] Export to CSV
- [ ] Verify against PDF

## Implementation Details

### Two Data Sources per Line

Lines in Schedules 12, 40, and 51 have data from two places in the PDF:

1. **Functional Classifications attachment** (pages 43–93): provides `includes` and `excludes` lists organized by service area sections
2. **Schedule instruction section**: provides `description`, `carry_forward_from`, `applicability`, `is_subtotal`, `is_auto_calculated`

These need to be merged into a single `fir_line_meta` row per line.

### Fields to Extract Per Line

| Field | Source |
|---|---|
| `schedule_id` | Serial FK to `fir_schedule_meta.id` |
| `schedule` | Text identifier (e.g., `"10"`, `"51A"`) — denormalized from schedule context |
| `line_id` | 4-character alphanumeric code from the PDF (e.g., `"0410"`; `"000A"` on schedules 76X, 80C, 81X) |
| `line_name` | Heading text (e.g., `"Fire"`) |
| `section` | Section heading within the schedule (e.g., `"Protection Services"`) |
| `description` | Narrative text from schedule instructions |
| `includes` | From Functional Classifications or schedule instructions. Format as newline-separated plain text (one item per line). |
| `excludes` | From Functional Classifications or schedule instructions. Format as newline-separated plain text (one item per line). |
| `is_subtotal` | Whether this is a computed subtotal row (infer from context: words like "Subtotal", "Total", or lines that sum other lines) |
| `is_auto_calculated` | Whether auto-populated from another schedule (infer from "carried forward from" language) |
| `carry_forward_from` | SLC reference if auto-populated (e.g., `"12 9910 05"`) |
| `applicability` | Restrictions like "Upper-tier only", "City of Toronto only" |
| `valid_from_year` | NULL (baseline) |
| `valid_to_year` | NULL (baseline) |
| `change_notes` | NULL (baseline) |

### Extraction Strategy

Given the volume (~26 schedules, potentially hundreds of lines each), work in two passes through `FIR2025 Instructions.txt` using the offset map from Task 04:

1. **Functional Classifications first**: The Functional Classifications section sits between the Introduction and Schedule 02 in the text file. Use the offset map to locate this region (it will not have a schedule-number key — find it as the text between the end of the Introduction and the first schedule offset). Extract all includes/excludes for Schedules 12, 40, 51. Store in a temporary structure keyed by (schedule, line_id). Note: the Functional Classifications may reference "Schedule 51" generically rather than distinguishing 51A from 51B. When this occurs, assign the includes/excludes to all applicable sub-schedules and note the ambiguity in `change_notes`.
2. **Schedule-by-schedule**: For each schedule, use its line offset from the offset map to seek directly to that section. Read forward to the next schedule's offset (or EOF). Within that slice, extract line descriptions, subtotal flags, carry-forward references, and applicability notes.
3. **Merge**: For Schedules 12, 40, 51 — combine the Functional Classifications data with the schedule instruction data. Where a line appears in both sources with different descriptions, use the schedule instruction text for the `description` field and Functional Classifications data only for `includes`/`excludes`.

### Handling Section Boundaries

Lines within a schedule are grouped into sections (e.g., "General Government", "Protection Services"). The `section` field captures which group a line belongs to. Pay attention to section headings in the PDF — they are usually bolded or underlined. The first and last lines of each section are particularly important to get right (audit plan section boundary check).

### Identifying Subtotals and Auto-Calculated Lines

- **Subtotals**: Lines named "Subtotal", "Total", or that reference "sum of lines above". Set `is_subtotal = True`.
- **9910-style lines**: Lines with a `line_id` ending in `9910` (and similar pattern lines that represent schedule-level totals) should also be marked `is_subtotal = True`, even if not explicitly labelled as subtotals in the PDF. Add a note in `change_notes` that their subtotal status was inferred from the line_id pattern.
- **Auto-calculated**: Lines described as "carried forward from SLC X Y Z" or "auto-populated". Set `is_auto_calculated = True` and populate `carry_forward_from`.

### Expected Volume

Rough estimates per schedule category:
- Revenue/Expense schedules (10, 12, 40): 50–100+ lines each (largest)
- Taxation schedules: 10–30 lines each
- Other schedules: 5–30 lines each

Total: likely 500–1000+ line metadata rows.

### Data File Approach

Even with the pre-converted text files, extraction logic involves parsing heuristics that may need manual correction. Save the extracted data as a CSV at `fir_instructions/exports/baseline_line_meta.csv`. This allows re-loading without re-parsing and serves as the human-editable source of truth before DB insertion.

## Tests

- [ ] Test insertion of line metadata records
- [ ] Test that every schedule in `fir_schedule_meta` has at least one line in `fir_line_meta`
- [ ] Test `line_id` format validation (4-character alphanumeric: digits for most schedules, alphanumeric for 76X, 80C, 81X)
- [ ] Test that `is_subtotal` and `is_auto_calculated` default to False
- [ ] Test that `carry_forward_from` is populated only when `is_auto_calculated` is True
- [ ] Test idempotent insertion

## Documentation Updates

- [ ] None expected (no new CLI commands)

## Success Criteria

- Every schedule has line metadata entries
- `line_id` values are valid 4-character alphanumeric strings
- Schedules 12, 40, 51 have `includes`/`excludes` populated from Functional Classifications
- Subtotal and auto-calculated lines are correctly flagged
- `carry_forward_from` references use the PDF SLC format
- Section assignments are correct at section boundaries
- Spot-check 10 lines per schedule category against the PDF

## Verification

```sql
-- Lines per schedule
SELECT schedule, count(*) FROM fir_line_meta GROUP BY schedule ORDER BY schedule;

-- Schedules with no lines (should be empty)
SELECT sm.schedule FROM fir_schedule_meta sm
LEFT JOIN fir_line_meta lm ON sm.schedule = lm.schedule
WHERE lm.id IS NULL;

-- Subtotal and auto-calculated counts
SELECT schedule,
    count(*) FILTER (WHERE is_subtotal) as subtotals,
    count(*) FILTER (WHERE is_auto_calculated) as auto_calc
FROM fir_line_meta GROUP BY schedule ORDER BY schedule;

-- Lines with carry_forward_from but not flagged as auto_calculated (should be empty)
SELECT * FROM fir_line_meta WHERE carry_forward_from IS NOT NULL AND NOT is_auto_calculated;

-- Functional Classifications coverage
SELECT schedule,
    count(*) FILTER (WHERE includes IS NOT NULL) as has_includes,
    count(*) FILTER (WHERE excludes IS NOT NULL) as has_excludes
FROM fir_line_meta WHERE schedule IN ('12', '40', '51A', '51B')
GROUP BY schedule;
```
