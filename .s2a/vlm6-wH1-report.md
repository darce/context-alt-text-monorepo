# Lane wH1 — publish association-completeness stamp + fix detection sampling-frame

**Branch:** `fix/wh1` · **Base:** `271265886b075b1078cec7e30c224152708ec7fb`  
**Owned files:** `report.py`, `face_bakeoff.py` (unchanged — walker not required), `test_eval_harness_report.py`, `test_eval_harness_face_bakeoff.py`  
**Not touched:** `face_assignment.py`, `manifest.py`, `face_metrics.py`, generators, `docs/tasks/vlm/bakeoff-results/*`, operator docs (wH2)

---

## Finding 1 — Face report does not publish `geometry_incomplete_*` / `association_complete` (wG2 residual 1)

### Task 1 diagnosis (DBG-10)

**Divergence shape (stated before the fix):** wG2 stamps `AssignmentResult.geometry_incomplete_gt` / `association_incomplete_media` after excluding null-y GT from IoU. Face report is built by `_detection_from_assignment` → `score_face_run_record`, which published only `tp/fp/fn/precision/recall/sampling_frame`. Stamp was correct and invisible — third instance of the same class (wF4 → wG1 for `labeled_y_missing_*`; now association-completeness).

Followed **wG1's seam**: publish on the face freeze surface from the real upstream stamp (no boundary recount; rg-015). Placed fields on **`detection`** (not a new top-level block) because they qualify detection P/R — operators reconciling `tp+fn` against `n_gt` look here. Field names match the assignment stamp exactly.

**Denominator (EVAL-03):**
- `geometry_incomplete_gt` is out of **n_gt that entered association** = `tp + fn + geometry_incomplete_gt` (also `provenance.total_gt_boxes` on the extended face corpus = 12).
- `association_incomplete_media` is out of **`counts.scored`** (scoreable non-error items; = 11 on face freeze corpus).
- `association_complete` is corpus-level completeness (`geometry_incomplete_gt == 0`).

#### Reproduction probe (pre-wiring / committed freeze, verbatim)

```text
=== COMMITTED face detection (pre-wiring blindness) ===
{
  "fn": 4,
  "fp": 1,
  "precision": 0.8571428571428571,
  "recall": 0.6,
  "tp": 6
}
geometry_incomplete in committed? False
```

#### Assignment stamp present but unpublished (pre-wiring live path)

```text
=== AssignmentResult geometry stamp ===
geometry_incomplete_gt 1
association_incomplete_media 1
missed_gt 3
missed_stranger_gt 2
tp=6 fn=5 incomplete=1 tp+fn=11 tp+fn+inc=12
media 11: unmatched_gt=(0,) incomplete=(1,) complete=False
```

Live `_detection_from_assignment` keys pre-wiring: `['fn', 'fp', 'precision', 'recall', 'sampling_frame', 'tp']` — no `geometry_incomplete_*` / `association_complete`.

### RED capture (pre-wiring blindness)

```text
committed freeze: geometry_incomplete_gt absent
live detection block: no geometry_incomplete_* / association_complete keys
AssignmentResult.geometry_incomplete_gt=1 on extended face corpus
→ face freeze cannot pin association-completeness (wG2 residual 1 confirmed)
```

### Fix

1. **`_detection_from_assignment`** reads `assignment.geometry_incomplete_gt` / `association_incomplete_media` and publishes them plus derived `association_complete` (`geometry_incomplete_gt == 0`). No recount of `association_by_media` at the report boundary (rg-015; stamp-disagreement unit test pins this).
2. **FN path unchanged** — still `missed_gt + missed_stranger_gt` (complete GT only). Incomplete boxes never re-enter FN (Task 3).
3. **Invariant** updated: `tp + fn + geometry_incomplete_gt` equals GT boxes that entered association.
4. **Markdown** `## Detection` line includes the three fields; warning line when `geometry_incomplete_gt > 0` states the identity against `n_gt`.
5. **`face_bakeoff.py` not modified** — residual is report aggregation, not the walker (same as wG1).

### GREEN capture (post-wiring)

```text
=== LIVE detection block (post-wiring GREEN) ===
{
  "association_complete": false,
  "association_incomplete_media": 1,
  "fn": 5,
  "fp": 1,
  "geometry_incomplete_gt": 1,
  "precision": 0.8571428571428571,
  "recall": 0.5454545454545454,
  "tp": 6
}
tp=6 fn=5 incomplete=1
tp+fn=11 tp+fn+incomplete=12
n_gt provenance.total_gt_boxes=12
identity holds? True
```

### Task 1 — freeze can see it (TEST-15 acceptance)

Stale freeze already fails (Expected-red). Separation of causes: compare **live vs constant-0 mutation** on `detection.geometry_incomplete_gt`, not pass/fail of the freeze bit.

Mutation: wrap `score_face_assignment` to `replace(..., geometry_incomplete_gt=0, association_incomplete_media=0)` — stamp-only; FN/TP arithmetic unchanged.

```text
=== TASK1 mutation proof ===
live geometry_incomplete_gt=1
blind_mutation geometry_incomplete_gt=0
discriminates=True
live association_complete=False blind=True
fn unchanged live=5 blind=5
```

pytest:

```text
test_face_detection_publishes_geometry_incomplete_stamp PASSED
test_detection_from_assignment_publishes_stamp_not_recount PASSED
test_face_geometry_incomplete_constant_zero_mutation_diverges PASSED
test_face_anchor_freeze_sees_geometry_incomplete_counter PASSED
```

**How staleness was separated from counter observability:** both live and blind re-scores mismatch the committed freeze (pre-existing + new fields). The mutation proof asserts `live_n != blind_n` on `detection.geometry_incomplete_gt` specifically. If wiring were decorative (field absent or constant), that equality would hold and the test fails.

---

## Finding 2 — Detection sampling-frame text claims `tp+fn` equals all GT that reached association (wG2 residual 2)

### Reproduction probe (verbatim, pre-fix)

```text
=== sampling_frame (detection) pre-fix ===
... error-item media excluded from association (listed in failures);
tp+fn equals GT boxes that reached association
```

Live arithmetic post-wG2: `tp=6, fn=5, incomplete=1` → `tp+fn=11 ≠ n_gt=12`. Identity that holds: `tp+fn+geometry_incomplete_gt = 12 = n_gt`.

### RED capture

```text
sampling_frame claims: tp+fn equals GT boxes that reached association
actual: tp+fn=11, n_gt=12, geometry_incomplete_gt=1
operator reconciling tp+fn against corpus size finds discrepancy of 1 with no explanation
```

### Fix

Updated `FACE_BAKEOFF_SAMPLING_FRAMES["detection"]` (single registry; also mirrored under `provenance.sampling_frames.detection` and `detection.sampling_frame`):

- FN language: **unmatched complete GT** (named + stranger).
- Adds: `geometry_incomplete_gt = GT boxes excluded from IoU (null/invalid centre-y; not detector FN)`.
- Identity: **`tp+fn+geometry_incomplete_gt equals GT boxes that reached association`**.
- States `association_complete=false when geometry_incomplete_gt>0`.
- Removed obsolete `tp+fn equals ...` claim.

**Did not change detection arithmetic** (`sr-001`) — wG2's `fn=5` / recall≈0.545 is correct.

### GREEN capture

```text
=== FACE_BAKEOFF_SAMPLING_FRAMES[detection] ===
all_gt_boxes_on_scoreable_media_via_association: named and anonymous GT share one population (HARM-01 / EVAL-16); TP=IoU-matched pairs; FN=unmatched complete GT (named missed_gt + missed_stranger_gt); FP=unmatched detections; geometry_incomplete_gt = GT boxes excluded from IoU (null/invalid centre-y; not detector FN); tp+fn+geometry_incomplete_gt equals GT boxes that reached association; association_complete=false when geometry_incomplete_gt>0; error-item media excluded from association (listed in failures)
```

Identity verification on extended face corpus:

| Quantity | Value |
| --- | --- |
| `detection.tp` | 6 |
| `detection.fn` | 5 |
| `detection.geometry_incomplete_gt` | 1 |
| `tp+fn+geometry_incomplete_gt` | **12** |
| `provenance.total_gt_boxes` / n_gt scoreable | **12** |

```text
test_face_detection_sampling_frame_discloses_geometry_incomplete PASSED
```

---

## Finding 3 — Confirm incomplete boxes are not re-counted as FN (wG2 residual, third clause)

### Probe (verbatim)

```text
=== Task 3 probe: incomplete not re-absorbed as FN ===
assignment.geometry_incomplete_gt = 1
assignment.missed_gt = 3
assignment.missed_stranger_gt = 2
detection.fn (from assignment path) = 5
detection.tp = 6
expected fn = missed_gt + missed_stranger_gt = 5
fn includes incomplete? False
fn equals complete-only misses? True
scored.detection.fn == det.fn? True
media 11: unmatched_gt=(0,) incomplete=(1,)
Alice (idx 1) in unmatched_gt? False
Alice (idx 1) in incomplete? True
```

### Result

**No re-absorption.** Report path uses `assignment.missed_gt + missed_stranger_gt` only; incomplete never enters FN. wG2 exclusion survives to publication. Confirmed by fixture test (`fn=1` complete Bob miss + `geometry_incomplete_gt=1` Alice; not `fn=2`).

```text
test_detection_incomplete_not_reabsorbed_as_fn PASSED
```

---

## Disagreements

**None** on the residual claims after live probes:

1. Committed face report had **no** `geometry_incomplete_*` / `association_complete` (confirmed).
2. AssignmentResult stamp was already `geometry_incomplete_gt=1` on media 11 Alice (confirmed).
3. Sampling frame still claimed `tp+fn equals ...` while `tp+fn=11 ≠ n_gt=12` (confirmed).
4. Report path does not re-absorb incomplete as FN (confirmed; not a latent bug).
5. Constant-0 stamp mutation discriminates (`1` vs `0`).

---

## New findings (not owned)

1. **Committed face freeze `detection.fn=4` / `recall=0.6` is pre-wG2 arithmetic** (and lacks `sampling_frame` entirely). Live post-wG2 is `fn=5` / recall≈0.545 with incomplete=1. Regen must absorb both the wG2 arithmetic shift and this lane's new fields — not only the new keys.
2. **Media 11 still uses `faces=[]`** — incomplete+dets combination remains unexercised on the freeze corpus (wG2 AUDIT-07 incidence zero). Stamp is non-zero via the zero-det incomplete path; mechanism for n_det>0 is covered by unit tests in face_assignment, not freeze.
3. **wH2 / operator docs** may still describe `tp+fn = n_gt` — out of scope; disclosure string is fixed in code.

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1409 passed, 4 skipped`  
(Base: `5 failed, 1403 passed, 4 skipped` — **+6 new tests**, all green.)

### Expected-red

| Test | Cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | **Pre-existing** caption freeze staleness (wd-A / Wave E / wG3). Not caused by wH1. |
| `test_expect_report_matches_committed_freeze_green` | Same caption freeze staleness. |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | Face report freeze stale: **pre-existing** (wG1 identity_ordering, wG2 fn/recall, wd-A sampling_frame, corpus traps) **plus wH1**: new `detection.geometry_incomplete_gt` / `association_incomplete_media` / `association_complete` keys; updated `detection.sampling_frame` text; MD Detection line + incomplete warning. |
| `test_face_expect_report_matches_committed_freeze_green` | Same — live re-score now includes geometry-incomplete stamp + new frame text; committed freeze does not. |
| `test_cli_score_face_expect_report_end_to_end_green` | Same face report staleness vs live re-score. |

**wH1-owned field delta for face freeze regen:**

| Field path | Type | Denominator | Expected value (extended face corpus) |
| --- | --- | --- | --- |
| `detection.geometry_incomplete_gt` | `int` | n_gt entered association (`tp+fn+incomplete` = 12) | `1` |
| `detection.association_incomplete_media` | `int` | `counts.scored` (=11) | `1` |
| `detection.association_complete` | `bool` | corpus-level | `false` |
| `detection.tp` | `int` | — | `6` (unchanged by wH1; for identity check) |
| `detection.fn` | `int` | complete GT only | `5` (wG2 arithmetic; not re-absorbed) |
| `detection.sampling_frame` | `str` | — | registry string containing `tp+fn+geometry_incomplete_gt equals` and `geometry_incomplete_gt = GT boxes excluded`; must **not** contain obsolete `tp+fn equals GT boxes that reached association` |
| `provenance.sampling_frames.detection` | `str` | — | same string as `detection.sampling_frame` |

Also MD: `## Detection` line naming `geometry_incomplete_gt` / `association_incomplete_media` / `association_complete`; warning line when incomplete > 0 with `n_gt=tp+fn+incomplete=12`.

Exact new disclosure text (registry):

```text
all_gt_boxes_on_scoreable_media_via_association: named and anonymous GT share one population (HARM-01 / EVAL-16); TP=IoU-matched pairs; FN=unmatched complete GT (named missed_gt + missed_stranger_gt); FP=unmatched detections; geometry_incomplete_gt = GT boxes excluded from IoU (null/invalid centre-y; not detector FN); tp+fn+geometry_incomplete_gt equals GT boxes that reached association; association_complete=false when geometry_incomplete_gt>0; error-item media excluded from association (listed in failures)
```

### Unexpected-red

**None.**

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
base 271265886b075b1078cec7e30c224152708ec7fb
 .../scene/tests/test_eval_harness_face_bakeoff.py  |  87 +++++++
 .../scene/tests/test_eval_harness_report.py        | 264 ++++++++++++++++++++-
 .../scripts/eval_harness/report.py                 |  56 ++++-
 3 files changed, 396 insertions(+), 11 deletions(-)
```

(`face_bakeoff.py` not modified — residual is report aggregation, not the walker.)

---

## Could not verify

- Post-regen face report byte identity (explicitly not this lane; regen stage owns artifacts).
- Production prevalence of null-y GT with non-empty detections (freeze corpus still uses media-11 `faces=[]`; unit tests cover n_det>0).
- Whether wH2 docs still claim `tp+fn = n_gt` (out of scope; code disclosure is fixed).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **Regen stage** | Absorb face report fields in the table above. Do **not** edit scoring code (`sr-001`). Expected live values on current extended face corpus: `geometry_incomplete_gt=1`, `association_incomplete_media=1`, `association_complete=false`, `tp=6`, `fn=5`, `fp=1`, `recall≈0.545`, sampling_frame = registry string above. Also absorb pre-existing wG1 `identity_ordering` block and wG2 arithmetic if not already in committed freeze. |
| **wH2 (docs)** | If operator docs still say detection `tp+fn` equals all GT boxes, update to `tp+fn+geometry_incomplete_gt` and point at the published stamp fields. |
| **(none for face_assignment)** | Stamp source is correct; no re-open of wG2 association logic required. |
