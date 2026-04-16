# Range Line Headings in FIR2025 Markdown Files

All `## Lines XXXX to YYYY - Name` headings found in the 2025 markdown source files.
The extractor (`_parse_line_heading`) captures only the first ID in a range and creates
a single `fir_line_meta` record. The trailing IDs are silently dropped.

No range headings appear in `FIR2025 - Functional Categories.md`.

---

## 1. Parsed correctly — one record created for the first ID only

The regex `Lines?\s+(\w{4})(?:\s+to\s+\w{4})?...` matches these and captures the
first 4-character line ID. The line name is parsed normally.

| File | Line | Raw heading | Extracted id | Dropped IDs |
|------|------|-------------|-------------|-------------|
| FIR2025 S10.md | 109 | `Lines 0696 to 0698 - Other:` | 0696 | 0697, 0698 |
| FIR2025 S54.md | 115 | `Lines 1096 to 1098 - Other` | 1096 | 1097, 1098 |
| FIR2025 S54.md | 240 | `Lines 2096 to 2098 - Other` | 2096 | 2097, 2098 |
| FIR2025 S54.md | 298 | `Lines 1096 to 1098 – Other` | 1096 | 1097, 1098 |
| FIR2025 S70.md | 203 | `Lines 0890 to 0891 - Other` | 0890 | 0891 |
| FIR2025 S70.md | 335 | `Lines 2640 to 2650 - Other` | 2640 | 2641–2650 |
| FIR2025 S70.md | 521 | `Lines 5076 to 5079 – Other` | 5076 | 5077–5079 |
| FIR2025 S70.md | 547 | `Lines 6610 to 6640 - Other` | 6610 | 6611–6640 |
| FIR2025 S74.md | 247 | `Lines 1297 to 1298 - Other:` | 1297 | 1298 |
| FIR2025 S76.md | 29 | `Lines 0297 to 0298 - Other` | 0297 | 0298 |
| FIR2025 S76.md | 47 | `Lines 0497 to 0498 - Other` | 0497 | 0498 |
| FIR2025 S77.md | 47 | `Lines 0496 to 0498 - Other` | 0496 | 0497, 0498 |
| FIR2025 S77.md | 81 | `Lines 0696 to 0698 - Other` | 0696 | 0697, 0698 |
| FIR2025 S77.md | 109 | `Lines 0896 to 0898 - Other` | 0896 | 0897, 0898 |
| FIR2025 S77.md | 159 | `Lines 1097 to 1098 - Other` | 1097 | 1098 |
| FIR2025 S77.md | 195 | `Lines 1497 to 1498 - Other` | 1497 | 1498 |
| FIR2025 S77.md | 287 | `Lines 2693 to 2698 - Other` | 2693 | 2694–2698 |
| FIR2025 S80.md | 293 | `Lines 1497 to 1498 - Other` | 1497 | 1498 |
| FIR2025 S80.md | 315 | `Lines 0801 to 0849 - (I) Proportionally Consolidated Joint Local Boards` | 0801 | 0802–0849 |
| FIR2025 S80.md | 319 | `Lines 0851 to 0899 - (II) Fully Consolidated Local Boards and Any Local Entities Set Up by the Municipality.` | 0851 | 0852–0899 |

Note: S54.md lines 115 and 298 both produce a record for id `1096` — they are
deduplicated by `_extract_per_schedule_lines`, which keeps only the first occurrence.

---

## 2. Parsed with malformed `line_name` — hyphen/en-dash used between IDs instead of "to"

These headings use a punctuation character between the two IDs rather than the word
"to". The regex treats the first ID as `line_id` and everything after the separator
(including the second ID) as `line_name`, producing a nonsensical name.

| File | Line | Raw heading | Extracted id | Extracted line_name (wrong) |
|------|------|-------------|-------------|-------------|
| FIR2025 S72.md | 297 | `Lines 2890-2891 - Other` | 2890 | `2891 - Other` |
| FIR2025 S72.md | 423 | `Lines 4890 – 4891 - Other` | 4890 | `4891 - Other` |

---

## 3. Not parsed — range heading not recognised, no record created

These headings fail to match the regex for various reasons and produce no record at all.

| File | Line | Raw heading | Reason not matched |
|------|------|-------------|-------------------|
| FIR2025 S10.md | 299 | `Lines 1890 to1898 - Other` | Typo: missing space between "to" and "1898" (`to1898`) |
| FIR2025 S53.md | 111 | `Lines 204 to 220` | IDs are 3 digits, not 4; also no name after the range |
| FIR2025 S53.md | 119 | `Lines 235 to 298` | IDs are 3 digits, not 4; also no name after the range |
| FIR2025 S60.md | 61 | `Lines 0810 to 0898` | No name after the range (nothing after the final ID) |
| FIR2025 S60.md | 227 | `Lines 5010 to 5290` | No name after the range |
| FIR2025 S74.md | 121 | `Lines 0297 and 0298 - Other` | Uses "and" instead of "to" between IDs |
