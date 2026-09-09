# VLM-6 S2A F1d-3 — audience green-path restore + describe_baseline secrets revert

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1-9 + F1-10 only (assignment #529)  
**Owned files:** `scene/tests/test_eval_harness_cli.py`, `scripts/eval_harness/describe_baseline.py`  
**Did not touch:** `scripts/eval_harness/{cli.py,report.py}` (sibling-owned), determinism helpers, `score-face`, bakeoff anchors, `golden.json`.

## Verdict

**merge_ready** for F1-9 + F1-10. F1-9 green-path restored with separate wrong-name failure test (net +1). F1-10 **reverted** `get_secret_provider` (preferred route). Full `eval_harness` selection shows the same two sibling-owned pipeline failures and no others.

## F1-9 — restore weakened default-audience coverage (TEST-15, sr-001)

### Defect

`test_cmd_score_default_local_emits_no_public_artifact` had been converted from a **successful** default score into an expected wrong-name failure. That moved coverage sideways: a regression that emits public artifacts only on a *successful* default score was unwatched.

### Fix

1. Restored `_w1_audience_manifest_and_record` default to a **clean** success fixture (`inject_wrong_name=False`).
2. Restored `test_cmd_score_default_local_emits_no_public_artifact` to a successful score that asserts:
   - local report exists
   - `run-x-report.public.{json,md}` **absent**
   - on-disk `verdict == "pass"`
3. Added **new** `test_cmd_score_default_local_wrong_name_exits_nonzero` (wrong-name floor on default audience).
4. Public redaction test still uses `inject_wrong_name=True`.

Net test count: **up by 1** (not sideways).

### RED / GREEN evidence (TEST-15)

Temporary production regression (reverted; `cli.py` left byte-identical to pre-probe):

```python
# scripts/eval_harness/cli.py audience gate
if True:  # F1-9 RED regression: emit public artifact on every score
```

**RED** — restored green-path test fails when a public artifact is emitted on successful default score:

```
$ uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py::test_cmd_score_default_local_emits_no_public_artifact -q --tb=line

F                                                                        [100%]
=================================== FAILURES ===================================
E   AssertionError: assert not True
     +  where True = exists()
     +    where exists = (... / 'run-x-report.public.json').exists
----------------------------- Captured stdout call -----------------------------
.../run-x-report.public.md
.../run-x-report.md
scored=2/2 insertion_rate=1.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 ...
FAILED scene/tests/test_eval_harness_cli.py::test_cmd_score_default_local_emits_no_public_artifact
1 failed in 1.04s
```

**GREEN** — after restoring the audience gate (`if getattr(args, "audience", ...) == Audience.PUBLIC.value`):

```
$ uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py::test_cmd_score_default_local_emits_no_public_artifact \
    scene/tests/test_eval_harness_cli.py::test_cmd_score_default_local_wrong_name_exits_nonzero \
    scene/tests/test_eval_harness_cli.py::test_cmd_score_public_audience_emits_redacted_public_artifact \
    -q --tb=short

...                                                                      [100%]
3 passed in 0.99s
```

`cli.py` restored byte-identical after the probe (`diff -q` clean vs backup).

## F1-10 — unauthorized secrets-provider refactor (preferred: full revert)

### Route taken

**Full revert** of the `get_secret_provider()` hunk in `describe_baseline.py`.

### Why not keep + fallback

- History is stripped in this sandbox (`git log -S get_secret_provider` only shows the sandbox base).
- No later lane-owned commits depend on the provider call in this file.
- Preferred brief route: maintenance belongs in its own task; do not re-file.

### Evidence

Provider symbols absent; direct env lookup restored:

```
$ grep -n "get_secret_provider\|ACX_EVAL_API_KEY\|from shared" \
    scripts/eval_harness/describe_baseline.py

270:        key = os.environ.get("ACX_EVAL_API_KEY", "")
273:            sys.exit("missing ACX_EVAL_BASE_URL / ACX_EVAL_API_KEY / ACX_EVAL_TENANT_ID")
```

- `get_secret_provider` / `shared.secrets`: **absent**
- `os.environ.get("ACX_EVAL_API_KEY", "")`: **present**

Sandbox has no `main` ref; equivalent check: the provider hunk is empty (no provider import, no provider call). Do **not** re-file the secrets migration from this lane.

## Full eval_harness selection (verbatim)

```
$ cd apps/prototype-description-service && \
  uv run --extra dev pytest scene/tests/ -k eval_harness -q --tb=line

...
FAILED scene/tests/test_eval_harness_pipeline.py::test_old_run_record_scores_unchanged_without_slice2_keys
FAILED scene/tests/test_eval_harness_pipeline.py::test_weave_bench_run_record_replays_and_stamps_source_provenance
2 failed, 662 passed, 4 skipped, 408 deselected, 9 warnings in 34.13s
```

### Notes vs baseline `d3799f5f` (2 failed, 662 passed, 3 skipped)

| metric | baseline | this run |
| --- | --- | --- |
| failed | 2 (P-01 pipeline additive-schema) | **same 2** — not fixed, `report.py` not touched |
| passed | 662 | 662 |
| skipped | 3 | **4** (extra env skip: face models / fixtures) |
| selected | 667 | **668** (+1 from F1-9 new test) |

- Same two failures only: `test_old_run_record_scores_unchanged_without_slice2_keys`, `test_weave_bench_run_record_replays_and_stamps_source_provenance` (VLM-6-S2A-P-01 / sibling).
- Net test count **up**: 668 collected vs 667. New `test_cmd_score_default_local_wrong_name_exits_nonzero` is collected and **passes**.
- Pass digit equals baseline because this sandbox has **+1 environmental skip** vs the baseline host (models/fixtures missing). Without that extra skip the pass count would be 663. Intent of “net +1 green test” is met; digit comparison to 662 is confounded by env skip delta.
- CLI file alone: **73 passed**.

Skips (all env, none xfail/weaken):

1. ORT SFace weights unavailable (`test_eval_harness_face_bakeoff`)
2. real LocalWP XMP fixture not present
3. FIR-3 face models missing (`landmark_cache`)
4. `GOLDEN_IMAGES_DIR` not set

## Heuristics cited

| ID | Item | How satisfied |
| --- | --- | --- |
| **TEST-15** | F1-9 | Forced public-artifact emission on successful default score → restored test went red; revert → green |
| **sr-001** | F1-9 | Did not keep the weakened failure-only form; restored success path and added failure as separate test |
| **DBG-11** | F1-10 | N/A for fallback (revert route); absence of provider is the fix |

## Constraints checklist

- [x] No existing test weakened, skipped, or xfailed
- [x] Did not touch `cli.py` / `report.py` (except temporary RED probe restored)
- [x] Did not fix P-01 pipeline failures
- [x] Full `-k eval_harness` selection reported verbatim
- [x] F1-10 route stated: **full revert**
- [x] F1-9 RED/GREEN pair captured

## Not fixed (out of scope)

- VLM-6-S2A-P-01 (`counts` additive keys) — sibling owns `report.py`
- VLM-6-S2A-P-02 (coverage-scope meta finding)
- Secrets-provider migration for `describe_baseline` — belongs in a dedicated maintenance task; not re-filed here
