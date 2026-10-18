# Lane wE4 report — `face_metrics.py` namedness predicate

**Branch:** `fix/we4`  
**Base:** `88ed0e524bea8ee625afd405ca7f551d8ae1b5ba`  
**Lane commits:**

sha-guard:ignore-next-block
```
5e011c9d4848ca18537d151ba02dc4aa9517aa4b  test(wE4): RED coverage for namedness predicate (RA-02, RA-03)
b0e453b63424c2dc674e30d0d77b1e305332af66  fix(wE4): single named_box_name predicate for face_metrics (RA-02/03)
```

**Owned files only:** `face_metrics.py`, `test_eval_harness_face_metrics.py`.

---

## 1. Per finding

### RA-02 — single namedness predicate still false outside L→R / association

**Severity:** medium · **Verdict:** fixed (within face_metrics ownership)

#### Reproduction probe (verbatim, pre-fix)

```text
$ ./.venv/bin/python - <<'PY'
from scripts.eval_harness.face_metrics import (
    sort_identity_rows_by_normalized_centre, predicted_left_to_right,
)
rows = [
    {"name": "  ", "bbox": {"x": 0, "y": 0, "width": 10, "height": 10}},
    {"name": " Bob ", "bbox": {"x": 50, "y": 0, "width": 10, "height": 10}},
]
print("sort_rows names:", [r["name"] for r in sort_identity_rows_by_normalized_centre(
    rows, image_width=100, image_height=100)])
print("predicted LTR:", predicted_left_to_right(rows, image_width=100, image_height=100))
PY

sort_rows names: ['  ', ' Bob ']
predicted LTR: ['Bob']
```

`sort_identity_rows_by_normalized_centre` used `str(row.get("name") or "")` (line ~323) while L→R paths used `gt_box_name`. Same-centre name tie-break also diverged: raw `" Bob "` sorted before `"Alice"`.

#### RED capture (verbatim)

```text
$ ./.venv/bin/python -m pytest \
  scene/tests/test_eval_harness_face_metrics.py::test_face_metrics_namedness_sites_share_one_predicate \
  scene/tests/test_eval_harness_face_metrics.py::test_sort_identity_rows_name_tiebreak_uses_stripped_namedness \
  -v -p no:randomly

FAILED test_face_metrics_namedness_sites_share_one_predicate
  AssertionError: face_metrics must expose named_box_name as the single namedness predicate

FAILED test_sort_identity_rows_name_tiebreak_uses_stripped_namedness
  AssertionError: assert [' Bob ', 'Alice'] == ['Alice', ' Bob ']
  At index 0 diff: ' Bob ' != 'Alice'
```

#### Fix

- Introduced `named_box_name` as the **single** face_metrics namedness entry.
- Routed `predicted_left_to_right`, `labeled_order` / `labeled_left_to_right`, and `sort_identity_rows_by_normalized_centre` through it.
- Sort still keeps every row (storage multiset / face_pass contract); only the tertiary sort-key name is normalized (`named_box_name(...) or ""`). Row `name` fields are not rewritten.
- Guard test spies the module predicate: a reintroduced inline name check never increments the spy → fails (not an enumeration of call sites).

#### GREEN capture (verbatim)

```text
$ ./.venv/bin/python -m pytest \
  scene/tests/test_eval_harness_face_metrics.py::test_face_metrics_namedness_sites_share_one_predicate \
  scene/tests/test_eval_harness_face_metrics.py::test_sort_identity_rows_name_tiebreak_uses_stripped_namedness \
  -v -p no:randomly

PASSED test_face_metrics_namedness_sites_share_one_predicate
PASSED test_sort_identity_rows_name_tiebreak_uses_stripped_namedness
```

Post-fix probe:

```text
sort_rows names: ['  ', ' Bob ']          # rows preserved
sort_keys via predicate: [None, 'Bob']    # key uses named_box_name
predicted LTR: ['Bob']
```

**Out of ownership (not fixed here):** `_apply_face_gate` (bakeoff), `_build_single_subject_cohort_by_media` / occlusion filter (report.py), `face_bakeoff` `any(box.name)`. See Cross-lane.

---

### RA-03 — zero-width / non-strip characters count as named

**Severity:** low · **Verdict:** fixed in face_metrics; association still strip-only

**Chosen rule (explicit):** a box is named iff after (1) removing Unicode category `Cf` format controls (ZWSP/ZWJ/ZWNJ/BOM/soft-hyphen/…) and (2) `str.strip()` of Unicode whitespace, a non-empty string remains. That remaining string is the identity; empty → anonymous (`None`). Visible text with an embedded format char is kept without the format char (`"A\u200bB"` → `"AB"`). Incidence on the golden corpus was **not** measured (`AUDIT-07`) — mechanism only.

#### Reproduction probe (verbatim, pre-fix)

```text
$ ./.venv/bin/python - <<'PY'
from scripts.eval_harness.face_assignment import gt_box_name
from scripts.eval_harness.face_metrics import labeled_left_to_right
for label, s in [("ZWSP","\u200b"),("ZWJ","\u200d"),("BOM","\ufeff"),("NBSP","\u00a0")]:
    print(label, "gt=", repr(gt_box_name({"name": s})),
          "ltr=", labeled_left_to_right([{"name": s, "x": 0.5, "y": 0.5}]))
PY

ZWSP gt= '\u200b' ltr= ['\u200b']
ZWJ  gt= '\u200d' ltr= ['\u200d']
BOM  gt= '\ufeff' ltr= ['\ufeff']
NBSP gt= None     ltr= []
```

#### RED capture (verbatim)

```text
FAILED test_named_box_name_rejects_invisible_format_chars
  AssertionError: named_box_name missing
```

#### Fix

`named_box_name` implements the Cf + strip rule above; all face_metrics namedness sites use it. L→R no longer emits format-only “names”.

#### GREEN capture (verbatim)

```text
PASSED test_named_box_name_rejects_invisible_format_chars

ZWSP named= None gt= '\u200b' ltr= []
ZWJ  named= None gt= '\u200d' ltr= []
BOM  named= None gt= '\ufeff' ltr= []
NBSP named= None gt= None     ltr= []
```

`face_assignment.gt_box_name` remains strip-only (not owned). Association/miss counts for ZWSP still treat format-only strings as named — cross-lane.

---

## 2. Disagreements

None on mechanism. Both findings reproduced on base.

Scope note (not a disagreement with the defect claim): RA-02’s full harness list includes bakeoff/report/face_bakeoff sites outside this lane’s file set. Those survivors remain; face_metrics internal divergence is closed.

---

## 3. New findings (not owned)

| Id | Severity | Note |
| --- | --- | --- |
| (residual RA-02) | medium | `bakeoff._apply_face_gate`, `report._build_single_subject_cohort_by_media`, occlusion named filter, `face_bakeoff` still use raw name truthiness / no strip. |
| (residual RA-03) | low | `face_assignment.gt_box_name` still strip-only; association `missed_named` for ZWSP remains 1. Align with `named_box_name` rule when that file is open. |

---

## 4. Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1341 passed, 4 skipped` (baseline was `5 failed, 1338 passed, 4 skipped`; +3 new tests, all green).

### Expected-red (not this lane; do not regenerate)

| Test | Owner / cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | anchor-freeze byte-identity; pre-existing at base (regeneration stage) |
| `test_expect_report_matches_committed_freeze_green` | same |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | same |
| `test_face_expect_report_matches_committed_freeze_green` | same |
| `test_cli_score_face_expect_report_end_to_end_green` | same |

No **new** expected-red from this lane: golden corpus appears free of Cf-only / padding-only names that would change published scores under the stronger predicate. Diff against committed freezes matches the pre-existing Wave C drift, not a new field from this change.

### Unexpected-red

None.

---

## 5. `git diff --stat` against base

```text
 .../scene/tests/test_eval_harness_face_metrics.py  | 107 +++++++++++++++++++++
 .../scripts/eval_harness/face_metrics.py           |  71 +++++++++++---
 2 files changed, 164 insertions(+), 14 deletions(-)
```

(Plus this report file in the report commit.)

---

## 6. Could not verify

- Corpus incidence of Cf-only / zero-width GT names on golden-150 or celebs01 (`AUDIT-07`) — not measured; no impact claim.
- Whether any frozen report field would change after a full regeneration solely due to this predicate (unlikely; no unexpected suite reds).
- End-to-end face_gate / cohort behaviour for padded names (out of owned files).

---

## 7. Cross-lane requests

| To | Request |
| --- | --- |
| **face_assignment / whoever next owns it** | Align `gt_box_name` with `face_metrics.named_box_name` rule (drop Unicode `Cf` then strip; empty → None). Until then association and face_metrics diverge on ZWSP/BOM. Prefer moving the shared body to one place to restore a truly single harness predicate. |
| **wE1 (`report.py`)** | Route single-subject cohort builder and occlusion named filter through the shared namedness predicate (strip + empty → anonymous). Whitespace-only `"   "` must not enter the single-subject cohort map. |
| **bakeoff owner (not in Wave E file map)** | `_apply_face_gate`: key matched boxes by stripped `named_box_name` / `gt_box_name`, not raw `str(name)`. Padded `" Alice "` currently fails intersection with roster `"Alice"`. |
| **face_bakeoff owner** | `any(box.name)` truthiness treats whitespace-only as named → twin universe runs; use namedness predicate. |
