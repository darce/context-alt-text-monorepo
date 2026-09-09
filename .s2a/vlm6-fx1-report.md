# Lane fx1 report — metrics correctness, rendering, PUBLIC redaction

**Branch:** `fix/fx1`  
**Base:** `b28e126e89bc41202e0168276f8493511212c80d` (`feature/vlm-6`)  
**Commits:**
- Slice 1: `e7d2d0c6c2468ca6fa745f427e75e1dcba537e5e` — HARM-01/06/07/09 + RV3-04
- Slice 2: `3677f42c5d53de37bfec51745f8b3821ac36591a` — HARM-04 + RV1-02/03/04 + RV4-01/05

**Worktree:** `/home/ubuntu/lane-gx2` only. No merge/rebase.

---

## 1. Per finding

### HARM-01 (high) — detection FN drift — **FIXED**

**Change:** `_detection_from_assignment` sets `fn = missed_gt + missed_stranger_gt`. Detection is identity-agnostic (“was a box found?”); identification remains named-only for FN fold-in (`face_assignment.py` docstring unchanged — still correct for id).

**Why:** `tp` summed all association pairs (named+stranger) while `fn` used named-only `missed_gt` → recall over different populations.

**RED/GREEN:**
```
HARM-01 RED: broken fn=0 recall=1.0 (want fn=1 recall=0.5)
HARM-01 GREEN: fixed fn=1 recall=0.5
```
Test: `test_detection_from_assignment_counts_stranger_fn` — also asserts `tp + fn == GT boxes in association`.

Confirmed: `_detection_from_assignment` had **zero** prior test references (only production call site).

### HARM-09 (low) — surface `missed_stranger_gt` — **FIXED**

**Change:** `slices.unknown_rejection.missed_stranger_gt = int(assignment.missed_stranger_gt)`; deleted wave-C deferral comment.

**RED/GREEN:** Key absence was the pre-fix state (deferred comment). GREEN: `test_score_face_unknown_rejection_surfaces_missed_stranger_gt` asserts key present and `== 1` when stranger detections dropped.

### HARM-06 (medium) — named-GT predicate — **FIXED**

**Change:** Single `gt_box_name()` in `face_assignment.py`: `None` / empty / whitespace → anonymous. Used by `_gt_fields`, `collect_matched_faces`, and report headline association counts. `_leftmost_unique_names` is the single leftmost-wins loop for both labeled and predicted paths.

**RED/GREEN:**
```
HARM-06 RED: old_gt_box_name('')='' (non-None = wrong)
HARM-06 GREEN: gt_box_name('')=None
```
Test: `test_gt_box_name_empty_string_is_anonymous` (empty name → stranger miss, not named `missed_gt`).

### HARM-07 (low) — fabricated y=0.0 — **FIXED**

**Change:** Never invent `y=0.0`. When all named boxes have `y`, sort via `normalized_centre_order_key(x,y,name)`. When any named box lacks `y`, sort by `(x, name)` only (real primary + name tertiary). Partial-x fixtures still order by real `x`.

**RED/GREEN:**
```
HARM-07 RED: y-default order=['Alice', 'Bob'] (invented y=0.0 path)
HARM-07 GREEN: no fabricated y; y-aware order ['Low','High'] at same x
```
Test: `test_labeled_left_to_right_tie_stable_across_input_order`.

### RV3-04 (medium) — alias pin — **FIXED**

**Change:** `predicted_names_for_positional = predicted_left_to_right` (object identity). Test requires strict `is`; drives alias through Zebra/Aardvark + centre-y fixtures.

**RED/GREEN:**
```
RV3-04 RED soft-pin: soft_ok=True (mutant re-clone passes behavioural or-fallback)
RV3-04 GREEN strict-is: real alias is=True; mutant strict_ok=False
```

### HARM-04 (medium) — face MD nulls/bools — **FIXED**

**Change:** `_fmt_prov` renders bools as `true`/`false`. `_markdown_face` routes nullable/bool fields through `_fmt_prov`, adds `started_at` line. Test exercises **face** renderer.

**RED/GREEN:**
```
HARM-04 RED str(False)= False
HARM-04 GREEN _fmt_prov(False)= false
```
Test: `test_face_markdown_renders_null_and_bool_json_tokens`.

### RV1-02 (high) — sample-size outside shared predicate — **FIXED**

**Change:** `SCORE_PASS_MIN_SCORED_IMAGES` check moved into `score_vacuous_category_labels` (label `sample_size`). `build_score_vacuity_reasons` formats reason from that label. Compare already consults the shared predicate via `_compare_vacuous_categories` — **no cli.py edit required**.

**RED/GREEN:**
```
RV1-02 RED old labels sample_size? False
RV1-02 GREEN new labels ['sample_size', ...]
```
Test: `test_sample_size_in_shared_vacuity_predicate_blocks_compare` (forged `verdict=pass` + `scored=1`).

### RV1-03 (medium) — floor n=2 unjustified — **FIXED**

**Change:** `SCORE_PASS_MIN_SCORED_IMAGES = 5` with documented derivation: first n where `P(all-correct|p=0.5) = 0.5^n < 0.05` (`0.5^5 = 0.03125`; `n=2` yields `0.25`).

**RED/GREEN:** n=2 measurable corpus now `not_ready` (`test_undersized_but_gt1_corpus_is_not_ready`). Pass fixtures expanded to n≥5.

### RV1-04 (medium) — IEEE-corner floors — **FIXED**

**Change:**
- `POSITION_ACCURACY_FLOOR = 0.5`
- `PLACEMENT_ACCURACY_FLOOR = 0.5`
- `FABRICATED_FACT_RATE_CEILING = 0.5`

Derivation: at-or-below chance on binary L→R/spatial claim, or majority of traps firing, is measured-and-bad. Boundary tests at threshold ± eps.

**RED/GREEN:**
```
RV1-04 RED pos_acc=0.0001 vs old floor 0.0: would PASS; vs new 0.5 FAIL
RV1-04 GREEN fab=0.9999 fails under ceiling 0.5
```

### RV4-01 (high) — PUBLIC path-list identity leak — **FIXED**

**Change:** Nested path lists emit `media_id:N` when resolvable, else `<path>` / `<absolute>`. Deleted space-bearing-basename heuristic. Idempotent on already-redacted tokens (second `_redact_public_paths` pass).

**RED/GREEN:**
```
RV4-01 RED old path celebs01/JaneDoePrivate-with-obama.jpg
RV4-01 GREEN new path media_id:10
```
Test: `test_public_path_lists_opaque_no_space_identity_slug` — slug absent from whole PUBLIC blob; `excluded_images` / `degraded_paths` = `["media_id:10"]`.

### RV4-05 (medium) — case-sensitive scrub — **FIXED**

**Change:** `_scrub_identity_names` uses NFKC + case-insensitive regex; also hyphen/underscore/slug compacted forms. Allow-listed string fields default-deny (opaque unless free-text handler).

**RED/GREEN:**
```
RV4-05 RED old jane doe private JaneDoePrivate
RV4-05 GREEN new [redacted] [redacted]
```
Test: `test_public_scrubs_case_and_slug_identity_variants`.

---

## 2. Disagreements

None. All 11 findings treated as real; each fixed with RED→GREEN evidence.

---

## 3. Anchor tests broken (for lane fx5)

| Test | Cause |
|------|--------|
| `test_face_generator_regenerates_byte_identical_committed_anchor` | HARM-01 (detection fn/recall) + HARM-09 (`missed_stranger_gt` key) |
| `test_face_expect_report_matches_committed_freeze_green` | same |
| `test_cli_score_face_expect_report_end_to_end_green` | same |

Diff artifact shows new `slices.unknown_rejection.missed_stranger_gt` and detection count shifts. **Do not regenerate from this lane** — fx5 owns freeze regen.

No caption determinism-anchor failures observed from this lane.

---

## 4. Full suite result

```
10 failed, 1268 passed, 4 skipped, 31 warnings in ~178s
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

### Expected-red (this lane — do not fix here)

**fx5 — face freeze (HARM-01/09):**
1. `scene/tests/test_eval_harness_face_determinism_anchor.py::test_face_generator_regenerates_byte_identical_committed_anchor`
2. `...::test_face_expect_report_matches_committed_freeze_green`
3. `...::test_cli_score_face_expect_report_end_to_end_green`

**fx4 — CLI fixtures assume SCORE_PASS_MIN=2 (RV1-03):**
4. `test_cmd_score_public_audience_emits_redacted_public_artifact`
5. `test_cmd_score_default_local_emits_no_public_artifact`
6. `test_cmd_score_exits_zero_when_no_wrong_names_and_no_failures`
7. `test_cli_score_check_determinism_runs_cross_process_guard`
8. `test_cli_score_determinism_certifies_written_rubric_gate`
9. `test_cli_score_audience_public_check_determinism_covers_both_labels`
10. `test_score_freeze_certification_exits_nonzero_on_anchor_mismatch` (likely sample-size / freeze interaction)

Owned modules alone: **178 passed** (`test_eval_harness_report.py` + `test_eval_harness_face_metrics.py`).

---

## 5. `git diff --stat` vs `b28e126e`

```
 .../scene/tests/test_eval_harness_face_metrics.py  |  60 ++-
 .../scene/tests/test_eval_harness_report.py        | 527 +++++++++++++--------
 .../scripts/eval_harness/face_assignment.py        |  22 +-
 .../scripts/eval_harness/face_metrics.py           |  67 +--
 .../scripts/eval_harness/report.py                 | 288 +++++++----
 5 files changed, 620 insertions(+), 344 deletions(-)
```

---

## 6. What could not be verified

- End-to-end `_cmd_compare` CLI SystemExit path with forged files: verified via shared predicate + `_compare_vacuous_categories` (same call site compare uses). Did not shell out a full compare CLI process with temp JSON files.
- Live corpus with real `wp-content/uploads/..._maryarce.jpg` paths: synthetic fixtures only (as required).
- Whether fx4 caption freezes need regen solely from RV1-03 (suite showed no caption-anchor reds attributed to us; CLI fixture reds are sample-size).

---

## 7. Cross-lane requests

### → fx4 (`cli.py` / CLI tests)
- **RV1-03:** `SCORE_PASS_MIN_SCORED_IMAGES` is now **5**. Expand clean-score CLI fixtures to ≥5 scored images (or assert `not_ready` where intentional). Tests listed above currently expect exit 0 on 2-image corpora.
- **RV1-02:** No cli.py change required — sample_size is in `score_vacuous_category_labels`. Optional: prettier message for `sample_size` in `_compare_vacuous_categories` (currently falls through to generic `None — category not observed` branch).

### → fx5 (determinism anchors)
- Regenerate **face** freeze after integrating HARM-01 + HARM-09 (`missed_stranger_gt` key + detection fn/recall). Tests named in §3.
- Do **not** regenerate from pre-fix digests; re-score under new semantics.

### → hx1
- HARM-09 satisfied: `missed_stranger_gt` surfaced under `slices.unknown_rejection`.

### Files not touched (as required)
`cli.py`, `describe_baseline.py`, `fusion_runner.py`, determinism generators, `check_lane_report_shas.py`, `docs/tasks/vlm/bakeoff-results/**`, anchor test freezes.

---

## Heuristics cited

TEST-15, AUDIT-07, EVAL-13, EVAL-16, EVAL-23, rg-005, rg-015, sr-001, sr-007.
