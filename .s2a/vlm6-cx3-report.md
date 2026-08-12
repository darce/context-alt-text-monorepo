# VLM-6 Wave C · lane cx3 — promote durability, crash safety, concurrency

**Branch:** `fix/cx3`  
**Worktree:** `~/lane-gx4`  
**Base:** `7812d71c832786328705a8d6ea6e1d7f41dc487b`  
**Owned files:**
- `apps/prototype-description-service/scripts/eval_harness/promote_atomic.py`
- `apps/prototype-description-service/scene/tests/test_vlm_promote_atomicity.py`

**Not touched (as required):** `provenance_sha.py`, `generate_determinism_anchor.py`,
`test_describe_baseline_pin_provenance.py`, `report.py`, `cli.py`, `face_metrics.py`,
`scripts/check_lane_report_shas.py`, `README.md`, any anchor freeze.

Heuristics: TEST-15, TEST-06, DBG-10, DBG-11, DIAG-01, DIAG-03, rg-006, rg-015, sr-001, AUDIT-07.

---

## Finding 1 — VLM6-R2-B-03 (HIGH) — unknown phase destroys evidence

### Reproduction (verbatim match)

```
phase='INSTALLING': after={'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
LEFT_MIXED=True journal_gone=True stage_gone=True
```

Same for `phase=None`, `"unknown"`, `"staged "`. Pre-fix only special-cased exact `"installing"`; everything else fell through to abandon cleanup.

### RED capture

Pre-fix path (abandon on non-exact installing):

```
phase='INSTALLING': after={'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
LEFT_MIXED=True journal_gone=True stage_gone=True
```

Test: `test_vlm6_r2_b03_unknown_phase_preserves_evidence` (parametrized ×4).

### Fix

Allow-list `phase in {"staged", "installing"}` (`_KNOWN_PHASES`). Anything else raises
`PromoteError` naming the phase and **preserves** journal + stage. No tear-down on unknown.

### GREEN capture

```
FIXED raises: ... unknown phase='INSTALLING' (allowed=['installing', 'staged']); refuse to tear down...
FIXED preserve journal=True stage=True
```

---

## Finding 2 — VLM6-R2-B-01 (HIGH) — legacy journal silently ignored

### Reproduction

```
before {'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
after  {'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
legacy_still True stage_still True
SILENT_IGNORE_LEGACY= True
```

### RED capture

With `_check_legacy_journal` neutered (pre-fix behaviour): `SILENT_IGNORE_LEGACY=True`.

### Fix

On recover entry (and thus `atomic_promote` via recover): if
`.vlm-anchor-promote.journal` exists → `PromoteError` naming the path, requiring
operator reconcile. **No migrate** path (safer; no second crash surface). Scavenge also
protects all stages when legacy journal is present.

Constant: `LEGACY_PROMOTE_JOURNAL = ".vlm-anchor-promote.journal"`.

### GREEN capture

```
FIXED legacy raises: legacy promote journal present at .../.vlm-anchor-promote.journal; refuse to proceed...
```

Tests: `test_vlm6_r2_b01_legacy_journal_refused`, `test_vlm6_r2_b01_legacy_blocks_atomic_promote`.

---

## Finding 3 — VLM6-R2-B-02 (HIGH) — no lock; concurrent promote + scavenge

### Reproduction

```
scavenge ['.../.vlm-caption-promote-stage-A']
PromoteError: phase=installing incomplete stage at .../stage-B: missing ['run.json', 'rep.json'] ...
dest {'man.json': 'AAA_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
MIXED_STUCK= True

6a scavenge live stage without journal (aged): reclaimed=[...stage-live...] exists=False
DATA_LOSS_IF_CONCURRENT= True
```

50-thread stress (pre-fix / no-lock):

```
50 no-lock: errors=43 prefixes=['W45', 'W46', 'W48'] consistent=False HYBRID=True
  state={'man.json': 'W46_man.json', 'run.json': 'W48_run.json', 'rep.json': 'W45_rep.json'}
```

### Fix

1. **Exclusive per-namespace flock** (`.vlm-{generator}-promote.lock`) held across
   recover + promote + cleanup and scavenge (`_namespace_lock`).
2. Heartbeat (pid + wall time) written while held; scavenge skips stages newer than
   last heartbeat.
3. **Unique journal tmp**: `.{journal_name}.{pid}-{uuid}.tmp` (no more fixed
   `.{journal_name}.tmp` clobber).
4. Public APIs lock; internal `_recover_promote_unlocked` /
   `_scavenge_orphan_stages_unlocked` run under held lock (no re-entrant flock).

### GREEN capture

```
50 with-lock: errors=0 prefixes=['W48'] consistent=True HYBRID=False
  state={'man.json': 'W48_man.json', 'run.json': 'W48_run.json', 'rep.json': 'W48_rep.json'}
```

### TEST-15 lock necessity

`test_vlm6_r2_b02_lock_absence_goes_red` monkeypatches `_namespace_lock` to a no-op
and **requires** errors or hybrid dest. Passes only when absence of the lock is
observable as failure. A lock test that stays green with lock deleted would fail
this assert.

Also: `test_vlm6_r2_b02_concurrent_promotes_consistent` (50 threads),
`test_vlm6_r2_b02_scavenge_does_not_reclaim_under_live_lock`,
`test_vlm6_r2_b02_journal_tmp_is_unique`.

---

## Finding 4 — VLM6-R2-B-04 (MEDIUM) — journal clear not dir-fsynced

### Reproduction (ghost state)

```
recover raised: PromoteError: phase=installing but stage dir missing: .../ghost ...
next atomic_promote BLOCKED: PromoteError: phase=installing but stage dir missing: ...
```

### Fix

`_finish_cleanup(dest_dir, journal_path, stage)` order:

1. `_fsync_path(dest_dir)` — installs durable
2. `journal.unlink()`
3. `_fsync_path(dest_dir)` — journal clear durable **before** stage removal
4. remove stage

Used by both successful `atomic_promote` and successful `recover_promote`.

Note: if a ghost journal already exists (pre-fix crash), recover still raises —
correct; operator must delete the ghost. The fix prevents **forming** the
non-convergent state on clean success paths.

### GREEN / order spy

```
_fsync_path(dest_dir)
journal_path.unlink(missing_ok=True)
_fsync_path(dest_dir)
# then stage teardown
```

Tests: `test_vlm6_r2_b04_cleanup_fsyncs_dest_after_journal_unlink`,
`test_vlm6_r2_b04_recover_cleanup_order`.

---

## Finding 5 — VLM6-R2-E-01 (MEDIUM) — tautology mid-flight spy test

### Problem

`test_rv3_03_bare_loop_mutant_fails_midflight_spy` asserted on a local `phases_seen`
list that production never appends to. Always green under any mutant.

### Fix

- Shared helper `_observe_midflight_journal_phases` drives the real
  `_write_promote_journal` spy (same contract as clean-promote).
- Bare `os.replace` loop → phases `[]` → `pytest.raises(AssertionError, match="journal must")`
  on the staged/installing post-conditions.
- Never assert only on a collector production does not touch.

### RED (bare mutant)

```
AssertionError: journal must record phase=staged mid-flight; saw []
```

---

## Finding 6 — delegated cleanup: remove `verify_git` from `validate_live_head_sha`

### Fix

Final shipped signature:

```python
def validate_live_head_sha(
    raw: str | None,
    *,
    git_cwd: Path | None = None,
) -> str | None:
```

Git verify is always on (`normalize_head_sha(..., verify_git=True, ...)`). No
parameter remains for callers to pass. Does **not** honor a dead flag (would reopen
fabricated-SHA hole VLM6-R2-D-03).

Test: `test_vlm6_cx3_validate_live_head_sha_no_verify_git_param`.

### Cross-lane request → cx4

`generate_determinism_anchor.py:455-458` still calls:

```python
live_head = validate_live_head_sha(
    args.live_head_sha,
    verify_git=bool(args.verify_live_head_sha),
)
```

cx4 must drop the `verify_git=` kwarg (and the dead CLI flag). Until then, three
CLI tests in `test_describe_baseline_pin_provenance.py` are **expected-red**:

- `test_rv2_04_cli_refuses_bad_live_head_sha`
- `test_rv2_05_cli_refuses_empty_live_head_sha`
- `test_rv2_05_cli_live_head_requires_no_pin`

Error: `TypeError: validate_live_head_sha() got an unexpected keyword argument 'verify_git'`.

---

## Disagreements

None. All six findings reproduced as stated (F3 50-thread numbers vary slightly
trial-to-trial but always `with_errors ≫ 0` and often hybrid without the lock).

---

## New findings (not owned — not fixed)

1. **Ghost recover remains non-auto-heal** for pre-existing ghost journals. By design
   after B-04 (preserve evidence). Operators still need a one-line `rm` of the journal
   for historic ghosts. Optional follow-up: a documented `promote doctor` / explicit
   `--force-abandon-ghost` — out of scope.
2. **Legacy stage dirs** (`.vlm-promote-stage-*`) without a legacy journal are still
   invisible to namespaced scavenge. Only protected when the legacy *journal* is
   present. Adjacent, low urgency.

---

## Full suite

```
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `3 failed, 1317 passed, 4 skipped` (321s)

| Class | Count | Notes |
| --- | ---: | --- |
| Passed | 1317 | Baseline 1307 + cx3 tests − 3 cx4 call-site regressions among prior greens |
| Skipped | 4 | Unchanged |
| **Expected-red (cx4)** | 3 | `test_describe_baseline_pin_provenance.py` CLI tests — `verify_git=` kwarg in `generate_determinism_anchor.py` (cx4 owns both) |
| **Unexpected-red** | 0 | — |

Promote-only: `27 passed` in `test_vlm_promote_atomicity.py`.

---

## `git diff --stat` against `7812d71c`

```
 .../scene/tests/test_vlm_promote_atomicity.py      | 452 ++++++++++++++++++++-
 .../scripts/eval_harness/promote_atomic.py         | 330 +++++++++++----
 .s2a/vlm6-cx3-report.md                            | (this report)
```

---

## Could not verify

- Real power-loss / metadata reorder on journal unlink without fsync (requires
  disk fault injection). Order spy + source inspection stand in (TEST-15 on order).
- Concurrent scavenge vs promote under true multi-process (tests use threads +
  flock, which is process-aware; multi-process stress not run).
- Full suite green end-to-end after cx4 lands `verify_git` call-site removal.

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **cx4** | Update `generate_determinism_anchor.py` call site: `validate_live_head_sha(args.live_head_sha)` only — no `verify_git=`. Drop `--verify-live-head-sha` CLI flag. Final cx3 signature: `validate_live_head_sha(raw: str \| None, *, git_cwd: Path \| None = None) -> str \| None`. |
| **integrator** | Merge cx3 before or with cx4; if cx3 lands alone, expect 3 reds in pin-provenance CLI tests until cx4. |

---

## Commits

Separate commits: production durability+concurrency+signature; tests; this report.
