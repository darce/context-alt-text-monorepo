# VLM-6 S2A F8 — shared out/ artifact selection order-dependence

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6` (sandbox: history-stripped)  

**Scope (owned):**
- `scene/tests/test_eval_harness_cli.py` — exact artifact filenames + isolation + permanent decoy control

**Did not touch:** `cli.py` production `_determinism_artifact_dir()` (OBS-04), `report.py`,
`test_eval_harness_pipeline.py` (pinned), `golden.json`, caption
`S2A-determinism-anchor-run-20260811*` artifacts, face anchor generator/artifacts
(item 2 untouched), `describe_baseline.py`.

## Verdict

**merge_ready for F8 item 1.** Artifact content assertions no longer use
glob-index over the shared `scripts/eval_harness/out/` directory. Suite colour
is independent of readdir order. Item 2 (sunglasses / occlusion_other twins)
was **not started** — stop after item 1 per brief time budget.

## Defect (VLM6-S2A-F7-02)

F7-01 correctly moved mismatch diagnostics into gitignored
`scripts/eval_harness/out/`. That directory is shared across the whole test
session. Two tests write files matching the same glob:

| test | file | body claim |
| --- | --- | --- |
| `test_cli_score_determinism_guard_detects_mutated_persisted_anchor` | `…-seed0.diff.txt` | `baseline_regime=randomized` |
| `test_cli_score_determinism_fail_artifact_carries_baseline_regime` | `…-seed2.diff.txt` | `baseline_regime=fixed:0` |

The regime test selected `artifacts[0]` after
`_determinism_artifact_dir().glob("determinism-mismatch-score-seed*.diff.txt")`.
Which file lands at index 0 is host readdir order.

**Observed macOS (base F7):** `1 failed, 714 passed, 3 skipped` with
`assert 'baseline_regime=fixed:0' in "…baseline_regime=randomized…"`.  
**Observed Linux (same base):** `714 passed, 4 skipped, 0 failed`.  
Same commit, opposite colour → not a gate.

## Item 1 — fix (TEST-15 / DBG-11 / sr-001 / OBS-04)

### Changes

1. **Exact filenames, never glob-index for content**
   - Regime test → `determinism-mismatch-score-seed2.diff.txt` (parent
     `PYTHONHASHSEED=0` → child seeds `2,1,42`; first fail is seed 2).
   - Mutated-persisted-anchor existence check → `…-seed0.diff.txt` (randomized
     baseline; still points at **real** production `out/` — existence-only
     F7-01 location claim).
   - Hash-order gate (already on `tmp_path`) → `…-seed0.diff.txt`.

2. **Isolate content-asserting tests** via
   `monkeypatch.setattr(cli_mod, "_determinism_artifact_dir", lambda: tmp_path)`:
   - **Isolated:** `test_cli_score_determinism_fail_artifact_carries_baseline_regime`,
     `test_f8_determinism_artifact_content_ignores_shared_out_decoy`
     (hash-order already passed its own `artifact_dir=tmp_path`).
   - **Left on real production `out/`:**  
     `test_cli_score_determinism_guard_detects_mutated_persisted_anchor`  
     (asserts diagnostic lands under `out/`, not `tmp_path`),  
     `test_f7_01_mismatch_artifact_never_dirties_bakeoff_results`  
     (entire claim is about where shipped code writes — do not monkeypatch),  
     face/caption anchor ANCHOR_MISMATCH tests (exact path under real `out/`).

3. **Permanent decoy control**  
   `test_f8_determinism_artifact_content_ignores_shared_out_decoy`:
   - Plants seed0 decoy (`baseline_regime=randomized`) + poisoned seed2 in real `out/`.
   - Proves alphabetical/seed0-first selection of that glob would **fail** the
     `fixed:0` assertion (encodes the macOS RED mode).
   - Runs the regime fail path isolated to `tmp_path`, reads exact seed2,
     asserts `fixed:0` and that shared poison did not leak into the body.

Production `_determinism_artifact_dir()` and ANCHOR_MISMATCH messages unchanged
(OBS-04). No test weakened/skipped/xfailed (sr-001).

## Decoy control evidence (TEST-15 / DBG-11)

### Half A — old form + decoy on this Linux host (honest negative)

Pre-seeded
`scripts/eval_harness/out/determinism-mismatch-score-seed0.diff.txt` with
`baseline_regime=randomized`, restored the pre-F8 `artifacts[0]` selection,
ran the regime test:

```
.                                                                        [100%]
1 passed in 2.73s
```

**Honest negative:** on this Linux host, `Path.glob` / readdir returned
`seed2` **before** `seed0`, so the decoy alone did **not** turn the base red.
Native order observed:

```
glob order: seed2 (fixed:0), seed0 (randomized)
artifacts[0] would be: determinism-mismatch-score-seed2.diff.txt
```

The macOS RED is still real (reported at F7 base); this host's readdir just
happens to put the correct file first — which is exactly the
platform-dependence under repair.

### Half A′ — same two files, seed0-first ordering (RED)

With the same decoy + correct seed2 present:

```
alpha order: seed0, seed2
alpha[0] would PASS fixed:0 assert? False
RESULT: alphabetical (seed0-first) → RED
  assert 'baseline_regime=fixed:0' in 'baseline_regime=randomized'

forced seed0-first → RED same assertion as macOS observation
```

### Half B — fixed form + decoy/poison (GREEN)

Planted seed0 decoy **and** a poisoned seed2 (`POISONED_SHARED_OUT`,
`baseline_regime=randomized`) in real `out/`, then ran the fixed regime test
(isolated + exact name):

```
.                                                                        [100%]
1 passed in 8.92s
```

Permanent control test (same setup, asserts poison not in body):

```
.                                                                        [100%]
1 passed in 2.55s
```

## Gate evidence

```
715 passed, 4 skipped, 408 deselected, 25 warnings in 104.83s (0:01:44)
```

Baseline at F7 was **714 passed, 4 skipped, 0 failed** on the Linux gate host
(macOS: 714 passed, 3 skipped, 1 failed). Post-F8: **0 failed**, passed count
**715 > 714** (new permanent decoy control).

### `make eval-anchor-check` — EXIT 0 both freezes

```
determinism check passed [score]: ... matches --expect-report .../S2A-determinism-anchor-run-20260811-report.json
determinism check passed [score-face]: ... matches --expect-report .../S2A-face-determinism-anchor-run-20260811-face-report.json
EXIT:0
```

### `git status` after runs against committed artifacts

Clean of bakeoff-results dirt; only lane-owned test edit + this report staged
for commit. Diagnostics under `scripts/eval_harness/out/` removed before commit
(gitignored).

## Item 2 — untouched

`provenance.coverage_gaps` still
`["failures", "occlusion.occlusion_other", "occlusion.sunglasses"]`.
No generator run, no sunglasses/`occlusion_other` twin pairs added, no face
anchor regeneration. Intentional stop after item 1.

## Heuristics cited

| ID | How satisfied |
| --- | --- |
| **TEST-15** | Permanent decoy control + order simulation prove green can go red under old selection |
| **DBG-11** | Decoy/poison in shared out/ → red under seed0-first; green after exact-name isolation |
| **sr-001** | No skip/xfail/weaken; suite gained one control test |
| **OBS-04** | Production diagnostic path and message text unchanged |
| **rg-015** | N/A for item 1 (no contract metadata); item 2 not reached |

## Files committed (content description; no sandbox SHAs)

1. `apps/prototype-description-service/scene/tests/test_eval_harness_cli.py`
   — exact filenames; regime + F8 control isolate `_determinism_artifact_dir`
   to `tmp_path`; hash-order exact seed0 name.
2. `.s2a/vlm6-fix-f8-report.md` — this report.
