# VLM-6 Wave C · lane cx1 — face namedness predicate + L→R ordering regression

**Branch:** `fix/cx1` · **Worktree:** `~/lane-gx2`  
**Base:** `7812d71c832786328705a8d6ea6e1d7f41dc487b` (`integ/fx-wave`)  
**Heuristics:** `TEST-15`, `TEST-06`, `DBG-10`, `HARM-06`, `HARM-07`, `AUDIT-07`, `rg-005`, `rg-015`, `sr-001`, `S2-07`

## Summary

Fixed both HIGH findings in owned modules. L→R extractors now share `gt_box_name` (strip; empty/whitespace → anonymous). Missing-`y` fallback is **per-box** (real sibling `y` preserved) with `LabeledOrderResult.order_degraded` / `y_missing_count` disclosure. Wave D may regenerate the caption anchor freeze once this ordering rule is integrated.

Owned paths touched:

| Path | Action |
| --- | --- |
| `scripts/eval_harness/face_metrics.py` | shared namedness via `gt_box_name`; `labeled_order` + per-box key; `LabeledOrderResult` |
| `scene/tests/test_eval_harness_face_metrics.py` | RED-proven tests for G-01 / A-01; strengthened namedness cross-site |
| `.s2a/vlm6-cx1-report.md` | this report |

**Not touched (out of scope):** `report.py`, `cli.py`, `promote_atomic.py`, provenance/anchor scripts, bakeoff freezes, `README.md`, `face_assignment.py` body (already owns correct `gt_box_name`; L→R now routes through it).

---

## Finding 1 — VLM6-R2-G-01 (HIGH) — HARM-07 ordering regression

### Reproduction (pre-fix, matches reviewer)

```text
boxes A(x=0.5,y=0.9), B(x=0.5,y=0.1), C(x=0.2,y=None)
labeled_left_to_right → ['C', 'A', 'B']   # wrong: whole-image (x,name) discards real y
correct by real y     → ['C', 'B', 'A']
identical x, no y     → alphabetical name order with no degraded counter
```

### TEST-15 RED (pre-fix path reimplemented locally)

```text
RED ordering: AssertionError("order got ['C', 'A', 'B']")
  pre-fix names=['C', 'A', 'B'] degraded=False y_missing=0
RED bare degraded: AssertionError()
  pre-fix degraded=False y_missing=0
```

### Fix

- `labeled_order()` / `_labeled_box_order_key()`: **per-box** key
  - y present → `(x, 0, y, name)` (≡ centre key)
  - y absent  → `(x, 1, 0.0, name)` (x-only spatial primary; missing-flag separates from real `y=0.0`)
- Never whole-image collapse to `(x, name)` that throws away sibling y.
- `LabeledOrderResult{names, y_missing_count, order_degraded}` for disclosure.
- `labeled_left_to_right` = `labeled_order(...).names` (API preserved).

### GREEN

```text
ordering GREEN: names=['C', 'B', 'A'] degraded=True y_missing=1
bare degraded GREEN: degraded=True y_missing=2
```

Tests: `test_labeled_order_per_box_missing_y_preserves_real_y`,
`test_labeled_order_identical_x_no_y_discloses_degraded_not_spatial`,
`test_labeled_order_identical_centre_x_distinct_y`.

---

## Finding 2 — VLM6-R2-A-01 (HIGH) — single namedness predicate was false

### Reproduction (pre-fix, matches reviewer verbatim)

```text
gt_box_name({"name": "   "}) → None
labeled_left_to_right([{name:"   ", ...}]) → ['   ']   # not anonymous
labeled ['  ', 'Bob']  gt [None, 'Bob']
id_pr 1 0 1 []          # false FN on whitespace "name"
strip-mismatch 0 1 1 [('y.jpg', 'Alice')]  # padded GT vs stripped pred
predicted_ws ['  ', 'Bob']
```

### TEST-15 RED (pre-fix path)

```text
RED ws labeled: AssertionError()
RED id_pr ws: got tp/fp/fn=(1, 0, 1)
RED strip-mismatch: labeled=[' Alice '] tp/fp/fn/wrong=(0, 1, 1, [('y.jpg', 'Alice')])
RED predicted_ws: got ['  ', 'Bob']
```

### Fix

- `predicted_left_to_right` and `labeled_order` both call **`gt_box_name`** (the one strip/empty→None predicate in `face_assignment.py`).
- Whitespace-only → skipped; padded → stripped before ordering and ID compare.
- Replaced self-certifying `gt_box_name`-only green with cross-site
  `test_namedness_predicate_shared_across_sites` (association + both L→R + `identification_pr`).

### GREEN (post-fix probe)

```text
None []
labeled ['Bob'] gt [None, 'Bob']
id_pr 1 0 0 []
strip-mismatch 1 0 0 []
predicted_ws ['Bob']
```

---

## Disagreements

None. Reviewer A’s “fallback intentional” read is rebutted by the concrete C,A,B vs C,B,A order change on mixed y-present/y-absent boxes — reachable whenever curated face_boxes omit y on any named box.

## New findings (not owned)

None beyond the cross-lane wiring gap below.

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `1311 passed, 4 skipped, 32 warnings` (≈324s).

| Class | Count | Notes |
| --- | --- | --- |
| Baseline (base commit) | 1307 passed, 4 skipped | as given |
| After fix | 1311 passed, 4 skipped | +4 tests (G-01×3 + A-01 cross-site) |
| Expected-red | 0 | |
| Unexpected-red | 0 | |

Face-metrics file alone: `56 passed`.

## `git diff --stat` vs `7812d71c`

```text
 .../scene/tests/test_eval_harness_face_metrics.py  | 162 +++++++++++++++++++--
 .../scripts/eval_harness/face_metrics.py           | 140 ++++++++++++------
 2 files changed, 247 insertions(+), 55 deletions(-)
```

(Report file is an additional commit on top.)

## Could not verify

- Live `report.py` aggregation of `order_degraded` into `faces.identity_ordering` (report lane owns `report.py`; not edited here).
- Anchor freeze regeneration (Wave D; blocked on this ordering rule being final — it is).
- Production corpus prevalence of missing-y named boxes (no network / no corpus edit).

## Cross-lane requests

1. **Report lane (`report.py`):** when building `faces.identity_ordering`, call `labeled_order(face_boxes)` (not only `labeled_left_to_right`) and aggregate:
   - **Suggested field:** `labeled_y_missing_images` (int) — count of scored images with `order_degraded=True`
   - Optional: `labeled_y_missing_paths` (list) for operator drill-down (redact like `degraded_paths`)
   - **Do not** overload `degraded_images` / `degraded_paths` — those mean predicted `identity_ordering` stamp == `DEGRADED` (S2-07 / rg-015 / A-07).
2. **Wave D caption-anchor regen:** safe to start after this branch is integrated; L→R semantics are final:
   - namedness = `gt_box_name` only
   - order key = per-box `_labeled_box_order_key` (y-present uses real y; y-absent uses x + missing-flag)
   - degradation disclosed via `LabeledOrderResult`

## Ordering semantics (final — for Wave D)

| Case | Result | `order_degraded` |
| --- | --- | --- |
| All named boxes have x+y | sort `(x,y,name)` | False |
| Mixed y present/absent | per-box: x primary; real y kept; missing-y after real-y at same x | True |
| All missing y, distinct x | sort by x (name tertiary for determinism only) | True |
| Identical x, no y | deterministic total order; **not** a spatial claim — counter only | True |
| Named but all missing x | `names=None` (malformed GT / exclude) | n/a |
| All anonymous | `names=[]` | False |

sha-guard:ignore-next-block
```
base 7812d71c832786328705a8d6ea6e1d7f41dc487b
```
