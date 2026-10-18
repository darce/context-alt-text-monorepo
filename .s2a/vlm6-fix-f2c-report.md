# VLM-6 S2A F2c — pinned import root + self-verifying provenance (C-01 / E-07 / D-06)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F2c only (assignment #536) — `scripts/eval_harness/cli.py` + `scene/tests/test_eval_harness_cli.py`  
**Did not touch:** `report.py`, `test_eval_harness_pipeline.py`, `describe_baseline.py`, bakeoff anchors, `golden.json`.

## Verdict

**merge_ready** for F2c. Determinism child import root pinned to package root; payload carries `build_reports_file` provenance; parent resolves and compares — mismatch is ERROR (OBS-04). Cwd decoy shadowing demonstrated RED→GREEN. Full `eval_harness` selection: **673 passed, 4 skipped, 0 failed** (baseline at F2b linux host: 671 passed, 4 skipped).

## How the child resolved imports before the pin (empirical)

Editable install of `prototype-description-service` puts the checkout on the module path (`report.__file__` under the worktree, not site-packages). Existing tests `monkeypatch.chdir(tmp_path)` still pass because the child finds the installed package **unless** a `scripts/` tree sits under cwd.

**Critical:** `python -c` puts `''` (cwd) at `sys.path[0]` **ahead of PYTHONPATH**. A decoy `scripts/eval_harness/` under cwd shadows both the editable install and a PYTHONPATH prepend. PYTHONPATH alone does **not** defeat cwd shadowing — both `cwd=` and `PYTHONPATH` must be pinned to the package root.

```text
=== UNPINNED cwd=decoy ===
rc 0
co_filename= /tmp/f2c-probe-.../scripts/eval_harness/report.py
result= ('DECOY_JSON_BYTES', 'DECOY_MD_BYTES')
path0= ''

=== PINNED cwd=import_root + PYTHONPATH ===
co_filename= .../apps/prototype-description-service/scripts/eval_harness/report.py
```

## Defect

`_run_determinism_children` spawned with `cwd=str(Path.cwd())` and inherited env. Parent scores via its own `build_reports`; child may bind cwd’s package. Agreement certifies two possibly-different builds; disagreement can be checkout mismatch misreported as nondeterminism.

## Fix (single-site — C-08 substrate)

1. **Pin:** `import_root = Path(__file__).resolve().parents[2]` used for both `cwd=` and `PYTHONPATH` prepend. Never `Path.cwd()`.
2. **Prove:** child payload includes `"build_reports_file": build_reports.__code__.co_filename` (score) / `build_face_reports.__code__.co_filename` (face). Parent compares `Path(...).resolve()` forms.
3. **Taxonomy (OBS-04):** provenance missing or mismatch → `determinism check ERROR [{label}]: ...` naming both paths. Byte mismatch remains `FAILED`.

## Tests (sr-001)

| Test | Intent |
|---|---|
| `test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy` | **new** — chdir to decoy tree; guard still passes (child binds parent module) |
| `test_cli_score_determinism_guard_errors_on_build_reports_provenance_mismatch` | **new** — ERROR names both paths + `[score]` |
| `test_cli_score_check_determinism_runs_cross_process_guard` | discrimination control GREEN |
| `test_cli_score_determinism_guard_detects_mutated_persisted_anchor` | discrimination control FAILED still fires |
| banner / face FAILED mocks | migrated to include matching provenance so they still reach their original assertion class |

No test skipped, xfailed, or weakened.

## Evidence

### Gate (verbatim)

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
673 passed, 4 skipped, 408 deselected, 9 warnings in 39.65s
```

Determinism subset:

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/test_eval_harness_cli.py -k 'determinism' -q
13 passed, 69 deselected, 3 warnings in 16.87s
```

### SHADOWING RED / GREEN (TEST-15 + DBG-11)

Decoy package under temp dir re-exports real `report.py` symbols then overrides `build_reports` → `('DECOY_JSON_BYTES', 'DECOY_MD_BYTES')`. Guard invoked with `chdir(decoy_root)`.

**RED — unpinned simulation** (sandbox has history stripped; simulated `fe957a92` by restoring `cwd=str(Path.cwd())` and removing the provenance gate only):

```text
$ # cwd=Path.cwd(), no provenance check
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py::test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy -q --tb=line
F
E   SystemExit: determinism check FAILED [score]: cross-process re-score differs under PYTHONHASHSEED=0 (document=JSON+MD; artifact=.../determinism-mismatch-score-seed0.diff.txt; stderr='')
1 failed in 3.15s
```

Child bound the decoy → content mismatch reported as FAILED (false regression).

**GREEN — pinned restore:**

```text
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py::test_cli_score_determinism_guard_pins_import_root_against_cwd_decoy -q
.                                                                        [100%]
1 passed in ~5s
```

### PROVENANCE ERROR (OBS-04)

```text
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py::test_cli_score_determinism_guard_errors_on_build_reports_provenance_mismatch -q
.                                                                        [100%]
1 passed
```

Asserts: `determinism check ERROR [score]`, both parent and decoy paths in message, no `FAILED`.

### Discrimination control (TEST-15)

```text
$ uv run --extra dev pytest \
  scene/tests/test_eval_harness_cli.py::test_cli_score_check_determinism_runs_cross_process_guard \
  scene/tests/test_eval_harness_cli.py::test_cli_score_determinism_guard_detects_mutated_persisted_anchor -q
..                                                                       [100%]
2 passed
```

Clean → `determinism check passed [score]`; mutated anchor → `determinism check FAILED [score]`. Pin does not disable the gate.

## Heuristics

| ID | How satisfied |
|---|---|
| **OBS-04** | Environment drift → ERROR with both paths; build regression → FAILED |
| **TEST-15** | Decoy RED without pin; GREEN with pin; clean + mutated controls |
| **DBG-11** | Removing pin (cwd=Path.cwd() + drop provenance) restores decoy FAILED |
| **sr-001** | Existing tests migrated for provenance field; none weakened/skipped/xfailed |

## Residual / not fixed

- History stripped in this sandbox (`fe957a92` not present); DBG-11 used an unpinned simulation of that substrate rather than `git checkout fe957a92 -- cli.py`. Behavior match: unpinned `cwd=Path.cwd()` + no provenance check.
- Residual finding VLM-6-S2A-B-11 (`describe_baseline` secrets path) out of scope for F2c.
