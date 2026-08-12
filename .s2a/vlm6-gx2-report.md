# Lane gx2 — honest adoption verdicts, real redaction, face-metrics rewiring

Branch: `fix/gx2` (forked from `feature/vlm-6` @ `fc18e27d`)

Heuristics: `TEST-15`, `EVAL-04`, `EVAL-13`, `EVAL-16`, `EVAL-19`, `EVAL-23`, `AUDIT-07`, `rg-002`, `rg-005`, `rg-006`, `rg-015`, `sr-001`, `sr-007`.

## 1. What changed

| File | Reason |
|------|--------|
| `scripts/eval_harness/report.py` | Shared vacuity predicate + quality floors + sample-size floor; PUBLIC free-text scrub shape; S2-07 un-fold of `degraded_images`; wire `missed_stranger_gt` into `face_unknown_rejection`; `_fmt_prov` for null provenance; `ScoreVerdict.NON_COMPARABLE`. |
| `scripts/eval_harness/cli.py` | Import shared vacuity; `_compare_vacuous_categories` delegates to `score_vacuous_category_labels` / `fabricated_fact_is_vacuous` (S2-01/S2-06); `_VERDICT_NON_COMPARABLE` aliases enum. |
| `scene/tests/test_eval_harness_report.py` | TEST-15 pins for S2-01..07 / S4-05 / S2-09; update pass fixtures to min sample size 2; S2-07 / public-path expectation updates. |
| `scene/tests/test_eval_harness_cli.py` | S2-09 raw verdict strings → `ScoreVerdict`; green-path fixtures clear S2-05 min sample size. |
| `scripts/eval_harness/README.md` | S2-10: document `not_ready` / `non_comparable` + category-vacuity / quality-floor gates. |
| `.s2a/vlm6-gx2-report.md` | This report. |

## 2. Per-finding resolution

| ID | Resolution |
|----|------------|
| **S2-01** | Fixed. Shared `fabricated_fact_is_vacuous()`: traps==0 **or** either rate is None is vacuous — including stamped numeric `0.0` with zero traps. Used by both `build_score_verdict` and `compare`. |
| **S2-02** | Fixed. Named constants (sr-007), conservative degenerate-extreme policy: `POSITION_ACCURACY_FLOOR=0.0`, `PLACEMENT_ACCURACY_FLOOR=0.0`, `FABRICATED_FACT_RATE_CEILING=1.0`. Breach is **fail** (measured and bad), never `not_ready`. Justification: without operator-chosen production thresholds, only total-failure extremes are defensible; an absent gate is the finding. |
| **S2-03** | Fixed (shape). Free-text keys classified (`_PUBLIC_PER_IMAGE_FREE_TEXT_FIELDS`, `_PUBLIC_FAILURE_*`); every admitted free-text value goes through `_public_free_text_value`; failures are allow-listed (no whole-record pass-through). Nested path lists scrubbed (`_public_list_path` / space-bearing basenames → `<path>`). Whole-blob assertion in tests. |
| **S2-04** | Fixed. Absolute media paths → `<absolute>` (not identifying basename). Per-image/failure paths → `media_id:N`. Model weight basenames retained. |
| **S2-05** | Fixed. `SCORE_PASS_MIN_SCORED_IMAGES=2` → `not_ready` (insufficient sample), not fail. |
| **S2-06** | Fixed. `score_vacuous_category_labels()` is the single vacuity set (placement, positional, identity_ordering, fabricated_fact, detection/ID P/R, caption scalars). `compare` prefixes role; score builds detailed AUDIT-07 reasons from the same labels. |
| **S2-07** | Fixed. `degraded_images` / `degraded_paths` = true `identity_ordering=degraded` stamps only. Exclusions live solely in `order_unknown_excluded` (+ MD warning). Vacuity text cites `order_unknown_excluded`, not overloaded degraded. |
| **S4-05** | Fixed. `_fmt_prov(None) → "null"` for caption + face MD head_sha/started_at. |
| **S2-09** | Fixed. `ScoreVerdict.NON_COMPARABLE`; CLI alias; 18 raw test compares converted. |
| **S2-10** | Fixed. README verdict table + exit-prefix table document `not_ready` / quality floors / category vacuity. |
| **gx3 rewiring** | Fixed. `face_unknown_rejection(..., missed_stranger_gt=assignment.missed_stranger_gt)` — required kwarg **not** defaulted (sr-001). Verified `face_identification_pr(..., missed_gt=assignment.missed_gt)` already named-only; `_association_counts_for_media` named-only. Optional JSON `missed_stranger_gt` field deferred (freeze stability; rate already uses it). |

## 3. TEST-15 proofs

### 3.1 S2-01 — `fab_rate=0.0` traps=0 no longer certifies

**RED (pre-fix live probe):**
```
S2-01 fab_rate=0 traps=0 => pass []
```

**GREEN:**
```
scene/tests/test_eval_harness_report.py::test_build_score_verdict_zero_fab_rate_with_zero_traps_is_vacuous PASSED
```
(`verdict=not_ready`, reason names `fabricated_fact` + `images_with_traps=0`)

### 3.2 S2-02 — three total-failure mutations fail

**RED (pre-fix live probe):**
```
S2-02 pos0 => pass []
S2-02 place0 => pass []
S2-02 fab1 => pass []
```

**GREEN:**
```
scene/tests/test_eval_harness_report.py::test_build_score_verdict_quality_floors_fail_total_failure_mutations PASSED
```
(each mutation → `verdict=fail` with `quality-floor:` reason)

### 3.3 S2-03/S2-04 — PUBLIC free-text name scrub (whole blob)

**RED (pre-fix probe shape from finding):** after `_redact_caption_report_for_public`, name present in `path` / `short_error` / `failures`.

**GREEN:**
```
scene/tests/test_eval_harness_report.py::test_public_redaction_scrubs_free_text_identity_names_everywhere PASSED
```
(`Jane Doe Private` absent from entire `json.dumps(redacted)`; path=`media_id:10`; failures allow-listed)

### 3.4 S2-01/S2-06 — score/compare shared vacuity

**GREEN:**
```
scene/tests/test_eval_harness_report.py::test_score_and_compare_agree_on_vacuous_fabricated_fact PASSED
```

### 3.5 gx3 rewiring — 25 TypeErrors green without relaxing required kwarg

**RED (fork baseline):**
```
TypeError: face_unknown_rejection() missing 1 required keyword-only argument: 'missed_stranger_gt'
```
(25 tests across report / face_determinism / cli score-face)

**GREEN:** signature still has no default (`inspect.Parameter.empty`); sample:
```
scene/tests/test_eval_harness_report.py::test_score_face_run_record_full_corpus_and_floor_gated_rollup PASSED
```

### 3.6 S2-05 / S2-07 / S4-05 / S2-09

```
test_single_image_measurable_corpus_is_not_ready PASSED
test_order_unknown_excluded_not_folded_into_degraded_images PASSED
test_markdown_renders_null_provenance_as_null_not_none PASSED
test_score_verdict_enum_includes_non_comparable PASSED
```

## 4. Suite result

**Baseline at fork (re-asserted):** `27 failed, 1222 passed, 4 skipped`  
(25 × TypeError `missed_stranger_gt`; 2 × generator regen — not ours)

**Final full suite:**
```
3 failed, 1254 passed, 4 skipped, 31 warnings in 173.37s (0:02:53)
```

### Remaining reds (itemized)

| test | cause | owner |
|------|-------|-------|
| `test_generator_regenerates_byte_identical_committed_anchor` | pin-mode `started_at: null` vs committed sentinel clock (gx4) | **wave-C regen** (not ours) |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | same for face run-record | **wave-C regen** (not ours) |
| `test_expect_report_matches_committed_freeze_green` | caption freeze stale after S2-06/S2-07 (see cross-lane) | **wave-C regen** — freeze report bytes must move |

The third red is freeze-stale from intentional honesty fixes (not a silent regression). Regenerating `docs/tasks/vlm/bakeoff-results/**` is explicitly out of ownership.

## 5. Cross-lane requests (wave-C regen)

1. **Caption freeze regen** (`S2A-determinism-anchor-run-20260811-report.json` + MD + digests):
   - `faces.identity_ordering.degraded_images`: folded exclusion count → **true DEGRADED stamp count only** (0 on golden/no-stamp corpus).
   - `degraded_paths`: empty when no true degraded stamps (exclusions stay in `order_unknown_excluded` / positional `excluded_images`).
   - Verdict reason text: positional vacuity cites `order_unknown_excluded=…` not `degraded_images=…`.
   - New vacuity reason when `positional_images=0`: `category-vacuity: identity_ordering …`.
   - Fabricated-fact vacuity reason may include `/ S2-01` trailer and rate value when stamped `0.0` with traps=0.
2. **Generators** (already red from gx4): null `started_at` / `head_sha` in pin mode; then update `_FROZEN_DIGESTS`.
3. **Optional AUDIT-07**: after regen, surface `missed_stranger_gt` on `slices.unknown_rejection` JSON (wired into rate now; field deferred to avoid face freeze churn while rates unchanged on current face anchor).
4. **S4-05 MD**: after caption regen, freeze MD will show `started_at: null` / `head_sha: null` (renderer fixed).

## 6. What you could not verify

- Golden-100 adoption path end-to-end against a real operator corpus (unit + harness-37 only).
- Whether production LocalWP free-text paths always contain spaces (space-bearing basename heuristic is defense-in-depth alongside roster scrub + media_id tokens).
- Face freeze JSON equality after optional `missed_stranger_gt` key is added (deferred; rate already attributed).
- That every historical hand-built scored dict outside tests includes detection P/R / identity_ordering stamps required by the converged vacuity set (new tests and CLI green fixtures do).
- Full multi-hashseed face determinism under concurrent file edits during development (final suite face expect-report green after field removal).
