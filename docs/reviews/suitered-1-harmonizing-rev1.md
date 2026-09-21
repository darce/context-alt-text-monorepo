VERDICT: MERGE

# SUITERED-1 harmonizing review (rev1)

POR: {"file_count": 26, "line_count": 4198, "md5": "97a1c0d899b1a16b6dff1f352f3a4306", "sample_lines": {"173": "++        f\"{_RECEIPT_PREFIX}-{os.getpid()}-{time_ns()}.json\"", "41": "-@@ -501,14 +496,21 @@ def _rebuild_post_accept_typed_error("}}

Subject `feature/suitered-1` at tip `c7d7d0e0e401382265f65c31f82efc5ad989a937`, integrating to `main` at
`b2de2ae8a24caecb31b1587b024acc67e6e57527`. This is the single harmonizing gate review: the branch's own
defect findings were adjudicated in earlier passes and are closed in the handoff DB (0 open on the task ref).
Scope here is deliberately narrow — the merge risk carried by the production-code delta, plus whether the
branch introduces new suite red.

## Method

The diff touches 25 files, of which only four are non-test, non-doc:
`db/models/identity.py`, `pyproject.toml`, `recognition/application/scan/service.py`, and
`recognition/infrastructure/repositories/cluster_repository.py`. Each was read in full. Suite behaviour was
established by diffing full-suite failure SETS (branch vs main), not by comparing counts, because counts
alone cannot distinguish a fixed test from a newly-broken one.

## Production delta assessment

**`identity.py` — `__mapper_args__ = {"eager_defaults": True}` on `IdentityCluster`.** Correct repair for the
server-default class of bug: server-side defaults are populated at FLUSH, and `expire_on_commit=False` does
not cover them, so an async consumer touching a defaulted column after commit triggers a lazy refresh and
raises `MissingGreenlet`. `eager_defaults` makes SQLAlchemy fetch defaults via RETURNING on insert. Postgres
supports RETURNING, so the cost is bounded and there is no extra round trip. Sound.

**`pyproject.toml` — `required_plugins = ["pytest-timeout"]`.** This is the highest-value line in the diff.
Without it, a `pytest` invocation lacking the plugin does not error: it emits `PytestConfigWarning: Unknown
config option: timeout` and runs the suite completely UNBOUNDED, silently voiding the `timeout = 300` bound
directly below it. The bound existed but was inert, which is precisely the failure mode of an artifact that
emits a well-formed value without performing the work. `required_plugins` converts that into a loud
collection-time failure. Correct, and the inline comment states the reasoning accurately.

**`scan/service.py` — reentrant in-process persist lock.** The ownership guard
(`_persist_lock_owner_matches`) requires sync_session identity AND root-transaction identity AND
`reentry_depth > 0`, so identity alone cannot grant a reentrant pass. Two teardown orderings were checked
specifically: (a) `_release` clears `owner_sync_session`/`owner_root_transaction` and zeroes `reentry_depth`
before releasing, so a nested holder whose outer transaction already ended fails the owner match and cannot
decrement `reentry_depth` below zero; (b) `_capture_owner` refuses to re-arm when `released` is set or an
owner is already recorded, which closes the window the inline comment names — `event.remove` is deferred to
the next loop tick, so the listener outlives its own critical section and a re-arm would hand a stale owner
a pass into a lock a waiter now holds. The reentrant branch returns before `waiters` is incremented and does
not release the lock on exit, which is the correct pairing. No defect found.

**`cluster_repository.py` — `hasattr(model, "centroid_data")` to `"centroid_data" in state.dict`.** This
converts a force-load into a loaded-only read, so it was traced rather than accepted: `_to_domain` has 12
call sites, and only two of the feeding queries eager-load `centroid_data` (one pre-existing at L304, one
added by this branch at L1642). That would be a silent data-omission on the other ten paths — `centroid`
returning None instead of a vector, with `merge_suggestions.py` and `merge_candidates.py` branching on
`centroid is not None` and therefore degrading quietly rather than erroring. It is NOT a defect, because the
relationship is declared `lazy="joined"` (`identity.py:236-243`), so `centroid_data` is eager-joined on every
query path and `state.dict` is populated regardless. Recorded below as F1 for the latent fragility only.

## Suite evidence

Failure sets were compared directly. Every failure observed on the branch also fails on `main`; the branch
introduces no new red. Two node ids initially appeared branch-only and both proved to be linked-worktree
provisioning gaps in GITIGNORED files rather than code: the root worktree carries an untracked
`.env` that the linked worktree never received (so the two trees pointed at different database config, and
`test_heal_refuses_wrong_table_vector_typmod` ran on one and skipped on the other), and the 37MB
`face_recognition_sface_2021dec.onnx` is matched by `models/.gitignore` and exists only in the root
worktree. After provisioning both into the branch worktree, the heal test skips exactly as it does on main.
The remaining failures are pre-existing and are recorded as SUITERED-1-PX-01..04 in the handoff DB, all
deferred to wave SUITERED-2 — chiefly the macOS/APFS EILSEQ latin-1 path fixtures, a test patching a
renamed router symbol, and a genuine idempotency-contract failure that returns 202 where 409 is required.
None of those is a regression from this branch.

## Findings

- F1 (LOW) — `cluster_repository._to_domain` now reads `centroid_data` only when already loaded, and ten of
  its twelve feeding query paths do not eager-load it explicitly. Correctness today rests entirely on the
  `lazy="joined"` declaration in `identity.py`. Failure scenario: a future change to that relationship (to
  `lazy="select"`, `lazy="raise"`, or a `noload`/`raiseload` option on one of the ten queries) makes
  `IdentityCluster.centroid` silently None on those paths; `merge_suggestions.py:377-389` and
  `merge_candidates.py:291` branch on `centroid is not None`, so merge suggestions would quietly degrade to
  the fallback embedding path and produce different clustering output with no error raised anywhere. Suggest
  either asserting loaded-ness in `_to_domain` or adding the explicit `selectinload` to the remaining paths.

- F2 (LOW) — Linked worktrees are not provisioned with the gitignored assets the suite needs (`.env`, the
  two ONNX model files). Failure scenario: any agent or operator running the suite in a linked worktree sees
  failures that do not exist on main, and — as happened during this very review — can misread them as
  regressions introduced by the branch under test, or conversely dismiss a real regression as "just the
  worktree". Suggest a provisioning step in the worktree-creation helper that copies or symlinks the
  gitignored asset set.

## Conclusion

The production delta is four changes, each independently justified and none carrying a merge blocker. The
branch strictly reduces suite red relative to main and introduces no new failing test. Merge.

## Addendum — rev1 re-bind at `0021dd815`

The subject tip advanced by one commit after the first staging. The delta is
`git diff --stat c7d7d0e0e 0021dd815` = one file, `+12 / -122`, entirely
`docs/operator/harness-patch-filter-test-output.md`. No production file, test,
or config changed, so the production-delta assessment above stands unmodified.

**What the commit does.** That operator report has carried three unresolved
conflict regions from `ac881abe` since before this branch existed; the markers
are present on `main` and the file was byte-identical between `main` and this
branch, so the branch did not introduce them. The merge gate's tip scan
(`^(<{7,} |>{7,} )`) refuses any branch whose tip contains them, which made the
defect a blocker for every merge rather than for this one. It was resolved
rather than waived past the `WORKBAY_ALLOW_CONFLICT_MARKERS` escape hatch,
per [sr-001] — do not relax a compliance check to silence a violation.

**Resolution reviewed.** The HEAD side is a strict structural superset (it adds
the §0 scope split, the §1.1-1.6 breakdown, and §4's per-item exit criteria), so
it forms the base. Four pieces unique to the `ac881abe` side were grafted back
rather than dropped: the patch-shape description sentence, the four
`TestEdgeCases` test names, the harness-contract lesson, and the rollout steps
for repos that copied the hook. 335 -> 225 lines. `grep -cE '^(<{7,} |>{7,} )'`
returns 0; the single residual `=======` match is the pytest summary banner,
which the gate pattern does not match.

**Suite evidence at the re-bound tip.** Because the delta is docs-only, the
suite evidence recorded against `c7d7d0e0e` applies unchanged to `0021dd815`:
`6737 passed, 60 skipped, 29 deselected, 3 xfailed in 295.88s`, where the 29
deselections are the pre-existing failures enumerated in the Suite evidence
section and proven non-regressive by failure-set diff against `main`
(`comm -13 main branch` is empty).

No new finding. Verdict unchanged.
