# Lane `fx2` — audience redaction + score verdict

**Branch:** `feature/vlm-6-fx2` (this lane's branch)  
**Owned files only:**
- `apps/prototype-description-service/scripts/eval_harness/report.py`
- `apps/prototype-description-service/scene/tests/test_eval_harness_report.py`
- `.s2a/vlm6-fx2-report.md` (this report)

**Findings fixed:** VLM6-A-01, VLM6-A-05, VLM6-B-07

**Gate:** `scene/tests/test_eval_harness_report.py` → **107 passed**

```
cd apps/prototype-description-service && .venv/bin/python -m pytest scene/tests/test_eval_harness_report.py -q
# 107 passed
```

---

## VLM6-A-01 (high) — PUBLIC redaction leaks private roster names

**Files:** `report.py` (`_PUBLIC_PER_IMAGE_ALLOW_FIELDS`, `_public_per_image_row`, `_redact_caption_report_for_public` per-image loop)

**Behaviour change:** PUBLIC `per_image` is rebuilt from an explicit allow-list (rg-015). Name-bearing fields (`inserted_identities`, `missing_identities`, `must_right_failures`, `hallucinated_names`, `wrong_name_hits`, …) and any future unknown key are dropped by default. Nested `long` / `placement` / `hallucination` use nested allow-lists so fact-string lists cannot carry roster names.

### RED (unfixed)

```
assert private not in json.dumps(pub_row)
E   assert 'Shared Private Person' not in '...'
E     ities": ["Shared Private Person"], "must_right_failures": ["Shared Private Person"], ...
```

```
assert private not in json.dumps(pub_row)
E   assert 'Future Leak Person' not in '...'
E     ... "inserted_identities": ["Future Leak Person"], ... "brand_new_name_field": ["Future Leak Person"]
```

### GREEN (fixed)

```
test_public_per_image_allow_list_strips_identity_name_fields PASSED
test_public_per_image_allow_list_drops_future_name_field PASSED
```

---

## VLM6-A-05 (medium) — `build_score_verdict` persists `pass` when nothing measurable

**Files:** `report.py` (`ScoreVerdict.NOT_READY`, `build_score_verdict` category-vacuity block)

**Behaviour change:** Critical scored categories with claim-unit π=0 no longer yield `verdict=pass`. Centralised `ScoreVerdict.NOT_READY` (`sr-007`) with AUDIT-07 reasons naming positional + placement frames. Hard failures still win as `fail` (vacuity reasons appended). Clean measurable fixture still passes.

### RED (unfixed)

```
assert verdict["verdict"] != ScoreVerdict.PASS.value
E   AssertionError: assert 'pass' != 'pass'
```

### GREEN (fixed)

```
test_score_verdict_not_ready_when_positional_and_placement_vacuous PASSED
test_score_verdict_pass_when_positional_and_placement_measurable PASSED
```

Post-fix verdict reasons on vacuous clean corpus:

```
verdict: not_ready
- category-vacuity: positional — claim unit=image with face_boxes L→R order; compared_images=0 degraded_images=1 excluded_images=1 (π=0 on face_boxes; AUDIT-07)
- category-vacuity: placement — claim unit=asserted spatial_fact; claims=0 accuracy=None abstained=0 images_scored=1 (π=0 on spatial_facts; AUDIT-07)
```

---

## VLM6-B-07 (high) — placement never inspected by the verdict

**Files:** same `build_score_verdict` change as A-05

**Behaviour change:** Placement enters the verdict. `claims==0` or `accuracy is None` on a scored run is category-vacuity and blocks `pass` (EVAL-04 / EVAL-23). Isolated test makes positional measurable so only placement fires.

### RED (unfixed)

```
assert verdict["verdict"] != ScoreVerdict.PASS.value
E   AssertionError: assert 'pass' != 'pass'
```

(full-corpus score previously PASSed with placement unmeasured; vacuity was MD disclosure only)

### GREEN (fixed)

```
test_score_verdict_blocks_pass_on_vacuous_placement_alone PASSED
```

---

## Cross-lane requests

| Owner | Need |
| --- | --- |
| **CLI lane** (`test_eval_harness_cli.py`) | Update `test_score_persisted_verdict_control_pass_on_real_golden` — real golden has face_boxes/spatial_facts on 0/37, so honest verdict is now `not_ready` with category-vacuity reasons, not `pass` + `reasons=[]`. Same for any CLI test that asserts `verdict=="pass"` on real golden without measurable categories. |
| **CLI lane** (`cli.py`) | Optionally hard-exit non-zero on `verdict=not_ready` so process exit matches artifact (OBS-04). Currently CLI exit gates do not re-read category vacuity; artifact is honest, process may still exit 0. |
| **Docs / README** | Document `ScoreVerdict.NOT_READY` / `not_ready` alongside `pass` \| `fail` \| `pass_ungated`. |
| **Determinism anchor** | Anchor narrative that assumes bare `pass` on vacuous corpus needs refresh if re-generated. |

---

## Deferred

| Item | Reason |
| --- | --- |
| Making real golden adoption-`pass` | Requires Golden-100 / Slice 1 population of `face_boxes` and `spatial_facts` (π>0 claim units). Gate is honest *today* via `not_ready`; not weakened. |
| Aggregate `per_identity` private subjects on publishable images | A-01 scope was per-image allow-list. `per_identity` still filters by publishable-subject set; a private name listed on a publishable entry's `present_identities` remains in aggregate keys (separate surface). |
| Placement accuracy floor (non-vacuous wrong claims) | Finding only requires vacuity to block pass, not a numeric placement accuracy threshold. |
