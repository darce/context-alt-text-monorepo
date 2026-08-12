# VLM-6 lane `fx1` fix report

Branch: `feature/vlm-6-fx1` (this lane's branch). Base: `e2575b5ef09ed75de7f792546439d53624c9d344`.

Owned files only:
- `apps/prototype-description-service/scripts/eval_harness/cli.py`
- `apps/prototype-description-service/scene/tests/test_eval_harness_cli.py`
- `.s2a/vlm6-fx1-report.md`

TEST-15 method: write defect-reproducing tests → run against unfixed code (RED) → apply fix → re-run (GREEN). Final gate: **15 passed**.

---

## VLM6-E-01 (high) — `insertion_rate` polarity inversion

**Files:** `cli.py` (`_COMPARE_LOWER_IS_BETTER` / `_COMPARE_HIGHER_IS_BETTER`); `test_cli_compare_insertion_rate_lower_is_better`

**Behaviour change:** `caption.insertion_rate` moved to lower-is-better (hallucinated-identity rate).

**RED (unfixed):**
```
caption.insertion_rate: baseline=0.1 candidate=0.5 (higher-better)
Failed: DID NOT RAISE SystemExit
```
Candidate with *more* insertions was treated as better; worse-case did not exit non-zero.

Also:
```
SystemExit: compare regression gate: ... caption.insertion_rate: candidate 0.05 < baseline 0.1
```
(lower insertion_rate incorrectly failed meet-or-beat)

**GREEN:**
```
test_cli_compare_insertion_rate_lower_is_better PASSED
```
Higher insertion_rate → `compare regression gate` + `insertion_rate`; lower → PASS with `lower-better` surface.

---

## VLM6-A-02 / VLM6-F-02 (high) — `compare` claimed same-corpus without validation

**Files:** `cli.py` (`_cmd_compare`, `_compare_require_caption_report`, `_compare_protocol_mismatches`, `_compare_non_degenerate_corpus`); tests `test_cli_compare_rejects_handwritten_four_field_json`, `test_cli_compare_rejects_pass_ungated_baseline`, `test_cli_compare_rejects_manifest_digest_mismatch`

**Behaviour change:** Fail closed unless both inputs are `schema=acx-eval/v1` + `kind=report`, non-degenerate counts, matching protocol pins (`score_manifest_sha256`, `eval_mode`, `rubric_gate`, prompt/pipeline flags, audience), and baseline `verdict=pass`. `pass_ungated` / bare four-field JSON refused.

**RED:**
```
Failed: DID NOT RAISE SystemExit   # handwritten four-field JSON
Failed: DID NOT RAISE SystemExit   # pass_ungated baseline
Failed: DID NOT RAISE SystemExit   # manifest digest mismatch
```

**GREEN:**
```
test_cli_compare_rejects_handwritten_four_field_json PASSED
test_cli_compare_rejects_pass_ungated_baseline PASSED
test_cli_compare_rejects_manifest_digest_mismatch PASSED
```
Exit text includes `compare same-corpus gate:` / `compare adoption gate:` with schema/kind/protocol/verdict detail.

Heuristics: `rg-005`, `rg-008`, `EVAL-13`.

---

## VLM6-A-03 / VLM6-F-01 / VLM6-E-02 (high) — gate omitted every category that matters

**Files:** `cli.py` (full adoption metric tables + `_compare_vacuous_categories` + harness-37 block); tests `test_cli_compare_vacuous_category_blocks_adoption`, `test_cli_compare_harness_37_refuses_adoption_pass`, `test_cli_compare_meet_or_beat_all_categories_pass`

**Behaviour change:** Compare surfaces detection/identification P/R, positional accuracy, identity ordering, placement, fabricated-fact rates, plus caption scalars. `None`/π=0 categories → `BLOCKED non_observable_categories`. Corpus `scored=total=37` → `NOT_ADOPTION_ELIGIBLE corpus=harness-37` (no adoption PASS).

**RED:**
```
Failed: DID NOT RAISE SystemExit   # vacuous placement still comparable
AssertionError: assert ('37' in 'compare regression gate: ... insertion_rate ...' ...)
SystemExit: compare regression gate: ... insertion_rate: candidate 0.05 < baseline 0.1
  # (false polarity; never reached adoption-category surface)
```

**GREEN:**
```
test_cli_compare_vacuous_category_blocks_adoption PASSED
test_cli_compare_harness_37_refuses_adoption_pass PASSED
test_cli_compare_meet_or_beat_all_categories_pass PASSED
```
Adoption PASS path prints all category labels including `detection.precision`, `position_accuracy`, `placement.accuracy`, `fabricated_fact_rate`.

Heuristics: `EVAL-23`, `EVAL-04`, `AUDIT-07`.

---

## VLM6-F-03 (high) — manifest drift only warned

**Files:** `cli.py` (`_fold_manifest_drift_into_verdict`, `--allow-manifest-relabel`); tests `test_cmd_score_manifest_drift_fails_closed`, `test_cmd_score_allow_manifest_relabel_marks_non_comparable`, `test_score_fetch_sha_drift_fails_closed_without_relabel_flag`

**Behaviour change:** `manifest_matches_fetch=false` hard-fails (`score manifest-drift gate`). `--allow-manifest-relabel` persists `verdict=non_comparable` (compare rejects) and still exits non-zero. Missing fetch-time sha keeps distinct `manifest-mismatch` token.

**RED:**
```
[score] WARNING manifest drift: scored against manifest ddd... but fetched under 9a49...
Failed: DID NOT RAISE SystemExit
# and: unrecognized arguments: --allow-manifest-relabel
```

**GREEN:**
```
test_cmd_score_manifest_drift_fails_closed PASSED
test_cmd_score_allow_manifest_relabel_marks_non_comparable PASSED
test_score_fetch_sha_drift_fails_closed_without_relabel_flag PASSED
```
Hard-fail message: `score manifest-drift gate: ... manifest_matches_fetch=false ... EVAL-13`. Relabel path writes `verdict=non_comparable`.

Heuristic: `EVAL-13`.

---

## VLM6-E-05 (high) — `score` rewrote committed freeze reports

**Files:** `cli.py` (`_score_report_base`, `_refuse_report_overwrite`, `--allow-overwrite-report`); test `test_cmd_score_does_not_clobber_committed_freeze_reports`

**Behaviour change:** Run-records under `docs/tasks/vlm/bakeoff-results` write reports to git-ignored `OUT_DIR`. Existing reports under that tree refuse overwrite without `--allow-overwrite-report`. Operator tmp/out may re-score freely.

**RED:**
```
Failed: DID NOT RAISE SystemExit
# freeze sentinel was overwritten by plain score
```

**GREEN:**
```
test_cmd_score_does_not_clobber_committed_freeze_reports PASSED
```
Freeze sentinel preserved; report lands in `OUT_DIR`.

Heuristic: `rg-002`.

---

## VLM6-A-04 (medium) — PUBLIC verdict folds only on LOCAL

**Files:** `cli.py` (`_cmd_score` public path stamps LOCAL folded verdict); test `test_cmd_score_public_carries_local_folded_verdict`

**Behaviour change:** After LOCAL schema/evidence/relabel folds, PUBLIC artifact receives the same `verdict` dict before write.

**RED:**
```
AssertionError: assert 'pass' == 'fail'
  - fail
  + pass
# LOCAL fail, PUBLIC still pass
```

**GREEN:**
```
test_cmd_score_public_carries_local_folded_verdict PASSED
```
Both audiences: `verdict=fail`.

---

## VLM6-A-06 (medium) — `score-face --public` clobbered LOCAL

**Files:** `cli.py` (`_cmd_score_face` audience-suffixed paths); test `test_cmd_score_face_public_uses_audience_suffix`

**Behaviour change:** LOCAL → `{base}-face-report.json`; PUBLIC → `{base}-face-report.public.json` (same pattern as caption reports).

**RED:**
```
AssertionError: public face report must use .public suffix
assert False
```

**GREEN:**
```
test_cmd_score_face_public_uses_audience_suffix PASSED
```
PUBLIC lands on `.public.json`; LOCAL bytes unchanged.

---

## VLM6-A-07 (low) — face gate re-derived instead of reading written artifact

**Files:** `cli.py` (`_cmd_score_face` gates on `json.loads(json_path.read_text())`); test `test_cmd_score_face_gates_on_written_document`

**Behaviour change:** After write, gate reads back the written document. No second `score_face_run_record` re-derive.

**RED:**
```
Failed: DID NOT RAISE SystemExit
# re-derived scored=3/3 while written counts.scored=0
```

**GREEN:**
```
test_cmd_score_face_gates_on_written_document PASSED
```
Exit: `score-face zero-scored gate: scored=0 items`.

Heuristic: `TEST-15`.

---

## VLM6-A-08 (low) — `_serialize_score_docs` swallowed renderer errors

**Files:** `cli.py` (`_serialize_score_docs`); test `test_serialize_score_docs_propagates_renderer_errors`

**Behaviour change:** Default re-raises `KeyError`/`TypeError`/`AttributeError`. Schema-degraded fail paths may set `tolerate_renderer_error=True` and emit loud `**RENDERER ERROR**` markdown (never the pre-fix soft stub).

**RED:**
```
Failed: DID NOT RAISE KeyError
# stub markdown absorbed the exception
```

**GREEN:**
```
test_serialize_score_docs_propagates_renderer_errors PASSED
```

Heuristic: `sr-006`.

---

## Cross-lane requests

None blocking. Related surfaces other lanes may care about:

1. **Report builders / Golden-100 (other lanes):** `compare` now refuses adoption PASS on the 37-item harness and on vacuous placement/positional/fabricated-fact categories. When Golden-100 lands, those categories must become non-None with non-zero denominators or adoption will stay blocked by design.
2. **Docs/README (not owned):** mention `--allow-manifest-relabel`, `--allow-overwrite-report`, and that freeze run-records score into `out/`.
3. **`generate_determinism_anchor.py` (not owned):** uses `_serialize_score_docs`; default path still works for well-formed scored docs. If it scores freeze-tree paths, outputs now land in `OUT_DIR` unless `--allow-overwrite-report` is wired there separately.

---

## Deferred

| Item | Reason |
|------|--------|
| Golden-100 corpus population (`face_boxes`, `spatial_facts`, `reference_facts`) | Slice 1 work; not in this lane. Gate is honest *today* via vacuity/harness-37 blocks rather than pretending π>0. |
| Making detection/identification P/R fail closed when identity is set-based only | Right-names-on-wrong-faces still can score clean on set-based P/R until positional labels exist; positional/`identity_ordering` vacuity already blocks adoption. |
| New `ScoreVerdict` enum member in `report.py` | Not owned. Used string `non_comparable` in CLI fold + compare reject list; promoting to `report.ScoreVerdict` is a follow-up for the report-owning lane. |

---

## Test evidence summary

| Phase | Command (literal paths) | Result |
|-------|-------------------------|--------|
| RED | 14 new finding tests vs unfixed `cli.py` | **14 failed** |
| GREEN | 15 finding tests after fix | **15 passed** |
| Regression | `test_eval_harness_cli.py -k "score and not determinism and not face_bakeoff and not buffalo"` | **47 passed** |
