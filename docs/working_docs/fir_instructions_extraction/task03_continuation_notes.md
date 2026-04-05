# Task 03 Continuation Notes

**Status as of 2026-04-04**: Extraction module created and partially tested. FIR2023 has a row-grouping bug that needs fixing before running the full extraction.

---

## What's Done

- Created `src/municipal_finances/fir_instructions/extract_changelog.py` with all core functions.
- Tested FIR2025 (8 entries ✓), FIR2024 (11 entries ✓), FIR2020 (31), FIR2021 (34), FIR2022 (64), FIR2019 (6).
- FIR2025 and FIR2024 look correct. Others need verification.

## Root Cause of FIR2023 Problem

The FIR2023 PDF has tightly packed rows — the bottom of one row overlaps the top of the next by only ~2-3 pts:

```
'71'  top=91.7  bottom=97.1
'74E' top=99.8  bottom=105.2   ← gap = 99.8 - 97.1 = 2.7 pts
```

Current `_group_words_into_rows` uses `y_tolerance=4.0` which merges these. Each row in the schedule zone has a separate schedule code (71, 74E, 51C, 79, 80B) that ends up merged into one row, producing nonsense like `schedule = "51C 80B 74E 71 79"`.

Same issue for minor changes rows in FIR2023:
```
'10'  top=165.3 bottom=170.7
'10'  top=173.3 bottom=178.7   ← gap = 2.6 pts
```

## Fix Needed

**Option A (recommended)**: Reduce `y_tolerance` to `1.5` or `2.0`. This was originally set to 4.0 to handle FIR2022 split rows (y≈234/237, y≈285/288, gap ~3 pts). Need to check whether 2.0 still handles those FIR2022 split rows.

Check with:
```python
import pdfplumber
pdf_path = Path('fir_instructions/change_logs/FIR2022 Changes.pdf')
with pdfplumber.open(pdf_path) as pdf:
    page = pdf.pages[0]
    words = page.extract_words()
    # Look at words near y=234 and y=237 (the known split rows)
    close_words = [w for w in words if 230 <= w['top'] <= 295]
    for w in close_words:
        print(f"  {w['text']!r} top={w['top']:.1f} bottom={w['bottom']:.1f} x0={w['x0']:.1f}")
```

**Option B**: Use a tighter tolerance for grouping (e.g. `top - prev_top > threshold` instead of `top - max_bottom > threshold`). This uses top-to-top distance which is more stable.

**Option C**: Reduce tolerance to 2.0 AND handle FIR2022 split rows as a post-processing step (detect rows where heading or description is missing and merge with next).

## Remaining Steps After Fix

1. Run extraction on all 7 PDFs, verify counts:
   - FIR2019: expected unknown
   - FIR2020: expected unknown
   - FIR2021: expected unknown
   - FIR2022: expected ~40 (got 64 — likely same bug)
   - FIR2023: expected 50+ (got 27 — confirmed bug)
   - FIR2024: expected ~10 (got 11 ✓)
   - FIR2025: expected ~7 (got 8 ✓)

2. Save to `fir_instructions/exports/baseline_fir_instruction_changelog.csv`

3. Create CLI module `src/municipal_finances/fir_instructions/cli.py` with:
   - `extract-changelog` command (runs extraction + saves CSV)
   - `load-changelog` command (loads CSV → DB)
   Register in `app.py`.

4. Write tests in `tests/fir_instructions/test_extract_changelog.py`:
   - `test_insert_changelog_entries` with valid data
   - `test_idempotent_insertion`
   - `test_change_type_values_valid`
   - `test_slc_wildcard_parsing`
   - `test_load_from_csv`

5. Add README note about `fir_instructions/exports/` folder.

6. Create branch, commit each logical step, open PR.

7. Update `progress_tracker.md`.

## Key Algorithm Details (Validated)

- Schedule zone: `[sch_x - 15, sch_x + 35]`
- SLC zone: `[sch_x + 35, slc_x + 30]` (slc_x = header "SLC" label x-position)
- Remaining words (heading + description): `x0 >= slc_x + 30`
- Heading/description split: largest inter-word gap (must be > 10 pts)
- Section detection: "MAJOR CHANGE" / "MINOR CHANGE" text
- Data row: first word in schedule zone, first char is alnum, not a header row
- Blank-schedule row: first word in SLC zone, matches `^[A-Za-z0-9]+$`
- Schedule for blank-schedule rows: first SLC-zone token that is not 4 digits and not `x+`
- Header row detection: contains "slc" and ("heading" or "description") tokens

## Column x-positions by year (for reference)

| PDF  | sch_x | slc_x | heading_x | desc_x | SLC zone end |
|------|-------|-------|-----------|--------|--------------|
| 2025 | 52    | 128   | 298       | 592    | 158          |
| 2024 | 45    | 108   | 226       | 445    | 138          |
| 2023 | 60    | 117   | 219       | 419    | 147          |
| 2022 | 59    | 122   | 186       | 392    | 152          |
| 2021 | 59    | 121   | 186       | 392    | 151          |
| 2020 | 50    | 115   | 181       | 395    | 145          |
| 2019 | 45    | 105   | 168       | 392    | 135          |
