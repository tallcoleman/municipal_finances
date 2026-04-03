# FIR Instructions Extraction Plan

## Goal

Extract structured metadata from the annual FIR Instructions PDFs and store it in the database, linked to the existing FIR data. This enables users exploring schedule/line/column data to directly call up the relevant instructions without opening a PDF.

Source PDFs are in `fir_instructions/source_files/`. Currently available: FIR2022, FIR2023, FIR2024, FIR2025.

---

## Background: Document Structure

Each annual FIR Instructions PDF (~400–500 pages) has three main parts:

**Part 1 — Introduction**
General context: accounting standards, SLC coding system, cross-cutting reporting rules. The SLC (Schedule-Line-Column) system uniquely identifies every data point: `SLC 10 9930 01` = Schedule 10, Line 9930, Column 01. In the database, the `slc` field on `firrecord` encodes this as `slc.{schedule_code}.L{line_id}.C{column_id}.{sub}`.

**Part 2 — Functional Classifications**
A standalone attachment defining what activities belong under each line in Schedules 12 (Grants/User Fees), 40 (Expenses), and 51 (Tangible Capital Assets). Organized by service area (General Government, Protection Services, Transportation, Environmental, Health, Social, Recreation, Planning). Each line gets a structured list of what to include/exclude.

**Part 3 — Schedule-by-Schedule Instructions**
One section per schedule (~26 schedules). Each section contains general information about the schedule's purpose, line-by-line descriptions (what to report, inclusion/exclusion rules, carry-forward sources), and column-by-column descriptions.

**Content Changes attachment**
A structured table (Schedule / SLC / Heading / Description) documenting exactly what changed from the prior year. The PDFs distinguish Major Changes (new/deleted schedules) from Minor Changes (new/updated/removed lines or columns). This is the key input for versioning.

### The 26 Schedules

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
| Remeasurement Gains & Losses | 71 (new in 2023) |
| Long Term Liabilities | 74, 74E (new in 2023) |
| Other Information | 76, 77, 80, 81, 83 |

Note: the schedule list itself changes over time. Schedule 51C and 79 were deleted in 2023.

---

## Database Tables

### `fir_schedule_meta`

One row per (schedule, version). Describes a schedule as a whole.

| Column            | Type          | Notes                                                               |
| ----------------- | ------------- | ------------------------------------------------------------------- |
| `id`              | serial PK     |                                                                     |
| `schedule`        | text          | e.g. `"10"`, `"51A"`, `"74E"`                                       |
| `schedule_name`   | text          | e.g. `"Consolidated Statement of Operations: Revenue"`              |
| `category`        | text          | e.g. `"Revenue"`, `"Taxation"`, `"Expense"`                         |
| `description`     | text          | General purpose paragraph from the instructions                     |
| `valid_from_year` | int nullable  | First FIR year this version applies; NULL = before our earliest PDF |
| `valid_to_year`   | int nullable  | Last FIR year this version applies; NULL = still current            |
| `change_notes`    | text nullable | Brief summary of what changed to create this version                |

### `fir_line_meta`

One row per (schedule, line, version). The richest table — covers both Functional Classifications content and schedule-specific reporting rules.

| Column               | Type          | Notes                                                                                |
| -------------------- | ------------- | ------------------------------------------------------------------------------------ |
| `id`                 | serial PK     |                                                                                      |
| `schedule_id`        | serial FK     | FK to `fir_schedule_meta.id`                                                         |
| `schedule`           | text          | Corresponds to `fir_schedule_meta.schedule` but is not a FK                          |
| `line_id`            | text          | 4-digit string, e.g. `"0410"`                                                        |
| `line_name`          | text          | e.g. `"Fire"`                                                                        |
| `section`            | text nullable | Section heading within the schedule, e.g. `"Protection Services"`                    |
| `description`        | text nullable | Full narrative from the PDF about what to report                                     |
| `includes`           | text nullable | Items explicitly included (from Functional Classifications or schedule instructions) |
| `excludes`           | text nullable | Items explicitly excluded                                                            |
| `is_subtotal`        | bool          | Whether this is a computed subtotal row                                              |
| `is_auto_calculated` | bool          | Whether auto-populated from another schedule                                         |
| `carry_forward_from` | text nullable | SLC reference if auto-populated, e.g. `"12 9910 05"`                                 |
| `applicability`      | text nullable | Any restriction, e.g. `"Upper-tier only"`, `"City of Toronto only"`                  |
| `valid_from_year`    | int nullable  | First FIR year this version applies; NULL = before our earliest PDF                  |
| `valid_to_year`      | int nullable  | Last FIR year this version applies; NULL = still current                             |
| `change_notes`       | text nullable | Brief summary of what changed to create this version                                 |

### `fir_column_meta`

One row per (schedule, column, version).

| Column            | Type          | Notes                                                               |
| ----------------- | ------------- | ------------------------------------------------------------------- |
| `id`              | serial PK     |                                                                     |
| `schedule_id`     | serial FK     | FK to `fir_schedule_meta.id`                                        |
| `schedule`        | text          | Corresponds to `fir_schedule_meta.schedule` but is not a FK         |
| `column_id`       | text          | 2-digit string, e.g. `"01"`                                         |
| `column_name`     | text          | e.g. `"Ontario Conditional Grants"`                                 |
| `description`     | text nullable | What the column captures                                            |
| `valid_from_year` | int nullable  | First FIR year this version applies; NULL = before our earliest PDF |
| `valid_to_year`   | int nullable  | Last FIR year this version applies; NULL = still current            |
| `change_notes`    | text nullable | Brief summary of what changed to create this version                |

### `fir_instruction_changelog`

One row per documented or inferred change. Tracks all changes across all years from both PDF Content Changes sections and data-inferred differences. This table is the source of truth for populating `valid_from_year`/`valid_to_year` on the other tables.

| Column        | Type          | Notes                                                                                                                                                                                                 |
| ------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `id`          | serial PK     |                                                                                                                                                                                                       |
| `year`        | int           | FIR year in which this change took effect                                                                                                                                                             |
| `schedule`    | text          | Affected schedule                                                                                                                                                                                     |
| `slc_pattern` | text nullable | SLC reference from PDF (may contain wildcards like `xx`), e.g. `"40 xxxx 05"`                                                                                                                         |
| `line_id`     | text nullable | Parsed line ID if deterministic                                                                                                                                                                       |
| `column_id`   | text nullable | Parsed column ID if deterministic                                                                                                                                                                     |
| `heading`     | text nullable | Line/column heading from the PDF or inferred from data                                                                                                                                                |
| `change_type` | text          | One of: `new_schedule`, `deleted_schedule`, `new_line`, `deleted_line`, `updated_line`, `new_column`, `deleted_column`, `updated_column`, `inferred_new`, `inferred_deleted`, `inferred_label_change` |
| `severity`    | text nullable | `"major"` or `"minor"` (from PDF labelling); NULL for inferred                                                                                                                                        |
| `description` | text nullable | Verbatim from PDF, or auto-generated description for inferred changes                                                                                                                                 |
| `source`      | text          | `"pdf_changelog"` or `"data_inferred"`                                                                                                                                                                |

**Effective date semantics:**
- `valid_from_year = NULL`: applies from before our earliest PDF (pre-2022)
- `valid_to_year = NULL`: still currently in effect
- Query for year Y: `(valid_from_year IS NULL OR valid_from_year <= Y) AND (valid_to_year IS NULL OR valid_to_year >= Y)`

---

## Linking to `firrecord`

The `slc` field on `firrecord` encodes schedule, line, and column. Parse it to join to metadata:

```sql
-- Example: join firrecord to line metadata for a given data year
SELECT r.*, m.*
FROM firrecord r
JOIN fir_line_meta m
  ON m.schedule = <parsed schedule from r.slc>
 AND m.line_id     = <parsed line from r.slc>
 AND (m.valid_from_year IS NULL OR m.valid_from_year <= r.marsyear)
 AND (m.valid_to_year   IS NULL OR m.valid_to_year   >= r.marsyear)
WHERE r.marsyear = 2023
```

A helper function or generated column to extract schedule/line/column from the SLC string will make this ergonomic. The SLC format is: `slc.{schedule_code}.L{line_4digits}.C{column_2digits}.{sub}`.

---

## Extraction Approach

### Phase 0: Extract all Content Changes tables (fast, do this first)

Read only the Content Changes pages from each PDF (1–3 pages per PDF, already in a structured table format). Extract every row into `fir_instruction_changelog` with `source = "pdf_changelog"`.

This is the fastest step and determines the full scope of versioning work before any heavy extraction begins.

**Known change volumes:**
- FIR2022: ~40 entries (moderate — new lines/columns in Schedules 61, 72B)
- FIR2023: ~50+ entries (major — two new schedules 71 and 74E, three deleted: 51C, 79, 80B; driven by PSAB standards PS 3280 and PS 3450)
- FIR2024: ~10 entries (minor)
- FIR2025: ~7 entries (minor)

**Page locations in each PDF:**
- FIR2022: ~pages 29–31
- FIR2023: ~page 29
- FIR2024: ~page 30
- FIR2025: ~page 43

### Phase 1: Extract FIR2025 as the full baseline

Extract all three metadata tables from the FIR2025 PDF (the most current instructions). This is the bulk of the extraction work. Set `valid_from_year = NULL` and `valid_to_year = NULL` on all baseline rows (meaning "applies from the beginning and is still current").

Work through the PDF in sections:
1. Schedule list and categories (~pages 5–6 of 2025 PDF)
2. Functional Classifications attachment (~pages 43–93): provides `includes`/`excludes` content for Schedules 12, 40, 51 lines
3. Each schedule's instruction section: provides `description`, `carry_forward_from`, `applicability`, column descriptions

Expect ~2–5 PDF read passes per schedule across 26 schedules.

### Phase 2: Apply documented changes backwards to create versioned rows

Using the changelog from Phase 0, identify every line/column that changed in 2024, 2023, or 2022. For each:

1. Read the relevant section of the older PDF to extract the prior-version description
2. Create a new row in the metadata table with the older description and appropriate `valid_from_year`/`valid_to_year`
3. Update the existing (newer) row's `valid_from_year` to the year the new version took effect
4. Set `change_notes` on the new row from the changelog description

For lines that were deleted in a given year: set `valid_to_year` on the existing row.
For lines that were added in a given year: set `valid_from_year` on the existing row.

Work year by year: 2024 changes, then 2023 changes (the largest set), then 2022 changes.

### Phase 3: Infer changes for years without PDFs (see below)

---

## Inferring Changes from Data for Years Without PDFs

For FIR years where no instructions PDF is available (any year older than 2022, or future gaps), changes can be inferred by comparing the set of SLC values and their labels present in the actual `firrecord` data across adjacent years.

### What can be inferred from the data

The `firrecord` table contains `schedule_line_desc`, `schedule_column_desc`, and `slc` for every data point. By comparing adjacent years:

| Observable change | Inferred change type |
|---|---|
| SLC present in year Y but absent in Y-1 | `inferred_new` (new line or column) |
| SLC present in year Y-1 but absent in Y | `inferred_deleted` |
| Same SLC, `schedule_line_desc` differs between Y-1 and Y | `inferred_label_change` |
| Same SLC, `schedule_column_desc` differs between Y-1 and Y | `inferred_label_change` |

### Inference procedure

Run a SQL diff for each adjacent year pair where at least one year lacks a PDF:

```sql
-- New SLCs in year Y (not present in Y-1)
SELECT r.slc, r.schedule_line_desc, r.schedule_column_desc, Y as year
FROM (SELECT DISTINCT slc, schedule_line_desc, schedule_column_desc FROM firrecord WHERE marsyear = Y) r
WHERE r.slc NOT IN (SELECT DISTINCT slc FROM firrecord WHERE marsyear = Y-1);

-- Deleted SLCs (present in Y-1 but not Y)
SELECT r.slc, r.schedule_line_desc, r.schedule_column_desc, Y as year
FROM (SELECT DISTINCT slc, schedule_line_desc, schedule_column_desc FROM firrecord WHERE marsyear = Y-1) r
WHERE r.slc NOT IN (SELECT DISTINCT slc FROM firrecord WHERE marsyear = Y);

-- Label changes (same SLC, different description)
SELECT a.slc, a.schedule_line_desc AS old_desc, b.schedule_line_desc AS new_desc, Y as year
FROM (SELECT DISTINCT slc, schedule_line_desc FROM firrecord WHERE marsyear = Y-1) a
JOIN (SELECT DISTINCT slc, schedule_line_desc FROM firrecord WHERE marsyear = Y) b
  ON a.slc = b.slc AND a.schedule_line_desc != b.schedule_line_desc;
```

### Limitations of inferred changes

Inferred changes have lower confidence than PDF-documented changes:

- **Structural vs. description changes**: data differences prove that something changed structurally (line added/removed), but cannot capture changes to reporting rules or descriptions that didn't affect whether municipalities reported data on a line
- **Noise**: a line absent in year Y might simply have no municipalities reporting on it, not necessarily a structural removal
- **Label drift**: `schedule_line_desc` in the data is copied from the Excel template and may have minor formatting differences that aren't meaningful changes

### Distinguishing confidence levels

Both inferred and PDF-documented changes are stored in `fir_instruction_changelog`. Distinguish them with:
- `source = "pdf_changelog"`: authoritative, from official documentation
- `source = "data_inferred"`: approximate, derived from data differences

The `change_notes` field on metadata rows should also note when a version boundary was inferred rather than documented. The UI should surface this distinction to users (e.g., "instructions valid from 2021, based on data evidence").

### Handling inferred changes in metadata rows

For years without PDFs, when an inference suggests a line was new in year Y:
- The metadata row gets `valid_from_year = Y`
- No prior-version row is created (since we have no source for the prior description)
- `change_notes` = `"New in FIR{Y} (inferred from data; no instructions PDF available for prior year)"`

For an inferred deletion in year Y:
- The metadata row gets `valid_to_year = Y-1`
- `change_notes` = `"Removed in FIR{Y} (inferred from data)"`

---

## File-Based Persistence

Extraction and auditing are expensive: they require PDF access, LLM calls, and careful human review. Once the metadata tables are validated, export them to files so the work can be shared, version-controlled, and reloaded into a fresh database without repeating any of those steps.

### Export format

Export each table as a CSV file, one file per table:

```
fir_instructions/
    exports/
        fir_schedule_meta.csv
        fir_line_meta.csv
        fir_column_meta.csv
        fir_instruction_changelog.csv
```

CSV is preferred over JSON or Parquet because:
- Human-readable and diff-friendly in version control
- Directly loadable with `psql \copy` or pandas without transformation
- Compatible with the project's existing data pipeline conventions

Exclude the `id` (serial PK) column on export — IDs are database-internal and will be reassigned on load. All other columns should be present, including nullable fields (exported as empty strings).

### Exporting from the database

Add an `export-instructions` CLI command to `app.py` that dumps all four tables to the `fir_instructions/exports/` directory:

```bash
uv run src/municipal_finances/app.py export-instructions
uv run src/municipal_finances/app.py export-instructions --output-dir path/to/dir
```

Implementation: use `COPY (SELECT ...) TO STDOUT WITH CSV HEADER` via psycopg2, or a pandas `read_sql` + `to_csv`. Export all four tables in a single command; log row counts per table on completion.

### Loading from file

Add a `load-instructions` CLI command that reads the exported CSVs and inserts them into the database, skipping any row that already exists (match on the natural key: `schedule` + `valid_from_year` + `valid_to_year` for schedule/line/column tables; all non-id columns for changelog):

```bash
uv run src/municipal_finances/app.py load-instructions
uv run src/municipal_finances/app.py load-instructions --input-dir path/to/dir
```

Use `INSERT ... ON CONFLICT DO NOTHING` to make the load idempotent. After loading, log row counts inserted vs. skipped. The command should run `init-db` implicitly if the target tables do not yet exist.

### Workflow integration

The recommended workflow for a new environment:

1. Run `init-db` to create all tables.
2. Run `load-instructions` to populate metadata from the exported CSVs (fast, no PDF access needed).
3. Run `load-years` to populate `firrecord` and related tables.

Re-extraction is only needed when new FIR PDFs are published or extraction errors are found during audit. After any re-extraction and re-audit, re-run `export-instructions` and commit the updated CSVs to version control.

---

## Audit Plan

### Automated checks

1. **Coverage check**: query `firrecord` for all distinct (schedule, line) pairs. Every pair should have at least one matching row in `fir_line_meta` for the relevant year. Flag gaps.
2. **Orphan check**: every row in `fir_line_meta` should have corresponding `firrecord` rows in at least one year within its valid range. Flag entries with zero data matches.
3. **Format validation**: `line_id` matches `/^\d{4}$/`; `column_id` matches `/^\d{2}$/`; `schedule` is in the known schedule list for that year.
4. **Non-overlapping version ranges**: for a given (schedule, line_id) pair, no two rows should have overlapping valid year ranges.
5. **SLC cross-reference**: where `carry_forward_from` is populated, verify the referenced SLC exists in the data.
6. **Changelog completeness**: every row in `fir_instruction_changelog` with `source = "pdf_changelog"` should have produced at least one versioned row (with non-null `valid_from_year`) in the corresponding metadata table.

### Human review protocol

1. **Random sample review**: after extraction, generate a review sheet with 30–50 randomly sampled (schedule, line, year) entries showing the extracted `line_name`, `description`, and `includes`. Reviewer opens the PDF to the cited schedule and confirms accuracy. Target: 100% name agreement, ≥90% description completeness.

2. **Section boundary check**: verify that `section` groupings (e.g., "Protection Services", "Transportation Services") are correctly assigned at section transitions — particularly at the first and last line of each section.

3. **Completeness by schedule**: for each schedule, compare the count of line entries in `fir_line_meta` against a manual count of line headings in the schedule's own table of contents. Flag discrepancies > 2 lines.

4. **Column description check**: for schedules with complex column structures (12, 40, 51A, 51B), verify each column name and description against the PDF.

5. **Version boundary spot check**: pick 10–15 lines that appear in the changelog as having changed. Verify that the `valid_to_year` on the prior-version row and `valid_from_year` on the new row are both set correctly, and that `change_notes` accurately reflects the PDF's description of the change.

6. **Inferred vs. documented reconciliation**: for years where both a PDF changelog and data-inferred changes are available (2022–2025), compare the two sets. Any inferred change that is not in the PDF changelog (or vice versa) should be investigated — it indicates either a data anomaly or a missed extraction.

7. **Year-over-year diff on new PDFs**: when a new FIR year's PDF becomes available, diff the extracted metadata against the prior year's. Flag new lines, deleted lines, and changed descriptions for human review before loading. This catches extraction errors and genuine policy changes simultaneously.
