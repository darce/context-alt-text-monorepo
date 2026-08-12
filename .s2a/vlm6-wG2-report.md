# Lane wG2 — nullable `y` crash in detection association

**Branch:** `fix/wg2` · **Base:** `cc1da6219d2407dca6c676d6e6583635bcdc9672`  
**Owned files:** `face_assignment.py`, `manifest.py`, `test_eval_harness_face_assignment.py`, `test_eval_harness_pipeline.py`  
**Finding:** wF4 residual 3 — `associate_detections` still `float(gt["y"])` when `n_det > 0`

---

## Posture decision (Task 1)

**Chose: degrade-with-stamp (option 2), not refuse (1), never x-only match (3).**

### Reasoning + evidence

1. **Schema makes null-y first-class, not corrupt media.** `FaceBox.y: float | None = None` (wF4) exists so `labeled_y_missing_images` / `order_degraded` can be non-zero. A required float made the freeze corpus *structurally* blind.
2. **How manifests are produced:** `identity_sources.FaceRegion` requires full `(x,y,w,h)` — IPTC/MWG regions with any null coord are **dropped** (`if None in (x, y, w, h): continue`). Export never emits null-y. Null-y only appears via deliberate operator/author hand-edit of `FaceBox` (trap media 11, or partial curation for L→R degradation testing).
3. **Detectors are independent of GT completeness.** A run-record can legitimately carry detections while a sibling GT box omits `y`. Media 11 uses `faces=[]` as a corpus-shaped dodge around the crash, not because the combination is invalid.
4. **Association meaning without `y`:** IoU needs a full centre → pixel-corner box. A null-y box has no defined vertical centre. Matching on `x` alone (option 3) invents association results that look complete — the silent-degrade class this wave sequence convicts (`rg-015`, `DIAG-03`, `S2-07`).
5. **Refuse is too coarse:** raising on any null-y when `n_det > 0` would crash scoring of complete sibling boxes on the same image (media-11 shape: Bob has y, Alice does not). That punishes partial labeling instead of disclosing it.
6. **Parallel with `labeled_order`:** L→R degrades with `order_degraded` stamp (x-only *order* is still meaningful). Association cannot produce *any* valid IoU without y → exclude the box and stamp incompleteness; do not invent pairs; do not count as detector FN.

**Deciding question answered:** null-y + detections can happen legitimately as incomplete GT labeling coexisting with an independent detector pass — not media corruption. Degrade-with-stamp is correct; the stamp must be in the returned structure.

---

## Finding 1 — `associate_detections` crashes on null-y when `n_det > 0`

### Reproduction probe (verbatim, pre-fix)

```text
gt = [{"x": 0.5, "y": None, "w": 0.2, "h": 0.2, "name": "Alice", "source": "iptc"}]
dets = [[40.0, 40.0, 20.0, 20.0]]  # n_det > 0
associate_detections(dets, gt, [100, 100])
```

### RED capture (verbatim)

```text
Traceback (most recent call last):
  File "<stdin>", line 7, in <module>
  File ".../scripts/eval_harness/face_assignment.py", line 180, in associate_detections
    cx, cy, w, h, name = _gt_fields(gt)
  File ".../scripts/eval_harness/face_assignment.py", line 141, in _gt_fields
    return float(gt["x"]), float(gt["y"]), float(gt["w"]), float(gt["h"]), gt_box_name(gt)
TypeError: float() argument must be a string or a real number, not 'NoneType'
```

Same crash via `collect_matched_faces` / `score_face_assignment` (both call `associate_detections` when faces non-empty).

TEST-15 RED tests (written before the fix; 6 failures captured):

```text
FAILED ...::test_associate_null_y_with_detections_does_not_crash - TypeError: float() ... NoneType
FAILED ...::test_associate_null_y_not_x_only_match - TypeError: float() ... NoneType
FAILED ...::test_associate_null_y_zero_det_stamps_incomplete_not_fn - assert (0, 1) == (0,)
FAILED ...::test_collect_matched_faces_null_y_with_detections_no_crash_no_fn_inflate - TypeError
FAILED ...::test_score_face_assignment_propagates_geometry_incomplete_stamp - TypeError
FAILED ...::test_associate_facebox_model_null_y - TypeError (FaceBox attribute path)
```

Zero-det path did not crash but classified incomplete GT as `unmatched_gt` (silent FN inflation for Alice on media 11).

### Fix

In `face_assignment.py`:

- `_gt_y_optional` / `_gt_fields` return `y: float | None` (null, blank, non-numeric → missing; same coercion as `labeled_order` RA-04).
- `associate_detections` partitions complete vs geometry-incomplete GT **before** any IoU path.
- IoU + Hungarian only on complete boxes; original indices remapped.
- New `AssociationResult` fields:
  - `geometry_incomplete_gt: tuple[int, ...]`
  - `association_complete` property (`len(geometry_incomplete_gt) == 0`)
- Incomplete indices **never** enter `unmatched_gt` (not detector FN).
- `AssignmentResult.geometry_incomplete_gt` / `association_incomplete_media` propagated by `score_face_assignment`.
- `collect_matched_faces` keeps 5-tuple return (callers outside this lane unpack five values); stamp lives on each `AssociationResult` in the associations dict.
- `manifest.FaceBox` docstring updated to document association stamp policy.

### GREEN capture (verbatim)

Crash probe post-fix:

```text
pairs ()
unmatched_det (0,)
unmatched_gt ()
geometry_incomplete_gt (0,)
association_complete False
```

Tests:

```text
.......                                                                  [100%]
7 passed, 29 deselected in 0.78s
```

Owned face_assignment + pipeline suite: `96 passed`.

---

## Caller blast radius

| Caller | File | Owned? | Behaviour with stamp |
| --- | --- | --- | --- |
| `collect_matched_faces` | `face_assignment.py` | **yes** | Uses `unmatched_gt` (complete only) for FN; pairs only for matched probes. Stamp on `AssociationResult` retained in `associations` dict. |
| `score_face_assignment` | `face_assignment.py` | **yes** | Propagates corpus totals onto `AssignmentResult.geometry_incomplete_gt` / `association_incomplete_media`. |
| Twin re-detect path | `face_bakeoff.py` | no (wG1) | Uses `assoc.pairs` only. Incomplete GT simply never match (embedding=None for that box). **Ignores stamp** → Cross-lane. |
| Occlusion pair extract | `report.py` | no (wG1) | Uses `assoc.pairs` only. Same silent omission of incomplete GT. Detection FN uses `assignment.missed_gt` (no longer includes incomplete) — numbers move; stamp not published. **Cross-lane.** |
| Landmark cache | `landmark_cache.py` | no | Uses `assoc.pairs` for named landmarks only. Incomplete named GT skipped (no cache entry) — correct for twin universe; stamp ignored. **Cross-lane note.** |
| Tests constructing `AssociationResult` | `test_eval_harness_report.py` | no | New field has default `()` — no break. |

A caller that ignores the degradation stamp reintroduces silent-degrade one level up for *completeness disclosure*, but cannot reintroduce the crash or x-only invented pairs. FN inflation via incomplete-as-unmatched is closed at the association source.

---

## Task 3 — inspected-sites table (null-y after FaceBox loosening)

| Site | Receives FaceBox? | null-y behaviour | Changed? |
| --- | --- | --- | --- |
| `face_assignment._gt_fields` / `_gt_y_optional` | yes (dict or model) | Was `float(y)` crash; now returns `None` for missing/blank/non-numeric | **yes** |
| `face_assignment.associate_detections` | yes | Was crash when `n_det>0`; now exclude + stamp; zero-det also stamps incomplete ≠ FN | **yes** |
| `face_assignment.gt_normalized_centre_to_pixel_corner` | coords only | Only called with complete `cy` after partition | no (call sites gated) |
| `face_assignment.iou_pixel_corner` | pixel boxes | Only on complete GT pixel-corner + dets | no |
| `face_assignment.collect_matched_faces` unmatched loop | yes (name only) | Already name-only (wF4); now only complete indices in `unmatched_gt` | **yes** (semantic: incomplete not FN) |
| `face_assignment.score_face_assignment` | via collect | Propagates geometry incomplete counts | **yes** |
| `manifest.FaceBox.y` | schema | `float \| None = None` (wF4); docstring documents association stamp | **yes** (doc only) |
| `face_metrics.labeled_order` | yes | Degrades with `order_degraded` / `y_missing_count`; never raises | no (already safe) |
| `face_metrics.labeled_left_to_right` | yes | Delegates to `labeled_order` | no |
| `face_metrics.named_box_name` / `gt_box_name` | yes | Name only; ignores geometry | no |
| `face_metrics.wire_bbox_normalized_centre` | **no** (wire corner `{x,y,width,height}`) | `float(bbox["y"])` on wire det/identity bbox, not FaceBox centre-y | no (different shape) |
| `face_metrics.normalized_centre_order_key` | floats | Requires numeric centre_y from callers that already have coords | no |
| `report._normalize_face_boxes_for_order` | yes (dict path) | Blank/non-numeric y → None before labeled_order | no (wG1) |
| `report` caption score path (`labeled_order`) | yes | Aggregates `labeled_y_missing_*`; excludes order_degraded from positional | no |
| `report.occlusion_inputs` → `associate_detections` | yes | Crash fixed by our change; stamp ignored for disclosure | no code change here |
| `report` detection FN from `assignment.missed_gt` | AssignmentResult | Indirect: incomplete no longer in FN → **published numbers move** | no (consumer of our change) |
| `face_bakeoff` twin → `associate_detections` | yes | Crash fixed; stamp ignored | no |
| `landmark_cache.build_landmark_cache` → `associate_detections` | yes | Crash fixed; incomplete never cached | no |
| `identity_sources.FaceRegion` / extract | produces FaceRegion | Requires full y; drops incomplete regions | no — never emits null-y |
| `export_identities` face_boxes emit | FaceRegion → dict | Always full y from FaceRegion | no |
| `generate_face_determinism_anchor` media 11 | authors FaceBox | Deliberate null-y + `faces=[]` dodge | no (not owned; dodge now unnecessary for crash, still fine) |
| `fusion_runner` box.x/y | product person boxes | Not FaceBox | no |
| `cli.py` wire bbox `raw["y"]` | wire corner | Not FaceBox | no |
| `face_run_record` landmarks `float(y)` | landmark px | Not FaceBox centre | no |
| `spatial_facts` / `placement_metrics` | relation phrases | Not FaceBox centre-y float path | no |
| `test_eval_harness_pipeline.py` `_FACE_BOXES` | fixture has y | Has complete y; no null-y crash path in gate tests | no change needed |

**No third crash site found** beyond `_gt_fields` / `associate_detections` (the residual wF4 named). Downstream of association, consumers only read pairs/unmatched/name — they no longer float null y.

---

## Disagreements

**None** on the residual claim after live probes:

1. Pre-fix `n_det>0` + `y=None` → `TypeError` (confirmed).
2. Media 11 trap uses `faces=[]` so production path was unexercised on corpus (confirmed).
3. Option 3 (x-only match) would invent pairs at perfect IoU if y were fabricated as 0.5 — rejected by design + test `test_associate_null_y_not_x_only_match`.

**Not a disagreement — clarification:** wF4 framed this as needing "face_assignment hardening (wF2)". Harden-with-stamp is the fail-closed shape; refuse would over-block mixed complete/incomplete images.

---

## New findings (not owned)

1. **Face report does not publish `geometry_incomplete_*` / `association_complete`.** Stamp exists on `AssignmentResult` but `report.py` / face bakeoff freeze cannot pin it until wired (`rg-015` one level up). Similar to wF4 note that face bakeoff never publishes `labeled_y_missing_*`.
2. **Detection sampling-frame text claims `tp+fn` equals GT boxes that reached association.** Post-wG2: `tp+fn+incomplete = n_gt` (12 = 6+5+1). Report disclosure text should mention geometry-incomplete exclusion (wG1 / regen).
3. **`generate_face_determinism_anchor` comment** still says media 11 uses `faces=[]` "so no float(y)" — obsolete rationale after this fix (corpus can now carry null-y + dets safely).

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1394 passed, 4 skipped`  
(Base: `5 failed, 1387 passed, 4 skipped` — +7 new tests, all green.)

### Expected-red

| Test | Cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | **Pre-existing** caption freeze stale (wd-A / Wave E). Not caused by wG2. |
| `test_expect_report_matches_committed_freeze_green` | Same caption freeze staleness. |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | Face report freeze stale: **pre-existing** (wF4 corpus + wd-A fields) **plus wG2** reclassifies media-11 Alice (null-y) out of detection FN. |
| `test_face_expect_report_matches_committed_freeze_green` | Same. |
| `test_cli_score_face_expect_report_end_to_end_green` | Same. |

### Unexpected-red

**None.**

### AUDIT-07 — mechanism vs incidence

| Claim | Status |
| --- | --- |
| **Mechanism confirmed** | Yes — pre-fix TypeError on null-y + `n_det>0`; incomplete-as-FN on zero-det path. |
| **Incidence measured (current face anchor)** | **Zero** entries with null-y **and** detections. Media 11 has null-y Alice with `n_det=0`. Latent hazard closed; not an observed production crash on this corpus. |
| **Published arithmetic that moves on this corpus** | Yes — media 11 Alice is no longer a detection FN (see regen table). |

### Live value shifts regen must absorb (face report, post-wF4 baseline → post-wG2)

After wF4 live was roughly `detection.fn=6`, `recall=0.5` (Alice+Bob both FN at zero det). Post-wG2 live re-score of man+run:

| Field | Post-wF4 live (pre-wG2) | Post-wG2 live | Cause |
| --- | --- | --- | --- |
| `detection.fn` | 6 | **5** | Alice null-y excluded from FN (`geometry_incomplete_gt`) |
| `detection.recall` | 0.5 | **≈0.545** (`6/(6+5)`) | same |
| `detection.tp` / `fp` / `precision` | 6 / 1 / ≈0.857 | **unchanged** | complete boxes only |
| `assignment.missed_gt` (named) | 4 (if Alice counted) | **3** | Alice not FN |
| `assignment.missed_stranger_gt` | 2 | **2** | unchanged |
| `geometry_incomplete_gt` (new) | n/a | **1** | media 11 Alice |
| `association_incomplete_media` (new) | n/a | **1** | media 11 |
| Freeze file still has | `fn=4`, `recall=0.6` | still stale | pre-media-11 freeze |

Caption freeze: **no** association/detection number movement from this lane.

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
base cc1da6219d2407dca6c676d6e6583635bcdc9672
 .../tests/test_eval_harness_face_assignment.py     | 131 +++++++++++++++-
 .../scripts/eval_harness/face_assignment.py        | 167 +++++++++++++++------
 .../scripts/eval_harness/manifest.py               |  10 +-
 3 files changed, 265 insertions(+), 43 deletions(-)
```

(Plus this report file in the report commit.)

---

## Could not verify

- Face report publishing `geometry_incomplete_*` (report.py owned by wG1; stamp not yet in freeze surface).
- Production prevalence of null-y + detections outside the anchor corpus (no network / no real operator corpora).
- Post-regen face report byte identity (explicitly not this lane; must not regenerate).
- Whether landmark_cache / twin bakeoff operators will surface incomplete-GT media in provenance once stamp is ignored (mechanism safe; disclosure incomplete).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **Face freeze regen stage** | Regenerate face report JSON+MD after wF4 man+run + this association change. **Do not** re-extend corpus. Absorb: wF4 table **and** wG2 shifts above (`detection.fn` 6→5 not 4→6; recall ≈0.545 not 0.5). If report wires `geometry_incomplete_*`, pin those too. Same three face freeze tests should go green after regen. **Published association/detection numbers: yes, `detection.fn` / `detection.recall` / named `missed_gt` move for media 11 Alice.** |
| **Caption freeze regen stage** | No wG2 number movement. Still needs wd-A / Wave E field absorbs only. |
| **wG1 / `report.py`** | (1) Publish `geometry_incomplete_gt` + `association_incomplete_media` (or per-path list) from `AssignmentResult` into face report so freeze can pin association completeness. (2) Fix detection `sampling_frame` text: `tp+fn+geometry_incomplete_gt` equals GT boxes that reached association, not `tp+fn` alone. (3) Do not re-count incomplete boxes as FN. |
| **wG1 / `face_bakeoff.py`** | Optional: if twin pass should refuse or disclose media with `not assoc.association_complete`, read the stamp; currently pairs-only (safe but silent on completeness). |
| **landmark_cache (optional)** | Same optional disclosure; pairs-only is functionally safe. |
| **Schema note** | Keep `FaceBox.y` optional. Requiring float re-opens labeled_y_missing blindness **and** undoes the need for this stamp path. |
