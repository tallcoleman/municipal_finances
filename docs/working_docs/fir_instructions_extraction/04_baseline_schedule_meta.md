# Task 04: Extract FIR2025 Baseline — Schedule Metadata (Phase 1a)

## Goal

Extract schedule-level metadata from the FIR2025 Instructions PDF and populate `fir_schedule_meta` for all 26 schedules. This is the first part of the Phase 1 baseline extraction.

## Task List

- [ ] Read the schedule list and categories from FIR2025 PDF (~pages 5–6)
- [ ] For each schedule, read its instruction section's opening paragraph to extract the general description
- [ ] Create `fir_schedule_meta` rows for all 26 schedules
- [ ] Set `valid_from_year = NULL` and `valid_to_year = NULL` on all rows (baseline = "always current")
- [ ] Write insertion logic
- [ ] Export to CSV
- [ ] Verify against PDF

## Implementation Details

### The 26 Schedules to Extract

| Category | Schedules |
|---|---|
| Revenue | 10, 12 |
| Taxation | 20, 22, 22A, 22B, 22C, 24, 26, 28, 72 |
| Expense | 40, 42 |
| Tangible Capital Assets | 51A, 51B |
| Net Financial Assets / Net Debt | 53 |
| Cash Flow | 54 |
| Reserves & Reserve Funds | 60, 61A, 61B, 62 |
| Financial Position | 70 |
| Remeasurement Gains & Losses | 71 |
| Long Term Liabilities | 74, 74E |
| Other Information | 76, 77, 80, 81, 83 |

### Fields to Extract Per Schedule

- `schedule_id`: From the schedule number (e.g., `"10"`, `"51A"`)
- `schedule_name`: Full title (e.g., `"Consolidated Statement of Operations: Revenue"`)
- `category`: From the table above
- `description`: The general purpose paragraph from the schedule's instruction section
- `valid_from_year`: NULL (baseline)
- `valid_to_year`: NULL (baseline)
- `change_notes`: NULL (baseline, no changes to note)

### Extraction Approach

1. Pages 5–6 of FIR2025 contain a table of contents / schedule listing with names and categories
2. Each schedule's instruction section begins with a general description paragraph
3. Extract both in a single pass through the PDF, section by section

### Storage

Use the same insertion pattern as Task 03. Create an `insert_schedule_meta` function or reuse a generic insertion function.

## Tests

- [ ] Test insertion of schedule metadata records
- [ ] Test that all 26 schedules are present after insertion
- [ ] Test idempotent insertion (re-inserting same data doesn't create duplicates)
- [ ] Test that `schedule_id` values match the known schedule list
- [ ] Test that no required fields are NULL (schedule_id, schedule_name, category)

## Documentation Updates

- [ ] None expected (no new CLI commands)

## Success Criteria

- `fir_schedule_meta` contains exactly 26 rows (one per schedule)
- Every row has a non-empty `schedule_name`, `category`, and `description`
- `schedule_id` values match the known set for 2025
- `valid_from_year` and `valid_to_year` are both NULL on all baseline rows
- Spot-check 5 schedule descriptions against the PDF for accuracy

## Verification

```sql
-- Should return 26
SELECT count(*) FROM fir_schedule_meta;

-- All categories should match expected set
SELECT DISTINCT category FROM fir_schedule_meta ORDER BY category;

-- No empty names or descriptions
SELECT * FROM fir_schedule_meta WHERE schedule_name IS NULL OR schedule_name = '' OR description IS NULL OR description = '';
```

## Questions

1. Some schedules have sub-schedules (e.g., 22A, 22B, 22C are sub-schedules of 22). Should the `description` for sub-schedules reference the parent schedule's description, or be fully standalone?
2. The category assignments in the plan — are these exactly as labeled in the PDF, or are they our own grouping? If the PDF uses different category names, which should we use?
3. Should the `description` be the first paragraph only, or the entire general information section for the schedule? Some schedules have multi-paragraph introductions. Recommend: include the full general information section, not just the first paragraph.
