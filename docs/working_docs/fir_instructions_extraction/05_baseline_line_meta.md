# Task 05: Extract FIR2025 Baseline — Line Metadata (Phase 1b)

## Goal

Extract line-level metadata for all schedules from the FIR2025 Instructions PDF. This is the largest extraction task, covering both the Functional Classifications attachment and the schedule-by-schedule instruction sections.

## Prerequisites

- Task 01 (database models) complete
- Task 02 (SLC parsing) complete
- Task 04 (schedule metadata) complete — need `fir_schedule_meta` rows (for the `schedule_id` FK and `schedule` text values)

## Task List

- [ ] Extract Functional Classifications from FIR2025 PDF (~pages 43–93)
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
| `line_id` | 4-digit code from the PDF (e.g., `"0410"`) |
| `line_name` | Heading text (e.g., `"Fire"`) |
| `section` | Section heading within the schedule (e.g., `"Protection Services"`) |
| `description` | Narrative text from schedule instructions |
| `includes` | From Functional Classifications or schedule instructions |
| `excludes` | From Functional Classifications or schedule instructions |
| `is_subtotal` | Whether this is a computed subtotal row (infer from context: words like "Subtotal", "Total", or lines that sum other lines) |
| `is_auto_calculated` | Whether auto-populated from another schedule (infer from "carried forward from" language) |
| `carry_forward_from` | SLC reference if auto-populated (e.g., `"12 9910 05"`) |
| `applicability` | Restrictions like "Upper-tier only", "City of Toronto only" |
| `valid_from_year` | NULL (baseline) |
| `valid_to_year` | NULL (baseline) |
| `change_notes` | NULL (baseline) |

### Extraction Strategy

Given the volume (~26 schedules, potentially hundreds of lines each), work through the PDF in batches:

1. **Functional Classifications first** (pages 43–93): Extract all includes/excludes for Schedules 12, 40, 51. Store in a temporary structure keyed by (schedule, line_id).
2. **Schedule-by-schedule**: For each schedule's instruction section, extract line descriptions, subtotal flags, carry-forward references, and applicability notes.
3. **Merge**: For Schedules 12, 40, 51 — combine the Functional Classifications data with the schedule instruction data.

### Handling Section Boundaries

Lines within a schedule are grouped into sections (e.g., "General Government", "Protection Services"). The `section` field captures which group a line belongs to. Pay attention to section headings in the PDF — they are usually bolded or underlined. The first and last lines of each section are particularly important to get right (audit plan section boundary check).

### Identifying Subtotals and Auto-Calculated Lines

- **Subtotals**: Lines named "Subtotal", "Total", or that reference "sum of lines above". Set `is_subtotal = True`.
- **Auto-calculated**: Lines described as "carried forward from SLC X Y Z" or "auto-populated". Set `is_auto_calculated = True` and populate `carry_forward_from`.

### Expected Volume

Rough estimates per schedule category:
- Revenue/Expense schedules (10, 12, 40): 50–100+ lines each (largest)
- Taxation schedules: 10–30 lines each
- Other schedules: 5–30 lines each

Total: likely 500–1000+ line metadata rows.

## Tests

- [ ] Test insertion of line metadata records
- [ ] Test that every schedule in `fir_schedule_meta` has at least one line in `fir_line_meta`
- [ ] Test `line_id` format validation (4-digit string)
- [ ] Test that `is_subtotal` and `is_auto_calculated` default to False
- [ ] Test that `carry_forward_from` is populated only when `is_auto_calculated` is True
- [ ] Test idempotent insertion

## Documentation Updates

- [ ] None expected (no new CLI commands)

## Success Criteria

- Every schedule has line metadata entries
- `line_id` values are valid 4-digit strings
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

## Questions

1. How should `includes` and `excludes` be formatted? The Functional Classifications lists items as bullet points. Options: (a) newline-separated plain text, (b) semicolon-separated, (c) JSON array. Recommend: newline-separated plain text for CSV compatibility and human readability.
2. For schedules with sub-schedules (e.g., 51A, 51B), the Functional Classifications might reference "Schedule 51" generically. How should the `includes`/`excludes` be assigned — to both 51A and 51B, or only to the matching sub-schedule?
3. Some lines appear in both the Functional Classifications and the schedule instructions with slightly different descriptions. Which takes precedence? Recommend: use the schedule instruction `description` field for the narrative, and Functional Classifications only for `includes`/`excludes`.
4. This task is the largest single extraction effort. Should it be split further — e.g., by schedule category — to make review more manageable? The risk is that section/format patterns established early save time later.
5. Lines that are "9910"-style (typically totals like "Total Revenue") — should these be marked `is_subtotal = True` even if the PDF doesn't explicitly call them subtotals?
