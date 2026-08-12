# VLM-6 S2A F2d — certify the artifact actually written (C-02 / GATE-05 / F2C-01)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6`  
**Commit:** `9c08464d28d01955e0d891b69b740a2344fad10f`  
<!-- Corrected (VLM6-S2A-F2D-01): the lane wrote its own sandbox-clone SHA,
     which does not exist here. This is the commit that landed this report locally. -->

**Scope:** `scripts/eval_harness/cli.py` + `scene/tests/test_eval_harness_cli.py` only.  
**Did not touch:** `report.py`, `test_eval_harness_pipeline.py`, `describe_baseline.py`, bakeoff anchors, `golden.json`.

## Verdict

**merge_ready** for F2d. Caption determinism guard certifies the same `rubric_gate` + `audience` documents `_cmd_score` writes; under `--audience public` both LOCAL (`score`) and PUBLIC (`score-public`) labels run; data argv paths are resolved so F2c's package-root pin governs imports only.

## Defect

`_check_score_determinism_cross_process` called `build_reports` without `audience` / `rubric_gate`, so it always certified LOCAL + `enforce`. Meanwhile `_cmd_score` scored with the operator's `rubric_gate`, wrote that LOCAL report, and under `--audience public` wrote a second redacted pair that received **zero** determinism coverage. Success line claimed the files just written were bit-identical across seeds; it was true about a different object (GATE-05).

F2C-01: after F2c pinned child `cwd` to package root, unresolved relative record/manifest argv resolved against the pin → child `FileNotFoundError` as ERROR.

## Fix

1. **Thread real params** — guard takes `rubric_gate`, `audience`, `label`; parent baseline + child script both pass them to `build_reports`.
2. **Certify every written artifact** — LOCAL label `score`; under public, second pass label `score-public` (OBS-04: red line names which artifact diverged).
3. **Structural write path** — guard returns certified `(json, md)`; when `--check-determinism`, `_cmd_score` writes *those* bytes (one conceptual build). Without the flag, existing `score_run_record` → fold → serialize path unchanged.
4. **Schema fold ordering** — fold runs after certification. On a clean report it is a no-op (certified == written). On hard-key drift it mutates and we re-serialize the fail artifact; that path is not the normal determinism claim (documented, not silent).
5. **F2C-01** — `str(record_path.resolve())` + `str(Path(manifest_path).resolve())` at score **and** face call sites. Pin unchanged.

## Tests (sr-001)

| Test | Intent |
|---|---|
| `test_cli_score_determinism_certifies_written_rubric_gate` | **new** GATE-05: pre-shape enforce≠skip; after fix written+certified both `skip` |
| `test_cli_score_audience_public_check_determinism_covers_both_labels` | **new** both labels pass; public artifact written |
| `test_cli_score_determinism_public_label_fails_on_mismatch` | **new** TEST-15: FAILED `[score-public]` |
| `test_cli_score_determinism_resolves_relative_paths_from_foreign_cwd` | **new** F2C-01 relative paths + foreign cwd |
| existing determinism suite | discrimination control GREEN + FAILED still fires |

No test skipped, xfailed, or weakened.

## Evidence

### Gate (verbatim)

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
677 passed, 4 skipped, 408 deselected, 9 warnings in 58.37s
```

Baseline (F2c host): **673 passed, 4 skipped**. Post-F2d: **677 passed, 4 skipped, 0 failed** (count greater; zero failed).

Determinism + F2d subset:

```text
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py \
    -k 'determinism or certifies_written or audience_public_check or relative_paths' -q
17 passed, 69 deselected, 3 warnings in 36.29s
```

### GATE-05 rubric_gate RED / GREEN (proved, not argued)

```text
PRE-F2D certified verdict.rubric_gate = enforce
WRITTEN --rubric-gate skip verdict.rubric_gate = skip
PRE-F2D certified == written? False
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED
POST-F2D certified verdict.rubric_gate = skip
POST-F2D certified == skip written? True
```

Commands: `build_reports(...)` without `rubric_gate` (pre-F2d baseline shape) vs `build_reports(..., rubric_gate="skip")` (written shape); then `_check_score_determinism_cross_process(..., rubric_gate="skip")` returns certified bytes equal to the skip document.

### Public-audience coverage

Structural + discrimination (public-only hash-order divergence not constructed — said plainly):

- Clean `--audience public --check-determinism` prints **both**  
  `determinism check passed [score]` and `determinism check passed [score-public]` and exits 0.
- Mutating the publishable item between baseline and child yields  
  `determinism check FAILED [score-public]` (not ERROR).

Public-only divergence that leaves LOCAL bit-identical while PUBLIC differs would require injecting nondeterminism inside `_filter_for_public_audience` / redaction only; not done here. Coverage is proven by label execution + FAILED control, not by a public-only mutation that stays green on LOCAL.

### F2C-01 relative paths

Pre-fix (unresolved argv + pin): child `FileNotFoundError: 'run-det.json'` →  
`determinism check ERROR [score]: subprocess seed=0 rc=1`.  
Post-fix: `determinism check passed [score]` from foreign fixture cwd with relative paths.

### DBG-11 (revert only `cli.py` to pre-F2d; keep new tests)

```text
=== DBG-11 RED: revert only cli.py to pre-F2d ===
FFFF
FAILED ...certifies_written_rubric_gate - TypeError: unexpected keyword argument 'rubric_gate'
FAILED ...audience_public_check_determinism_covers_both_labels
  - assert 'determinism check passed [score-public]' in '...passed [score]...'
FAILED ...public_label_fails_on_mismatch - TypeError: unexpected keyword argument 'rubric_gate'
FAILED ...resolves_relative_paths_from_foreign_cwd
  - SystemExit: determinism check ERROR [score]: ... FileNotFoundError: 'run-det.json'
4 failed, 82 deselected in 9.17s

=== restore F2d cli.py ===
....
4 passed, 82 deselected in 19.81s
```

### Heuristics cited

| ID | How satisfied |
|---|---|
| **OBS-04** | Labels `score` / `score-public`; ERROR vs FAILED taxonomy preserved; schema-fold post-cert only on hard-key drift and re-serializes fail artifact |
| **TEST-15** | Clean public two-label green; public mismatch FAILED; relative-path green after fix |
| **DBG-11** | Revert-only-cli.py → 4 new tests red; restore → green |
| **sr-001** | No existing test weakened; transport/params migrated; assertions kept |

## Not fixed / out of scope

- Public-only (LOCAL-green, PUBLIC-red) nondeterminism injection — structural coverage only.
- Schema-fold remains after certification; mutates only on hard-key schema errors (documented above).
- Sibling findings F1-* / other F2 items already landed; this report is F2d only.

## Constraints check

- Owned files only: `cli.py`, `test_eval_harness_cli.py`, this report.
- Gate passed with **0 failed** and passed count **> baseline**.
- `merge_ready` claimed with rubric_gate RED/GREEN pair + two-label passing control + DBG-11.
