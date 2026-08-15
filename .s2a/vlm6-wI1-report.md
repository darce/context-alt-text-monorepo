# Lane wI1 — regenerate the CAPTION determinism freeze

**Branch:** `fix/wi1` · **Base:** `3796f3501abbef21ef257a3a0b3f73f3fb5167da`  
**Owned files:** caption report JSON/MD, `test_eval_harness_determinism_anchor.py` digests/constants only  
**Not touched:** any `*face*` artifact, `test_eval_harness_face_determinism_anchor.py`, **any file under `scripts/`**

---

## Task 1 — regenerate + contract verification

### Regeneration

```text
write_anchor(manifest_path=golden.json, pin mode, fixture_revision=0*40,
             canonical_timestamp=2026-08-11T00:00:00Z)
→ man + run byte-identical to committed wG3 freeze (no rewrite of man/run)
→ report JSON/MD differ (only those installed under bakeoff-results/)
```

Man/run digests unchanged (wG3 pins hold). Only report artifacts rewritten from live scorer on the wG3 38-entry corpus.

### Contract verification table (Task 1.1 — wG3 predicted vs regenerated)

| field path | wG3 predicted | regenerated actual | match? |
| --- | --- | --- | --- |
| `counts.scored` / `total` | 38 / 38 | 38 / 38 | **yes** |
| `faces.detection.tp` | 53 | 53 | **yes** |
| `faces.detection.fp` / `fn` | unchanged 3 / 6 | 3 / 6 | **yes** |
| `faces.detection.precision` | 0.9464… | 0.9464285714285714 | **yes** |
| `faces.detection.recall` | 0.8983… | 0.8983050847457628 | **yes** |
| `faces.identity_ordering.order_unknown_excluded` | 38 | 38 | **yes** |
| `faces.identity_ordering.labeled_y_missing_images` | **1** (new key) | **1** | **yes** |
| `faces.identity_ordering.labeled_y_missing_paths` | `["mock_images/y-missing-mixed-order.jpg"]` | same | **yes** |
| `faces.identity_ordering.degraded_images` / `positional_images` | 0 / 0 | 0 / 0 | **yes** |
| `faces.identification.evaluated_images` | 38 | 38 | **yes** |
| `faces.identification.precision` | slight ↑ | 0.8857142857142857 (was 0.8787…) | **yes** |
| `faces.identification.recall` | slight ↑ | 0.8157894736842105 (was 0.8055…) | **yes** |
| `faces.identification.macro_recall` | slight ↑ | 0.8980952380952381 (was 0.8966…) | **yes** |
| `faces.identification.per_identity["Bea Burke"].tp` | +1 → 2 | 2 | **yes** |
| `faces.identification.per_identity["Caitlin Weaver"].tp` | +1 → 12 | 12 | **yes** |
| `verdict.wrong_name_rate` | 0.1053 (4/38) | 0.1053 | **yes** |
| `provenance.coverage_gaps.*.total` | 38 | 38 | **yes** |
| `provenance.coverage_gaps.face_boxes.populated` | 1 | 1 | **yes** |
| `provenance.coverage_gaps.face_boxes.pi_zero` | false | false | **yes** |
| `provenance.corpus_traps` | 1-entry trap inventory | present (media 39) | **yes** |
| `provenance.manifest_sha256` prefix | `sha256:7462d325…` | `sha256:7462d3259f068aa1…` | **yes** |
| **Keys must appear** `labeled_y_missing_*` | absent → present | **present** | **yes** |

**Contract mismatches: none.** Every wG3 prediction materialised. No scorer edit required or performed (`sr-001`).

### Full accounted-for diff (Task 1.3)

52 leaf JSON diffs old→new. Every one accounted for:

| Diff | Cause |
| --- | --- |
| `counts.scored/total` 37→38 | **wG3** media 39 trap |
| `corpus.manifest_entries` 37→38 | **wG3** |
| `caption.gated_score_scored` 34→35 | **wG3** trap contributes gated row |
| `faces.detection.tp` 51→53; P/R shift | **wG3** trap adds 2 named faces, seed_index 37 no FN/FP deviation |
| `faces.detection.fp/fn` unchanged | **wG3** predicted |
| `identity_ordering.labeled_y_missing_*` **added** (1 + path) | **wd-A/wE1 publish** + **wG3** corpus makes counter non-zero; freeze predated keys |
| `identity_ordering.order_unknown_excluded` 37→38 | **wG3** |
| `identification.evaluated_images` 37→38; P/R/macro_recall ↑ | **wG3** |
| `per_identity` Bea tp 1→2; Caitlin tp 11→12 / recall 0.786→0.8 | **wG3** |
| `positional.excluded_images` +trap path | **wG3** (trap still order-unknown for L→R) |
| `per_image[37]` added (media 39) | **wG3** |
| `placement.images_scored` 37→38 | **wG3** |
| `provenance.corpus_traps` **added** | **wG3** EVAL-03 trap inventory |
| `provenance.note` + freeze-corpus sentence | **wG3** generator note |
| `provenance.manifest_sha256` / `score_manifest_sha256` golden→freeze man | **wG3** |
| `coverage_gaps` totals 37→38; face_boxes 0→1, pi_zero false | **wG3** |
| `metric_backing_refusals.face_boxes` **removed** | **wG3 residual 2** (1/38 not vacuous) |
| other refusals reason 0/37→0/38 | **wG3** |
| `provenance.quality_floor_caveat` **added** | **wE1** pre-existing publish (stale freeze omitted it) |
| `quality.mean_fkre/repetition/tag_coverage` | **wG3** media 39 quality row in means |
| `strata` easy n 16→17; faces domain n 19→20 (+excluded) | **wG3** trap strata |
| `verdict.wrong_name_rate` 0.1081→0.1053 + reasons scored=38 | **wG3** |

**MD mirror:** same causal set (images 38/38, detection line, identification lines, y-missing warning, coverage gaps 1/38, face_boxes refusal dropped, quality_floor_caveat line, quality means).

**No unaccounted field movement.** No value moved for a reason nobody owned.

---

## Task 2 — pin update list

| Artifact | Old digest | New digest |
| --- | --- | --- |
| man (unchanged) | `2eae07326bd5a63834fe838de9fbc4e46ab71599ed213c6eacb1fd66757c57b7` | same |
| run (unchanged) | `b5c3040aad98939b71c2242ed2cdbd8efcdb4a51bd65ec8f5f45e8a1a70e58cf` | same |
| report JSON | `c2fcfa3407ff62254556201cc35dfcb25eb4a46105e0764fe4b25a347423b0e6` | `990e15178f9e0b2450d1f14099ea466e7dfad0c827897dc56862771279ce1394` |
| report MD | `dc7bf05496e37883bbe3e4cdf336f63a4e5bd489ed14aaf7bfcf439e04e14f3b` | `7c0e4ae779df28765f55f90e20e0dadc1702bcb4a1978e0a0b5b315336b281f9` |

Pins updated only after Task 1 field-by-field verification. No assertion weakened, no skip/xfail, no tolerance widen (`sr-001`).

---

## Task 3 — freeze red-on-mutation (TEST-15)

**Baseline after Task 2:** `write_anchor` report JSON/MD **byte-identical** to committed freeze (digest `sha256:990e1517…`). Caption freeze tests green.

### Mutation transcript 1 — `labeled_y_missing_images`

```text
=== MUTATION TRANSCRIPT: labeled_y_missing_images ← strip order_degraded at labeled_order() ===
setup: source-aggregation mutation (in-process; scripts/ untouched)
  [RED] faces.identity_ordering.labeled_y_missing_images: freeze=1  mutant=0
  [RED] faces.identity_ordering.labeled_y_missing_paths: freeze=['mock_images/y-missing-mixed-order.jpg']  mutant=[]
  regenerated report JSON == committed freeze? False
  FREEZE GATE: RED (good — byte-identity / ANCHOR_MISMATCH)
  mutant digest: 868bbe3b1412f0b29a2fa40d4358becba485e89fb2a7fd01f450c42e1b47c123
  freeze digest: 990e15178f9e0b2450d1f14099ea466e7dfad0c827897dc56862771279ce1394
```

### Mutation transcript 2 — `order_unknown_excluded`

```text
=== MUTATION TRANSCRIPT: order_unknown_excluded ← always labeled_order_known ===
setup: source-aggregation mutation (in-process; scripts/ untouched)
  [RED] faces.identity_ordering.order_unknown_excluded: freeze=38  mutant=0
  regenerated report JSON == committed freeze? False
  FREEZE GATE: RED (good — byte-identity / ANCHOR_MISMATCH)
  mutant digest: a7b19659d4b6a5424fcd111c43b3eca51c3be34a8b3a6ef9decb1b7114795b0f
  freeze digest: 990e15178f9e0b2450d1f14099ea466e7dfad0c827897dc56862771279ce1394
```

### Mutation transcript 3a — `identification.evaluated_images`

```text
=== MUTATION TRANSCRIPT: identification.evaluated_images ← identification_pr excludes every image ===
setup: source-aggregation mutation (in-process; scripts/ untouched)
  [RED] faces.identification.evaluated_images: freeze=38  mutant=0
  [RED] faces.identification.precision: freeze=0.8857142857142857  mutant=None
  [RED] faces.identification.recall: freeze=0.8157894736842105  mutant=None
  regenerated report JSON == committed freeze? False
  FREEZE GATE: RED (good — byte-identity / ANCHOR_MISMATCH)
  mutant digest: 199426cc2640694cb31d624e8e6131445d0191176a18ca8372a55ecc614984f4
  freeze digest: 990e15178f9e0b2450d1f14099ea466e7dfad0c827897dc56862771279ce1394
```

### Mutation transcript 3b — identification P/R/macro/`per_identity` tp

```text
=== MUTATION TRANSCRIPT: identification per_identity/P/R/macro ← identification_pr constant-zero ===
setup: source-aggregation mutation (in-process; scripts/ untouched)
  [RED] faces.identification.precision: freeze=0.8857142857142857  mutant=None
  [RED] faces.identification.recall: freeze=0.8157894736842105  mutant=None
  [RED] faces.identification.macro_recall: freeze=0.8980952380952381  mutant=None
  [still-GREEN] faces.identification.evaluated_images: freeze=38  mutant=38  # (pinned by 3a)
  [RED] faces.identification.per_identity.Bea Burke.tp: freeze=2  mutant='<ABSENT>'
  [RED] faces.identification.per_identity.Caitlin Weaver.tp: freeze=12  mutant='<ABSENT>'
  regenerated report JSON == committed freeze? False
  FREEZE GATE: RED (good — byte-identity / ANCHOR_MISMATCH)
  mutant digest: 697f320942d4dca0349f626429f4e93b8dd7b955d19c81f28c744ee32f8e8c6f
  freeze digest: 990e15178f9e0b2450d1f14099ea466e7dfad0c827897dc56862771279ce1394
```

**All required counters flip the freeze red under source-aggregation mutation.** None left unpinned.

---

## Per-finding summary

### Finding — caption freeze stale vs wG3 corpus + pre-existing publish fields

**Reproduction probe (pre-regen):**

<!-- sha-guard:ignore-next-block -->
```text
man match True
run match True
report_json match False
report_md match False
old report_json digest c2fcfa3407ff6225…
live labeled_y_missing_images=1  (committed: key ABSENT)
live counts.scored=38              (committed: 37)
```

**RED capture (baseline suite):**

```text
FAILED test_generator_regenerates_byte_identical_committed_anchor
FAILED test_expect_report_matches_committed_freeze_green
# + 3 face freezes (wI2, not owned)
5 failed, 1409 passed, 4 skipped
```

**Fix:** regenerate caption report JSON/MD via committed `write_anchor`; update report digest pins only after field-by-field contract check. No scoring-code change.

**GREEN capture:**

```text
pytest scene/tests/test_eval_harness_determinism_anchor.py -q -p no:randomly
19 passed

full suite: 3 failed, 1411 passed, 4 skipped
# only the three face freezes remain (wI2)
```

---

## Disagreements

**None.** Checked each wG3 claim:

1. Live score on extended man+run emits `labeled_y_missing_images=1` with trap path — confirmed.
2. Committed pre-regen freeze omitted the keys entirely — confirmed.
3. All aggregate shifts in wG3 table match regenerated values exactly — confirmed.
4. `metric_backing_refusals.face_boxes` drops (1/38 not vacuous) — confirmed (wG3 residual 2).
5. Man+run unchanged under regen — confirmed (digests identical).

---

## New findings (not owned)

1. **Face freeze still stale (wI2)** — three reds remain; detection now includes `geometry_incomplete_gt` / `association_*` (wH1) plus prior wG1/wG2/wF4 drift. Not touched.
2. **`Makefile` `eval-anchor-check` still points caption leg at golden** (wH2 residual) — docs fixed; make target not owned here.

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `3 failed, 1411 passed, 4 skipped`  
(Base: `5 failed, 1409 passed, 4 skipped` — caption freezes −2 fail / +2 pass.)

### Expected-red

| Test | Cause / owner |
| --- | --- |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | **wI2** face report freeze |
| `test_face_expect_report_matches_committed_freeze_green` | **wI2** |
| `test_cli_score_face_expect_report_end_to_end_green` | **wI2** |

### Unexpected-red

**None.**

Caption freezes now **green**:
- `test_generator_regenerates_byte_identical_committed_anchor`
- `test_expect_report_matches_committed_freeze_green`

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
base 3796f3501abbef21ef257a3a0b3f73f3fb5167da
 .../tests/test_eval_harness_determinism_anchor.py  |  24 ++--
 ...S2A-determinism-anchor-run-20260811-report.json | 143 ++++++++++++++-------
 .../S2A-determinism-anchor-run-20260811-report.md  |  55 ++++----
 3 files changed, 136 insertions(+), 86 deletions(-)
 # (+ this report under .s2a/)
```

**Explicit:** zero files under `apps/prototype-description-service/scripts/` changed (`git diff --stat … -- scripts/` empty). Scoring code frozen.

---

## Could not verify

- Production prevalence of missing-y named boxes (no network / no real corpus) — freeze trap is synthetic.
- Face freeze post-regen green (wI2 owns).
- Cross-process CLI `score --check-determinism --expect-report` operator path after regen (unit/cross-process harness tests cover the same gate; full CLI smoke not re-run beyond suite).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **wI2 (face regen)** | Proceed independently; caption side is done. Do not touch caption report digests. |
| **Makefile / ops (optional)** | Swap `eval-anchor-check` caption `--manifest` to bakeoff-results caption man (wH2 residual). |

---

## Acceptance checklist

- [x] All caption freeze tests green
- [x] Complete accounted-for diff of regenerated artifacts
- [x] One red-on-mutation transcript per observable counter
- [x] No `scripts/` edits
- [x] No scorer/test weakening
- [x] Face freezes left for wI2 (3 expected-red)
