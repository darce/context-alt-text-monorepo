# Lane `fx2` — journaled promote protocol: durability holes + de-duplication

**Branch:** `fix/fx2` (forked from `feature/vlm-6` @ `b28e126e`)  
**Commits:**
- Slice 1: `0d4f1ed882776c76383d74bda352b1acf4eea13a` — extract shared promote + RV2-01/02/03 + RV3-02/03
- Slice 2: `eba9cf2885c9af0d0b3481a7871d354c90f47dcf` — RV2-04/05/07 CLI + scavenge

**Owned files touched:**
- `scripts/eval_harness/promote_atomic.py` (**new** shared module)
- `scripts/eval_harness/generate_determinism_anchor.py`
- `scripts/eval_harness/generate_face_determinism_anchor.py`
- `scene/tests/test_vlm_promote_atomicity.py`
- `scene/tests/test_describe_baseline_pin_provenance.py` (CLI/pin tests for RV2-04/05)
- `.s2a/vlm6-fx2-report.md` (this report)

**Findings fixed:** HARM-02, RV2-01, RV2-02, RV2-03, RV3-02, RV3-03, RV2-04, RV2-05, RV2-07

**Full suite:** `1289 passed, 4 skipped` (see §5)

---

## 1. Per finding

### HARM-02 (medium) — protocol implemented twice

**Change:** Extracted `scripts/eval_harness/promote_atomic.py` with `atomic_promote`, `recover_promote`, `PromoteNamespace`, `CAPTION_PROMOTE`, `FACE_PROMOTE`. Both generators import the same symbols and wrap with their namespace.

**Structural share assert:**
```python
assert cap._atomic_promote_core is face._atomic_promote_core
assert cap._atomic_promote_core is atomic_promote
```
(`test_harm02_caption_and_face_share_promote_impl`)

**RED:** Pre-extraction, `inspect.getsource` equality was `False` (reviewer). A re-clone would make `_atomic_promote_core` identity fail.

**GREEN:** 12 promote tests + HARM-02 identity test pass.

---

### RV2-01 (high) — corrupt journal deletes its own evidence

**Change:** `_load_journal` raises `PromoteError` on `JSONDecodeError`/`OSError` and **never unlinks**. Message names journal path, generator, dest.

**RED (old path mutant):**
```
after old path journal exists: False  [RED: evidence destroyed]
```

**GREEN (fixed):**
```
raised PromoteError: unparseable promote journal at .../.vlm-caption-anchor-promote.journal ...
journal still exists: True
content preserved: '{truncated'
```
Test: `test_rv2_01_corrupt_journal_refuses_and_preserves_evidence`

---

### RV2-02 (high) — incomplete stage leaves dest mixed then success

**Change:** In `phase=installing`, collect missing staged names; if any, `PromoteError` **before** any teardown. Only after every name installs do we drop stage+journal. Docstring restored to a true claim.

**RED (old continue+teardown mutant):**
```
after old recovery state={'man.json': 'NEW_man.json', 'run.json': 'NEW_run.json', 'rep.json': 'OLD_rep.json'}
mixed=True, journal/stage gone, reported success
```

**GREEN:**
```
raised: phase=installing incomplete stage ... missing ['rep.json'] ... refuse to leave dest mixed
journal preserved: True
stage preserved: True
```
Test: `test_rv2_02_incomplete_stage_installing_is_fatal`

---

### RV2-03 (high) — caption and face share one journal namespace

**Change:**
| | caption | face |
|---|---|---|
| journal | `.vlm-caption-anchor-promote.journal` | `.vlm-face-anchor-promote.journal` |
| stage prefix | `.vlm-caption-promote-stage-` | `.vlm-face-promote-stage-` |
| generator stamp | `"caption"` | `"face"` |

Recovery asserts `journal["generator"] == ns.generator` before acting.

**RED (old shared-namespace mutant):**
```
old shared recover installed face artifacts under caption authority: all NEW
```

**GREEN:** Face journal ignored by caption recover (different filename); foreign generator field under caption journal name → `PromoteError: generator mismatch`.
Test: `test_rv2_03_foreign_generator_journal_refused`

---

### RV3-02 (high) — face promote zero crash coverage

**Change:** `test_s4_02_crash_mid_install_recover_yields_all_new` parametrized over caption **and** face wrappers; patches `promote.os.replace` at the shared module. HARM-02 identity assert keeps it one implementation.

**RED (bare loop, no journal):**
```
mid mixed=True after recover mixed=True
after={'man.json': 'NEW_man.json', 'run.json': 'OLD_run.json', 'rep.json': 'OLD_rep.json'}
RED (face bare-loop): assert all-new FAILS: True
```

**GREEN:** Parametrized crash test passes for both `caption` and `face` ids.

---

### RV3-03 (medium) — clean-promote cannot fail when journaling removed

**Change:** Spy on `_write_promote_journal`; assert both `phase=staged` and `phase=installing` observed mid-flight **and** journal file exists on disk after each write. Post-state alone is no longer sufficient.

**RED (bare replace loop):**
```
phases_seen=[] (empty → 'staged' not in phases FAILS)
RED assert: staged in phases → False
```

**GREEN:** `test_s4_02_clean_promote_leaves_no_journal` sees both phases.

---

### RV2-04 (high) — `--live-head-sha` accepts anything

**Change:** `validate_live_head_sha` in shared module (local S4-06 equivalent — see cross-lane). CLI `main` and `write_anchor` (when `live_head_sha is not None`) call it. Refuses: forty zeros, non-40-hex, non-hex. Optional `--verify-live-head-sha` runs `git rev-parse --verify <sha>^{commit}`.

**RED (old path):**
<!-- sha-guard:ignore-next-block -->
```
OLD accepts '0000000000000000000000000000000000000000' → stamped as head_sha
OLD accepts 'deadbeef' → stamped as head_sha
OLD accepts 'None' → stamped as head_sha
OLD accepts 'not-a-sha-at-all!!!' → stamped as head_sha
```

**GREEN:**
<!-- sha-guard:ignore-next-block -->
```
refuse '0000…0000': … fabricated 40-zero sentinel …
refuse 'deadbeef': … must be a 40-char lowercase hex git SHA …
refuse 'None': …
refuse 'not-a-sha-at-all!!!': …
```
Tests: `test_rv2_04_*` in `test_describe_baseline_pin_provenance.py`

---

### RV2-05 (medium) — empty `--live-head-sha` silently exits pin mode

**Change:**
1. Pin mode gated **only** on explicit `--pin` / `--no-pin` (`BooleanOptionalAction`, default True) and `pin_live_provenance` flag — **not** on `live_* is None`.
2. Empty/whitespace `--live-head-sha` → `SystemExit` at parse.
3. `--live-head-sha` / `--live-started-at` with default pin → require `--no-pin`.

**RED (old gate):**
```
old gate pin_active=False with live_head_sha='' → exits pin, injects wall-clock
```

**GREEN:**
```
empty refused: --live-head-sha must not be empty; …
pin_live_provenance=True alone → pin active regardless of live_*
```
Tests: `test_rv2_05_*`

---

### RV2-07 (low) — orphaned stage directories never scavenged

**Change:** `scavenge_orphan_stages(dest, ns, max_age_sec=3600)` called at start of `write_anchor` / `write_face_anchor`. Removes stage dirs matching the generator prefix older than the bound with **no** matching journal reference. Corrupt journal → protect all stages (never destroy recovery evidence). Logs reclaimed paths.

**RED:** Without scavenge, orphan stage remains forever in bakeoff-results.

**GREEN:**
```
GREEN scavenge reclaimed=[.../.vlm-caption-promote-stage-left-behind] exists=False
```
Tests: `test_rv2_07_scavenge_*`

---

## 2. The extraction (HARM-02)

| Symbol | Role |
|---|---|
| `PromoteNamespace` | frozen dataclass: `generator`, `journal_name`, `stage_prefix` |
| `CAPTION_PROMOTE` / `FACE_PROMOTE` | distinct namespaces |
| `atomic_promote(src, dest, names, ns)` | journaled set promote |
| `recover_promote(dest, ns)` | crash recovery |
| `scavenge_orphan_stages(...)` | RV2-07 |
| `validate_live_head_sha(...)` | RV2-04/05 |
| `PromoteError` | fatal recover/promote refuse |

**Generators import:**
```python
from scripts.eval_harness.promote_atomic import (
    CAPTION_PROMOTE,  # or FACE_PROMOTE
    atomic_promote, recover_promote, ...
)
_atomic_promote_core = atomic_promote  # structural re-export
def _atomic_promote(src, dest, names):
    atomic_promote(src, dest, names, _PROMOTE_NS)
```

---

## 3. Findings disagreed with

None. All nine reproduced; RED mutants confirmed each.

---

## 4. Freeze bytes

**No freeze regeneration performed** (per wave instruction). Protocol changes do **not** alter freeze *content* bytes — only journal/stage filenames under bakeoff-results during promote. fx5 regen is unaffected by content; if any old in-progress journal used the pre-namespace name (`.vlm-anchor-promote.journal`), it is no longer auto-recovered (operator must reconcile once). No committed freeze paths rewritten by this lane.

---

## 5. Full suite result

```
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
# 1289 passed, 4 skipped, 31 warnings in 189.96s (0:03:09)
```

No determinism-anchor failures in this worktree.

---

## 6. `git diff --stat` against `b28e126e`

```
 .../tests/test_describe_baseline_pin_provenance.py | 113 +++++++
 .../scene/tests/test_vlm_promote_atomicity.py      | 287 +++++++++++++++--
 .../eval_harness/generate_determinism_anchor.py    | 192 ++++--------
 .../generate_face_determinism_anchor.py            | 138 ++------
 .../scripts/eval_harness/promote_atomic.py         | 348 +++++++++++++++++++++
 5 files changed, 805 insertions(+), 273 deletions(-)
```

---

## 7. What could not be verified

- **`git rev-parse` verify path** (`--verify-live-head-sha`): implemented; not exercised against a real foreign SHA in CI (would need a known-good and known-bad commit in the clone). Format-level refuse fully tested.
- **Live mid-fsync crash on journal write** producing a truncated journal: simulated via hand-written corrupt file (same recovery arm).
- **Concurrent caption+face promote race** under real multi-process load: namespace separation unit-tested only.

---

## 8. Cross-lane requests

| To | Request |
|---|---|
| **fx4** (`describe_baseline.py`) | `validate_live_head_sha` in `promote_atomic` mirrors `resolve_head_sha`. Prefer a single shared helper (e.g. move format guard to a tiny `provenance_sha.py` or export from describe_baseline and import in generators). Flagged duplication for this wave. |
| **fx5** (freeze regen) | No freeze content change from fx2. Journal filenames changed — only matters for interrupted in-progress promotes mid-wave. Regen freezes after fx1 metrics land as planned. |
| **coordinator** | Integrate after fx1 if freezes depend on metrics; promote protocol is independent of metric numbers. |

---

## Heuristics cited

`TEST-15`, `AUDIT-07`, `EVAL-23`, `rg-002`, `rg-006`, `rg-008`, `rg-015`, `sr-001`, `sr-006`
