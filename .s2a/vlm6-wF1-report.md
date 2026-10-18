# Lane wF1 — one namedness predicate, one y-missing rule

**Branch:** `fix/wf1`  
**Base:** `f406193709619d143f463cc5dfa3f316fecb7333`  
**Owned files:** `face_metrics.py`, `report.py`, `test_eval_harness_face_metrics.py`, `test_eval_harness_report.py`

## Interface notice (for wF2)

**`face_metrics.named_box_name` name, signature, and semantics are unchanged.**  
This lane only *consumes* it from `report.py` and extends `labeled_order` y-coercion. wF2 may keep importing `named_box_name` as-is.

Commits (tests → fix → report):

sha-guard:ignore-next-block
```
026c70fc test(wF1): RED coverage for labeled_order y-missing + report namedness
5ff0d997 fix(wF1): labeled_order y-coerce + report named_box_name routing
```

---

## 1. Per finding

### Task 1 — RA-04 source: `labeled_order` blank/non-numeric `y` (from wE1)

**Claim (wE1):** `labeled_order([{"name":"A","x":0.5,"y":""}])` raises `ValueError`; report boundary normalises but non-report callers do not.

#### Reproduction probe (verbatim, unfixed)

```
ERR y='' -> ValueError: could not convert string to float: ''
ERR y='  ' -> ValueError: could not convert string to float: '  '
ERR y='abc' -> ValueError: could not convert string to float: 'abc'
OK  y=None -> names=['A'] degraded=True y_missing=1
OK  y=0.3 -> names=['A'] degraded=False y_missing=0
```

Traceback site (all three bad y values):

```
File ".../scripts/eval_harness/face_metrics.py", line 434, in labeled_order
    y_val: float | None = None if y is None else float(y)
ValueError: could not convert string to float: ''
```

**Reproduced.** Not a disagreement.

#### RED capture (TEST-15)

```
FAILED test_labeled_order_blank_non_numeric_y_is_missing
  ValueError: could not convert string to float: ''
  at face_metrics.py:434  float(y)
```

#### Fix

In `labeled_order`, coerce `y` with try/`float`; on `TypeError`/`ValueError` → `None` (same missing-y branch as `y is None` → `order_degraded=True`). No third state; never invents `0.0`.

Consumer `_normalize_face_boxes_for_order` in `report.py` kept as **defense-in-depth**. Source fix makes it redundant for correctness; removing it would not change published numbers today (same missing-y semantics). Kept so report path stays stable if a future `labeled_order` regression reappears.

#### GREEN capture

```
=== Task1 GREEN ===
y='' -> names=['A'] degraded=True y_missing=1
y='  ' -> names=['A'] degraded=True y_missing=1
y='abc' -> names=['A'] degraded=True y_missing=1
PASSED test_labeled_order_blank_non_numeric_y_is_missing
PASSED test_empty_string_y_normalized_before_labeled_order_in_report  # report path unchanged
```

---

### Task 2 — report named filters through `named_box_name` (from wE4)

**Claim (wE4):** single-subject cohort builder and occlusion named filter still use raw name truthiness; whitespace-only `"   "` can enter the cohort map.

#### Sites audited in `report.py`

| Site | Pre-fix | Action |
|------|----------|--------|
| `_build_single_subject_cohort_by_media` | `if name:` raw truthiness | **Changed** → `named_box_name` |
| `build_real_occlusion_pairs` named filter | raw truthiness on box name | **Changed** → `named_box_name` |
| `build_real_occlusion_pairs` `true_name=` | `str(raw name)` | **Changed** → normalised name from predicate |
| `_collect_identity_names_for_public_scrub` face_boxes | `box.get("name")` truthiness | **Changed** → `named_box_name` |
| `_collect_identity_names_for_public_scrub` identities | `ident.get("name")` truthiness | **Changed** → `named_box_name` |
| missed_gt counting (`gt_box_name`) | already a predicate | **Left** — mirrors association (`face_assignment`); not raw truthiness |
| `_identity_names_from_rows` wire validation | requires non-empty name or raises | **Left** — predicted-row contract, not GT namedness filter |

#### Reproduction probe (verbatim, unfixed)

```
cohort map: {1: 'cohort-a', 2: 'cohort-b', 3: 'cohort-c'}
media 1: named_box_name=None in_cohort=True raw_truthy=True
  DIVERGENCE media 1   # name='   '
media 2: named_box_name='Alice' in_cohort=True  # name='\u200bAlice'
occlusion raw truthiness:
  name='\u200b' raw_truthy=True named_box_name=None
  name='   ' raw_truthy=True named_box_name=None
  name='\u200bAlice' raw_truthy=True named_box_name='Alice'
```

**Reproduced** for whitespace / format-only. `"\u200bAlice"` already agreed on *is-named* but raw `true_name` kept the ZWSP; post-fix uses stripped `"Alice"`.

#### RED capture (TEST-15)

```
FAILED test_single_subject_cohort_namedness_agrees_with_face_metrics
  AssertionError: media_id=1 name='   ': cohort=True named_box_name=None

FAILED test_occlusion_named_filter_agrees_with_face_metrics
  AssertionError: occlusion true_names=['   ', '\u200bAlice', 'Bob', '\u200b']
               vs named_box_name path=['Alice', 'Bob']
```

#### Fix

Import `named_box_name`; route every GT-box / identity-row namedness decision listed above through it. Tests assert **agreement** with `face_metrics` (TEST-06), not hardcoded sets.

#### GREEN capture

```
=== Task2 GREEN cohort ===
name='   ' cohort=False pred=False agree=True
name='\u200bAlice' cohort=True pred=True agree=True
name='Alice' cohort=True pred=True agree=True
name='\u200b' cohort=False pred=False agree=True
PASSED test_single_subject_cohort_namedness_agrees_with_face_metrics
PASSED test_occlusion_named_filter_agrees_with_face_metrics
```

---

## 2. Disagreements

**None.** Both cross-lane claims reproduced on base code before any fix (DBG-10).

---

## 3. New findings (not owned)

| Finding | Severity | Notes |
|---------|----------|-------|
| `report.py` missed_gt still uses `gt_box_name` (strip-only) | low residual | Intentional association parity; ZWSP-only boxes still diverge from `named_box_name` until face_assignment aligns (wE4 cross-lane residual). |
| `_identity_names_from_rows` still truthy-checks wire names | low | Whitespace-only predicted name passes validation (`"   "` is truthy). Different contract (positional wire rows). Out of this task’s cohort/occlusion scope. |
| wF2 surfaces (`face_assignment` / bakeoff / face_bakeoff) | known | Still raw namedness on those files — not owned here. |

---

## 4. Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1375 passed, 4 skipped` (196s)

### Expected-red (baseline anchor freezes — not ours; do not regenerate)

Same five as base `f4061937` (`5 failed, 1372 passed` + 3 new wF1 greens = 1375):

1. `test_generator_regenerates_byte_identical_committed_anchor`
2. `test_expect_report_matches_committed_freeze_green`
3. `test_face_generator_regenerates_byte_identical_committed_anchor`
4. `test_face_expect_report_matches_committed_freeze_green`
5. `test_cli_score_face_expect_report_end_to_end_green`

No *new* test names failed. This lane did not add freeze reds beyond the pre-existing set. If regeneration later rewrites face freezes, the fields most likely to shift from wF1 (only on corpora with padded/blank/format-control names) are:

- `slices.demographic` / single-subject cohort membership (whitespace-only no longer counted as named)
- `slices.occlusion.*.` pair counts / `true_name` strings (normalised names; format-only boxes excluded)

Golden bakeoff-results corpus at baseline already red for other Wave E reasons; incidence of blank/ZWSP names on that corpus was **not** measured here (`AUDIT-07`).

### Unexpected-red

**None.**

---

## 5. `git diff --stat` against base

```
 .../scene/tests/test_eval_harness_face_metrics.py  | 21 ++++++
 .../scene/tests/test_eval_harness_report.py        | 82 ++++++++++++++++++++++
 .../scripts/eval_harness/face_metrics.py           | 13 +++-
 .../scripts/eval_harness/report.py                 | 41 +++++++----
 4 files changed, 139 insertions(+), 18 deletions(-)
```

(plus this report file on the report commit)

---

## 6. Could not verify

- Whether any committed freeze corpus entry actually carries whitespace-only or Cf-only box names (would change published face-report bytes after regeneration). Mechanism confirmed; incidence not measured (`AUDIT-07`).
- Live MCP handoff write path (`make context` has no rule in this worktree layout); work done on branch isolation only.

---

## 7. Cross-lane requests

| To | Request |
|----|---------|
| **wF2** | **`named_box_name` semantics: UNCHANGED.** Keep importing `face_metrics.named_box_name` (same name/signature/rule: drop Cf → strip → empty→None). `labeled_order` now accepts blank/non-numeric `y` as missing — safe for any wF2 caller of `labeled_order` without report’s normaliser. |
| **face_assignment owner** | Align `gt_box_name` with `named_box_name` (Cf drop) so report missed_gt (`gt_box_name`) and face_metrics namedness converge on ZWSP-only boxes. Prefer one shared body. |
| **wF3 / freeze regen** | Do not treat wF1 as introducing new freeze test names; only possible field-level churn is occlusion `true_name` normalisation + demographic single-subject cohort exclusion of whitespace/format-only boxes if such GT exists. |
| **None for bakeoff/face_bakeoff** | Already owned by wF2 per wave brief. |
