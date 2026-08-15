# Lane wF4 — close the blind freeze: extend the face anchor corpus

**Branch:** `fix/wf4` · **Base:** `f406193709619d143f463cc5dfa3f316fecb7333`  
**Owned files:** face anchor man/run JSON, `generate_face_determinism_anchor.py`, `test_eval_harness_face_determinism_anchor.py`  
**Scope exceptions (hard blockers, no other Wave F owner):** `manifest.py` (`FaceBox.y` optional), `face_assignment.py` (unmatched-GT name path)

---

## Finding 1 — Blind freeze on `labeled_y_missing_images` (wd-A residual / VLM6-R2-G-01)

### Reproduction probe (pre-extension, verbatim)

```text
=== PROBE 1: face_boxes inventory ===
n_entries=10 with_face_boxes=9
named_boxes_missing_y=0 order_degraded_images=0

=== PROBE 2: committed face report has no labeled_y_missing ===
labeled_y_missing in face report? False

=== PROBE 3: caption freeze identity_ordering ===
{
  "degraded_images": 0,
  "degraded_paths": [],
  "order_unknown_excluded": 37,
  "positional_images": 0
}

=== PROBE 4: score face-manifest entries via score_run_record (dict path) ===
live labeled_y_missing_images= 0

=== PROBE 5 (decisive): mutate labeled_order to strip order_degraded; counter stays 0 ===
live=0 blind_mutation=0 equal? True
BLINDNESS CONFIRMED
```

wd-A's claim holds: zero named boxes missing `y` → counter structurally always 0 → wiring to constant 0 is invisible.

### RED capture (pre-extension control — mutation invisible)

```text
live labeled_y_missing_images=0
blind_mutation labeled_y_missing_images=0
equal? True
# Freeze cannot see a constant-0 / order_degraded-strip regression
```

### Fix

1. **Media 11** `celebs01/y-missing-mixed-order.jpg`: named Bob with `y=0.1` + named Alice **missing `y`** (same `x=0.5`). Zero detections (association never `float()`-coerces null y for matched pairs). Shape is the G-01 mixed form, not all-missing.
2. **`FaceBox.y: float | None = None`** — schema previously forbade the condition the counter measures (hard schema blindness).
3. **`collect_matched_faces` unmatched path** uses `gt_box_name` only (no `_gt_fields` float coerce) so zero-det null-y GT is scoreable.
4. Manifest + run-record regenerated in lockstep; report freezes **not** rewritten (regen stage owns them).
5. Digest pins updated for man+run only.

### GREEN capture (post-extension — mutation now visible)

```text
=== ACCEPTANCE GREEN ===
live labeled_y_missing_images=1 blind_mutation=0 discriminates=True

man match True
run match True
report match False   # expected — regen stage

pytest ...::test_labeled_y_missing_constant_zero_goes_red_on_extended_corpus PASSED
pytest ...::test_face_anchor_corpus_includes_mixed_y_order_degraded_trap PASSED
```

TEST-15 bar met: the Task-1 constant-0 mutation that **passed** against the old corpus now **fails** (diverges) against the extended corpus.

---

## Finding 2 — VLM6-R2-C-02 corpus half (trap sampling frame)

### Reproduction

Media 9/10 exist solely to trip pre-HARM-01 named-only FN. Operator reading `detection-recall: 0.600` has no corpus-level inventory of deliberate traps. Media 11 is the same class of trap for G-01.

### Fix

`provenance.corpus_traps` on the face run-record (free-form provenance dict — no GoldenManifest schema change):

| media_id | kind | trips |
| --- | --- | --- |
| 9 | `HARM-05_pure_stranger_miss` | pre-HARM-01 named-only detection FN |
| 10 | `HARM-05_mixed_named_anonymous_miss` | pre-HARM-01 named-only detection FN |
| 11 | `VLM6-R2-G-01_mixed_y_order_degraded` | `labeled_y_missing_images` always-0 freeze blindness |

**Detection arithmetic not changed.** Trap media not removed. Number is correct for the corpus; sampling frame is now disclosed (`EVAL-03`).

### GREEN

```text
pytest ...::test_corpus_traps_disclose_deliberate_trap_media PASSED
```

---

## Disagreements

**None** on the blindness claim after live probes:

1. Named boxes missing `y` on pre-extension face manifest: **0** (confirmed via `named_box_name`).
2. `labeled_y_missing_images` on face-manifest caption-style score: **0**.
3. Constant-0 / strip-`order_degraded` mutation equaled live: **blindness confirmed**.
4. Detection arithmetic is correct for the corpus; C-02 is disclosure only — not disputed.

**Note:** Face bakeoff report still has **no** `labeled_y_missing_*` field (counter lives on caption `score_run_record` / `faces.identity_ordering`). Observability is via corpus shape + the new control test that scores the face manifest through the caption aggregation path. Regenerating the face report alone does **not** surface this counter unless a later lane wires it into face bakeoff.

---

## New findings (not owned)

1. **Face bakeoff never publishes `labeled_y_missing_*`** — only caption `score_run_record` does. Corpus extension makes the counter *possible*; face freeze report still cannot pin it until report wiring lands (wF1 / report.py — not this lane).
2. **Caption golden corpus still has zero `face_boxes`** — caption freeze `labeled_y_missing_images` remains structural 0 (caption corpus lane / regen).
3. **`associate_detections` still `float(gt["y"])` when `n_det > 0`** — null-y boxes with any detection will crash. Trap media uses `faces=[]` deliberately. A production null-y box with detections needs a face_assignment hardening (wF2).
4. **GoldenManifest `extra=forbid`** blocks a top-level `corpus_traps` field on the manifest; inventory lives on run-record provenance instead.

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1375 passed, 4 skipped`  
(Base: `5 failed, 1372 passed, 4 skipped` — +3 new tests, all green.)

### Expected-red

| Test | Cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | **Pre-existing** caption freeze stale (wd-A / Wave E field adds: `labeled_y_missing_*`, etc.). Not caused by wF4 corpus. |
| `test_expect_report_matches_committed_freeze_green` | Same caption freeze staleness. |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | Face report freeze stale: **pre-existing** `coupling_flag` True→true + wd-A `detection.sampling_frame` **plus wF4 corpus**: `counts.scored/total` 10→11, `detection.fn` 4→6, `detection.recall` 0.6→0.5, coupling `missed_gt` 1→3, coupling id/det recall →0.5, provenance note + live `coverage_gaps` recompute. Man+run byte-match generator (verified). |
| `test_face_expect_report_matches_committed_freeze_green` | Same face report staleness vs live re-score of extended man+run. |
| `test_cli_score_face_expect_report_end_to_end_green` | Same face report staleness. |

### Unexpected-red

**None.**

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
base f406193709619d143f463cc5dfa3f316fecb7333
 .../test_eval_harness_face_determinism_anchor.py   | 221 +++++++++++++++++++--
 .../scripts/eval_harness/face_assignment.py        |   6 +-
 .../generate_face_determinism_anchor.py            |  88 +++++++-
 .../scripts/eval_harness/manifest.py               |   8 +-
 ...-face-determinism-anchor-manifest-20260811.json |  39 ++++
 .../S2A-face-determinism-anchor-run-20260811.json  |  38 +++-
 6 files changed, 378 insertions(+), 22 deletions(-)
```

(Plus this report file in the report commit.)

### Pins moved (owned)

| Artifact | Old digest (prefix) | New digest |
| --- | --- | --- |
| face manifest | `sha256:67685bb7…` | `32eff309b37822deb4474ca05dac4b0343e7a2378e4d25ab013020b5c565b5bd` |
| face run-record | `sha256:43d160d6…` | `20ed14fe53bf1554f0aa348f5b0270d426e68f31d9db9fec97f6bdfcee01adab` |
| `manifest_sha256` prefix | `sha256:021109aa` | `sha256:02003e25` |

Report digests **unchanged** (regen stage).

### Live value shifts regen must absorb

| Field | Freeze (stale) | Live (post-wF4) |
| --- | --- | --- |
| `counts.scored` / `total` | 10 | 11 |
| `detection.fn` | 4 | 6 |
| `detection.recall` | 0.6 | 0.5 |
| `detection.tp` / `fp` / `precision` | 6 / 1 / 0.857… | **unchanged** |
| `gate_proposal.identification_detection_coupling.detection_recall` | 0.6 | 0.5 |
| `…identification_recall` | ~0.667 | 0.5 |
| `…missed_gt` | 1 | 3 |
| `provenance.corpus_traps` | absent | 3-entry trap inventory |
| `detection.sampling_frame` | absent in freeze | present (wd-A; also regen) |

Existing media 1–10 published cells that are not causally downstream of media 11 (matched Alice/Bob decisions, FP media 7, etc.) retain their individual outcomes; aggregate detection FN/recall and celebs01 missed_gt move because media 11 adds two unmatched named GT boxes.

---

## Could not verify

- Caption-side freeze becoming non-blind (golden has no `face_boxes`; out of scope).
- Face report publishing `labeled_y_missing_*` (not in face bakeoff scorer).
- Production prevalence of missing-y named boxes (no network / no real corpus).
- Post-regen face report byte identity (explicitly not this lane).
- Merge conflict risk on `face_assignment.py` with concurrent wF2 (minimal one-line name path).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **Face freeze regen stage** | Regenerate `S2A-face-determinism-anchor-run-20260811-face-report.json` + `.md` from the wF4 man+run. **Do not** re-extend the corpus. Expected value shifts: table above. Also absorb pre-existing `coupling_flag` True→true and wd-A `detection.sampling_frame` / `provenance.sampling_frames.detection`. Update report digests in `test_eval_harness_face_determinism_anchor.py` `_FROZEN_DIGESTS` for report JSON+MD only (man+run already pinned by wF4). Expected-red tests that should go green after regen: `test_face_generator_regenerates_byte_identical_committed_anchor`, `test_face_expect_report_matches_committed_freeze_green`, `test_cli_score_face_expect_report_end_to_end_green`. |
| **Caption freeze regen stage** | Unrelated to wF4 corpus; still needs wd-A `labeled_y_missing_images=0` + paths `[]` on golden (still blind — caption has no face_boxes). |
| **wF2 / face_assignment** | Confirm the unmatched-GT `gt_box_name` path (or harden `_gt_fields` for null y). Association with `n_det>0` still crashes on null y — fail-closed or skip-null-y policy needed for non-trap corpora. |
| **wF1 / report.py (optional)** | If face bakeoff should publish `labeled_y_missing_*`, wire `labeled_order` over GT boxes into face report — currently only caption `score_run_record` surfaces it. Corpus is ready. |
| **Schema note** | `FaceBox.y: float \| None = None` landed in this branch as a hard blocker (counter was schema-impossible). Reviewers: keep optional; required float re-opens structural blindness. |
