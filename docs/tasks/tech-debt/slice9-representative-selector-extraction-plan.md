# Slice 9 increment 3 — RepresentativeSelector extraction (task plan)

**Task:** `MAINT-descsvc-deadcode-20260613` · **Branch:** `feature/maint-descsvc-deadcode-20260613`
**Status:** planned · **Predecessor:** increment 2 `CentroidMaintainer` (`ebd60730`, review PASS)
**Planning-review:** wrdc93fd3 (3-lens, adversarially verified) — findings SLICE9-PLAN-01/02/03 addressed in this revision.

## Objective

Extract the representative-selection concern out of the 1064-LOC `AssignmentWriter` god-class into a cohesive `RepresentativeSelector`, behaviour-preserving, mirroring the landed `CentroidMaintainer` extract-class + delegate pattern. Second half of the Slice 9 "AssignmentWriter split."

## Current-state defect found during planning (must be honoured, not silently "fixed")

`_should_add_representative` (`assignment_writer.py:609`) sets `self._last_decision_was_upgrade = True` at **:653** (inside `if upgrade_target:`), then **unconditionally resets it to `False` at :655** before any non-early-return path. The only earlier return is the user-selected guard at :641 (also `False`). Therefore `_last_decision_was_upgrade` is **always `False`** when the consumers read it via `getattr(self, "_last_decision_was_upgrade", False)` at `persist_assignment:443` and `persist_assignments_chunk:547`. Consequences **today**:

- `reason == "representative_upgrade"` is never chosen → the accepted-write reason is `"diverse_addition"` (or `"novel_pose_addition"`) even when a quality upgrade physically occurred (`remove_representative(upgrade_target.id)` at :643 still runs — the *upgrade itself happens*; only its label/event is suppressed).
- The `if is_upgrade and self._run_context:` block emitting `event_type="representative_upgraded"` (:456-465) is unreachable dead code.

**Asymmetry:** `_last_decision_was_novel_pose = True` at :674 is followed by an *immediate* `return True, cached_reps` at :675, so the novel-pose path **is** reachable and correct. Only the upgrade flag is dead. This is an observability bug (wrong reason + missing event), not a clustering-correctness bug.

**No test pins it.** `rg` over `recognition/tests/` finds zero assertions on `representative_upgrade` / `novel_pose_addition` / `diverse_addition` / `representative_upgraded`; existing tests assert only the `QUALITY_UPGRADE` log line and the `representative_selected` event-*type*. So nothing currently guards these values — the new 3a test is the sole guard.

## Decomposition (vertical, TDD, each independently mergeable)

### Sub-slice 3a — remove the `_last_*` temporal coupling (strictly behaviour-preserving)

The de-risking step; ships before any code moves. **Preserves observed behaviour, including the always-False upgrade flag.**

- Change `_should_add_representative` to return an explicit frozen dataclass `RepAdmission(should_add: bool, cached_reps: list[ClusterRepresentative], rep_count: int, was_upgrade: bool, was_novel_pose: bool)` instead of stashing `self._last_*`. **`was_upgrade` must reproduce the current observed value (always `False` at every return path) — do not "correct" it here.** `was_novel_pose` reproduces the current per-path value (True only on the :675 novel-pose return).
- Update `persist_assignment` (439-453) and `persist_assignments_chunk` (547-549) to read the returned `RepAdmission`. **Preserve each consumer's existing `existing_rep_count` source exactly:** `persist_assignment` passes `self._last_rep_count` (set at :625 = pre-upgrade-removal `current_count`) into `_create_and_add_representative(existing_rep_count=...)` at :453; the chunk path uses its own current value. If the two sources differ, `RepAdmission` carries the field each consumer needs — do **not** collapse them into one value that changes either path.
- Delete the three `self._last_*` attributes and their `getattr` reads after both consumers are migrated.
- **TDD (sole guard):** `test_should_add_representative_returns_admission` asserts, against CURRENT behaviour, all three reason-driving fields: upgrade-target case → `was_upgrade is False` (documents the latent bug), novel-pose case → `was_novel_pose is True`, plain diverse case → both `False`; and that `rep_count` equals the value the corresponding consumer passes today. RED before `RepAdmission` exists.
- Verification: representative/cluster/centroid suites stay green; ruff; targeted suite. (Note: existing suites do *not* assert reason values — the new test is what pins them.)
- Evidence anchor: `assignment_writer.py:609` (`_should_add_representative`), `:439`-`453`/`:547`-`549` (consumers), decision `claude_slice_complete_slice9_3a_*`.

### Sub-slice 3a-fix — upgrade-flag bug fix (SEPARATE, behaviour-CHANGING, own review)

Not part of the behaviour-preserving refactor. Carve out only after 3a lands.

- Fix `_should_add_representative` so a real quality upgrade reports `was_upgrade=True` (move/guard the `:655` reset so it does not clobber the True set at :653), restoring `reason == "representative_upgrade"` and the `representative_upgraded` event.
- TDD: an **event-reason regression test** asserting that an upgrade decision yields `reason == "representative_upgrade"` and emits one `representative_upgraded` run-context event; a non-upgrade yields `diverse_addition`/`novel_pose_addition` and no upgrade event.
- This is a user-visible observability change → its own slice, its own review verdict, explicitly flagged as behaviour-changing.

### Sub-slice 3b — extract the `RepresentativeSelector` (selection surface, not "pure")

- New `recognition/application/persistence/representative_selector.py`: `RepresentativeSelector(settings, cluster_repository)` owning the selection surface — the 7 module-level helpers (`_compute_identity_quality`, `_select_diverse_representatives`, `_is_novel_pose`, `_find_upgradeable_representative`, `_get_pose_bucket`, `_normalize_embedding`, `_compute_fingerprint`) + `_should_add_representative` (now stateless after 3a) + `_select_diverse_representatives_seeded` + `_select_reps_to_preserve`. **These are not pure functions** — `_should_add_representative` issues a repo write (`remove_representative` at :643) and `_select_reps_to_preserve` reads the repo (:699); the class therefore legitimately takes `cluster_repository`.
- `AssignmentWriter.__init__` builds `self._reps = RepresentativeSelector(settings, cluster_repository)`; corresponding methods become thin delegators (or call sites repoint to `self._reps`).
- TDD: `test_representative_selector.py` pins the admission decision + diverse-selection math directly. RED before module exists.
- Verification: representative/cluster/curation/split suites green; import smoke (selector imports `domain.*` + `application.settings`, never `assignment_writer` → no cycle).
- Evidence anchor: new `representative_selector.py`, decision `claude_slice_complete_slice9_3b_*`.

### Sub-slice 3c — (design-decision, default DEFER) relocate the repo-writing rep orchestration

`recompute_representatives` (clear+select+persist+update cluster) and `_create_and_add_representative` (writes a rep + emits a run-context event) are persistence orchestration. Review-decided options:
- (i) **default/recommended:** keep them on `AssignmentWriter`, calling `self._reps` for selection sub-steps — `AssignmentWriter` stays the single persistence entry point; smaller blast radius. Defer 3c.
- (ii) move them onto `RepresentativeSelector` (needs `run_context` + write access; larger, more cohesive "representative lifecycle" object).

## Out of scope

- The `ClusterRepository` Protocol prefix-seam split — HIGH risk, DOMAIN-5 refuted the broad split (~20 direct consumers); separate plan + go-ahead.
- Any change to selection thresholds, accepted-write idempotency, or event payloads — except the explicitly-scoped 3a-fix.

## Risks & mitigations

- **Reason/event regression in 3a** (the central planning-review finding): mitigated by making 3a reproduce the always-False upgrade flag and by the new direct unit test that pins all three reason fields at current behaviour. The bug fix is isolated to 3a-fix with its own regression test. No existing suite guards these values, so the new tests are mandatory, not optional.
- **`existing_rep_count` per-consumer divergence**: `RepAdmission` preserves each consumer's exact current source; verify both call sites in 3a.
- **Hidden state on `AssignmentWriter`** beyond the three mapped attrs → repo-wide `rg "_last_"` before 3b (currently only the three).
- **Import cycle** → selector depends downward only; import smoke, as with `CentroidMaintainer`.
- **Hot-path blast radius** (14 production importers of `AssignmentWriter`, ~29 incl tests) → no merge without representative/cluster/split/curation suites green at HEAD; pre-merge gate unchanged.

## Convergence

3a lands behaviour-preserving (always-False upgrade flag faithfully reproduced) with the new direct reason/admission test; 3a-fix optionally restores the upgrade reason/event as a separate reviewed behaviour change; 3b extracts the selection surface; 3c decided (default defer). Each sub-slice: failing test first, targeted suites green, slice-complete decision recorded.
