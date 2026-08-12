# VLM-6 Wave E · Lane wE3 report — `promote_atomic.py` journal trust + lock scope

**Branch:** `fix/we3`  
**Base:** `88ed0e524bea8ee625afd405ca7f551d8ae1b5ba`  
**Owned files:** `promote_atomic.py`, `test_vlm_promote_atomicity.py`  
**Findings:** RC-01, RC-02, RC-03, RC-04, RC-05, CDX-04, CDX-05, RE-02  

cx3 credit: same-namespace promote serialisation and no self-deadlock in the traced
call graph hold (RC/CDX). This lane only hardens journal trust + cross-namespace
temp/lock scope.

---

## 1. Per finding

### RC-01 — journal `stage` trusted → external tree install+delete (high)

**Reproduction (unfixed, verbatim):**

```
=== RC-01 stage-escape external delete ===
before victim=['man.json', 'precious.txt', 'rep.json', 'run.json']
recover: no raise
after dest={'man.json': 'EVIL_man.json', 'run.json': 'EVIL_run.json', 'rep.json': 'EVIL_rep.json'}
victim.exists()=False
precious survived=False
```

**RED (validation bypassed mutant re-confirmed):**

```
victim.exists()=False precious=False
dest man=EVIL_man.json
RED confirmed: external tree destroyed
```

**Fix:** `_validate_stage_path` — stage must resolve under `dest`, be a direct
child, and basename must start with `ns.stage_prefix`. Refuse with `PromoteError`
before any install or `_finish_cleanup` delete.

**GREEN (post-fix, verbatim):**

```
PromoteError: ... stage escapes dest: stage='.../important_data' ... refuse to install from or delete external tree (RC-01)
victim.exists()=True precious=True
dest man=OLD_man.json
```

Test: `test_rc01_hostile_stage_refuses_and_preserves_external`,
`test_rc01_stage_wrong_prefix_refused`.

---

### RC-02 — unhashable `phase` → `TypeError` (medium)

**Reproduction (unfixed):**

```
=== RC-02 unhashable phase ===
TypeError: unhashable type: 'list'
journal=True stage=True
```

**RED:**

```
TypeError: unhashable type: 'list'
RED confirmed
```

**Fix:** `_validate_phase` requires `isinstance(phase, str)` before frozenset
membership; non-strings take the same `PromoteError` unknown-phase path.

**GREEN:**

```
PromoteError: ... has unknown phase=['installing'] (allowed=['installing', 'staged']); ...
```

Test: `test_rc02_unhashable_phase_is_promote_error`.

---

### RC-03 — legacy refuse wedges; message names non-existent recover (medium)

**Reproduction (unfixed):**

```
legacy promote journal present at .../.vlm-anchor-promote.journal; refuse to proceed — operator must reconcile pre-namespace-split crash state (recover under the old layout, then remove the legacy journal). Silent ignore of a present promote journal is forbidden (VLM6-R2-B-01).
```

**Fix:** Keep hard refuse (sr-001). Rewrite message: no automated recovery; numbered
manual steps ending in `remove {legacy}` after reconcile; name real namespaced
journal filenames. No fake “old layout recover” API (`rg-006`).

**GREEN:**

```
... refuse to proceed. There is no automated recovery for pre-namespace journals. Manual steps: (1) inspect ... (4) remove ... only after that manual reconcile to clear the block. Namespaced journals use '.vlm-caption-anchor-promote.journal' / '.vlm-face-anchor-promote.journal'. ...
has fake recover API: False
```

Test: `test_rc03_legacy_message_names_real_clear_path` (also proves clearable after `rm`).

---

### RC-04 — path-like `names` → `FileNotFoundError` wedge (low)

**Reproduction (unfixed):**

```
raised FileNotFoundError: [Errno 2] No such file or directory: '.../dest/.sub/../../escape_target.json.promoting'
journal preserved=True
stage preserved=True
```

**Fix:** `_validate_promote_names` / `_is_plain_basename` — refuse separators, `..`,
non-strings with `PromoteError` at journal load and `atomic_promote` entry.

**GREEN:**

```
PromoteError: ... unsafe promote name 'sub/../../escape_target.json' — must be a plain basename ...
```

Tests: `test_rc04_pathlike_names_refuse_promote_error`,
`test_rc04_pathlike_names_refuse_on_atomic_promote`.

---

### RC-05 — ghost installing + missing stage incomplete guidance (low)

**Reproduction (unfixed):**

```
attempt 0: blocked: phase=installing but stage dir missing: ...
  mentions journal_name=False
  mentions remove/rm=False
```

**Fix:** Error includes `journal={journal_path}` and explicit operator clear:
remove journal after manual reconcile; do not remove if stage may still be recoverable.

**GREEN:**

```
phase=installing but stage dir missing: ... (journal=.../.vlm-caption-anchor-promote.journal ...); ... remove ... to clear the block; do not remove if stage may still be recoverable (RC-05)
names journal: True
```

Test: `test_rc05_ghost_installing_names_journal_and_clear_path` (clearable after unlink).

---

### CDX-04 — caption/face share `.<stem>.promoting` (high)

**Reproduction (unfixed concurrent):**

```
caption: tmp pattern = .shared-stem.json.promoting  (no ns/pid)
face: tmp pattern = .shared-stem.json.promoting  (no ns/pid)
results={'caption': "FileNotFoundError: ... .shared-stem.json.promoting -> ...", 'face': 'ok'}
dest content=FACEION
```

**RED (shared-tmp mutant):**

```
errors=["FileNotFoundError: ... .shared-stem.json.promoting -> ..."]
hybrid_or_error=True
RED confirmed
```

**Fix:** `_promoting_tmp(dest, ns, name)` →
`.{generator}-{pid:x}-{name}.promoting` — unique per namespace + process, not stem.
Used in both recover install and `atomic_promote` install loops.

**GREEN:**

```
cap .caption-<pid>-stem.json.promoting
face .face-<pid>-stem.json.promoting
errors=[] final_ok=True len=4160
```

Tests: `test_cdx04_promoting_tmp_is_namespace_scoped`,
`test_cdx04_concurrent_caption_face_same_stem_no_hybrid`.

---

### CDX-05 — `names` can replace lock inode (medium)

**Reproduction (unfixed):**

```
atomic_promote of lock name: SUCCEEDED (bug)
lock content after: 'NEWLOCKBODY'
```

**RED (validation bypassed):**

```
lock after='NEWLOCK'
RED confirmed
```

**Fix:** `_validate_promote_names` rejects reserved basenames (both locks, both
journals, legacy journal, stage-prefix names, `*.promoting` / `*.tmp`).

**GREEN:**

```
PromoteError: atomic_promote: reserved promote name '.vlm-caption-promote.lock' collides with lock/journal infrastructure ... (CDX-05)
lock content='OLD'
```

Tests: `test_cdx05_reserved_lock_name_refused`,
`test_cdx05_reserved_journal_name_refused`.

---

### RE-02 — journal uniqueness test is source greptest (medium)

**Reproduction (reviewer + local):** grepping `uuid`/`getpid` + banning exact
`f".{ns.journal_name}.tmp"` stays green under concat fixed-tmp mutant
`dest_dir / ("." + ns.journal_name + ".tmp")`.

**Fix:** Replace greptest with behavioural observation of runtime tmp paths under
concurrent writers (`test_vlm6_r2_b02_journal_tmp_is_unique_behavioural`).
Control mutant test `test_vlm6_r2_b02_journal_tmp_fixed_mutant_goes_red` proves
fixed-tmp collides (TEST-15).

**GREEN:** both tests pass; mutant asserts `len(set(tmp_paths)) < n_writers`.

---

## 2. Disagreements

**None.** Every owned finding reproduced on base `88ed0e52` before fix.

cx3 same-namespace flock / no self-deadlock: agreed (not re-litigated; residual
issues were journal trust + cross-namespace temp/reserved names only).

---

## 3. New findings (not owned)

| Id | Note |
| --- | --- |
| wE3-N1 | Concurrent caption+face promote of the **same final basename** is still last-writer-wins on the dest path (by design under separate locks). Namespaced temps prevent byte-hybridization; generators should keep stems/artifact names disjoint. Out of scope to add a global dest lock without generator ownership (wE2 owns generators). |

---

## 4. Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1350 passed, 4 skipped` (~301s)

Baseline at base commit: `5 failed, 1338 passed, 4 skipped`.

### Expected-red (anchor-freeze byte-identity — not this lane)

- `test_generator_regenerates_byte_identical_committed_anchor`
- `test_expect_report_matches_committed_freeze_green`
- `test_face_generator_regenerates_byte_identical_committed_anchor`
- `test_face_expect_report_matches_committed_freeze_green`
- `test_cli_score_face_expect_report_end_to_end_green`

No bakeoff-results regeneration. No new published fields → freeze red set unchanged
at 5 (pass count +12 from new promote tests).

### Unexpected-red

**None.**

---

## 5. `git diff --stat` against base

```
 apps/prototype-description-service/scene/tests/test_vlm_promote_atomicity.py | 379 ++++-
 apps/prototype-description-service/scripts/eval_harness/promote_atomic.py    | 241 +++-
 2 files changed, 586 insertions(+), 34 deletions(-)
```

(Report file committed separately; not in the code diff above.)

---

## 6. Could not verify

- Multi-process (not just multi-thread) CDX-04 stress under load — thread stress +
  distinct tmp basenames are sufficient for the shared-temp hybrid class; full
  process-pool stress not re-run (cx3 already process-validated same-namespace flock).
- `workbay_handoff_mcp` unavailable in this lane environment (`ModuleNotFoundError`);
  deliverable is this `.s2a` report + commits on `fix/we3`.

---

## 7. Cross-lane requests

| To | Request |
| --- | --- |
| wE2 (`generate_determinism_anchor.py` / face twin) | Optional hardening: ensure caption vs face default stems / run-record basenames cannot collide under a shared `out_dir` even when the user passes the same `--stem`. Promote temps are now namespace-scoped; final dest last-writer-wins remains if basenames match. |
| (none to wE1/wE4/wE5/wE6) | — |
