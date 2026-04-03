# Review Continuation Context

This document captures the remaining work for the comprehensive review of the FIR instructions extraction task documents. Two tasks remain: finishing the Additional Considerations review (Task #8) and writing the final alignment/summary analysis (Task #9).

## Commits Made So Far

On the `plan-updates` branch, the following commits have been made as part of this review:

1. Fix `valid_from_year = NULL` semantics from "pre-2022" to "pre-2019" in `00_shared_instructions.md`
2. Add missing unique constraint `(year, schedule, slc_pattern, change_type, source)` for `fir_instruction_changelog` in `01_database_models.md`, with a note about PostgreSQL NULL handling
3. Fix `schedule_id` FK resolution logic in `09_file_persistence.md` — rewrote `resolve_schedule_ids` to use range-overlap join instead of equality join on `(schedule, valid_from_year, valid_to_year)`
4. Clarify CSV conventions in `00_shared_instructions.md` (intermediate vs canonical CSVs) and fix year range "2009" → "2000" in `08b_data_inference.md`
5. Incorporate TODOs and add two missing audit checks (column coverage, inferred-vs-documented reconciliation) in `11_audit_checks.md`
6. Create `12_human_review_reports.md` covering the 6 human review protocol items from the extraction plan's audit section
7. Promote Additional Considerations from `03_content_changes_extraction.md` into its main body: added "PDF Table Parsing" section and task list items for splitting multi-change entries and tagging schedule-level changes

## Task #8: Review Additional Considerations (IN PROGRESS)

### What's Done

Task 03's Additional Considerations have been reviewed and promoted (commit #7 above). The five considerations were handled as follows:
- #1 (skip non-table header content) → promoted into new "PDF Table Parsing" section
- #2 (carry forward blank column values) → promoted into new "PDF Table Parsing" section
- #3 (split multi-change entries) → promoted as task list item
- #4 (tag schedule-level changes) → promoted as task list item
- #5 (try Python PDF library first) → promoted into new "PDF Table Parsing" section

### What Remains

Review the Additional Considerations sections of Tasks 04–10 and promote items that are substantive enough to belong in task lists, testing plans, implementation details, or validation criteria. Below is the analysis of each task's considerations with a recommendation.

#### Task 04 (`04_baseline_schedule_meta.md`) — 3 considerations

1. **Sub-schedule descriptions should reference parent schedule.** This is extraction guidance affecting data quality. Currently only in Additional Considerations.
   - **Recommendation: Promote** into the "Fields to Extract Per Schedule" section as a note under `description`.

2. **Category normalization check against PDFs.** The plan's category table may differ from actual PDF categories. Currently not in the task list.
   - **Recommendation: Promote** as a task list item (lightweight check, possibly just a note during extraction).

3. **`description` should include the entire general information section, not just the first paragraph.** This directly contradicts the current "Fields to Extract" section which says "The general purpose paragraph." The Extraction Approach section also says "general description paragraph."
   - **Recommendation: Promote** by updating the `description` field note in "Fields to Extract" and the corresponding line in "Extraction Approach" to say "entire general information section."

#### Task 05 (`05_baseline_line_meta.md`) — 4 considerations

1. **`includes` and `excludes` formatted as newline-separated plain text.** Affects CSV compatibility and downstream consumers.
   - **Recommendation: Promote** into the "Fields to Extract Per Line" table as a note on the `includes`/`excludes` fields, or into a brief "Data Formatting" subsection.

2. **Sub-schedule ambiguity in Functional Classifications.** Schedule 51 generic references need to be assigned to 51A/51B. Affects merge correctness.
   - **Recommendation: Promote** into the "Extraction Strategy" step 1 (Functional Classifications) or the "Merge" step 3 as a note about handling "Schedule 51" references.

3. **Conflicting descriptions between Functional Classifications and schedule instructions.** Resolution rule: use schedule instruction for `description`, Functional Classifications only for `includes`/`excludes`.
   - **Recommendation: Promote** into the "Merge" description (step 3 of "Extraction Strategy"). This is a key decision that affects data correctness and should not be buried.

4. **9910-style lines should be marked `is_subtotal = True`.** Affects subtotal identification completeness.
   - **Recommendation: Promote** into the "Identifying Subtotals and Auto-Calculated Lines" section as an additional bullet point.

#### Task 06 (`06_baseline_column_meta.md`) — 1 consideration

1. **Columns with no narrative description should get `"No description provided."`** Affects data consistency (NULL vs empty vs sentinel).
   - **Recommendation: Promote** into "Extraction Notes" as an additional bullet. Minor but prevents ambiguity during extraction.

#### Task 07 (`07_apply_changes_backwards.md`) — 3 considerations

1. **When only part of a line changed, copy unchanged fields from the current version.** Practical extraction guidance.
   - **Recommendation: Promote** into the "Versioning Procedure" section under "Line/column updated in year Y" step 2 (create new metadata row with old content) — add a note that unchanged fields should be copied from the existing row.

2. **Create versioned rows even for trivial changes.** Reinforces the versioning procedure.
   - **Recommendation: Keep as Additional Consideration.** The versioning procedure already implies this, and the consideration adds useful emphasis without needing to be in the main body.

3. **Application-level overlap check.** Suggests adding a check that prevents overlapping version ranges during load/update operations.
   - **Recommendation: Promote** as a task list item and test case. This is a concrete requirement that should be implemented, not just a suggestion. The test already exists ("Test that version ranges don't overlap"), but the task list should include implementing the check itself.

#### Task 08a (`08a_reporting_completeness_inference.md`) — 4 considerations

1. **Municipality tier filtering for expected-schedule checks.** Acknowledged as a future refinement.
   - **Recommendation: Keep as Additional Consideration.** The three-prior-years heuristic is the current approach; tier filtering is explicitly deferred.

2. **Note the run date when reporting 2025 figures.** Affects output clarity.
   - **Recommendation: Promote** into the "Report Modes" section output format. Add a note that the CLI output should include the data extraction date for years where reporting is still in progress.

3. **Cached summary refresh cadence documentation.** Conditional on caching approach.
   - **Recommendation: Keep as Additional Consideration.** Only relevant if caching is chosen; the consideration already explains when to apply it.

4. **Insufficient-history degradation also applies to Task 08b internal calls.** Cross-task interaction.
   - **Recommendation: Keep as Additional Consideration.** This is already covered by the "Handling Insufficient History" section's note that "This behaviour applies equally to the CLI, the API, and the internal logic used by Task 08b."

#### Task 09 (`09_file_persistence.md`) — 3 considerations

1. **`--overwrite` flag for `ON CONFLICT DO UPDATE`.** This is a concrete feature.
   - **Recommendation: Promote** as a task list item. The implementation details describe `ON CONFLICT DO NOTHING` but the `--overwrite` flag is only in Additional Considerations. Add a task list item and add a brief description of the flag behavior to the Load Command section.

2. **Exported CSVs should not be caught by `.gitignore`.** A concrete check.
   - **Recommendation: Promote** as a task list item: "Verify `fir_instructions/exports/` is not excluded by `.gitignore`."

3. **Schema mismatch handling (extra/missing columns in CSV).** Defensive import logic.
   - **Recommendation: Promote** into the Load Command implementation details. Add a brief note about ignoring extra columns (with warning) and raising errors on missing required columns.

#### Task 10 (`10_api_endpoints.md`) — 4 considerations

1. **Lookup endpoint returns partial results for missing metadata.** Affects API contract.
   - **Recommendation: Promote** into the "Lookup Endpoint" section as a note on the response behavior when one or more metadata types is missing.

2. **Enriched `firrecord` endpoint feasibility assessment.** An investigation task.
   - **Recommendation: Keep as Additional Consideration.** This is a "nice to have" assessment, not a requirement. The alternative (separate lookup call) is documented.

3. **Changelog endpoint should support `severity` filter.** Missing query parameter.
   - **Recommendation: Promote** into the Changelog endpoint's query params list. This is a straightforward omission.

4. **Rate limiting / caching for lookup endpoint.** Performance consideration.
   - **Recommendation: Keep as Additional Consideration.** Only relevant if usage patterns show it's needed.

### Summary of Recommended Promotions

| Task | Item | Where to promote |
|------|------|-----------------|
| 04 | #1 Sub-schedule descriptions | Fields to Extract, `description` note |
| 04 | #2 Category normalization check | Task list item |
| 04 | #3 Entire general info section | Fields to Extract + Extraction Approach |
| 05 | #1 includes/excludes formatting | Fields to Extract or Data Formatting subsection |
| 05 | #2 Sub-schedule ambiguity | Extraction Strategy step 1 or Merge step 3 |
| 05 | #3 Conflicting description resolution | Extraction Strategy step 3 (Merge) |
| 05 | #4 9910-style subtotals | Identifying Subtotals section |
| 06 | #1 No-description columns | Extraction Notes bullet |
| 07 | #1 Copy unchanged fields | Versioning Procedure, "updated" step |
| 07 | #3 Application-level overlap check | Task list item |
| 08a | #2 Run date on 2025 figures | Report Modes output format |
| 09 | #1 --overwrite flag | Task list item + Load Command section |
| 09 | #2 .gitignore check | Task list item |
| 09 | #3 Schema mismatch handling | Load Command implementation |
| 10 | #1 Partial results in lookup | Lookup Endpoint section |
| 10 | #3 Severity filter on changelog | Changelog endpoint query params |

Items recommended to **keep as Additional Considerations** (not promote): Task 07 #2 (trivial changes), Task 08a #1 (tier filtering), #3 (cache cadence), #4 (insufficient history in 08b), Task 10 #2 (enriched firrecord endpoint), #4 (rate limiting).

## Task #9: Check Alignment with project_goals.md and Write Final Summary

This task should produce a final analysis addressing all of the user's original review questions. The analysis should cover:

### 1. Cross-Consistency

**Findings from this review (already addressed in commits):**
- `valid_from_year = NULL` semantics were inconsistent ("pre-2022" in shared instructions vs "pre-2019" everywhere else) → fixed
- `fir_instruction_changelog` lacked a unique constraint in the Task 01 model definition → added
- `schedule_id` FK resolution in Task 09 used equality join instead of range-overlap → fixed
- Year range in Task 08b said "2009–2025" but `fir_data_notes.md` says data starts from 2000 → fixed to "2000–2025"
- Task 11 had TODO comments for checks not yet incorporated → promoted to full check implementations

**No remaining cross-consistency issues were found** across the task documents after these fixes. Key cross-references that were verified:
- Task 03 → Task 07 (changelog drives versioning): consistent
- Task 04/05/06 → Task 09 (baseline CSVs vs canonical CSVs): clarified via CSV conventions section
- Task 08a → Task 08b (completeness feeds inference): consistent, including insufficient-history handling
- Task 07 version semantics → Task 00 shared conventions: consistent after the NULL semantics fix
- Task 09 load → Task 01 models (unique constraints for ON CONFLICT): consistent after unique constraint addition
- Task 11/12 → extraction plan audit section: now fully covered

### 2. Alignment with project_goals.md

The extraction work directly serves these project goals from `docs/project_goals.md`:

- **"Extract the information about what is in each line from the instructions PDF and make them easily accessible when users are exploring the data. Going from 'what does this line mean' to an explanation should be one click."** — This is the primary goal addressed by the entire extraction plan. Tasks 04–06 extract the metadata, Task 10 exposes it via API with a `/instructions/lookup/` endpoint that takes an SLC and year and returns combined schedule/line/column metadata. The one-click experience is achievable with the lookup endpoint.

- **"Add in useful metadata to help query for related information across multiple schedules."** — The `section`, `category`, `includes`/`excludes`, and `applicability` fields in the metadata tables enable cross-schedule queries. For example, finding all lines related to "Protection Services" across schedules 12, 40, and 51.

- **"The site is primarily designed for municipalities participating in FIR reporting, not for people interested in exploring and analyzing the data."** / **"The instructions that provide more detail on what is included in each line are in PDF format; cross-referencing the instructions and data reports is therefore quite difficult."** — The extraction plan directly addresses this by making instruction content queryable alongside data.

**Potential gaps relative to project goals:**
- The project goals mention "guides designed for these users" — the extraction tasks don't produce user-facing guides, but the structured metadata is a prerequisite for generating them.
- The project goals mention "themes" and cross-schedule metadata — the `section` and `category` fields partially address this, but a dedicated thematic tagging system (e.g., "health-related lines across all schedules") is not part of the current extraction plan. This could be a future enhancement built on the extracted metadata.
- The project goals mention "annotate values to provide additional context" — the `change_notes` field provides some annotation, but user-contributed annotations are not part of this plan.

### 3. Task 09 Ordering Question

**Conclusion: Task 09 should NOT move earlier.** The analysis found that:

- Tasks 03–07 each save intermediate CSVs (prefixed `baseline_`) for human review during extraction. These are working files, not the canonical exports.
- Task 09 produces canonical exports (named after DB tables) from the fully verified database state.
- Moving Task 09 earlier would conflate these two purposes and create confusion about which CSVs are authoritative.
- The CSV conventions section added to `00_shared_instructions.md` clarifies this distinction.

### 4. Audit Plan Coverage

**Conclusion: The audit plan is now fully covered** after the additions in this review:

- **Automated checks (6 items in plan):** All 6 are in Task 11, plus 2 additional checks (column coverage, inferred-vs-documented reconciliation) were added to cover gaps identified during review. Total: 8 automated checks.
- **Human review protocol (7 items in plan):** All 7 are now covered by Task 12 (created during this review) as structured report generators.

### 5. Implementation Gaps

**No critical implementation gaps were found.** The task documents collectively cover the full extraction pipeline from PDF parsing through API exposure. Minor items identified:
- The `resolve_schedule_ids` function in Task 09 is described conceptually but not fully implemented in the instructions — the range-overlap join logic is left as a TODO-style comment. This is acceptable since the instructions describe the correct approach; implementation details will be worked out during coding.
- PostgreSQL NULL handling in unique constraints (noted in Task 01) could cause duplicate changelog rows for schedule-level entries where `slc_pattern` is NULL. Mitigation options are documented.
