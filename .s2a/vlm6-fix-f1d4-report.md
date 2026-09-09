# VLM-6 S2A F1d-4 — move corpus keys out of `counts` (VLM-6-S2A-P-01)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1d-4 only (assignment #531)  
**Owned files:** `scripts/eval_harness/report.py`, `scripts/eval_harness/cli.py` (read site), `scene/tests/test_eval_harness_report.py` (read-site assertions)  
**Did not touch:** `scene/tests/test_eval_harness_pipeline.py` (contract file), `test_eval_harness_cli.py`, `describe_baseline.py`, determinism helpers, `score-face`, bakeoff anchors, `golden.json`.

## Verdict

**merge_ready** for F1d-4. Corpus-integrity keys moved out of pinned `counts` into `scored["corpus"]`. Both pipeline equality guards pass **unmodified**. Full `eval_harness` selection: **0 failed, 664 passed, 4 skipped**.

## Defect

`score_run_record()` put `manifest_entries`, `media_id_extra`, `media_id_missing` into `counts`. That dict is a pinned contract shape:

- `test_old_run_record_scores_unchanged_without_slice2_keys` asserts `counts == {total, scored, failed}` exactly
- `test_weave_bench_run_record_replays_and_stamps_source_provenance` asserts the same

Bisect pin (per brief): break introduced at `e7a9028b`; five subsequent commits shipped red because earlier F1 gates only ran two of four eval_harness test files (VLM-6-S2A-P-02).

## Fix (sr-001)

1. **Write site** (`report.py` / `score_run_record`): `counts` remains `{total, scored, failed}`; new top-level `corpus` block holds the three multiset fields.
2. **Read sites**:
   - `build_score_verdict` truncation reason → `scored["corpus"]`
   - `cli.py` truncation exit gate → `scored["corpus"]`
   - `test_eval_harness_report.py` shape + multiset assertions → `scored["corpus"]`
3. **Not done:** relax pipeline assertions / delete tests (forbidden by sr-001).

## Evidence

### RED before (pipeline contract broken)

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_pipeline.py::test_old_run_record_scores_unchanged_without_slice2_keys \
  scene/tests/test_eval_harness_pipeline.py::test_weave_bench_run_record_replays_and_stamps_source_provenance \
  -q --tb=line

FAILED ...::test_old_run_record_scores_unchanged_without_slice2_keys
  Left contains 3 more items:
  {'manifest_entries': 1, 'media_id_extra': 0, 'media_id_missing': 0}

FAILED ...::test_weave_bench_run_record_replays_and_stamps_source_provenance
  Left contains 3 more items:
  {'manifest_entries': 2, 'media_id_extra': 0, 'media_id_missing': 0}

2 failed in 1.68s
```

### GREEN after

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_pipeline.py::test_old_run_record_scores_unchanged_without_slice2_keys \
  scene/tests/test_eval_harness_pipeline.py::test_weave_bench_run_record_replays_and_stamps_source_provenance \
  -q --tb=line

..                                                                       [100%]
2 passed in 1.13s
```

### Contract file untouched (sr-001)

```text
$ git diff --stat -- apps/prototype-description-service/scene/tests/test_eval_harness_pipeline.py
# (empty — zero changes)
```

### Full self-verify gate

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
664 passed, 4 skipped, 408 deselected, 9 warnings in 31.74s
```

Baseline at brief `b62983ce` was **2 failed, 663 passed, 3 skipped**. Post-fix: **0 failed**, passed **664** (≥ 664 required).

### TEST-15 — truncation still fires; clean control still exits 0

CLI truncation tests (post-move read path):

```text
$ uv run --extra dev pytest \
  scene/tests/test_eval_harness_cli.py::test_score_guard_fetch_limit_truncation_fails_coverage_gate \
  scene/tests/test_eval_harness_cli.py::test_score_persisted_verdict_fail_truncation_real_golden \
  -q
2 passed in 0.99s
```

Programmatic discrimination (class-unique `truncation:` token):

```text
CLEAN counts: {'total': 3, 'scored': 3, 'failed': 0}
CLEAN corpus: {'manifest_entries': 3, 'media_id_missing': 0, 'media_id_extra': 0}
CLEAN verdict: pass []
TRUNC counts: {'total': 1, 'scored': 1, 'failed': 0}
TRUNC corpus: {'manifest_entries': 3, 'media_id_missing': 2, 'media_id_extra': 0}
TRUNC verdict: fail
TRUNC reasons: ['truncation: media-id multiset differs (missing=2, extra=0)']
```

### DBG-11 — causation by absence

Temporarily restored the pre-fix write site (keys back inside `counts`). Pipeline tests failed again with the same three extra keys. Restoring the fix re-greened both tests (2 passed).

## Heuristics satisfied

| ID | How |
|----|-----|
| **sr-001** | Fixed production placement; did not weaken/delete either pipeline equality assert. `git diff` on that file is empty. |
| **TEST-15** | Truncation mismatch still fails with `truncation:` reason; clean full multiset still passes. |
| **DBG-11** | Reverting the write site restored both pipeline failures; re-applying the fix cleared them. |

## What was not fixed

Nothing in F1d-4 scope left open. Sibling findings (B-11 residual oci_vault parity note; P-02 process coverage-scope note) are out of this one-item brief.
