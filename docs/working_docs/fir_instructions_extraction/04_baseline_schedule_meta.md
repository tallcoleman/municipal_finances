# Task 04: Extract FIR2025 Baseline — Schedule Metadata (Phase 1a)

## Goal

Extract schedule-level metadata from the FIR2025 Instructions PDF and populate `fir_schedule_meta` for all 26 schedules. This is the first part of the Phase 1 baseline extraction.

## Task List

- [ ] Pre-convert all source PDFs to text (see Prerequisite below)
- [ ] Build page-offset maps for all source PDFs (see Prerequisite below)
- [ ] Check that category assignments in the plan match the categories used in the PDFs; if differences exist, note them and suggest a normalization approach
- [ ] For each schedule, locate and extract the entire General Instructions section using the text file + offset map
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

- `schedule`: From the schedule number (e.g., `"10"`, `"51A"`)
- `schedule_name`: Full title (e.g., `"Consolidated Statement of Operations: Revenue"`)
- `category`: From the table above
- `description`: The entire general information section for the schedule (not just the first paragraph). For sub-schedules (e.g., 22A, 22B, 22C), the description should also reference the parent schedule's purpose and shared context.
- `valid_from_year`: NULL (baseline)
- `valid_to_year`: NULL (baseline)
- `change_notes`: NULL (baseline, no changes to note)

### Prerequisite: PDF Text Extraction and Page-Offset Maps

Each source PDF in `fir_instructions/source_files/` must be converted to a plain-text file before extraction begins. This is done once and the output is reused by Tasks 04, 05, and 06.

**Convert all PDFs to text:**
```bash
for f in fir_instructions/source_files/*.pdf; do
    pdftotext -layout "$f" "${f%.pdf}.txt"
done
```

This produces one `.txt` file alongside each `.pdf` (e.g. `FIR2025 Instructions.txt`).

**Build page-offset maps:**

Each text file has a predictable structure of concatenated documents with independent internal page numbering. A page-offset map records, for each schedule, the character offset (or line number) in the `.txt` file where its section begins. Build this by searching for cover-page markers:

```python
import re

def build_schedule_offsets(txt_path: str) -> dict[str, int]:
    """Return {schedule_label: line_number} for each schedule cover page found."""
    offsets = {}
    with open(txt_path) as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        m = re.search(r'Schedule\s+(\d+[A-Z]?)\s*$', line.strip())
        if m:
            offsets[m.group(1)] = i
    return offsets
```

Save the offset maps alongside the text files as `FIR2025 Instructions.offsets.json` (and equivalents for other years). This allows any task to jump directly to a schedule's section without re-scanning.

**Files produced (one set per source PDF year):**
- `fir_instructions/source_files/FIR20XX Instructions.txt`
- `fir_instructions/source_files/FIR20XX Instructions.offsets.json`

Source PDFs available: 2019, 2020, 2021, 2022, 2023, 2024, 2025.

### Extraction Approach

1. Open `FIR2025 Instructions.txt` and load `FIR2025 Instructions.offsets.json`
2. For each of the 26 schedules, seek to the offset for that schedule and read forward until the next schedule's offset (or a fixed lookahead)
3. Within that slice, extract the text between `General Instructions` and the next major section heading — this is the `description` field
4. The schedule name is on the cover page (2–3 lines after the schedule number)
5. Spot-check 5 schedule descriptions against the original PDF for accuracy

### Storage

Use the same insertion pattern as Task 03. Create an `insert_schedule_meta` function or reuse a generic insertion function.

The `.txt` and `.offsets.json` files produced by the prerequisite step are shared artifacts — do not regenerate them per-task. They are committed to version control in `fir_instructions/source_files/` (small enough to track; avoids requiring `pdftotext` on every machine).

### Data File Approach

Since PDF extraction is expensive and non-deterministic, the extracted data should also be saved as a CSV file at `fir_instructions/exports/baseline_schedule_meta.csv` as part of this task. This allows re-loading without re-extraction as well as human verification and editing to make corrections.

## Tests

**Prerequisite: PDF text conversion and offset maps**
- [ ] Test that `pdftotext` produces a non-empty `.txt` file for each of the 7 source PDFs
- [ ] Test that `build_schedule_offsets` returns all 26 expected schedule keys for FIR2025 (no missing, no unexpected extras)
- [ ] Test that spot-checked offsets (Schedules 10, 40, 74) point to lines containing the expected schedule cover text

**Schedule metadata insertion**
- [ ] Test insertion of schedule metadata records
- [ ] Test that all 26 schedules are present after insertion
- [ ] Test idempotent insertion (re-inserting same data doesn't create duplicates)
- [ ] Test that `schedule` values match the known schedule list
- [ ] Test that no required fields are NULL (schedule, schedule_name, category)

## Documentation Updates

- [ ] None expected (no new CLI commands)

## Success Criteria

- `fir_schedule_meta` contains exactly 26 rows (one per schedule)
- Every row has a non-empty `schedule_name`, `category`, and `description`
- `schedule` values match the known set for 2025
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
