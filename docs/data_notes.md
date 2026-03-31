# FIR Data Notes

## Source columns

These are the columns present in the FIR open data CSV files and the combined parquet file.

### Municipality fields

These fields identify the municipality and are stored in the `municipality` table. Values are consistent within a given `munid` across years (or treated as such — the most recently loaded values are used).

| Column | Description |
|---|---|
| `MUNID` | Five-digit municipal ID. Primary key in the `municipality` table. e.g. `"21000"` for the Region of Peel. |
| `ASSESSMENT_CODE` | Four-digit code: first two digits identify the Upper Tier, last two identify the Lower Tier within it. e.g. Mississauga = `2105`, Brampton = `2110`, Peel (UT) = `2100`. |
| `MUNICIPALITY_DESC` | Municipality name. e.g. `"Toronto C"`, `"Rockcliffe Park V"`, `"Peel R"`. |
| `MSO_NUMBER` | Two-digit code for the Municipal Service Office. |
| `SGC_CODE` | Standard Geographic Code. Often the same as `MUNID`, but not always. |
| `UT_NUMBER` | Upper Tier number — the first two digits of `ASSESSMENT_CODE`. |
| `MTYPE_CODE` | Municipal type: `0` = Upper Tier, `1` = City, `3` = Separated Town, `4` = Town, `5` = Village, `6` = Township. |
| `TIER_CODE` | Tier: `LT` = Lower Tier, `ST` = Single Tier, `UT` = Upper Tier. |

### FIR record fields

These fields describe an individual data point and are stored in the `firrecord` table, with a foreign key to `municipality` via `munid`.

| Column | Description |
|---|---|
| `MARSYEAR` | FIR reporting year (2000–2023 in current data). |
| `LAST_UPDATE_DATE` | Date the municipality's data for this reporting year was last updated. |
| `SCHEDULE_DESC` | Name of the FIR schedule (e.g. `"Schedule 10 - Continuity of Taxes Receivable"`). |
| `SUB_SCHEDULE_DESC` | Sub-schedule description where applicable. |
| `SCHEDULE_LINE_DESC` | Line description within the schedule. |
| `SCHEDULE_COLUMN_DESC` | Column heading within the schedule. |
| `SLC` | Unique identifier for the data point combining Schedule, Line, and Column. Format: `slc.02X.L0020.C01.02` — where `02X` is the schedule number, `L0020` is the line number, and `C01.02` is the section and column. Schedules split into parts use suffixes instead of `X` (e.g. `slc.26A`, `slc.26B`). Affected schedules: 26, 51, 72, 74, 77, 80. |
| `DATATYPE_DESC` | Data type: `text`, `currency`, `non-currency`, or `percentage`. |
| `AMOUNT` | Numeric value for non-text data types; blank for text. |
| `VALUE_TEXT` | Text value for `text` data type; blank for numeric. |

## Data volume

The combined dataset (all years) contains approximately 13.5M rows:
- Lower Tier (`LT`): ~7.2M records
- Single Tier (`ST`): ~5.5M records
- Upper Tier (`UT`): ~0.8M records
