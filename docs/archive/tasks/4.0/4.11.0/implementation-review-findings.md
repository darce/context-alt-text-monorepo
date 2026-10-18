# v4.11.0 Implementation Review Findings

Date: 2026-01-20

## Scope

Review of the current branch state against:
- `docs/tasks/4.0/4.11.0/clustering-regression-investigation.md`
- `docs/tasks/4.0/4.11.0/implementation-plan.md`
- Relevant modified/untracked backend + frontend files

## Findings (ordered by severity)

### High

1. **Curriculum modulation direction mismatch**
   - Code makes thresholds *more lenient* as `curriculum_t` grows (`curriculum_adj = -0.05 * curriculum_t`), while the plan’s modulation coefficient implies mature clusters should become stricter.
   - Files:
     - `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py:94`
     - `docs/tasks/4.0/4.11.0/implementation-plan.md:75`

2. **Investigation defaults not implemented**
   - The investigation recommends lowering `suggestion_floor` to 0.65 and starting `curriculum_t` at 0.5; defaults remain `suggestion_floor=0.75` and `curriculum_t=0.0`.
   - This preserves a wide suggestion band for cold clusters and does not address the “no UI for unlabeled clusters” gap.
   - Files:
     - `apps/prototype-description-service/recognition/application/settings/clustering.py:151`
     - `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py:127`
     - `docs/tasks/4.0/4.11.0/clustering-regression-investigation.md:194`
     - `docs/tasks/4.0/4.11.0/clustering-regression-investigation.md:201`

### Medium

3. **Missing `curriculum_mode` flag**
   - The plan calls for a `curriculum_mode` flag in clustering settings, but no implementation exists.
   - Files:
     - `docs/tasks/4.0/4.11.0/implementation-plan.md:305`
     - `apps/prototype-description-service/recognition/application/settings/clustering.py:147`

4. **EMA update semantics differ from plan**
   - The plan describes batch-average EMA updates; production code updates `curriculum_t` per accepted identity.
   - `ClusterConfidenceTracker` exists but is only referenced by tests.
   - Files:
     - `apps/prototype-description-service/recognition/application/persistence/assignment_writer.py:475`
     - `apps/prototype-description-service/recognition/application/settings/adaptive.py:115`
     - `apps/prototype-description-service/recognition/tests/unit/test_curriculum_thresholds.py:12`

### Low

5. **Docstring now misleading**
   - The ConfidenceCheck header still claims early-stage thresholds are strict, but current logic is lenient for COLD/NASCENT clusters.
   - File: `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py:4`

## Open Questions

1. Should mature clusters become stricter (per plan) or more lenient (current implementation)?
2. Do we want to adopt the investigation’s defaults (`suggestion_floor=0.65`, `curriculum_t=0.5`) or update the investigation doc?
3. Should `curriculum_mode` be implemented, or removed from the plan?
4. Should `ClusterConfidenceTracker` be wired into production for batch-based updates?

## Notes

- No test or runtime verification was performed for these findings; this file reflects static code/document review only.
