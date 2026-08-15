# Lane wI2 — regenerate the FACE determinism freeze

**Base:** `3796f3501abbef21ef257a3a0b3f73f3fb5167da` (`integ/fx-wave`)  
**Branch:** `fix/wi2`  
**Scoring code under `scripts/`:** **not modified** (see `git diff --stat` below).

Generator: `python -m scripts.eval_harness.generate_face_determinism_anchor` via
`write_face_anchor(...)` with the same sentinels as the freeze tests
(`head_sha=0*40`, `started_at=2026-08-11T00:00:00Z`). Man+run byte-match
committed freezes (wF4 pins). Only report JSON+MD were copied into
`docs/tasks/vlm/bakeoff-results/`.

---

## Task 1.1 — Contract verification table

| Field path | Predicting lane | Predicted | Regenerated actual | Match? |
| --- | --- | --- | --- | --- |
| `counts.scored` | wF4 | `11` | `11` | **yes** |
| `counts.total` | wF4 | `11` | `11` | **yes** |
| `detection.tp` | wH1 / wG2 | `6` | `6` | **yes** |
| `detection.fp` | wH1 | `1` | `1` | **yes** |
| `detection.fn` | wG2 / wH1 | `5` | `5` | **yes** |
| `detection.recall` | wG2 / wH1 | `≈0.545` (`6/(6+5)`) | `0.5454545454545454` | **yes** |
| `detection.precision` | wF4 / wG2 | `≈0.857` (`6/7`) | `0.8571428571428571` | **yes** |
| `detection.geometry_incomplete_gt` | wH1 | `1` | `1` | **yes** |
| `detection.association_incomplete_media` | wH1 | `1` | `1` | **yes** |
| `detection.association_complete` | wH1 | `false` | `false` | **yes** |
| `detection.sampling_frame` | wH1 | registry string containing `tp+fn+geometry_incomplete_gt equals` and `geometry_incomplete_gt = GT boxes excluded`; not obsolete `tp+fn equals` alone | matches registry | **yes** |
| `provenance.sampling_frames.detection` | wH1 | same string as `detection.sampling_frame` | equal | **yes** |
| `identity_ordering.labeled_y_missing_images` | wG1 | `1` | `1` | **yes** |
| `identity_ordering.labeled_y_missing_paths` | wG1 | `["celebs01/y-missing-mixed-order.jpg"]` | same | **yes** |
| `identity_ordering.order_unknown_excluded` | wG1 | `2` | `2` | **yes** |
| `identity_ordering.degraded_images` | wG1 | `0` | `0` | **yes** |
| `identity_ordering.degraded_paths` | wG1 | `[]` | `[]` | **yes** |
| `identity_ordering.positional_images` | wG1 | `0` | `0` | **yes** |
| MD `## Identity ordering` + `scored_images=11` | wG1 | present | present (`denominator: scored_images=11`) | **yes** |
| MD `## Detection` geometry fields + incomplete warning `n_gt=…=12` | wH1 | present | present | **yes** |
| `provenance.corpus_traps` (3 entries, media 9/10/11) | wF4 | present | present | **yes** |
| `gate_proposal…missed_gt` | wF4 said `3` | `3` | `2` | **no — see Disagreements** (wG2 supersedes) |
| `gate_proposal…detection_recall` | wF4 said `0.5` | `0.5` | `0.545…` | **no — see Disagreements** (wG2 supersedes) |
| `gate_proposal…identification_recall` | wF4 said `0.5` | `0.5` | `0.571…` | **no — see Disagreements** (wG2 + celebs01 frame) |

**No scorer edits.** Every authoritative (later-lane) contract field matches. The three
wF4 gate-coupling cells disagree with wF4's pre-wG2 table only; live arithmetic is
jointly consistent with wG2 (Alice null-y not a named miss) — not a silent laundering.

---

## Task 1.3 — Arithmetic identity checks

| Identity | Expression | Result |
| --- | --- | --- |
| Detection GT partition | `tp + fn + geometry_incomplete_gt` | `6 + 5 + 1 = **12**` |
| vs `provenance.total_gt_boxes` | `12` | **holds** |
| Detection recall | `tp / (tp + fn)` | `6/11 = 0.545454…` **holds** |
| Detection precision | `tp / (tp + fp)` | `6/7 = 0.857142…` **holds** |
| wG1 denominator | `identity_ordering` counters out of `counts.scored` | `scored=11` **holds** |
| Association complete | `association_complete == (geometry_incomplete_gt == 0)` | `false` with incomplete=1 **holds** |

---

## Task 1.3 — Full accounted-for diff (committed freeze → regenerated)

Every changed flat key and its owning lane:

| Changed field | Old → new | Cause / lane |
| --- | --- | --- |
| `counts.scored` / `total` | 10 → 11 | wF4 media 11 |
| `detection.fn` | 4 → 5 | wF4 (+2 trap FNs) then wG2 (−1 Alice incomplete) net +1 |
| `detection.recall` | 0.6 → 0.545… | same |
| `detection.geometry_incomplete_gt` | absent → 1 | wH1 publish |
| `detection.association_incomplete_media` | absent → 1 | wH1 |
| `detection.association_complete` | absent → false | wH1 |
| `detection.sampling_frame` | absent → registry (wH1 text) | wd-A + wH1 correction |
| `identity_ordering.*` (entire block) | absent → wG1 values | wG1 |
| `gate…detection_recall` | 0.6 → 0.545… | mirrors detection (wF4+wG2) |
| `gate…identification_recall` | 0.667 → 0.571… | media 11 Bob as celebs01 missed_gt (+1) |
| `gate…missed_gt` | 1 → 2 | wF4+wG2 (Bob only; Alice incomplete) |
| `provenance.corpus_traps` | absent → 3 traps | wF4 |
| `provenance.note` | no G-01 / corpus_traps trailer → has both | wF4 |
| `provenance.manifest_sha256` / `score_manifest_sha256` | `sha256:021109aa…` → `sha256:02003e25…` | wF4 man digest |
| `provenance.sampling_frames.detection` | absent → same as detection | wd-A / wH1 |
| `provenance.total_gt_boxes` | 10 → 12 | wF4 (+2 boxes media 11) |
| `slices.full_corpus_identification.fn/missed_gt/recall/denom` | 3/2/0.571/7 → 4/3/0.5/8 | wF4 Bob (+Alice not in id miss for incomplete geom — only +1 missed_gt) |
| `slices.headline_identification.fn/missed_gt/recall/denom` | 2/1/0.667/6 → 3/2/0.571/7 | same, celebs01 frame |
| MD Detection / Identity ordering / gate lines | stale numbers | regenerated from live |

**Unchanged (spot-checked):** detection.tp/fp/precision; unknown_rejection; clustering;
occlusion cells; coverage_gaps list `['failures','occlusion.occlusion_other','occlusion.sunglasses']`;
decisions[] bodies for media 1–7; `detection_recall_coupling_flag` remains JSON `true`
(boolean — no True/true string drift remained in the committed freeze).

**No unpredicted field changes.** All deltas map to wF4 / wG1 / wG2 / wH1 / wd-A.

---

## Task 2 — Pin update list

| Artifact | Old digest | New digest |
| --- | --- | --- |
| `…-face-report.json` | `faf72705b708e77b57ec9255c7c5d9292b7d366f77348cac7a657db7ff394e52` | `c8e174db92b47d746c2497074d77f3197b016e4eec761ec1d5739488766058f6` |
| `…-face-report.md` | `cc60073dd1f126517370e5832cae142201b89df22b8fe49d6aec2e299bc06b7d` | `ff108e77facba690b79c94b5acaf37edbe5bf01784f526cccad80f4e3e5b8899` |
| manifest (input) | `sha256:32eff309…` | **unchanged** (wF4) |
| run-record (input) | `sha256:20ed14fe…` | **unchanged** (wF4) |

Updated only `_FROZEN_DIGESTS` report entries + comments in
`test_eval_harness_face_determinism_anchor.py`. No assertion weakened.

---

## Task 3 — Mutation transcripts (freeze green → red)

Baseline after Task 2: live re-score **byte-matches** committed freeze
(`report matches freeze? True`). Clean gate:

```
determinism check passed [score-face]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42); matches --expect-report …
```

### MUTATION 1 — **wF4 original** constant-0 `labeled_order` (order_degraded strip)

**Probe (verbatim shape):** monkeypatch `report.labeled_order` to return
`LabeledOrderResult(names=…, y_missing_count=0, order_degraded=False)`.

**RED capture:**

```
=== MUTATION 1: wF4 original constant-0 labeled_order (order_degraded strip) ===
byte-match freeze after mut1? False
  identity_ordering.labeled_y_missing_images: live/mut=0  freeze=1  diverge=True
  identity_ordering.labeled_y_missing_paths: live/mut=[]  freeze=['celebs01/y-missing-mixed-order.jpg']  diverge=True
FREEZE RED on labeled_y_missing_images? True
  mut= 0 freeze= 1
determinism check ANCHOR_MISMATCH [score-face]: live re-score diverges from --expect-report
  field: identity_ordering.labeled_y_missing_images 0 != 1
  (wF4 original constant-0 mutation now RED against green freeze)
```

**This is the single most important line:** the exact constant-0 wiring that Wave F
proved was *invisible* against the old corpus/report is now **red** on the green freeze.

### MUTATION 2 — `order_unknown_excluded` forced to 0

**Probe:** wrap `_identity_ordering_block_for_face` to force `order_unknown_excluded=0`.

**RED capture:**

```
=== MUTATION 2: order_unknown_excluded forced to 0 via identity_ordering block rewrite ===
byte-match freeze after mut2? False
  identity_ordering.order_unknown_excluded: live/mut=0  freeze=2  diverge=True
FREEZE RED on order_unknown_excluded? True
```

### MUTATION 3 — `geometry_incomplete_*` source stamp forced 0

**Probe:** wrap `score_face_assignment` with
`replace(ar, geometry_incomplete_gt=0, association_incomplete_media=0)`.

**RED capture:**

```
=== MUTATION 3b: score_face_assignment stamps geometry_incomplete_gt=0 (source aggregation) ===
byte-match freeze after mut3b? False
  detection.geometry_incomplete_gt: live/mut=0  freeze=1  diverge=True
  detection.association_incomplete_media: live/mut=0  freeze=1  diverge=True
  detection.association_complete: live/mut=True  freeze=False  diverge=True
  detection.fn: live/mut=5  freeze=5  diverge=False
FREEZE RED on geometry_incomplete_gt? True
```

(fn stays 5 — incomplete not re-absorbed into FN; stamp-only mutation.)

### MUTATION 4 — `detection.fn` forced to 0

**Probe:** wrap `_detection_from_assignment` to set `fn=0`, `recall=1.0`.

**RED capture:**

```
=== MUTATION 4: detection.fn forced to 0 (source _detection_from_assignment) ===
byte-match freeze after mut4? False
  detection.fn: live/mut=0  freeze=5  diverge=True
  detection.recall: live/mut=1.0  freeze=0.5454545454545454  diverge=True
FREEZE RED on detection.fn? True
```

**All four counters: freeze goes RED under mutation. None left unpinned.**

---

## Disagreements

1. **wF4 gate coupling table vs post-wG2 live** — wF4 predicted
   `missed_gt=3`, `detection_recall=0.5`, `identification_recall=0.5` on the
   post-extension corpus when Alice *and* Bob were detection/id misses. wG2
   reclassified Alice (null-y) as `geometry_incomplete_gt`, so:
   - gate `missed_gt` = **2** (prior 1 + Bob only)
   - `detection_recall` = **0.545…** (mirrors detection.fn=5)
   - celebs01 `identification_recall` = **0.571…** (4/7); full-corpus id recall
     is **0.5** (4/8) — wF4's "0.5" matches full-corpus, not the gate/headline frame.

   Counter-evidence: arithmetic identities hold; wG2's regen table explicitly
   supersedes wF4's detection.fn/recall; assignment named missed_gt path excludes
   Alice. **Not a scorer bug; not adjusted.**

2. **wF4 `coupling_flag True→true`** — committed freeze already stores JSON
   boolean `true` under `detection_recall_coupling_flag`. No residual drift to
   absorb.

---

## New findings (not owned)

1. **`test_face_anchor_freeze_sees_labeled_y_missing_counter`** and
   **`test_face_anchor_freeze_sees_geometry_incomplete_counter`** in
   `test_eval_harness_face_bakeoff.py` still assert Task-1 *blind* baselines
   (`"identity_ordering" not in committed`, `"geometry_incomplete_gt" not in
   committed_det`). After this regen those asserts fail. Tests need post-regen
   flip: assert freeze **pins** live values. **Not owned by wI2** — cross-lane.

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `4 failed, 1410 passed, 4 skipped`

### Expected-red

| Test | Owner / cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | **wI1** caption freeze (not this lane) |
| `test_expect_report_matches_committed_freeze_green` | **wI1** caption freeze |
| `test_face_anchor_freeze_sees_labeled_y_missing_counter` | **wG1 residual test** still asserts pre-regen blind freeze; flip after wI2 |
| `test_face_anchor_freeze_sees_geometry_incomplete_counter` | **wH1 residual test** same |

### Expected-green (this lane — verified)

| Test | Status |
| --- | --- |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | **GREEN** |
| `test_face_expect_report_matches_committed_freeze_green` | **GREEN** |
| `test_cli_score_face_expect_report_end_to_end_green` | **GREEN** |

Baseline was `5 failed, 1409 passed, 4 skipped` (3 face freeze reds + 2 caption).
After wI2: face freeze trio green (−3), two bakeoff "sees" tests red (+2) → net 4
failed, 1410 passed.

### Unexpected-red

**None.**

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
 .../test_eval_harness_face_determinism_anchor.py   | 14 ++--
 ...eterminism-anchor-run-20260811-face-report.json | 76 ++++++++++++++------
 ...-determinism-anchor-run-20260811-face-report.md | 21 ++++--
 3 files changed, 79 insertions(+), 32 deletions(-)
```

**`apps/prototype-description-service/scripts/`:** empty diff (no scoring-code changes).

---

## Could not verify

- Cross-process `ANCHOR_MISMATCH` SystemExit with monkeypatched aggregation inside
  child workers (mutations applied in-process to `build_face_reports` /
  `score_face_run_record`). Field-level byte divergence against the green freeze
  is the accepted proof shape used by waves F–H; clean gate green was shown
  without mutation.
- Production prevalence of null-y / order_degraded media (no network).
- Caption freeze (wI1 concurrent).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **Owner of `test_eval_harness_face_bakeoff.py` (wG1/wH1 residual)** | Flip `test_face_anchor_freeze_sees_labeled_y_missing_counter` and `test_face_anchor_freeze_sees_geometry_incomplete_counter` from "freeze lacks field" asserts to "freeze pins live values" (`identity_ordering.labeled_y_missing_images==1`, `detection.geometry_incomplete_gt==1`, etc.). Keep live-vs-mutation discrimination. |
| **wI1** | Caption freeze regen remains independent; leave the two caption reds. |

---

## Summary

Face report freezes regenerated from the committed generator; all authoritative
contract fields match; arithmetic identities hold; digests pinned; **wF4
constant-0 mutation now fails the green freeze** on `labeled_y_missing_images`;
`order_unknown_excluded`, `geometry_incomplete_*`, and `detection.fn` mutations
also go red. No `scripts/` edits. Three face freeze tests green.
