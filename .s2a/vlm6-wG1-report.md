# Lane wG1 — publish the y-missing counter where the face freeze can pin it

**Branch:** `fix/wg1` · **Base:** `cc1da6219d2407dca6c676d6e6583635bcdc9672`  
**Owned files:** `report.py`, `face_bakeoff.py` (unchanged — walker not required), `test_eval_harness_report.py`, `test_eval_harness_face_bakeoff.py`  
**Not touched:** `face_assignment.py`, `manifest.py`, `face_metrics.py`, generators, `docs/tasks/vlm/bakeoff-results/*`

---

## Finding 1 — Face bakeoff never published `labeled_y_missing_*` (wF4 residual)

### Task 1 diagnosis (DBG-10)

**Divergence shape (stated before the fix):** face report is built by a **different aggregation function** (`score_face_run_record`) that **never called** the ordering code (`labeled_order`) at all. It is not “same structure, drop field” — the face path never produced an `identity_ordering` block.

#### Reproduction probe (pre-fix / committed freeze, verbatim)

```text
=== COMMITTED face report ===
top keys include: counts, decisions, detection, failures, gate_proposal, ...
has identity_ordering False
labeled_y_missing in committed text? False
```

#### Caption path on the same extended face manifest (counter present)

```text
=== CAPTION score_run_record faces.identity_ordering ===
{
  "positional_images": 11,
  "degraded_images": 0,
  "degraded_paths": [],
  "order_unknown_excluded": 2,
  "labeled_y_missing_images": 1,
  "labeled_y_missing_paths": [
    "celebs01/y-missing-mixed-order.jpg"
  ]
}
```

#### Face path before wiring (structure only; confirmed no counter keys)

```text
=== FACE score_face_run_record top keys (pre-wiring, base) ===
['counts', 'decisions', 'detection', 'failures', 'gate_proposal', 'kind',
 'protocol_disclosures', 'provenance', 'report_kind', 'schema', 'slices', 'tau']
keys containing labeled_y_missing: []
keys containing identity_ordering: []
```

(Substring hit on `labeled_y_missing` in live pre-wiring dumps was only inside `provenance.corpus_traps` free text from wF4 — not a published counter.)

### RED capture (pre-wiring blindness)

```text
committed freeze: identity_ordering absent
live face score: no labeled_y_missing_* field
caption path on same corpus: labeled_y_missing_images=1
→ face freeze cannot pin the counter (wF4 residual confirmed)
```

### Fix

1. **`_identity_ordering_block_for_face`** in `report.py` — walks the same **scoreable** set as detection/assignment.
2. **GT counters** via real `labeled_order(_normalize_face_boxes_for_order(...))` — same source as caption `score_run_record` (rg-015: no boundary recount).
3. **Predicted stamp counters** (`positional_images` / `degraded_images` / `degraded_paths`) from item `identity_ordering` when present; face walk items omit the stamp → honest `0` (not fabricated degraded).
4. **`order_unknown_excluded`** matches caption positional-exclusion semantics (no usable labeled order, predicted DEGRADED, or recognition off).
5. Publish top-level **`identity_ordering`** on the face report (face report has no `faces.*` wrapper; **field names/semantics match caption** `faces.identity_ordering` exactly).
6. Markdown: `## Identity ordering` with denominator `counts.scored`.
7. PUBLIC path scrub: existing `_redact_public_paths` already rewrites `labeled_y_missing_paths` / `degraded_paths`.

**Denominator (EVAL-03):** image-level counters are out of **`counts.scored`** (scoreable non-error items). On the extended face anchor corpus: **scored = 11**.

### GREEN capture (post-wiring)

```text
=== FACE score_face_run_record identity_ordering ===
{
  "positional_images": 0,
  "degraded_images": 0,
  "degraded_paths": [],
  "order_unknown_excluded": 2,
  "labeled_y_missing_images": 1,
  "labeled_y_missing_paths": [
    "celebs01/y-missing-mixed-order.jpg"
  ]
}
counts.scored = 11

GT fields match caption on same corpus:
  labeled_y_missing_images: 1 == 1
  labeled_y_missing_paths: equal
  order_unknown_excluded: 2 == 2
(predicted stamp fields differ: face walk has no identity_ordering stamps)
```

### Task 3 — freeze can see it (TEST-15 acceptance)

Stale freeze already fails (Expected-red). Separation of causes: compare **live vs constant-0 mutation** on the counter cell, not pass/fail of the freeze bit.

```text
=== TASK3 mutation proof ===
live labeled_y_missing_images=1
blind_mutation labeled_y_missing_images=0
discriminates=True
committed has identity_ordering=False (stale baseline)
live vs committed: NEW field identity_ordering with labeled_y_missing_images=1
blind vs live specific delta on counter: 1 → 0
```

pytest:

```text
test_face_labeled_y_missing_constant_zero_mutation_diverges PASSED
test_face_anchor_freeze_sees_labeled_y_missing_counter PASSED
```

**How staleness was separated from counter observability:** both live and blind re-scores mismatch the committed freeze (pre-existing + new field). The mutation proof asserts `live_n != blind_n` on `identity_ordering.labeled_y_missing_images` specifically. If wiring were decorative (field absent or constant), that equality would hold and the test fails.

---

## Disagreements

**None** on the residual claim after live probes:

1. Committed face report had **no** `identity_ordering` / `labeled_y_missing_*`.
2. Caption path on the same face manifest already published `labeled_y_missing_images=1`.
3. Face path used a separate scorer that never called `labeled_order`.
4. After wiring, constant-0 mutation discriminates (`1` vs `0`).

Predicted-side `positional_images=0` on face items is **honest absence of stamps**, not a disagreement with caption’s `11` (caption items were stamped `positional` in the probe).

---

## New findings (not owned)

1. **Face walk never stamps `identity_ordering` on items** — predicted-side counters stay 0 until a face-fetch path stamps them (optional later; not required to pin GT `labeled_y_missing_*`).
2. **Caption golden corpus still has zero `face_boxes`** (wF4 note) — caption freeze `labeled_y_missing_images` remains structural 0 there (caption corpus / regen, not this lane).
3. **`associate_detections` still `float(gt["y"])` when `n_det > 0`** (wF4 / wG2 scope) — trap media uses empty dets by design.

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1392 passed, 4 skipped`  
(Base: `5 failed, 1387 passed, 4 skipped` — **+5 new tests**, all green.)

### Expected-red

| Test | Cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | **Pre-existing** caption freeze staleness (wd-A / Wave E). Not caused by wG1. |
| `test_expect_report_matches_committed_freeze_green` | Same caption freeze staleness. |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | Face report freeze stale: **pre-existing** (coupling_flag, sampling_frame, wF4 corpus counts/recall/corpus_traps) **plus wG1**: new top-level `identity_ordering` block (and MD `## Identity ordering` section). |
| `test_face_expect_report_matches_committed_freeze_green` | Same — live re-score now includes `identity_ordering`; committed freeze does not. |
| `test_cli_score_face_expect_report_end_to_end_green` | Same face report staleness vs live re-score. |

**wG1-owned field delta for face freeze regen:**

| Field path | Type | Denominator | Expected value (extended face corpus) |
| --- | --- | --- | --- |
| `identity_ordering.labeled_y_missing_images` | `int` | `counts.scored` (=11) | `1` |
| `identity_ordering.labeled_y_missing_paths` | `list[str]` | same scoreable set | `["celebs01/y-missing-mixed-order.jpg"]` |
| `identity_ordering.order_unknown_excluded` | `int` | `counts.scored` | `2` (fp-only + y-missing) |
| `identity_ordering.degraded_images` | `int` | scoreable items with predicted stamp | `0` |
| `identity_ordering.degraded_paths` | `list[str]` | — | `[]` |
| `identity_ordering.positional_images` | `int` | scoreable items with POSITIONAL stamp | `0` (face walk does not stamp) |

Also MD: `## Identity ordering` lines naming the same counters with `denominator: scored_images=11`.

### Unexpected-red

**None.**

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
base cc1da6219d2407dca6c676d6e6583635bcdc9672
 .../scene/tests/test_eval_harness_face_bakeoff.py  |  68 +++++++
 .../scene/tests/test_eval_harness_report.py        | 211 +++++++++++++++++++++
 .../scripts/eval_harness/report.py                 | 117 ++++++++++++
 3 files changed, 396 insertions(+)
```

(`face_bakeoff.py` not modified — residual is report aggregation, not the walker.)

---

## Could not verify

- Post-regen face report byte identity (explicitly not this lane; regen stage owns artifacts).
- Production prevalence of missing-y named boxes (no network / no real corpus).
- Whether a future face-walk stamp of `identity_ordering` should mirror caption fetch (out of scope; GT counter is independent).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **Regeneration stage** | Regenerate face report JSON+MD freezes under `docs/tasks/vlm/bakeoff-results/` so they absorb the new top-level `identity_ordering` block. Contract values on current extended face corpus (man+run digests already pinned by wF4): see table above. After regen, constant-0 mutation of `labeled_order.order_degraded` must make `test_face_expect_report_matches_committed_freeze_green` go **red** on `labeled_y_missing_images` (1→0). |
| **Regeneration stage** | Face MD freeze must include `## Identity ordering` with `labeled_y_missing_images=1` and `scored_images=11`. |
| **wG2 (if needed)** | No cross-file change required from this lane. Optional later: stamp face walk items with predicted `identity_ordering` if product wants non-zero predicted counters on face reports. |
| **wG3** | Caption freeze still structural-0 for y-missing if golden has no face_boxes — independent of this wiring. |
