# Lane `fx4` — vacuity honesty, generator provenance, anchor generators, docs

**Branch:** `feature/vlm-6-fx4` (this lane's branch)  
**Base:** `e2575b5ef09ed75de7f792546439d53624c9d344`  
**Owned files only** (nothing under `docs/tasks/vlm/bakeoff-results/**` was regenerated).

**Gate (excluding the five expected-red freeze tests):**
```
cd apps/prototype-description-service && .venv/bin/python -m pytest \
  scene/tests/test_eval_harness_determinism_anchor.py \
  scene/tests/test_eval_harness_face_determinism_anchor.py \
  scene/tests/test_eval_harness_caption_metrics.py \
  scene/tests/test_eval_harness_describe_baseline.py \
  scene/tests/test_eval_harness_manifest.py \
  --deselect …/test_generator_regenerates_byte_identical_committed_anchor \
  --deselect …/test_expect_report_matches_committed_freeze_green \
  --deselect …/test_face_generator_regenerates_byte_identical_committed_anchor \
  --deselect …/test_face_expect_report_matches_committed_freeze_green \
  --deselect …/test_cli_score_face_expect_report_end_to_end_green \
  -q
# 147 passed, 1 skipped, 5 deselected
```

---

## A. Anchor self-comparison / non-evidential face metrics

### VLM6-C-04 (high) — seeded predictions no longer pure GT echo

- **Files:** `generate_determinism_anchor.py` (`_identity_rows`, `_predicted_face_count`, `build_run_record`)
- **Choice:** **fixed seeded deviation** (not pure echo). Under-count / over-count face_count on index%7 / index%11; drop or inject identity names on index%5 / index%9. Keeps byte-stability while detection/identification can move (TEST-15).
- **Also:** `predictions_source=ground_truth_derived_fixture`, `face_metrics_evidential=false` in provenance.
- **RED (unfixed pure-echo scoring):**
  ```
  faces detection {'precision': 1.0, 'recall': 1.0, 'tp': 57, 'fp': 0, 'fn': 0}
  ident P/R 1.0 1.0; wrong_names []
  ```
- **GREEN (after fix):**
  ```
  detection {'fn': 6, 'fp': 3, 'precision': 0.944…, 'recall': 0.894…, 'tp': 51}
  ident P/R 0.878… 0.805…; wrong_names n=4 (Fixture-Wrong-*)
  test_seeded_predictions_are_not_pure_gt_echo PASSED
  ```
- **Behaviour:** Fixture predictions are labelled non-evidential and deliberately imperfect so metrics are not tautological.

### VLM6-E-04 (high) — MD surfaces coverage gaps + non-evidential face note

- **Files:** `generate_determinism_anchor.py` (`write_anchor` MD append); tests
- **RED:** committed / pre-fix MD had no `Coverage gaps` block (only JSON provenance).
- **GREEN:**
  ```
  test_generator_md_renders_coverage_gaps PASSED
  assert "Coverage gaps" in md; assert "non-evidential" in md
  ```
- **Behaviour:** Generated report MD always includes sampling-frame gaps and states face metrics are non-evidential.

---

## B. Vacuous categories honest

### VLM6-C-05 / VLM6-E-03 (high) — `fabricated_fact_rate` None when no traps

- **Files:** `caption_metrics.py:fabricated_fact_rate`
- **RED (unfixed):**
  ```
  AssertionError: expected None when no traps, got 0.0
  0.0
  ```
  (37 untrapped scores → rate `0.0` with denom=37)
- **GREEN:**
  ```
  test_fabricated_fact_rate_none_when_no_traps_corpus_wide PASSED
  assert fabricated_fact_rate(untrapped, over="all") is None
  ```
- **Behaviour:** Zero trap coverage → `None` (EVAL-19). Trap-present paths still return 0.0/fractions as before.

### VLM6-C-07 (medium) — `require_metric_backing` exercised by generator

- **Files:** `manifest.py:metric_backing_refusals`; `generate_determinism_anchor.py` stamps `metric_backing_refusals`
- **RED:** refusals absent from run-record provenance (API only unit-tested).
- **GREEN:**
  ```
  test_generator_stamps_metric_backing_refusals PASSED
  assert field in refusals for face_boxes/spatial_facts/reference_facts/demographic_cohort
  ```
- **Behaviour:** Generator calls the vacuity API and records refusals. Live score/verdict paths: see Cross-lane (fx2 already has `not_ready`).

### VLM6-E-07 (medium) — shared `compute_corpus_coverage_gaps`

- **Files:** `manifest.py:compute_corpus_coverage_gaps`; generators delegate
- **Behaviour:** Gap computation lives in `manifest.py` so live `cli`/`report` can stamp the same structure. Live call site not owned → Cross-lane.

---

## C. Coverage-gap accounting

### VLM6-C-01 (high) — populated count + threshold, not boolean

- **Files:** `manifest.py:compute_corpus_coverage_gaps`; `generate_determinism_anchor._coverage_gaps` alias
- **RED (old behaviour locked by prior test):** one injected row → `"face_boxes" not in gaps`.
- **GREEN:**
  ```
  test_coverage_gaps_keep_under_sampled_field_after_single_population PASSED
  assert gaps["face_boxes"]["populated"] == 1
  assert gaps["face_boxes"]["below_threshold"] is True
  ```
- **Behaviour:** Every registry field always reported with `populated`/`total`/`threshold`/`below_threshold`/`pi_zero`.

### VLM6-B-05 (medium) — vacuity keys on probe count

- **Files:** `generate_face_determinism_anchor.py:_is_vacuous_id_slice`, `compute_coverage_gaps`
- **RED (old predicate):**
  ```
  OLD vacuous on perfect n=5: True   # wrong — cell executed
  ```
- **GREEN:**
  ```
  NEW vacuous on perfect n=5: False
  test_id_slice_vacuity_keys_on_probe_count_not_errors PASSED
  assert "detection" not in gaps  # perfect detector tp>0, fp=fn=0
  ```
- **Behaviour:** ID vacuous iff `n_named_probes==0`; detection vacuous iff `tp+fp+fn==0` (not per-error-path zeros).

### VLM6-C-02 (medium) — gaps from `SHIPPED_CORPUS_COVERAGE_GAPS`

- **Files:** `manifest.py:compute_corpus_coverage_gaps`
- **GREEN:** `demographic_cohort` present in gaps on golden-37; registry cannot drift from disclosure.
- **Behaviour:** Gap keys = registry keys (incl. demographic_cohort).

### VLM6-C-08 (low) — schema-valid FaceBox in control

- **Files:** `test_eval_harness_determinism_anchor.py`
- **Behaviour:** Control uses `FaceBox(x,y,w,h,source=…)` (rg-005), not invalid `{width,height}` via silent `model_copy`.

### VLM6-B-04 (medium) — runtime `validate_coverage_gaps`

- **Files:** `generate_face_determinism_anchor.py:validate_coverage_gaps`; face generator calls it before promote
- **RED (old test was tautology):** only `compute != truncated` with no guard.
- **GREEN:**
  ```
  test_coverage_gaps_guard_fails_when_gap_list_under_declares PASSED
  with pytest.raises(CoverageGapsUnderDeclaredError): validate_coverage_gaps(report, declared=truncated)
  ```
- **Behaviour:** Under-declared gap list raises. Generator refuses to promote bad freezes.

---

## D. Provenance + atomic writes

### VLM6-F-04 (medium) — no fabricated contract `head_sha`

- **Files:** both generators
- **Behaviour:** Byte-stability sentinels live in `fixture_revision` / `canonical_timestamp`. Contract `head_sha` is `null` in pin mode (never 40 zeros). Optional `--live-head-sha` for real SHA.

### VLM6-F-05 (medium) — atomic multi-artifact promote

- **Files:** both generators (`_atomic_promote` via temp dir + `os.replace`)
- **Behaviour:** Full artifact set built and verified in temp, then same-directory atomic replace (rg-002).

### VLM6-C-09 (low) — no invented bboxes

- **Files:** `generate_determinism_anchor._identity_rows`
- **GREEN:** `assert "bbox" not in row` and `unpositioned is True` in `test_seeded_predictions_are_not_pure_gt_echo`.
- **Behaviour:** Fixture identity rows never invent pixel geometry.

---

## E. Documentation

### VLM6-C-03 (high) — Rubric caveat rewritten

- **Files:** `README.md`
- **Behaviour:** States measured `must_right` 34/37, `easy_wrong` 37/37; `RubricEmptyWarning` does **not** fire. Removed false “empty for every entry” claim.

### VLM6-F-06 / VLM6-E-06 (low/medium) — no hardcoded manifest digest

- **Files:** `README.md`
- **Behaviour:** Removed `859a083e…` literal; operators must read digest from the artifact. Inventory adds `demographic_cohort` 0/37 and fabricated-fact = undefined.

### VLM6-E-08 (medium) — “certified” means byte-stability only

- **Files:** `README.md` operator table + example command notes
- **Behaviour:** Green determinism gate explicitly “scoring-path byte-stability only”, not adoption / face quality.

---

## F. Baseline Δ reporting

### VLM6-C-06 (medium) — offline Δ vs zero-rule

- **Files:** `describe_baseline.py:score_rows_against_golden`, `_write_report`
- **Disposition from fx5:** implement (not defer). Adopted.
- **RED path:** unmatched media_ids → `status=undefined` (not a green absolute-only win); worse wrong-name caption → `delta.wrong_name_images > 0`.
- **GREEN:**
  ```
  test_score_rows_against_golden_undefined_when_no_match PASSED
  test_score_rows_delta_goes_red_when_candidate_worse_than_zero_rule PASSED
  test_write_report_includes_rubric_delta PASSED
  ```
- **Behaviour:** Report carries `summary.rubric_delta` vs zero-rule empty caption on real golden; MD prints Δ line.

---

## Anchor regeneration handoff

**Do not treat moving a headline from `0.0` → `None` as a regression.** That is the intended honesty outcome of this wave.

### Caption anchor regen
```bash
cd apps/prototype-description-service
.venv/bin/python -m scripts.eval_harness.generate_determinism_anchor \
  --manifest scene/tests/seed/golden.json \
  --out-dir ../../docs/tasks/vlm/bakeoff-results \
  --stem S2A-determinism-anchor-run-20260811 \
  --head-sha 0000000000000000000000000000000000000000 \
  --started-at 2026-08-11T00:00:00Z
```
(Also accept `--fixture-revision` / `--canonical-timestamp`.)

**Expected freeze number moves:**
| Field | Old freeze | After regen | Why |
| --- | --- | --- | --- |
| `faces.detection` P/R | 1.0 / 1.0 | ~0.94 / ~0.89 | seeded deviation |
| `faces.identification` P/R | 1.0 / 1.0 | ~0.88 / ~0.81 | seeded name drop/inject |
| `hallucination.fabricated_fact_rate` | **0.0** | **`None`** | no traps (EVAL-19) — **intended** |
| `verdict` | `pass_ungated` (stale) | `not_ready` (fx2) | category vacuity |
| `provenance.coverage_gaps` | 3 string fields | 4 structured records incl. `demographic_cohort` | C-01/C-02 |
| `provenance.head_sha` | 40 zeros | `null` + `fixture_revision` | F-04 |
| `predictions_source` / `face_metrics_evidential` | absent | set | C-04 |
| identity `bbox` | invented pixels | absent; `unpositioned=true` | C-09 |
| report MD | no coverage_gaps block | has `## Coverage gaps` | E-04 |

Also wait for **fx6** (`report.py`/`cli.py`) before regenerating — positional vacuity fields and verdict wiring will further change report bytes.

### Face anchor regen
```bash
cd apps/prototype-description-service
.venv/bin/python -m scripts.eval_harness.generate_face_determinism_anchor \
  --out-dir ../../docs/tasks/vlm/bakeoff-results
```

**Expected moves:**
| Field | Change |
| --- | --- |
| `provenance.head_sha` | 40 zeros → `null`; add `fixture_revision` |
| `coverage_gaps` predicate | perfect ID / perfect detection no longer listed as gaps |
| freeze digests | all four artifacts will change |

Update `_FROZEN_DIGESTS` in both test modules only as part of the regen lane.

### Expected-red tests (this lane — do not “fix” by editing freezes)
- `test_generator_regenerates_byte_identical_committed_anchor`
- `test_expect_report_matches_committed_freeze_green`
- `test_face_generator_regenerates_byte_identical_committed_anchor`
- `test_face_expect_report_matches_committed_freeze_green`
- `test_cli_score_face_expect_report_end_to_end_green`

---

## Cross-lane requests

1. **`cli.py` / `report.py` (fx6 or owners):** stamp `provenance.coverage_gaps = compute_corpus_coverage_gaps(manifest.entries)` on live fetch/score (VLM6-E-07). Import from `scripts.eval_harness.manifest`.
2. **`report.py`:** call `metric_backing_refusals` / honour `fabricated_fact_rate is None` in MD (`_fmt(None)` already) and in any gate that treated `0.0` as clean (fx2 verdict already blocks placement/positional; ensure fabricated-fact vacuity is named if not already).
3. **`cli.py` compare:** already blocks vacuous fabricated-fact via `images_with_traps==0` (fx1) — keep that; do not re-introduce meet-or-beat on `None`.
4. **Task plan (fx5):** phrase “empty on 0/37” vs “0/37 entries populate it” consistently with README inventory (same fact, same wording).
5. **MD renderer in `report.py`:** prefer first-class coverage_gaps + non-evidential face section so generators need not append MD post-hoc (fx4 currently appends if missing).

---

## Deferred

| Item | Reason |
| --- | --- |
| Golden-100 population of `face_boxes` / `spatial_facts` / `reference_facts` | Slice 1 corpus work; gate is honest today via `None` / `not_ready` / structured gaps |
| Florence offline Δ arm in describe_baseline | Zero-rule arm lands now; Florence freeze path needs a committed scored baseline not owned here |
| Committed freeze regen | Explicitly owned by a later serialized lane after fx6 |

---

## Heuristics cited

TEST-15, EVAL-04, EVAL-13, EVAL-16, EVAL-19, EVAL-23, AUDIT-07, MLDATA-09, rg-002, rg-005, rg-008, rg-015, sr-001, sr-006, sr-007.
