# FIR-12 lane F30 — BR-43 (foil-shortfall == 1)

Closed FIR-12-BR-43. Test-only. `fir_bakeoff_run.py` not modified.

## Change

Added `test_single_foil_shortfall_is_incomplete` in
`apps/prototype-description-service/scene/tests/test_eval_harness_fir_bakeoff_run.py`.

- Stratum `D_capture` on `_plan(tmp_path)` (seed 7).
- `expected_foils = expected_nonmated_search_count(...)`; `assert expected_foils == 2`.
- Submit `expected_foils - 1` foils; mated arm complete (`search_shortfall == 0`).
- Assert `nonmated_shortfall == 1` and `incomplete is True` on both the row and `points[stratum]`.

The existing `test_truncated_foil_set_is_incomplete` builds shortfall == 2
(keeps 1 of 3 A_true_occluder foils) and cannot kill `foil_shortfall > 1`.

## Full suite

```
cd /home/ubuntu/l1/fir12-n1/apps/prototype-description-service && PYTHONPATH=$PWD /home/ubuntu/vlm6-fix/apps/prototype-description-service/.venv/bin/python -m pytest scene/tests -q -p no:cacheprovider
```

```
4 failed, 1327 passed, 4 skipped, 10 warnings in 55.96s
```

The 4 failures are the pre-existing PGPASSWORD production-boot tests
(`test_describe_route::test_create_app_registers_route_and_upload_cap` and three
`test_describe_run_reclaim` startup tests). Not this finding.

## Mutant proof

Production restored after each mutant. `git diff --exit-code` clean on
`scripts/eval_harness/fir_bakeoff_run.py` before commit.

m1 and m2 run against the new test plus the existing truncated-foil test
(so the old shortfall==2 case is shown staying GREEN).

### m1 — RED

In `score_run`, `or foil_shortfall > 0` → `or foil_shortfall > 1` (c6).

```
FAILED scene/tests/test_eval_harness_fir_bakeoff_run.py::test_single_foil_shortfall_is_incomplete - AssertionError: assert False is True
 +  where False = BakeoffIETPoint(...).incomplete
1 failed, 1 passed in 0.16s
```

Verdict: **RED**. New test dies on `report.points[stratum].incomplete is True`.
`test_truncated_foil_set_is_incomplete` stayed GREEN (shortfall == 2 still
satisfies `> 1`).

### m2 — RED

In `RunReport.to_rows` (line ~206; finding names this StratumReport.to_rows),
`or foil_shortfall > 0` → `or foil_shortfall > 1`.

```
FAILED scene/tests/test_eval_harness_fir_bakeoff_run.py::test_single_foil_shortfall_is_incomplete - assert False is True
1 failed, 1 passed in 0.17s
```

Verdict: **RED**. New test dies on `row["incomplete"] is True`. Truncated-foil
test stayed GREEN.

### m3 — RED

In `score_run`, `or mated_shortfall > 0` → `or mated_shortfall > 1` (c5 twin).
Whole 62-test file (`test_eval_harness_fir_bakeoff_run.py`).

```
FAILED scene/tests/test_eval_harness_fir_bakeoff_run.py::test_overall_point_degrades_when_one_stratum_is_short - AssertionError: assert False is True
 +  where False = BakeoffIETPoint(...).incomplete
1 failed, 61 passed in 2.05s
```

Verdict: **RED**. Mated twin still dies. The new foil test stayed GREEN under
m3 (mated arm is complete; this is expected isolation, not a survivor of the
foil gate).

No mutant survived.

## Canon rule IDs

- **MLDATA-09** — a filter that removes the regime under test deletes the test.
  `foil_shortfall > 1` publishes the common shortfall==1 cell as COMPLETE.
- **EVAL-18** / **JANUS 2.3.4** (open-set IET / FPI) — non-mated probes are the
  FPI exposure; a truncated foil list cannot render a complete cell.
- **EVAL-19** / **JANUS 2.3.4** — FPI is a count against declared exposure; a
  missing foil understates it.
- **TEST-15** — every assertion proven live against a mutant (file docstring).

## Noticed, not fixed

Finding text says "StratumReport.to_rows (line ~206)". That predicate lives on
`RunReport.to_rows` in `fir_bakeoff_run.py`. Mutant applied at that line.
