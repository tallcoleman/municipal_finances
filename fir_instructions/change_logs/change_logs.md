# FIR Instructions Content Changes Tables

The "Content Changes" table of each FIR Instructions PDF outlines the changes to schedules, lines, and columns from the previous year.

## Files and Extracts

- PDF documents are extracts of the "Content Changes" tables from the larger instructions PDFs for each year.
- CSVs in `direct_extraction/` aim to cleanly and accurately reflect the text in the "Content Changes" tables as they are represented in the PDF. Typos are not corrected, column headers are not normalized, inline headings that break the tabular format are presented as-is, and column values are not filled down. However, the instructions block at the top of each table is removed, and multi-line values are condensed to one line if it is clear that the multiple lines only apply to one row.
- CSVs in `semantic_extraction/` are based on the `direct_extraction/` PDFs and aim to accurately reflect the intended content in the "Content Changes" tables. Where possible, typos are corrected, column headers are normalized, column values are filled down, and inline headings are represented in a new "Section Description" column. Multi-line values that apply to several rows are also resolved.