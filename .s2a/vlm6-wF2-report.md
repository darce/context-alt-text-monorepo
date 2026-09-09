# VLM-6 Wave F — lane wF2 report

**Lane:** wF2 — namedness in the assignment and gate path  
**Branch:** `fix/wf2`  
**Base:** `f406193709619d143f463cc5dfa3f316fecb7333`  
**Owned files:** `face_assignment.py`, `bakeoff.py`, `face_bakeoff.py` + tests  

---

## 1. Per finding

### Finding F1 — `gt_box_name` diverges from `named_box_name` (wE4 residual / RA-03)

**Claim (wE4):** `face_assignment.gt_box_name` is strip-only; association and face_metrics disagree on ZWSP/BOM.

#### Reproduction probe (verbatim, pre-fix)

```text
BOM          raw='\ufeffAlice'        gt_box_name='\ufeffAlice' named_box_name='Alice'      agree=False
ZWSP         raw='\u200bAlice'        gt_box_name='\u200bAlice' named_box_name='Alice'      agree=False
padded       raw=' Alice '            gt_box_name='Alice'      named_box_name='Alice'      agree=True
ws-only      raw='   '                gt_box_name=None         named_box_name=None         agree=True
empty        raw=''                   gt_box_name=None         named_box_name=None         agree=True
None         raw=None                 gt_box_name=None         named_box_name=None         agree=True
normal       raw='Alice'              gt_box_name='Alice'      named_box_name='Alice'      agree=True
ZWSP-only    raw='\u200b'             gt_box_name='\u200b'     named_box_name=None         agree=False
BOM-only     raw='\ufeff'             gt_box_name='\ufeff'     named_box_name=None         agree=False
ZWSP-mid     raw='A\u200bB'           gt_box_name='A\u200bB'   named_box_name='AB'         agree=False
```

**Reproduced.** Strip-only vs Cf-drop+strip diverges on BOM/ZWSP (named-but-different-key) and Cf-only (named vs anonymous).

#### RED capture (verbatim)

```text
FAILED scene/tests/test_eval_harness_face_assignment.py::test_gt_box_name_agrees_with_named_box_name_on_adversarial_names
E       AssertionError: gt_box_name must agree with face_metrics.named_box_name (single harness predicate); diverged on:
E           raw='\ufeffAlice' gt_box_name='\ufeffAlice' named_box_name='Alice'
E           raw='\u200bAlice' gt_box_name='\u200bAlice' named_box_name='Alice'
E           raw='A\u200bB' gt_box_name='A\u200bB' named_box_name='AB'
E           raw='\u200b' gt_box_name='\u200b' named_box_name=None
E           raw='\ufeff' gt_box_name='\ufeff' named_box_name=None
```

#### Fix

`gt_box_name` **delegates** to `face_metrics.named_box_name` (import + return). One shared body — not a second aligned copy (wE4 preference). Hard interface: reuse, do not reimplement.

#### GREEN capture (verbatim)

```text
BOM          gt='Alice'      named='Alice'      agree=True
ZWSP         gt='Alice'      named='Alice'      agree=True
padded       gt='Alice'      named='Alice'      agree=True
ws-only      gt=None         named=None         agree=True
ZWSP-only    gt=None         named=None         agree=True
normal       gt='Alice'      named='Alice'      agree=True
PASSED test_gt_box_name_agrees_with_named_box_name_on_adversarial_names
```

---

### Finding F2 — `_apply_face_gate` keys on raw `str(name)` (wE4 residual)

**Claim (wE4):** Padded `" Alice "` fails intersection with roster `"Alice"` → gate under-counts.

#### Reproduction probe (verbatim, pre-fix)

```text
padded face_box name vs roster Alice:
  stamp= {'eligible_names': [], 'suppressed_names': ['Alice']}
  people_present= someone
exact face_box name Alice:
  stamp= {'eligible_names': ['Alice'], 'suppressed_names': []}
  people_present= Alice, on the left
matched keys (raw)= [' Alice ']
in_context intersection with matched using raw: []
```

**Reproduced.** Silent under-count: eligible empty when box is padded.

#### Inverse hazard (roster collision under normalize)

Can the roster hold a pair that normalizes to one key (e.g. `"Alice"` and `"Alice "`)?

- **Golden corpora (incidence):** scan of 32 JSON fixtures/manifests under `scene/tests/seed`, `scripts/eval_harness/tests/fixtures`, `docs/tasks/vlm` — **0** padded / Cf / ws-only name fields among 270 name-like strings. No colliding pair in published data.
- **Mechanism:** if such a pair is ever passed as `known_names`, silent merge would change identity counts. Fix **detects and raises** `ValueError` with message `face_gate roster name collision after normalize: ...`.

#### RED capture (verbatim)

```text
FAILED test_apply_face_gate_keys_on_normalized_name_not_raw_str
E       AssertionError: padded face-box name must match roster Alice; got stamp={'eligible_names': [], 'suppressed_names': ['Alice']}

FAILED test_apply_face_gate_keys_bom_zwsp_name_to_roster
E       AssertionError: {'eligible_names': [], 'suppressed_names': ['Alice']}

FAILED test_apply_face_gate_detects_roster_normalization_collision
E       Failed: DID NOT RAISE ValueError
```

#### Fix

- Key matched boxes by `named_box_name(box)` (not `str(name)`).
- Intersect `in_context` roster forms via the same normalization.
- `_assert_no_roster_norm_collisions(known_names)` before intersect — fail closed on merge.

#### GREEN capture (verbatim)

```text
=== Task2 face gate padded ===
({'caption': 'Alice is here.', 'people_present': 'Alice, on the left', 'description': 'Alice stands.'}, {'eligible_names': ['Alice'], 'suppressed_names': []})

collision: raised ValueError("face_gate roster name collision after normalize: 'Alice' and 'Alice ' both normalize to 'Alice'")

PASSED test_apply_face_gate_keys_on_normalized_name_not_raw_str
PASSED test_apply_face_gate_keys_bom_zwsp_name_to_roster
PASSED test_apply_face_gate_detects_roster_normalization_collision
```

---

### Finding F3 — `face_bakeoff` `any(box.name)` truthiness (wE4 residual)

**Claim (wE4):** Whitespace-only name is truthy → twin-universe run for corpora with no actually-named boxes.

#### Reproduction probe (verbatim, pre-fix)

```text
ws-only any(box.name)= True
real     any(box.name)= True
empty    any(box.name)= False
zwsp     any(box.name)= True
ws-only named any= False
real     named any= True
zwsp     named any= False
```

**Reproduced.** `any(box.name)` opens twin pass for `"   "` and `"\u200b"`; namedness predicate does not.

#### RED capture (verbatim)

```text
FAILED test_twin_pass_skips_whitespace_and_cf_only_names_as_anonymous
E           AssertionError: whitespace-only: detector was invoked (truthiness gate leak)
E           assert 1 == 0
```

#### Fix

Replace `any(box.name for box in entry.face_boxes)` with `any(named_box_name(box) for box in entry.face_boxes)`.

#### What changes about which runs execute (control-flow blast radius)

| Entry face_boxes names | Pre-fix twin pass | Post-fix twin pass |
|---|---|---|
| at least one real name (`"Alice"`) | runs | runs (unchanged) |
| only `None` / `""` | skipped | skipped (unchanged) |
| only whitespace (`"   "`) | **runs** (bug) | **skipped** |
| only Cf-only (`"\u200b"`, `"\ufeff"`) | **runs** (bug) | **skipped** |
| mix of anonymous + real | runs | runs (unchanged) |

This alters **control flow** (which entries enter detect→cache→twin render), not merely a published number. On golden corpora: **no incidence** of whitespace/Cf-only names → no twin-pass pair count change today. Hazard closed for future/adversarial manifests.

#### GREEN capture (verbatim)

```text
PASSED test_twin_pass_skips_whitespace_and_cf_only_names_as_anonymous
```

---

## 2. Disagreements

**None.** All three wE4 cross-lane claims reproduced on current code before fix (DBG-10). No counter-evidence.

---

## 3. New findings (not owned)

| ID | Surface | Note |
|---|---|---|
| NF-1 | `face_metrics.named_box_name` docstring | Still says association uses strip-only `gt_box_name` — stale after this lane. wF1 owns the file; suggest one-line docstring update. |
| NF-2 | `_ablate_names` in bakeoff | Still matches raw roster strings in context text (word-boundary regex). A context that only contains the unpadded form while `known_names` only has a padded form would still miss ablation. Separate from gate intersection; not in scope. Golden incidence = 0. |

---

## 4. Full suite

**Command:**

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result line:** `5 failed, 1377 passed, 4 skipped, 33 warnings in 197.20s`

Baseline at base commit: `5 failed, 1372 passed, 4 skipped`.  
Delta: **+5 passed** (new tests); failure count unchanged.

### Expected-red (not owned — anchor-freeze byte-identity; regeneration stage)

1. `test_generator_regenerates_byte_identical_committed_anchor`
2. `test_expect_report_matches_committed_freeze_green`
3. `test_face_generator_regenerates_byte_identical_committed_anchor`
4. `test_face_expect_report_matches_committed_freeze_green`
5. `test_cli_score_face_expect_report_end_to_end_green`

No new fields published by this lane; freeze reds are the same five baseline reds. **Do not regenerate** `docs/tasks/vlm/bakeoff-results/`.

### Unexpected-red

**None.**

---

## 5. `git diff --stat` against base

```text
 .../tests/test_eval_harness_face_assignment.py     | 43 ++++++++++++
 .../scene/tests/test_eval_harness_face_bakeoff.py  | 78 ++++++++++++++++++++++
 .../scene/tests/test_eval_harness_pipeline.py      | 49 ++++++++++++++
 .../scripts/eval_harness/bakeoff.py                | 73 +++++++++++++++++---
 .../scripts/eval_harness/face_assignment.py        | 19 +++---
 .../scripts/eval_harness/face_bakeoff.py           |  6 +-
 6 files changed, 247 insertions(+), 21 deletions(-)
```

(Plus this report under `.s2a/vlm6-wF2-report.md`.)

---

## 6. Could not verify

- **Live concurrent state of `face_metrics.named_box_name` under wF1:** imported and used the base-commit contract (Cf drop + strip → empty = `None`). If wF1 later changes the predicate semantics, `gt_box_name` / gate / twin eligibility follow automatically via the shared import — intentional.
- **Whether any non-scanned operator-local manifests** outside the three trees above carry padded names. Incidence measured only on repo-scanned goldens (AUDIT-07: mechanism confirmed; golden incidence = 0).

---

## 7. Cross-lane requests

| To | Request |
|---|---|
| **wF1 (`face_metrics.py`)** | Optional docstring cleanup on `named_box_name`: remove the "Association still uses strip-only `gt_box_name`" residual note — association now delegates. No behaviour change. |
| **Regeneration stage** | No new published field from wF2. Keep the five baseline anchor-freeze reds; do not attribute them to namedness. Golden incidence of padded/Cf names = 0 → these fixes do **not** change currently-published gate/association numbers; they close latent hazards only (AUDIT-07). |

---

## Incidence statement (AUDIT-07)

| | Mechanism | Incidence on golden corpora |
|---|---|---|
| F1 association namedness | Confirmed diverge pre-fix; fixed by delegate | **0** ZWSP/BOM/padded names in scanned goldens → published association numbers unchanged |
| F2 face-gate intersection | Confirmed silent miss pre-fix; fixed by norm keys + collision raise | **0** padded box/roster pairs → published gate eligible counts unchanged |
| F3 twin eligibility | Confirmed control-flow leak pre-fix; fixed by predicate | **0** whitespace/Cf-only-only entries → twin-pass execution set unchanged on goldens |

**Summary:** mechanism confirmed for all three; incidence on current published corpora is zero. Fixes close latent silent-degrade hazards only.
