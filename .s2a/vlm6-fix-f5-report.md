# VLM-6 S2A F5 — frozen-anchor comparison (third determinism outcome)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6` (sandbox: history-stripped)  
**Scope:**
- `scripts/eval_harness/cli.py` — `--expect-report` + `ANCHOR_MISMATCH`
- `scene/tests/test_eval_harness_determinism_anchor.py` — real TEST-15 control
- `scene/tests/test_eval_harness_cli.py` — discrimination + flag coupling
- `scripts/eval_harness/README.md` — three-outcome operator table
- this report

**Did not touch:** `report.py`, `test_eval_harness_pipeline.py` (pinned),
`golden.json`, legacy `*run-record*.json`, the three committed
`S2A-determinism-anchor-run-20260811*` artifacts (no regenerate),
`describe_baseline.py` (B-11 residual).

## Verdict

**merge_ready** for F5 caption path. Frozen-anchor comparison is opt-in via
`--expect-report`; corruption goes red with a distinct third outcome; seed
FAILED and environment ERROR remain distinct messages; suite green above
baseline.

## Design choice: `--expect-report` (not sibling inference)

Discovery is **opt-in path**, not magic sibling of the run-record.

Why:
- Sibling inference would fire on every score of a co-located report, including
  intentional re-scores that rewrite that report.
- An explicit path makes CI pin the freeze and keeps day-to-day score free of
  accidental ANCHOR_MISMATCH after a deliberate scorer change.
- Matches the brief: prefer `--expect-report <path>` over inferred names.

Wired on `score` only (requires `--check-determinism`). Applied to the LOCAL
document only; PUBLIC certification stays seed-only (no committed public freeze).

## Three outcomes (OBS-04)

| Prefix | Meaning | Remedy |
| --- | --- | --- |
| `determinism check ERROR [label]:` | Child / path / import failure | Fix environment or path |
| `determinism check FAILED [label]:` | Seed diverge across children | Investigate scoring non-determinism |
| `determinism check ANCHOR_MISMATCH [label]:` | Certified JSON ≠ `--expect-report` | See stale-vs-corrupt below |
| `determinism check passed [label]:` | Seed-stable; with flag also matches freeze | None |

Seed-stability pass is **deferred** when `--expect-report` is set so the
operator never sees pass-then-mismatch on the same invocation.

### Stale vs corrupt (operator choice)

`ANCHOR_MISMATCH` names both legitimate causes and the regen command:

1. **Corrupted freeze or run-record** → investigate; **do NOT regenerate**
   (regenerating destroys the evidence).
2. **Deliberate scoring change** → regenerate on purpose via  
   `python -m scripts.eval_harness.generate_determinism_anchor`  
   and commit the new freeze.

## Heuristics

| ID | How satisfied |
| --- | --- |
| **OBS-04** | Three red classes + pass: ERROR / FAILED / ANCHOR_MISMATCH, each with a distinct message and remedy. |
| **TEST-15** | `test_corrupt_expect_report_makes_determinism_gate_red` corrupts a tmp freeze, runs the shipped gate, asserts `ANCHOR_MISMATCH`. Old sha256-tautology deleted. |
| **DBG-11** | Same corruption **passes silently** without `--expect-report` (pre-F5 behaviour preserved as the seed-only path); with flag goes **red**. Base silent-pass demonstrated on this tree before the flag existed in the call. |
| **sr-001** | No test weakened/skipped/xfailed; passed count increased. |

## Evidence

### DBG-11 / TEST-15 — corrupt freeze goes red; restore green

```text
=== RED: corrupt --expect-report ===
determinism check ANCHOR_MISMATCH [score]: fresh re-score does not match --expect-report /tmp/…/expect-corrupt.json (baseline=randomized; child_seeds=0,1,42; artifact=/tmp/…/determinism-anchor-mismatch-score.diff.txt). This is neither seed divergence (FAILED) nor environment drift (ERROR). Two legitimate causes — choose carefully: (1) the frozen report or the run-record was corrupted — investigate, do NOT regenerate (regenerating destroys the evidence); (2) scoring was deliberately changed and the freeze is now stale — regenerate on purpose via `python -m scripts.eval_harness.generate_determinism_anchor` and commit the new freeze.
EXIT_RED:1

=== GREEN: good --expect-report ===
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42); matches --expect-report /tmp/…/expect-good.json
…/S2A-determinism-anchor-run-20260811-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass_ungated …
EXIT_GREEN:0
```

Runs used **tmp copies** of the committed run-record and report.  
`git status --short docs/tasks/vlm/bakeoff-results/` → empty after every run.

### Base-passes-silently (proof gate is new coverage)

Without `--expect-report`, seed-stability alone still exits 0 even when a
doctored freeze file sits next to the record (parent and children agree on the
same run-record bytes — the pre-F5 hole):

```text
determinism check passed [score]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42)
EXIT:0
```

That is the same silent-pass class as base `439c8ee1` / pre-F5: corruption of an
external freeze was undetectable because nothing compared against it.

### Discrimination — three messages

| Scenario | Message class | Suite / CLI |
| --- | --- | --- |
| Clean seed + matching freeze | `determinism check passed [score]: …; matches --expect-report …` | CLI green above; `test_expect_report_matches_committed_freeze_green` |
| Seed diverge (mutated record between parent/child) with expect set | `determinism check FAILED` — **not** ANCHOR_MISMATCH | `test_cli_score_determinism_seed_failed_not_anchor_mismatch` |
| Matching freeze path missing | `determinism check ERROR` | path missing branch in `_check_expect_report` |
| Corrupt expect JSON | `determinism check ANCHOR_MISMATCH` | CLI red above; `test_corrupt_expect_report_makes_determinism_gate_red` |

### Gate

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
695 passed, 4 skipped, 408 deselected, 9 warnings in 80.64s (0:01:20)
```

Baseline was **693 passed, 3 skipped** (linux host note: 692/4). This run:
**0 failed**, passed **695** (> baseline). Net +3 from F5 controls (real
TEST-15 + green freeze match + CLI discrimination/coupling; replaced 1 tautology).

## Face path position (not forced)

`_check_face_determinism_cross_process` has the **same structural hole** (baseline
built from the same record children re-read). **No frozen face-report anchor
exists** in the repo. Generating one under time pressure was explicitly
out of scope (careless freeze is worse than none).

What a face anchor would need (separate lane):
- A regenerable offline face run-record + face-report JSON under a fixed stem
- A generator analogous to `generate_determinism_anchor.py` (seeded / offline)
- Wire `--expect-report` (or face-specific flag) into `score-face` the same way
- Digest pins + TEST-15 corruption control for the face freeze

**Leave face B-06 open.** Caption path is closed for F5.

## Residual

- **B-11** `describe_baseline.py` secrets path under `oci_vault` — still open;
  not F5 scope. Premise correction from inbox stands: default `env` backend makes
  provider and raw-env identical; residual risk is oci_vault fail-open only.
- Face frozen-anchor compare — deferred as above.

## Files changed (content summary)

| File | Change |
| --- | --- |
| `cli.py` | `_check_expect_report`, `expect_report=` on caption guard, `--expect-report` argparse, deferred pass announce |
| `test_eval_harness_determinism_anchor.py` | Replace sha256 tautology with gate-red + green freeze tests |
| `test_eval_harness_cli.py` | require-flag + FAILED-not-ANCHOR discrimination |
| `README.md` | third-outcome table + working command with `--expect-report` |
| `.s2a/vlm6-fix-f5-report.md` | this report |

No commit SHA recorded here (lane sandbox SHAs are not destination objects).
