# Range Line Headings in FIR2025 Markdown Files

All `## Lines XXXX to YYYY - Name` headings found in the 2025 markdown source files.
The extractor (`_parse_range_heading`) creates one `fir_line_meta` record per ID in
the range; all IDs from first to last inclusive receive the same `line_name` and a
description note identifying the full group.

No range headings appear in `FIR2025 - Functional Categories.md`.

---

## 1. Parsed correctly — one record per ID in range

`_parse_range_heading` matches these via `_LINE_RANGE_RE` (or `_LINE_RANGE_SINGULAR_RE`
for the `Line X to Line Y` format) and enumerates all IDs.

| File | Line | Raw heading | All IDs produced |
|------|------|-------------|-----------------|
| FIR2025 S10.md | 109 | `Lines 0696 to 0698 - Other:` | 0696, 0697, 0698 |
| FIR2025 S10.md | 299 | `Lines 1890 to1898 - Other` | 1890–1898 |
| FIR2025 S54.md | 115 | `Lines 1096 to 1098 - Other` | 1096, 1097, 1098 |
| FIR2025 S54.md | 240 | `Lines 2096 to 2098 - Other` | 2096, 2097, 2098 |
| FIR2025 S54.md | 298 | `Lines 1096 to 1098 – Other` | 1096, 1097, 1098 (deduplicated — first wins) |
| FIR2025 S60.md | — | `Line 0895 to Line 0898 - Other` | 0895, 0896, 0897, 0898 |
| FIR2025 S70.md | 203 | `Lines 0890 to 0891 - Other` | 0890, 0891 |
| FIR2025 S70.md | 335 | `Lines 2640 to 2650 - Other` | 2640–2650 |
| FIR2025 S70.md | 521 | `Lines 5076 to 5079 – Other` | 5076–5079 |
| FIR2025 S70.md | 547 | `Lines 6610 to 6640 - Other` | 6610–6640 |
| FIR2025 S72.md | 297 | `Lines 2890-2891 - Other` | 2890, 2891 |
| FIR2025 S72.md | 423 | `Lines 4890 – 4891 - Other` | 4890, 4891 |
| FIR2025 S74.md | 121 | `Lines 0297 and 0298 - Other` | 0297, 0298 |
| FIR2025 S74.md | 247 | `Lines 1297 to 1298 - Other:` | 1297, 1298 |
| FIR2025 S76.md | 29 | `Lines 0297 to 0298 - Other` | 0297, 0298 |
| FIR2025 S76.md | 47 | `Lines 0497 to 0498 - Other` | 0497, 0498 |
| FIR2025 S77.md | 47 | `Lines 0496 to 0498 - Other` | 0496, 0497, 0498 |
| FIR2025 S77.md | 81 | `Lines 0696 to 0698 - Other` | 0696, 0697, 0698 |
| FIR2025 S77.md | 109 | `Lines 0896 to 0898 - Other` | 0896, 0897, 0898 |
| FIR2025 S77.md | 159 | `Lines 1097 to 1098 - Other` | 1097, 1098 |
| FIR2025 S77.md | 195 | `Lines 1497 to 1498 - Other` | 1497, 1498 |
| FIR2025 S77.md | 287 | `Lines 2693 to 2698 - Other` | 2693–2698 |
| FIR2025 S80.md | 293 | `Lines 1497 to 1498 - Other` | 1497, 1498 |
| FIR2025 S80.md | 315 | `Lines 0801 to 0849 - (I) Proportionally Consolidated Joint Local Boards` | 0801–0849 |
| FIR2025 S80.md | 319 | `Lines 0851 to 0899 - (II) Fully Consolidated Local Boards and Any Local Entities Set Up by the Municipality.` | 0851–0899 |

Notes:
- S54.md lines 115 and 298 both refer to IDs 1096–1098; the second occurrence is
  suppressed by `seen_line_ids` deduplication — the first occurrence wins.
- S10.md line 299 (`Lines 1890 to1898`) and S72.md (`Lines 2890-2891`,
  `Lines 4890 – 4891`) and S74.md (`Lines 0297 and 0298`) were previously
  mis-categorised as unhandled; `_LINE_RANGE_RE` handles all of them.
- S60's `Line 0895 to Line 0898 - Other` uses the unique `Line X to Line Y` singular
  form and is matched by `_LINE_RANGE_SINGULAR_RE`.

---

## 2. Not parsed — range heading not recognised, no record created

These headings fail to match either range regex and produce no record.

| File | Line | Raw heading | Reason not matched |
|------|------|-------------|-------------------|
| FIR2025 S53.md | 111 | `Lines 204 to 220` | IDs are 3 digits, not 4-character `\w{4}` |
| FIR2025 S53.md | 119 | `Lines 235 to 298` | IDs are 3 digits, not 4-character `\w{4}` |
| FIR2025 S60.md | 61 | `Lines 0810 to 0898` | No dash-separated name after the IDs |
| FIR2025 S60.md | 227 | `Lines 5010 to 5290` | No dash-separated name after the IDs |

Note: S60's unnamed ranges (`Lines 0810 to 0898`, `Lines 5010 to 5290`) intentionally
produce no records — they serve as section labels in the source document, not
individual line definitions. Lines 0810–0898 and 5010–5290 that have actual
definitions appear as sub-headings or inline body text and are captured there.
