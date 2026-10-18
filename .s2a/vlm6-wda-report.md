# Lane wd-A — report.py: ordering disclosure counter + detection sampling frame

**Branch:** `fix/wda` · **Base:** `00bfdd55a462064a1875aabf6322010801aede95`  
**Files owned:** `scripts/eval_harness/report.py`, `scene/tests/test_eval_harness_report.py`  
**Heuristics:** TEST-15, TEST-06, DBG-10, DBG-11, DIAG-01, sr-001, rg-006, rg-015, S2-07, AUDIT-07

---

## Finding 1 — VLM6-R2-G-01 (HIGH, residual) — wire L→R ordering disclosure counter

**Source:** cross-lane request from lane cx1. Extractor fix landed in `face_metrics.labeled_order`; report aggregation was never wired.

### Reproduction probe (pre-fix, verbatim)

```text
=== PROBE Task1: labeled_order oracle ===
labeled_order names=['C', 'B', 'A'] order_degraded=True y_missing_count=1
labeled_left_to_right=['C', 'B', 'A'] (no degradation surface)

=== PROBE Task1: report does not aggregate order_degraded ===
identity_ordering: {'positional_images': 2, 'degraded_images': 0, 'degraded_paths': [], 'order_unknown_excluded': 0}
labeled_y_missing_images present? False
labeled_y_missing_paths present? False
```

### RED capture (verbatim)

```text
FAILED scene/tests/test_eval_harness_report.py::test_labeled_y_missing_images_aggregates_order_degraded
E   AssertionError: assert 'labeled_y_missing_images' in {'positional_images': 2, 'degraded_images': 0, 'degraded_paths': [], 'order_unknown_excluded': 0}

FAILED scene/tests/test_eval_harness_report.py::test_labeled_y_missing_paths_public_redacted
E   KeyError: 'labeled_y_missing_paths'
```

### Fix

In `score_run_record`:

- Call `labeled_order(face_boxes)` instead of `labeled_left_to_right` (names still come from `.names`).
- Aggregate scored images with `order_degraded=True` into:
  - `faces.identity_ordering.labeled_y_missing_images` (int)
  - `faces.identity_ordering.labeled_y_missing_paths` (list[str])
- **Do not** touch `degraded_images` / `degraded_paths` (predicted stamp `DEGRADED` only — S2-07 / rg-015).
- Markdown surfaces the y-missing counter as its own warning line.

PUBLIC redaction (Task 3):

- `labeled_y_missing_paths` scrubbed like `degraded_paths` via `_public_path_list` in `_redact_caption_report_for_public` and via `_redact_public_paths` key list.
- `labeled_y_missing_images` is an int under `faces.identity_ordering` (not provenance) → **no** `_PUBLIC_PROVENANCE_ALLOW_FIELDS` entry required; it survives PUBLIC by virtue of living outside the provenance allow-list. Chosen because the peer counters (`degraded_images`, `positional_images`) already live on that block.

### GREEN capture (verbatim)

```text
=== GREEN Task1 aggregate ===
{
  "degraded_images": 0,
  "degraded_paths": [],
  "labeled_y_missing_images": 1,
  "labeled_y_missing_paths": [
    "/ops/private/lane-wda/group-y-missing.jpg"
  ],
  "order_unknown_excluded": 0,
  "positional_images": 2
}

=== GREEN Task3 PUBLIC redaction ===
private path in blob? False
PUBLIC labeled_y_missing_paths: []
PUBLIC labeled_y_missing_images: 1

...                                                                      [100%]
3 passed in 0.76s
```

### TEST-15 note

Test constructs two scored images (one mixed-y `order_degraded=True`, one full coords) and asserts aggregate `== 1`. Counterfactual constant `0` fails that assertion. Pre-fix RED showed field absent when only `labeled_left_to_right` was used (no degradation surface).

---

## Finding 2 — VLM6-R2-C-02 (MEDIUM) — face detection sampling frame

### Reproduction probe (pre-fix, verbatim)

```text
=== PROBE Task2: face detection lacks sampling_frame ===
detection keys: ['fn', 'fp', 'precision', 'recall', 'tp']
detection: {'precision': 1.0, 'recall': 1.0, 'tp': 3, 'fp': 0, 'fn': 0}
sampling_frame in detection? False
hl has sampling_frame? True
hl sampling_frame type: str
```

Frozen face report (pre-fix): `detection` keys exactly `{tp,fp,fn,precision,recall}` with `precision=0.857 recall=0.600`.

### RED capture (verbatim)

```text
FAILED scene/tests/test_eval_harness_report.py::test_face_detection_carries_sampling_frame
E   AssertionError: assert 'sampling_frame' in {'precision': 1.0, 'recall': 1.0, 'tp': 3, 'fp': 0, ...}
```

### Fix

- Added `FACE_BAKEOFF_SAMPLING_FRAMES["detection"]` — same **string** shape as other floor-gated frames (rg-015: do not invent a new shape).
- `_detection_from_assignment` emits `"sampling_frame": FACE_BAKEOFF_SAMPLING_FRAMES["detection"]`.
- `provenance.sampling_frames` automatically includes `detection` via `dict(FACE_BAKEOFF_SAMPLING_FRAMES)`.
- Face MD Detection line surfaces `frame=\`...\``.
- **No change** to precision/recall arithmetic (verified live vs freeze: tp/fp/fn/precision/recall identical).

### GREEN capture (verbatim)

```text
=== GREEN Task2 sampling_frame ===
detection keys: ['fn', 'fp', 'precision', 'recall', 'sampling_frame', 'tp']
sampling_frame: all_gt_boxes_on_scoreable_media_via_association: named and anonymous GT share one population (HARM-01 / EVAL-16); TP=IoU-matched pairs; FN=unmatched GT (named missed_gt + missed_stranger_gt); FP=unmatched detections; error-item media excluded from association (listed in failures); tp+fn equals GT boxes that reached association
provenance.sampling_frames.detection present? True
```

Arithmetic pin (face freeze live rescore):

```text
tp freeze 6 live 6 match True
fp freeze 1 live 1 match True
fn freeze 4 live 4 match True
precision freeze 0.8571428571428571 live 0.8571428571428571 match True
recall freeze 0.6 live 0.6 match True
```

---

## Disagreements

**None** on the two owned findings after source checks:

1. **G-01 residual:** confirmed `labeled_order` exists with `order_degraded`; report only called `labeled_left_to_right` → counter unwired. Not a misdiagnosis.
2. **C-02:** confirmed face bakeoff `detection` lacked `sampling_frame` while floor-gated slices carry a string frame. Arithmetic not disputed; no change made.
3. **Overloading `degraded_images`:** rejected by design (S2-07). Predicted stamp vs GT-side y-missing are different conditions.

---

## New findings (not owned)

1. **Caption anchor corpus has zero `face_boxes`** (`order_unknown_excluded=37`, `labeled_y_missing_images` will freeze at **0** forever until corpus gains boxes with missing `y`). This is the blind-freeze hazard that let G-01 ship green — **corpus lane must act** (see Cross-lane).
2. **Face anchor manifest:** 9/10 entries have `face_boxes`, **0 named boxes missing `y`** — so even if caption-style ordering were on face bakeoff, the counter would still freeze at 0. Corpus still needs at least one mixed-y / missing-y named box for a non-vacuous freeze of the disclosure.
3. **Media 9/10 HARM-05 trip-wire disclosure** (C-02 corpus half) — out of scope; cross-lane to corpus.

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1338 passed, 4 skipped`  
(Base: `1 failed, 1339 passed, 4 skipped` — +3 new tests, net +4 expected freeze reds from field adds.)

### Expected-red

| Test | Cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | Caption freeze stale: new `faces.identity_ordering.labeled_y_missing_images` (0) + `labeled_y_missing_paths` ([]) |
| `test_expect_report_matches_committed_freeze_green` | Same caption freeze fields |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | **Pre-existing** at base (`coupling_flag=True`→`true`) **plus** new `detection.sampling_frame` + `provenance.sampling_frames.detection` |
| `test_face_expect_report_matches_committed_freeze_green` | Face freeze: `detection.sampling_frame` + `provenance.sampling_frames.detection` |
| `test_cli_score_face_expect_report_end_to_end_green` | Same face freeze fields |

### Unexpected-red

**None.** All five reds are freeze byte-identity / pre-existing face generator drift.

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
base 00bfdd55a462064a1875aabf6322010801aede95
 .../scene/tests/test_eval_harness_report.py        | 189 +++++++++++++++++++++
 .../scripts/eval_harness/report.py                 |  49 +++++-
 2 files changed, 234 insertions(+), 4 deletions(-)
```

(Plus this report file in the report commit.)

---

## Could not verify

- Live prevalence of missing-y named boxes in production corpora (no network / no corpus edit).
- Post-regen freeze byte identity (regeneration is explicitly **not** this lane).
- Whether caption MD freeze artifacts are also byte-compared for the y-missing warning line (JSON freeze is the gate that failed; MD may follow on regen).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **Caption freeze regen lane** | Regenerate `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811-report.json` (+ companion `.md` if tracked). New fields under `faces.identity_ordering`: `labeled_y_missing_images` (int, currently 0 on anchor corpus), `labeled_y_missing_paths` (list, currently `[]`). Expected-red tests: `test_generator_regenerates_byte_identical_committed_anchor`, `test_expect_report_matches_committed_freeze_green`. |
| **Face freeze regen lane** | Regenerate `S2A-face-determinism-anchor-run-20260811-face-report.json` (+ `.md`). New fields: `detection.sampling_frame` (str), `provenance.sampling_frames.detection` (same str). Arithmetic tp/fp/fn/precision/recall **unchanged**. Also absorbs pre-existing `coupling_flag` True→true drift. Expected-red: `test_face_generator_regenerates_byte_identical_committed_anchor`, `test_face_expect_report_matches_committed_freeze_green`, `test_cli_score_face_expect_report_end_to_end_green`. |
| **Corpus lane** | (1) Caption anchor corpus currently has **no `face_boxes`** → `labeled_y_missing_images` freezes at 0 (blind freeze). Add ≥1 scored image with named face_boxes where at least one named box lacks `y` so the counter is non-zero in freeze. (2) C-02 half: media 9/10 exist to trip pre-HARM-01 formula — consider a corpus disclosure that they are intentional HARM-05 trip-wires (do not change detection arithmetic here). |

### Field registry (for regen lanes)

| Field | Type | Section |
| --- | --- | --- |
| `labeled_y_missing_images` | int | `faces.identity_ordering` (caption report / `score_run_record`) |
| `labeled_y_missing_paths` | list[str] | `faces.identity_ordering` (caption report; PUBLIC-redacted) |
| `sampling_frame` | str | `detection` (face bakeoff / `score_face_run_record`) |
| `detection` key in `sampling_frames` | str | `provenance.sampling_frames` (face bakeoff) |
