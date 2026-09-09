# VLM-6 S2A F3 — document score gates / verdict / `--check-determinism` (B-08)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6` (sandbox: history-stripped `master`)  
**Scope (docs only):**  
- `apps/prototype-description-service/scene/tests/seed/README.md`  
- `docs/tasks/vlm/VLM-2A-caption-face-eval-harness-task-plan.md`  
- `apps/prototype-description-service/scripts/eval_harness/README.md` (new operator section)  
- this report  

**Did not touch:** any `.py`, `golden.json`, bakeoff anchors, `test_eval_harness_pipeline.py`, `describe_baseline.py` (B-11 residual, out of scope).

## Verdict

**merge_ready** for F3 (docs-only, rg-006). Broken copy-paste paths replaced with empirically captured RED output; working green path documented from a real exit-0 run; full operator gate/verdict/ERROR-vs-FAILED table added.

## Heuristics

| ID | How satisfied |
| --- | --- |
| **rg-006** | Every command written into docs was executed; broken baseline shape no longer claimed green. |
| **OBS-04** | Operator table teaches ERROR (environment) vs FAILED (build) for determinism, plus class-unique score gate prefixes. |
| **sr-001** | Did not weaken gates or invent a green baseline command; residual baseline identity-shape gap called out for a code/record lane. |

## Before / after (broken lines)

### seed/README.md (was L71–72)

**Before:** presented `cli score --check-determinism` against the seeded-stub baseline as **the** deterministic-scoring evidence path.

**After:** states committed baselines exit 1; points to suite evidence + eval-harness README operator section.

### task plan (was L111)

**Before:**

```text
uv run python -m scripts.eval_harness.cli score --run-record <baseline record> --check-determinism
# claimed: re-score committed baseline; deterministic sections diff-clean
```

**After:** documents that shape as **broken as written** with the real `ReportError` / exit 1; working evidence is the named pytest; gate reference lives in eval-harness README.

## Empirical evidence (pasted)

### RED — committed baselines (documented shape)

```text
$ cd apps/prototype-description-service
$ uv run --extra dev python -m scripts.eval_harness.cli score \
    --run-record ../../docs/tasks/vlm/VLM-2C-seeded-stub-run-record-20260707.json \
    --check-determinism
ReportError: items[0].identities[0] must be a dict identity row (keys include 'name'); got str — greenfield rejects bare-string identity lists
EXIT_CODE:1

$ uv run --extra dev python -m scripts.eval_harness.cli score \
    --run-record ../../docs/tasks/vlm/VLM-2A-baseline-20260706-run-record.json \
    --check-determinism
ReportError: items[2].identities[0] must be a dict identity row (keys include 'name'); got str — greenfield rejects bare-string identity lists
EXIT_CODE:1
```

`--rubric-gate skip` does **not** help: `ReportError` fires before gates.

Bare `score --check-determinism` (seed README implication without `--run-record`):

```text
eval_harness score: error: the following arguments are required: --run-record
EXIT_CODE:2
```

### RED — `fetch --check-determinism` free-reject (flag placement)

```text
$ uv run --extra dev python -m scripts.eval_harness.cli fetch --check-determinism
usage: eval_harness [-h]
                    {fetch,score,run,seed-roster,seed-scenes,face-bakeoff,score-face}
                    ...
eval_harness: error: unrecognized arguments: --check-determinism
EXIT_CODE:2
```

### GREEN — matched fixture (same shape as suite control)

```text
$ uv run --extra dev python -m scripts.eval_harness.cli score \
    --manifest /tmp/vlm6-f3-det-ly5h__cv/manifest.json \
    --run-record /tmp/vlm6-f3-det-ly5h__cv/run-det.json \
    --check-determinism
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42)
/tmp/vlm6-f3-det-ly5h__cv/run-det-report.md
scored=1/1 insertion_rate=1.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=enforce
EXIT_CODE:0
```

### GREEN — suite evidence path

```text
$ uv run --extra dev pytest scene/tests/test_eval_harness_cli.py \
    -k score_check_determinism_runs_cross_process -q
.                                                                        [100%]
1 passed, 94 deselected in 7.24s
```

### `run` announcement (before live gate)

```text
run --check-determinism: per-leg certification — 1 legs × 3 seeds = 3 fresh interpreter(s) before scoring completes
EXIT live subcommand requires ACX_EVAL_LIVE=1 (safety gate; see README)
```

### Full gate (docs-only must not change count)

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
686 passed, 4 skipped, 408 deselected, 9 warnings in 67.73s (0:01:07)
```

Brief named 687/3; this sandbox HEAD was already **686 passed, 4 skipped** post-F2f (see `.s2a/vlm6-fix-f2f-report.md`). Docs-only change left that count **exactly unchanged**.

### Diff stat (markdown only)

```text
 .../scene/tests/seed/README.md                     |  15 +-
 .../scripts/eval_harness/README.md                 | 153 ++++++++++++++++++++-
 .../VLM-2A-caption-face-eval-harness-task-plan.md  |   3 +-
 .s2a/vlm6-fix-f3-report.md                         | (this file)
```

## What was written into docs

1. **Honest baseline gap** — committed baselines cannot green `score --check-determinism` until identity rows are dict-shaped (code/record finding for a later lane; not weakened here).
2. **Working alternative** — suite control + matched-fixture command with real pass line (`baseline=…; child_seeds=…`).
3. **Operator table** in `scripts/eval_harness/README.md` § *Score gates, verdict, and `--check-determinism`*:
   - flag placement: `score` / `run` / `score-face` only; `fetch` rejects
   - `verdict` field contents; written **before** gates; red run still leaves `*-report.json`
   - every non-zero `score` exit prefix (schema, failed-items, truncation, manifest-mismatch, empty-rubric, must-right failures, wrong-name floor vacuity, wrong-name floor)
   - original S2A five named gates called out inside that set
   - determinism ERROR vs FAILED vs pass + mismatch artifact `determinism-mismatch-<label>-seed<n>.diff.txt`
   - `run` multiplier announcement

## Residual / next lane (not this item)

- **Baseline re-score path:** migrate or re-fetch committed run-records to dict identity rows so `score --run-record docs/tasks/vlm/… --check-determinism` can exit 0 (or document permanent archival of those records as pre-greenfield).
- **B-11** `describe_baseline.py` secrets path under `oci_vault` — still open; not docs scope.

## Commit SHA

- Docs + report land: `402b6a77eba9fb4ac1dfa47e3e51afec89881f2a`
- Verify: `git rev-parse --verify 402b6a77eba9fb4ac1dfa47e3e51afec89881f2a^{commit}`

<!-- Corrected (VLM6-S2A-F3-02): the lane cited sandbox-clone SHAs that resolve
     nowhere here, and paired them with a verify command guaranteed to fail.
     Replaced with the commit that actually landed this report. -->

