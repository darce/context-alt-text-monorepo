# VLM-6 fx6 — cross-lane wiring report

Lane: `fx6` · Branch: `feature/vlm-6-fx6` (this lane's branch) · Base: `e2575b5ef09ed75de7f792546439d53624c9d344`

Scope: `report.py`, `cli.py`, `test_eval_harness_report.py`, `test_eval_harness_cli.py`.

Heuristics: `TEST-15`, `EVAL-04`, `EVAL-13`, `EVAL-19`, `EVAL-23`, `AUDIT-07`, `rg-002`, `rg-005`, `rg-015`, `sr-001`, `sr-006`, `sr-007`.

---

## Findings fixed

### VLM6-B-03 — centre-based L→R on production positional path

**Files:** `report.py` (`score_run_record` positional wiring) · `cli.py` (`_extract_identities` + fetch call site)

**Behaviour change:** Production positional scoring calls `predicted_names_for_positional` (centre-x + leftmost-wins) instead of raw `identity_names` list order; wire extract delegates to `sort_identity_rows_by_normalized_centre` so corner-x never forks a third rule. Unit dims fallback preserves absolute centre-x order when capture size is missing.

**RED (unfixed `score_run_record` + corner extract):**
```
position_accuracy 0.0
position_hits 0 / 2
exact_order 0.0 swaps 1
corner-based names: ['Wide Right', 'Narrow Left'] ordering positional
```
Assertion target (GREEN): `pos["position_accuracy"] == 1.0` and extract names `['Narrow Left', 'Wide Right']`.

**GREEN:**
```
test_score_run_record_positional_uses_centre_x_not_corner_x PASSED
test_extract_identities_orders_by_centre_x_not_corner_x PASSED
assert pos["position_accuracy"] == pytest.approx(1.0)
assert names == ["Narrow Left", "Wide Right"]
```

---

### VLM6-B-10 — positional vacuity in report JSON + verdict consumption

**Files:** `report.py` (positional block fields; `build_score_verdict` status/evaluable; MD vacuity line)

**Behaviour change:** Report emits `evaluable` / `status` / `vacuity_signal` / `sampling_frame` on `faces.identification.positional`. Verdict treats `status=not_evaluable` / `evaluable=False` / `compared_images=0` as category-vacuity → `not_ready` (one `ScoreVerdict` enum, sr-007).

**RED (unfixed report JSON on real golden shape):**
```
vacuity fields {'evaluable': None, 'status': None, 'vacuity_signal': None, 'sampling_frame': None}
```
(keys absent → `.get` yields None; no machine-readable block)

**GREEN:**
```
test_score_run_record_positional_vacuity_signal_on_real_golden PASSED
assert pos["evaluable"] is False
assert pos["status"] == "not_evaluable"
assert pos["vacuity_signal"]  # non-empty, names π=0
assert scored["verdict"]["verdict"] == ScoreVerdict.NOT_READY.value

test_score_run_record_positional_vacuity_absent_when_measurable PASSED
assert pos["evaluable"] is True
assert pos["status"] == "scored"
assert pos["vacuity_signal"] is None
assert scored["verdict"]["verdict"] == ScoreVerdict.PASS.value
```

---

### Reconcile seven CLI tests to honest `not_ready` / measurable pass

**File:** `test_eval_harness_cli.py`

All seven originally failed as `assert 'not_ready' == 'pass'` (or exit-0 assumed over vacuous fixture). **Did not weaken the verdict.**

| Test (final name) | Old assertion | New assertion | Why honest |
| --- | --- | --- | --- |
| `test_cmd_score_public_audience_emits_redacted_public_artifact` | `verdict=="pass"`, exit 0 on vacuous W1 fixture | fixture gains face_boxes+spatial_facts+placement claim; still `verdict=="pass"`, exit 0 | Tests PUBLIC redaction happy path — needs a genuinely measurable clean run, not a dishonest pass |
| `test_cmd_score_default_local_emits_no_public_artifact` | `verdict=="pass"` on vacuous W1 | same measurable W1 fixture; `verdict=="pass"` | Same — LOCAL default success must be real pass |
| `test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures` | `verdict=="pass"` without face_boxes | measurable single-image fixture; `verdict=="pass"`, compared_images≥1, claims≥1 | Name claims exit 0 — only valid with π>0 categories |
| `test_score_guard_rubric_gate_skip_bypasses_must_right_gate` | skip → `pass_ungated` on vacuous corpus | measurable corpus; skip → `pass_ungated` exit 0; enforce still must-right fail | skip only exempts must-right; pass_ungated requires measurable categories |
| `test_score_persisted_verdict_not_ready_on_real_golden` (was `…_control_pass_on_real_golden`) | `verdict=="pass"`, reasons=[], exit 0 | `verdict=="not_ready"`, positional+placement reasons, exit ≠0, B-10 fields present | Real golden has face_boxes/spatial_facts on **0/37** — pass is dishonest |
| `test_score_persisted_verdict_skip_still_not_ready_on_real_golden` (was `…_pass_ungated_on_rubric_gate_skip`) | skip → `pass_ungated`, reasons=[], exit 0 | skip → `not_ready`, exit ≠0, rubric_gate=skip still recorded | skip does not clear category vacuity |
| `test_score_f1d2_control_clean_real_golden_not_ready` (was `…_still_passes`) | `verdict=="pass"`, reasons=[] | `verdict=="not_ready"`, reasons non-empty, must_right_defined=34, scored=37 | Controls denominators while readiness correctly refuses pass |

**RED (pre-test-update, post-fx2 merge):**
```
FAILED ...::test_score_persisted_verdict_control_pass_on_real_golden - AssertionError: assert 'not_ready' == 'pass'
  - pass
  + not_ready
```

**GREEN:** 7/7 updated tests pass (plus helpers `_single_name_measurable_fields`, measurable `_corpus_entries` / `_clean_score_manifest_and_record`).

---

### VLM6-OBS-04 — process exit matches artifact

**File:** `cli.py` (`_cmd_score` post-gate)

**Behaviour change:** After existing integrity/quality gates, if persisted `verdict==not_ready`, raise `ScoreGateError` with class token `score category-vacuity gate` so process exit is non-zero. No silent green over unmeasurable corpus.

**RED (artifact not_ready, process still green before gate):**
```
# test_score_persisted_verdict_control_pass_on_real_golden (pre OBS-04 exit gate)
assert main([...]) is None   # exit 0
# stdout: verdict=not_ready ...
AssertionError: assert 'not_ready' == 'pass'
```

**GREEN:**
```
test_score_persisted_verdict_not_ready_on_real_golden PASSED
with pytest.raises(SystemExit) as excinfo:
    main(["score", ...])
assert excinfo.value.code != 0
assert "category-vacuity" in str(excinfo.value).lower() or "not_ready" in ...
# message includes: score category-vacuity gate: verdict=not_ready (...)
```

---

### fabricated_fact_rate `None` coupling (fx4 / VLM6-C-05)

**Files:** `report.py` (`build_score_verdict`) · `cli.py` (`_compare_vacuous_categories`) · MD already None-safe via `_fmt`

**Behaviour change:** `fabricated_fact_rate is None` → category-vacuity reason → `not_ready` (not a clean 0.0 pass). Numeric `0.0` still allowed when traps exist and none fired. Compare treats `rate is None` as non-observable. Consumers accept both `0.0` and `None`.

**RED (inject None on otherwise-passable scored dict without vacuity fold):**
```
# Without fab None handling: verdict would be pass with empty reasons
# (only positional/placement checked). After fix:
assert verdict["verdict"] == ScoreVerdict.NOT_READY.value  # would fail as pass
```

**GREEN:**
```
test_build_score_verdict_treats_fabricated_fact_rate_none_as_vacuous PASSED
assert verdict["verdict"] == ScoreVerdict.NOT_READY.value
assert any("fabricated_fact" in r for r in verdict["reasons"])
# control: rate=0.0 + traps>0 → pass
assert verdict_ok["verdict"] == ScoreVerdict.PASS.value
```

---

## Expected-red (not this lane)

Determinism-anchor freeze tests remain red until the serialized regen lane rewrites frozen bytes (`sr-001` — do not loosen or skip):

- `test_generator_regenerates_byte_identical_committed_anchor`
- `test_expect_report_matches_committed_freeze_green`
- `test_face_generator_regenerates_byte_identical_committed_anchor`
- `test_face_expect_report_matches_committed_freeze_green`
- `test_cli_score_face_expect_report_end_to_end_green`

Owner: regen lane after fx4 + fx6 land.

---

## Cross-lane requests

None blocking for this lane's assigned work. Optional notes for others:

1. **fx4 / caption_metrics:** When `fabricated_fact_rate` returns `None` for no-trap corpora, consumers in this lane already treat it as vacuity. No further report/cli change expected.
2. **Regen lane:** Re-freeze determinism anchors after this branch merges; vacuity fields + centre-ordered positional change report bytes.
3. **Docs/README (not owned):** Document that `score` exits non-zero on `verdict=not_ready` (OBS-04) and that PUBLIC happy-path fixtures need measurable categories.

---

## Deferred

| Item | Reason |
| --- | --- |
| Real golden `verdict=pass` | Requires Golden-100 / Slice 1 population of `face_boxes` + `spatial_facts` (π>0). Gate is honest *today* via `not_ready` + non-zero exit. |
| Set-based ID scoring right-names-on-wrong-faces | Positional path is now centre-correct; set-based P/R still order-blind until box-grounded identity claims exist corpus-wide (Slice 1). |

---

## Verification summary

```
# RED evidence captured pre-fix (B-03, B-10, 7 CLI pass assertions, OBS-04 exit 0)
# GREEN battery (finding tests): 12 passed
# Owned modules full: scene/tests/test_eval_harness_cli.py + test_eval_harness_report.py
#   → 230 passed in ~61s
```

Commits: conventional `fix(vlm-6): ...` on this lane's branch (no Co-Authored-By).
