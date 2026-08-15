# Lane wG3 — the caption corpus is still structurally blind

**Branch:** `fix/wg3` · **Base:** `cc1da6219d2407dca6c676d6e6583635bcdc9672`  
**Owned files:** caption anchor man/run JSON, `generate_determinism_anchor.py`, `test_eval_harness_determinism_anchor.py`  
**Not touched:** `golden.json` (shared 37-entry seed), report artifacts, face corpus, `report.py` / `manifest.py` / face generators.

---

## Finding 1 — Caption freeze blind on `labeled_y_missing_images` (wF4 residual 2 / VLM6-R2-G-01)

### Reproduction probe (Task 1, pre-extension — golden seed, verbatim)

```text
=== PROBE 1: caption face_boxes inventory ===
n_entries=37 with_face_boxes=0

=== PROBE 2: committed caption report identity_ordering ===
{
  "degraded_images": 0,
  "degraded_paths": [],
  "order_unknown_excluded": 37,
  "positional_images": 0
}
labeled_y_missing in report? False

=== PROBE 2b: LIVE score identity_ordering ===
{
  "positional_images": 0,
  "degraded_images": 0,
  "degraded_paths": [],
  "order_unknown_excluded": 37,
  "labeled_y_missing_images": 0,
  "labeled_y_missing_paths": []
}

=== PROBE 3: why order_unknown_excluded=37 ===
entries with empty/absent face_boxes=37
These exclude from positional because labeled_order_known=False (no L→R GT), not because order_degraded

=== PROBE 5 (decisive): mutate labeled_order to strip order_degraded ===
live labeled_y_missing_images=0
blind_mutation labeled_y_missing_images=0
equal? True
BLINDNESS CONFIRMED
```

**Interpretation:** `order_unknown_excluded: 37` counts **absence of face_boxes** (no L→R GT → exclude), not GT-side `order_degraded`. The counter that should detect missing-y named boxes (`labeled_y_missing_images`) is structural 0 because no caption entry carries `face_boxes` at all. Same class of blindness wF4 proved on the face side.

### RED capture (pre-extension control — mutation invisible)

```text
live labeled_y_missing_images=0
blind_mutation labeled_y_missing_images=0
equal? True
# Freeze cannot see a constant-0 / order_degraded-strip regression
```

### Fix

1. **Do not bend `golden.json`.** Shared 37-entry seed stays `0/37 face_boxes` (other tests / face_metrics π=0 pins depend on it). Freeze corpus is a **dedicated caption anchor manifest** under bakeoff-results (owned path; wF4 face-manifest precedent, adapted).
2. **Media 39** `mock_images/y-missing-mixed-order.jpg`: named **Caitlin Weaver** with `y=0.1` + named **Bea Burke** **missing `y`** (same `x=0.5`). Mixed shape — not all-missing. Roster names only. Additive `media_id=39` (no renumber of 1–38).
3. **`build_caption_anchor_manifest(base)`** appends the trap to golden entries; **`write_anchor`** promotes man+run+reports from that extended corpus. Generator default seed remains golden; freeze man is the output.
4. **Man + run regenerated in lockstep**; **report freezes not rewritten** (regen stage owns them).
5. **`provenance.corpus_traps`** on the run-record (GoldenManifest `extra=forbid` — same place as wF4; no model change).
6. Digest pins updated for **man + run only**. Report digests unchanged.

**Deliberate divergences from wF4:**
| Aspect | wF4 (face) | wG3 (caption) |
| --- | --- | --- |
| Base corpus | Fully synthetic face man | golden.json seed + additive trap |
| Seed file | N/A (built in code) | golden.json **untouched** |
| Trap media_id | 11 | 39 |
| Run items | face detections (dim=8) | seeded describe + unpositioned identities (unchanged shape) |
| Report ownership | face reports not rewritten | caption reports not rewritten |

### GREEN capture (post-extension — mutation now visible)

```text
=== ACCEPTANCE GREEN (extended caption corpus) ===
live labeled_y_missing_images=1 blind_mutation=0 discriminates=True
live paths=['mock_images/y-missing-mixed-order.jpg']
order_unknown_excluded=38 positional=0 degraded=0
man entries=38 run items=38
manifest_sha256=7462d3259f068aa187cd5f2dc3cd934eaa3b4b2a71e441f9e362f7e6cbfc9fd3
```

```text
pytest ...::test_labeled_y_missing_constant_zero_goes_red_on_extended_caption_corpus PASSED
pytest ...::test_caption_anchor_corpus_includes_mixed_y_order_degraded_trap PASSED
pytest ...::test_corpus_traps_disclose_deliberate_caption_trap_media PASSED
```

**TEST-15 bar met:** the Task-1 constant-0 mutation that **passed** against golden (live=0==blind=0) now **fails** (diverges) against the extended freeze man (live=1, blind=0).

**Separating pre-existing report staleness from the counter proof:** acceptance scores **live vs mutated aggregation** on the extended man+run only. It does **not** compare to the committed report digest. Pre-existing freeze reds (report byte-identity) remain; the new difference is specifically `labeled_y_missing_images` 1→0 under mutation.

---

## Finding 2 — Trap sampling-frame disclosure (EVAL-03 / VLM6-R2-C-02)

### Reproduction

Media 39 exists solely to trip G-01 freeze blindness. An operator reading `labeled_y_missing_images=1` after regen needs the sampling frame.

### Fix

`provenance.corpus_traps` on the caption run-record:

| media_id | kind | trips |
| --- | --- | --- |
| 39 | `VLM6-R2-G-01_mixed_y_order_degraded` | `labeled_y_missing_images` always-0 freeze blindness |

### GREEN

```text
pytest ...::test_corpus_traps_disclose_deliberate_caption_trap_media PASSED
```

---

## Disagreements

**None** on the blindness claim after live probes:

1. Caption golden `with_face_boxes=0` confirmed.
2. Live + committed `labeled_y_missing_images` structural 0 (committed report lacks the field entirely — freeze pre-dates wd-A publish).
3. `order_unknown_excluded=37` is **absence of face data**, not degradation — confirmed by empty `face_boxes` on all 37.
4. Constant-0 mutation equaled live pre-extension — blindness confirmed.
5. wF4 residual 2 is correctly diagnosed; no counter-evidence.

---

## New findings (not owned)

1. **Committed caption report still omits `labeled_y_missing_*` keys** — live scorer emits them; freeze JSON predates the field. Regen must add keys, not only change values.
2. **`require_metric_backing(face_boxes)` is no longer refused on the freeze man** (1/38 populated → not vacuous). Still under-sampled in `coverage_gaps` (1 < threshold 5). Golden-alone still refuses. Intentional; not a gate weaken.
3. **Score-time man for caption freeze is now bakeoff-results man, not golden** — any operator docs / CLI examples that still say "score the freeze against golden.json" need a doc update (README out of scope this lane).

---

## Full suite

```bash
cd apps/prototype-description-service
./.venv/bin/python -m pytest scene/tests/ -q -p no:randomly
```

**Result:** `5 failed, 1391 passed, 4 skipped`  
(Base: `5 failed, 1387 passed, 4 skipped` — +4 tests: man digest pin + 3 acceptance/trap tests; all new tests green.)

### Expected-red

| Test | Cause |
| --- | --- |
| `test_generator_regenerates_byte_identical_committed_anchor` | **Man+run match.** Report JSON/MD still stale: pre-existing scoring-field drift **plus wG3 corpus**: `counts.scored/total` 37→38, detection tp 51→53 / precision+recall shift, identity_ordering `order_unknown_excluded` 37→38, **new** `labeled_y_missing_images=1` + paths, identification evaluated_images/P/R/macro_recall/per_identity (Bea Burke + Caitlin Weaver +1 tp each), wrong_name_rate 0.1081→0.1053, coverage_gaps totals 37→38 and face_boxes 0→1, verdict wrong_name_rate. Reports **not** regenerated (this lane). |
| `test_expect_report_matches_committed_freeze_green` | Same caption report staleness vs live re-score of extended man+run. |
| `test_face_generator_regenerates_byte_identical_committed_anchor` | **Pre-existing** face report freeze (wF4 corpus + coupling_flag + sampling_frame). Not caused by wG3. |
| `test_face_expect_report_matches_committed_freeze_green` | Same face report staleness. |
| `test_cli_score_face_expect_report_end_to_end_green` | Same face report staleness. |

### Unexpected-red

**None.**

---

## `git diff --stat` vs base

sha-guard:ignore-next-block
```text
base cc1da6219d2407dca6c676d6e6583635bcdc9672
 .../tests/test_eval_harness_determinism_anchor.py  | 264 ++++++++++++---
 .../eval_harness/generate_determinism_anchor.py    | 359 +++++++++++++++------
 .../S2A-determinism-anchor-manifest-20260811.json  | (new) caption freeze man
 .../S2A-determinism-anchor-run-20260811.json       |  72 ++++-
 4 files changed (+ report commit)
```

### Pins moved (owned)

| Artifact | Old digest (prefix) | New digest |
| --- | --- | --- |
| caption man | *(absent)* | `2eae07326bd5a63834fe838de9fbc4e46ab71599ed213c6eacb1fd66757c57b7` |
| caption run-record | `sha256:d105f3ad…` | `b5c3040aad98939b71c2242ed2cdbd8efcdb4a51bd65ec8f5f45e8a1a70e58cf` |
| `manifest_sha256` prefix | `sha256:83bfdc4e` (golden) | `sha256:7462d325` (freeze man) |

Report digests **unchanged** (regen stage):  
JSON `sha256:c2fcfa34…` · MD `sha256:dc7bf054…`

### Live value shifts regen must absorb

| Field | Freeze (stale) | Live (post-wG3) |
| --- | --- | --- |
| `counts.scored` / `total` | 37 | 38 |
| `faces.detection.tp` | 51 | 53 |
| `faces.detection.fp` / `fn` | 3 / 6 | **unchanged** |
| `faces.detection.precision` | 0.9444… | 0.9464… |
| `faces.detection.recall` | 0.8947… | 0.8983… |
| `faces.identity_ordering.order_unknown_excluded` | 37 | 38 |
| `faces.identity_ordering.labeled_y_missing_images` | *absent* / would be 0 | **1** |
| `faces.identity_ordering.labeled_y_missing_paths` | *absent* | `["mock_images/y-missing-mixed-order.jpg"]` |
| `faces.identity_ordering.degraded_images` | 0 | 0 |
| `faces.identity_ordering.positional_images` | 0 | 0 |
| `faces.identification.evaluated_images` | 37 | 38 |
| `faces.identification.precision` / `recall` / `macro_recall` | (prior) | slight ↑ from trap true-positives |
| `faces.identification.per_identity` Bea Burke / Caitlin Weaver tp | | +1 each |
| `wrong_name_rate` | 0.1081 | 0.1053 (4/38 vs 4/37) |
| `provenance.coverage_gaps.*.total` | 37 | 38 |
| `provenance.coverage_gaps.face_boxes.populated` | 0 | 1 |
| `provenance.corpus_traps` | absent | 1-entry trap inventory |
| `provenance.manifest_sha256` | `sha256:83bfdc4e…` | `sha256:7462d325…` |

Existing media 1–38 published cells not causally downstream of media 39 retain individual outcomes; aggregate detection tp (+2) and identity counts move only because the trap adds two named GT faces with matching seeded predictions (seed_index 37: no FN/FP deviation).

---

## Could not verify

- Post-regen caption report byte identity (explicitly not this lane).
- Production prevalence of missing-y named boxes (no network / no real corpus).
- Whether operators still pass `--manifest golden.json` to freeze checks out-of-tree (CLI default still golden seed; freeze score path in tests now uses caption man).

---

## Cross-lane requests

| To | Request |
| --- | --- |
| **Caption freeze regen stage** | Regenerate `S2A-determinism-anchor-run-20260811-report.json` + `.md` from the **wG3 man+run** (`S2A-determinism-anchor-manifest-20260811.json` + run). **Do not** re-extend the corpus or touch golden.json. Expected value shifts: table above. Absorb pre-existing field drift too (`labeled_y_missing_*` keys must **appear**, not only change). Update report digests in `test_eval_harness_determinism_anchor.py` `_FROZEN_DIGESTS` for report JSON+MD only (man+run already pinned by wG3). Expected-red tests that should go green after regen: `test_generator_regenerates_byte_identical_committed_anchor`, `test_expect_report_matches_committed_freeze_green`. Score-time man for freeze checks: **caption man**, not bare golden. |
| **Face freeze regen stage** | Unrelated to wG3; still needs wF4 face report regen (see wF4 report). |
| **wG1 / report.py** | Caption side already publishes `labeled_y_missing_*` on live score; regen surfaces it on freeze. No caption-side report.py change needed from this lane. |
| **Docs / README (optional)** | Document that the caption determinism freeze corpus is bakeoff-results man (golden+trap), while `scene/tests/seed/golden.json` remains the shared 0/37-face_boxes seed. |
