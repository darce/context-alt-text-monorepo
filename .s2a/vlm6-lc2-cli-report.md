# Lane report: `vlm6-lc2-cli` (VLM-6) — **reconstructed post-hoc by lane fx5**

> **Provenance warning:** This file was **not** authored by lane `lc2`.
> Lane `fx5` reconstructed it from merge `adefe97a` / offload commit
> `3e57f7e7` ("Fixed residual lc2 CLI gates") and verified behaviour against
> the code at **this lane's branch** HEAD. Inferred work items are **not**
> closed finding IDs — do not treat the labels below as handoff findings.

**Lane (original):** `feature/vlm-6-lc2`  
**Task:** `VLM-6`  
**Owned paths in the merge (from commit):**
- `apps/prototype-description-service/scripts/eval_harness/cli.py` (+268)
- `apps/prototype-description-service/scene/tests/test_eval_harness_cli.py` (+403)

## What the commit actually landed (verified at HEAD)

### 1. `ScoreGateError` + `_score_gate_fail` (post-write gates raise, not `sys.exit`)

`_cmd_score` / `_cmd_score_face` integrity gates raise `ScoreGateError` via
`_score_gate_fail`. `main()` maps that to `SystemExit` so standalone
`score` / `score-face` still exit non-zero with the gate message.

**Why:** so `run` can score every fetched provider record and exit once with a
per-record summary instead of aborting the loop on the first gate
(B-10 / residual CLI gates).

**Test that pins it:** `test_cmd_run_scores_all_records_despite_gate_failure`
(spies / injects `ScoreGateError` and asserts the multi-record summary exit).

### 2. Evidence gates folded into the on-disk verdict

`_fold_evidence_gates_into_verdict` mutates `scored["verdict"]` to fail when:

| Condition | Class token (operator message) |
| --- | --- |
| `record["aborted"]` | `score aborted-record gate:` |
| `counts.scored == 0` | `score zero-scored gate:` |

Standalone path also raises after write so CLI exit is non-zero.

**Tests:** `test_score_aborted_record_exits_nonzero`,
`test_score_zero_scored_exits_nonzero`.

### 3. Gate order on `_cmd_score` (class-unique tokens)

Verified message stems at HEAD (cite by **test name**, not frozen literals —
sibling lanes may rephrase operator text):

| Order | Gate | Discrimination test |
| --- | --- | --- |
| 1 | aborted-record | `test_score_aborted_record_exits_nonzero` |
| 2 | failed-items | pre-existing failed-items guards |
| 3 | zero-scored | `test_score_zero_scored_exits_nonzero` |
| 4 | truncation (media-id multiset) | `test_score_guard_fetch_limit_truncation_fails_coverage_gate` |
| 5 | manifest-mismatch (missing fetch-time sha) | `test_score_guard_missing_fetch_sha_fails_manifest_mismatch_gate` |
| 6 | empty-rubric (`must_right` / `easy_wrong` independent) | `test_score_guard_empty_must_right_fails_empty_rubric_gate`, `test_score_guard_empty_easy_wrong_fails_empty_rubric_gate` |
| 7 | must-right failures | `test_score_guard_caption_corruption_fails_must_right_gate` |
| 8 | wrong-name floor vacuity | (vacuity gate in `_cmd_score`) |
| 9 | wrong-name floor | `test_score_guard_wrong_names_fails_wrong_name_floor_gate` |

### 4. `IdentityOrdering` StrEnum (sr-007)

Producer `_extract_identities` emits `IdentityOrdering.POSITIONAL` /
`IdentityOrdering.DEGRADED` values (wire form still the string). Call sites
and tests import the enum rather than scattering `"positional"` /
`"degraded"` literals.

**Tests:** identity extraction / fetch tests asserting
`IdentityOrdering.DEGRADED.value` on unpositioned rows (A-07 / RH-06).

### 5. `compare` subcommand — meet-or-beat regression gate (VLM6-R2-08)

`_cmd_compare` loads baseline + candidate report JSON and fails closed on
regression for:

- higher-is-better: `caption.insertion_rate`, `caption.mean_gated_score`
- lower-is-better: `caption.must_right_failed_images`, `verdict.wrong_name_rate`
  (with fallback to `faces.identification.wrong_names` list length)

**Test:** `test_cli_compare_meet_or_beat_pass_and_regression`.

### 6. `run` continues after per-record gate failure

`_cmd_run` catches `ScoreGateError` per record, prints
`score gate failed for <path>: …`, then exits once:

`run score gates failed for N record(s): …`

## Explicit non-claims

- This reconstruction does **not** assert that any handoff finding ID was
  closed by lc2 — the original lane shipped no `.s2a` report and no finding
  table.
- Sibling lanes own `report.py`, bakeoff-results anchors, and later gate
  message edits; message text above is descriptive of HEAD at reconstruction
  time and should be re-checked via the named tests.

## Verification (fx5 reconstruction)

```bash
# Behaviour still present at HEAD — do not re-run full suite from this lane.
# Spot-check: symbols and tests named above exist in cli.py / test_eval_harness_cli.py.
```

Confirmed present at reconstruction time: `ScoreGateError`,
`_fold_evidence_gates_into_verdict`, `_cmd_compare`, the aborted/zero-scored
tests, and `test_cmd_run_scores_all_records_despite_gate_failure`.
