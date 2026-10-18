# VLM-6 S2A F2e — name seed regime + prove seed dimension (C-05 / D-05)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6`  
**Commit:** `aec65fc8a03f8b7482ffb5c8548640c7fc82186a`  
<!-- Corrected (VLM6-S2A-F2D-01 class): the lane wrote a sandbox-clone SHA
     that does not exist here. This is the commit that landed this report locally. -->

**Scope:** `scripts/eval_harness/cli.py` + `scene/tests/test_eval_harness_cli.py` only.  
**Did not touch:** `report.py`, `test_eval_harness_pipeline.py`, `describe_baseline.py`, bakeoff anchors, `golden.json`.

## Verdict

**merge_ready** for F2e. Parent baseline PYTHONHASHSEED regime is named on every pass/FAILED/ERROR line and in mismatch artifacts; child seeds that collide with a fixed parent are substituted so coverage is not silently narrowed; a set-repr injection proves the seed dimension can take the gate red without mutating a persisted anchor.

## Defects

### C-05 — irreproducible red + silent coverage collapse

Children ran under `PYTHONHASHSEED ∈ {0,1,42}` but the parent baseline ran under whatever the invoking shell gave the interpreter. Failures named only the child seed; operators could not reconstruct the other half of the comparison (OBS-04). When CI exported `PYTHONHASHSEED=0`, the seed-0 child became a byte-for-byte duplicate of the baseline configuration — four configs silently became three, while the success line still claimed "varied PYTHONHASHSEED" without naming the set.

### D-05 — seed dimension unproven

Existing tests only proved the gate catches a **mutated persisted anchor**. That failure mode needs no seed variation. Nothing showed the gate goes red because of hash-order dependence — the premise of varying `PYTHONHASHSEED`.

## Fix

1. **`_parent_hash_seed_regime()`** — reads `os.environ.get("PYTHONHASHSEED")` + `sys.flags.hash_randomization` → `fixed:<n>` or `randomized`.
2. **`_resolve_determinism_child_seeds(parent_fixed)`** — substitutes colliding child seeds with the lowest unused integers so the child set still contributes 3 *distinct* configurations (e.g. parent `0` → children `2,1,42`).
3. **Self-describing messages** — every pass / FAILED / ERROR line includes `baseline=…; child_seeds=…` (OBS-04).
4. **Mismatch artifacts** — header now carries `baseline_regime=` and `child_seeds=` so a red run is reconstructible from the artifact alone.
5. **D-05 proof test** — injects `repr(set(...))` into compared documents via `_run_determinism_children` (no `report.py` edit). Gate fails FAILED, not ERROR.

Single-site substrate change in `_run_determinism_children`; transport, import pin, and audience threading untouched.

## Tests (sr-001)

| Test | Intent |
|---|---|
| `test_parent_hash_seed_regime_names_fixed_and_randomized` | **new** C-05 regime naming unit |
| `test_resolve_determinism_child_seeds_substitutes_parent_collision` | **new** C-05 collision → substitute |
| `test_cli_score_determinism_pass_names_baseline_and_child_seeds` | **new** pass line names regime + seeds |
| `test_cli_score_determinism_collision_substitutes_seed_zero` | **new** `PYTHONHASHSEED=0` → `child_seeds=2,1,42` |
| `test_cli_score_determinism_fail_artifact_carries_baseline_regime` | **new** FAILED + artifact carry regime |
| `test_determinism_gate_detects_hash_order_dependence` | **new** D-05 / TEST-15 seed-order red |
| existing determinism suite | discrimination control unchanged |

No test skipped, xfailed, or weakened.

## Evidence

### Gate (verbatim)

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
683 passed, 4 skipped, 408 deselected, 9 warnings in 67.27s
```

Baseline (brief): **678 passed, 3 skipped, 0 failed**. Post-F2e: **683 passed, 4 skipped, 0 failed** (passed count greater; zero failed; linux host has one extra platform skip → 4 skipped matches F2d host).

F2e subset:

```text
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py \
    -k 'parent_hash_seed or resolve_determinism or determinism_pass_names or determinism_collision or fail_artifact_carries or hash_order_dependence' -q
6 passed, 86 deselected in 10.22s
```

### C-05 reproducibility — pass path names regime + seeds

```text
# Parent fixed at 7 (no collision with default children)
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=fixed:7; child_seeds=0,1,42)
```

Asserted by `test_cli_score_determinism_pass_names_baseline_and_child_seeds`.

### C-05 collision — pre vs post

**Pre-change** (DBG-11 revert of `cli.py` only; tests still post-F2e):

```text
# Pass line never names seeds or baseline:
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED

# Under PYTHONHASHSEED=0 parent, FAILED still fires first child as seed=0
# (duplicate configuration of baseline — silent coverage collapse):
determinism check FAILED [score]: cross-process re-score differs under PYTHONHASHSEED=0
  (document=JSON+MD; artifact=.../determinism-mismatch-score-seed0.diff.txt; stderr='')
```

**Post-change** with `PYTHONHASHSEED=0`:

```text
LIVE collision resolve: fixed:0 ('2', '1', '42') baseline=fixed:0; child_seeds=2,1,42

# Pass claims the substituted set (not 0,1,42):
determinism check passed [score]: ... (baseline=fixed:0; child_seeds=2,1,42)

# Unit: _resolve_determinism_child_seeds("0") == ("2", "1", "42")
#        _resolve_determinism_child_seeds(None) == ("0", "1", "42")
```

Asserted by `test_cli_score_determinism_collision_substitutes_seed_zero` and
`test_resolve_determinism_child_seeds_substitutes_parent_collision`.

### C-05 fail path + artifact

FAILED message includes regime; artifact header reconstructible:

```text
determinism check FAILED [score]: ... under PYTHONHASHSEED=<child>
  (baseline=fixed:0; child_seeds=2,1,42; document=...; artifact=...; stderr=...)

# artifact body contains:
baseline_regime=fixed:0
child_seeds=2,1,42
PYTHONHASHSEED=<child>   # not 0 when parent is fixed:0
```

Asserted by `test_cli_score_determinism_fail_artifact_carries_baseline_regime`.

### D-05 seed-sensitivity proof (TEST-15)

`test_determinism_gate_detects_hash_order_dependence` injects `SEED_PROBE:` + `repr(set(...))` into compared documents via a child script. No run-record mutation. Gate exits FAILED (not ERROR) with regime clause and a mismatch artifact containing `SEED_PROBE:`.

This is **not** the mutated-anchor test; the seed dimension is load-bearing for the gate substrate itself. Scope note: production `build_reports` paths remain seed-stable by design; the proof exercises `_run_determinism_children` comparison semantics with genuine hash-order dependence, without editing `report.py`.

### TEST-15 discrimination control

Clean score determinism still exits 0 with a passed line; mutated-anchor still exits FAILED. Existing suite retained:

```text
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py \
    -k 'check_determinism_runs_cross or determinism_guard_detects_mutated or parent_hash or resolve_determinism or determinism_pass_names or determinism_collision or fail_artifact_carries or hash_order_dependence' -q
8 passed, 84 deselected in 15.28s
```

### DBG-11 — causation by absence

```text
# Revert only cli.py to pre-F2e; keep new tests:
FFFFFF
6 failed, 86 deselected in 10.22s
# Failures: missing _parent_hash_seed_regime / _resolve_determinism_child_seeds;
# pass/fail messages lack baseline= / child_seeds=; artifact lacks baseline_regime=.

# Restore post-F2e cli.py:
......
6 passed, 86 deselected in 10.22s
```

Commands:

```text
git show HEAD~0:apps/prototype-description-service/scripts/eval_harness/cli.py  # post
# temporarily replaced with pre-commit parent version of cli.py only
pytest ... -k 'parent_hash_seed or resolve_determinism or determinism_pass_names or determinism_collision or fail_artifact_carries or hash_order_dependence' -q
# restore post-F2e cli.py; same pytest → green
```

## Heuristics satisfied

| ID | How |
|---|---|
| **OBS-04** | Pass/FAILED/ERROR name baseline regime + child seed set; artifact reconstructible |
| **TEST-15** | D-05 set-repr injection takes the gate red; clean path still green |
| **DBG-11** | Revert cli.py only → 6 new tests red; restore → green |
| **sr-001** | No existing test weakened/skipped/xfailed |

## Not in this slice

- **B-11** (`describe_baseline.py` secrets routing) — out of F2e scope; left for a dedicated slice.
- Pinning the parent process seed itself (force parent to a fixed seed) was **not** required; naming + collision substitution meets C-05. Parent remains free so operators can still run under randomized baselines; the claim text makes that explicit.

## Open questions

None for C-05/D-05. Seed dimension is proven at the gate substrate via set-repr injection; production report serialization remains intentionally seed-stable.
