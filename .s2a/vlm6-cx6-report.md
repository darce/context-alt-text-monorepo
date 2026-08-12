# VLM-6 Wave C · lane cx6 — CLI gate-prefix contract vs documentation

Lane: `cx6` · Branch: `fix/cx6` · Worktree: `~/lane-hx2`  
Base: `7812d71c832786328705a8d6ea6e1d7f41dc487b` (`integ/fx-wave`)

Commits:
sha-guard:ignore-next-block
```
cde86ae3 docs(cx6): match score-face freeze sample output to live 10/10
44f7c6fd fix(cx6): share score* gate prefixes across caption and face paths
78f88646 docs(cx6): document all score* gate prefixes + README drift test
```

Owned: `scripts/eval_harness/cli.py`, `scripts/eval_harness/README.md`  
Untouched: `report.py`, `face_metrics.py`, `promote_atomic.py`, `provenance_sha.py`,
`generate_determinism_anchor.py`, `scripts/check_lane_report_shas.py`, anchors.

Heuristics: `TEST-15`, `TEST-06`, `rg-006`, `rg-015`, `sr-001`, `AUDIT-07`.

---

## Finding 1 — VLM6-R2-F-02 — documented `scored=8/8` vs live `scored=10/10`

### Reproduction (reviewer probe)

```text
$ cd apps/prototype-description-service
$ ./.venv/bin/python -m scripts.eval_harness.cli score-face \
    --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json \
    --check-determinism \
    --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json \
    --freeze-certification
… scored=10/10 matched_faces=6 occlusion_n_eligible=1 directional_excluded=6
EXIT:0
```

Confirmed: live prints `scored=10/10`. README had `scored=8/8` (pre-HARM-05 corpus).

### Decision

**Doc bug, not code bug.** Freeze report + run-record both have 10 items
(`counts.scored=10`, `counts.total=10`). Wave B extended the face freeze;
README sample lagged.

### Fix

README line updated to match live:

```text
scored=10/10 matched_faces=6 occlusion_n_eligible=1 directional_excluded=6
```

### GREEN re-probe

Same command → `scored=10/10 … directional_excluded=6` matches README. `EXIT:0`.

---

## Finding 2 — VLM6-R2-F-03 — face/caption failed-items prefixes diverge

### Reproduction

Pre-fix face path (`cli.py` post-write integrity):

```python
_score_gate_fail(f"score-face gate failed: {failed} item(s) not scored …")
```

Caption:

```python
_score_gate_fail(f"score failed-items gate: {failed} item(s) not scored …")
```

`grep "failed-items gate"` → caption only. Face silent. (`rg-015`)

### RED (TEST-15)

Monkeypatched face failed-items to emit historical divergent prefix:

```text
EXIT MSG: score-face gate failed: 1 item(s) not scored (see failures[] in …)
HAS_SHARED_PREFIX: False
TEST-15 RED (expected): AssertionError — shared prefix missing from face failed-items message
  assertion: SCORE_GATE_PREFIX_FAILED_ITEMS in msg
  prefix: 'score failed-items gate:'
```

### Fix

Extracted module constants `SCORE_GATE_PREFIX_*` (single source). Face failed-items /
aborted-record / zero-scored now share caption prefixes; distinguishing token is a
**suffix** (`score-face:`). Face-only readback errors got a new class
`score face-report-readback gate:` (not the old overloaded `score-face gate failed:`).

### GREEN

```text
$ ./.venv/bin/python -m pytest \
    scene/tests/test_eval_harness_cli.py::test_score_face_failed_items_shares_caption_gate_prefix \
    -q -p no:randomly
.                                                                        [100%]
1 passed
```

Injected face `counts.failed=1` → message contains `score failed-items gate:` **and**
`score-face` suffix; does not start with `score-face gate failed:`.

---

## Finding 3 — VLM6-R2-F-01 — 15+ gate prefixes, README documented 10

### Enumeration (from source, not README)

`SCORE_GATE_PREFIXES` (16 after fix; was 15 pre-fix counting the divergent
`score-face gate failed:` as one class, plus freeze-cert refused / integrity set):

| Prefix | Path |
| --- | --- |
| `score schema error:` | caption |
| `score aborted-record gate:` | caption + face (shared) |
| `score zero-scored gate:` | caption + face (shared) |
| `score failed-items gate:` | caption + face (shared) |
| `score truncation gate:` | caption |
| `score manifest-mismatch gate:` | caption |
| `score manifest-drift gate:` | caption |
| `score manifest-relabel gate:` | caption |
| `score empty-rubric gate:` | caption (adoption) |
| `score must-right failures gate:` | caption (adoption) |
| `score wrong-name floor vacuity gate:` | caption (adoption) |
| `score wrong-name floor gate:` | caption (adoption) |
| `score quality-floor gate:` | caption (adoption) |
| `score category-vacuity gate:` | caption (adoption) |
| `score freeze-certification refused:` | caption |
| `score face-report-readback gate:` | face (was part of divergent `score-face gate failed:`) |

Previously undocumented (among the five Reviewer F counted): aborted-record,
zero-scored, manifest-drift, manifest-relabel, freeze-certification refused
(plus face-specific failed-items under the divergent prefix).

### RED (TEST-15)

Strip one constant from README text → drift test fails:

```text
missing: ['score manifest-drift gate:']
TEST-15 RED (expected): undocumented prefix(es) detected
  - score manifest-drift gate:
GREEN missing_real: []
GREEN: all 16 prefixes present in README
```

### Fix

1. README § "Score non-zero exit prefixes" expanded: every prefix, trigger, operator action.
2. `test_score_gate_prefixes_documented_in_readme` reads `SCORE_GATE_PREFIXES` and
   asserts each string appears in the README — durable against next-wave drift.

### GREEN

```text
$ ./.venv/bin/python -m pytest \
    scene/tests/test_eval_harness_cli.py::test_score_gate_prefixes_documented_in_readme \
    -q -p no:randomly
.                                                                        [100%]
1 passed
```

---

## Cross-lane: SCORE_PASS_MIN / null model (cx2)

**Does the eval-harness README currently repeat the `0.5^5 = 0.03125` derivation?**  
**No.** Grep of `scripts/eval_harness/README.md` finds no `0.5^5`, `0.03125`, or
coin-flip null-model wording. The n=5 floor lives only in `report.py` (cx2-owned):

```text
report.py:217: … < 0.05 (0.5^5 = 0.03125). n=2 yields 0.25 …
report.py:222: SCORE_PASS_MIN_SCORED_IMAGES = 5
```

cx6 did **not** invent replacement wording. If cx2 lands a corrected comment,
no README mirror is required today; flag only if a future README edit reintroduces it.

---

## New findings (not owned)

None filed. Adjacent observations only:

- Pre-gate hard failures (`score: --freeze-certification requires…`, argparse) are
  intentionally outside `SCORE_GATE_PREFIXES` (no report write). Already in README
  "Pre-gate hard failures" table — left as-is.
- `score gate failed for {record_path}:` is a `run` multi-record summary wrapper,
  not a class-unique integrity/adoption prefix — not in the frozenset.

---

## Full suite

```text
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
1309 passed, 4 skipped, 33 warnings in 314.35s (0:05:14)
```

Baseline: `1307 passed, 0 failed, 4 skipped`.  
Delta: **+2 tests** (F-03 shared-prefix + F-01 README drift).  
**Expected-red:** none (no other-lane scope).  
**Unexpected-red:** none.

Related subset (gate/face/freeze): `21 passed, 112 deselected`.

---

## `git diff --stat` vs `7812d71c`

```text
 .../scene/tests/test_eval_harness_cli.py           |  81 ++++++++++++++
 .../scripts/eval_harness/README.md                 |  53 +++++++--
 .../scripts/eval_harness/cli.py                    | 121 +++++++++++++++-----
 3 files changed, 211 insertions(+), 44 deletions(-)
```

---

## Could not verify

- Live CI log greps in a real pipeline (local injection only).
- Whether external scrapers hard-code the old `score-face gate failed:` string —
  if so they need to switch to `failed-items gate` / `face-report-readback gate`.
- cx2's final null-model wording (not shipped on this base yet).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **cx2** (`report.py`) | If you correct the `0.5^5` null-model comment: README does **not** currently repeat it — no cx6 mirror needed. If you add a README note later, coordinate so we don't reintroduce the bad derivation. |
| **Coordinator / log scrapers** | Prefer grepping shared class tokens (`failed-items gate`, `aborted-record gate`, `zero-scored gate`) not `score-face gate failed:` (removed). |
| **Any lane adding a score gate** | Add a `SCORE_GATE_PREFIX_*` constant + frozenset entry + README row; drift test enforces it. |
