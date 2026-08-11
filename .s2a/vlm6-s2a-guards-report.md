# VLM-6 Slice 2A — `vlm6-s2a-corruption-guards` lane report (item 4)

**Lane:** `vlm6-s2a-corruption-guards`  
**Task:** `VLM-6`  
**Scope:** Freeze the four adversarial corruptions as discrimination guards (TEST-15, second clause)  
**Base:** items 1–3 already on branch (`score` failed-items + wrong-name floor + cross-process determinism)

## Verdict

**merge_ready** — three new named gates + four discrimination-guard tests + this report committed.

## Empirical diagnosis at item-3 HEAD (before this lane)

| # | Corruption | Pre-lane exit | Distinguishing message? | Action |
| --- | --- | --- | --- | --- |
| 1 | every caption corrupted | **0** (false green) | no — `mean_gated_score=0.0`, `must_right_failed_images=N` reported only | **add** `score must-right failures gate` |
| 2 | wrong human names on every image | non-zero | yes — `score wrong-name floor gate: …` (item 2) | **cite existing** gate; freeze as guard test |
| 3 | corpus truncated 37→5 (stale full fetch sha) | **0** (false green) | `manifest_matches_fetch=false` recorded, **not gated** | **add** `score manifest-mismatch gate` |
| 4 | `must_right` emptied | **0** (false green) | `RubricEmptyWarning` only — warning ≠ gate | **add** `score empty-rubric gate` |

Notes on #3 variants:

- Truncated record+manifest with **matching** sha still exits 0 (self-consistent 5-image eval) — not the adversarial shape.
- Full record + truncated manifest already trips `score failed-items gate` (media_id missing). The discrimination guard uses the **stale fetch-sha** shape so the message names truncation/manifest mismatch, not a generic fail.

## What changed

### `cli.py` — `_cmd_score` additive gates (named)

Order after report write / score:

1. `score failed-items gate` (pre-existing)
2. **`score manifest-mismatch gate`** — `manifest_matches_fetch is False`
3. **`score empty-rubric gate`** — `must_right_defined_images == 0`
4. **`score must-right failures gate`** — `must_right_failed_images > 0`
5. `score wrong-name floor gate` (pre-existing, item 2)

Exact messages asserted by the guards:

| Corruption | Gate | Exact message shape | Existed? |
| --- | --- | --- | --- |
| every caption corrupted | `score must-right failures gate` | `score must-right failures gate: N image(s) failed Must-Right caption hard-gate (caption corruption / missing required names; see <report>)` | **newly-added** |
| wrong human names on every image | `score wrong-name floor gate` | `score wrong-name floor gate: wrong_name_rate=X exceeds floor=Y (see <report>)` | **already-existed** (item 2) |
| corpus truncated 37→5 | `score manifest-mismatch gate` | `score manifest-mismatch gate: score_manifest_sha256 differs from fetch-time manifest_sha256 — corpus truncation or post-fetch edit (see <report>)` | **newly-added** |
| `must_right` emptied | `score empty-rubric gate` | `score empty-rubric gate: golden corpus defines no Must-Right/Easy-Wrong rubric entries; caption hard gate is vacuous (see <report>)` | **newly-added** |

### Tests (`test_eval_harness_cli.py`)

Four permanent guards (tmp fixtures only — never mutate `scene/tests/seed/golden.json`):

- `test_score_guard_caption_corruption_fails_must_right_gate`
- `test_score_guard_wrong_names_fails_wrong_name_floor_gate`
- `test_score_guard_corpus_truncation_fails_manifest_mismatch_gate`
- `test_score_guard_empty_must_right_fails_empty_rubric_gate`

Each asserts **non-zero exit** and a message substring unique to its class (and absence of the other three class tokens).

Existing score fixtures updated so green paths use a real fetch-time `manifest_sha256` and a non-empty rubric — otherwise the new mismatch/empty-rubric gates would fire for the wrong reason.

## RED evidence (guards against ungated code)

Temporarily stripped the four discrimination gates (kept failed-items only). All four guards **FAILED** with `DID NOT RAISE SystemExit` (exit 0 false greens):

```
test_score_guard_caption_corruption_fails_must_right_gate FAILED
  Failed: DID NOT RAISE <class 'SystemExit'>
  scored=6/6 … verdict=pass wrong_name_rate=0.0

test_score_guard_wrong_names_fails_wrong_name_floor_gate FAILED
  Failed: DID NOT RAISE <class 'SystemExit'>
  scored=2/2 … wrong_names=2 verdict=fail wrong_name_rate=1.0
  (verdict fail but CLI still exited 0 without the floor gate)

test_score_guard_corpus_truncation_fails_manifest_mismatch_gate FAILED
  Failed: DID NOT RAISE <class 'SystemExit'>
  scored=5/5 … verdict=pass

test_score_guard_empty_must_right_fails_empty_rubric_gate FAILED
  Failed: DID NOT RAISE <class 'SystemExit'>
  scored=6/6 … verdict=pass  (+ RubricEmptyWarning only)

========================= 4 failed, 1 warning in 1.00s =========================
```

Every guard can go red — none are vacuous against pre-fix code.

## GREEN evidence (gates restored)

```
test_score_guard_caption_corruption_fails_must_right_gate PASSED
test_score_guard_wrong_names_fails_wrong_name_floor_gate PASSED
test_score_guard_corpus_truncation_fails_manifest_mismatch_gate PASSED
test_score_guard_empty_must_right_fails_empty_rubric_gate PASSED

========================= 4 passed, 1 warning in 1.00s =========================
```

Live gate messages (same fixtures):

```
score must-right failures gate: 6 image(s) failed Must-Right caption hard-gate (caption corruption / missing required names; see …)
score wrong-name floor gate: wrong_name_rate=1.0 exceeds floor=0.0 (see …)
score manifest-mismatch gate: score_manifest_sha256 differs from fetch-time manifest_sha256 — corpus truncation or post-fetch edit (see …)
score empty-rubric gate: golden corpus defines no Must-Right/Easy-Wrong rubric entries; caption hard gate is vacuous (see …)
```

## Suite counts

| Suite | Baseline (before this lane) | After |
| --- | --- | --- |
| `test_eval_harness_cli.py` + `test_eval_harness_report.py` | **123 passed** | **127 passed** |

(+4 discrimination guards; no skips/xfails.)

## Verification command

```bash
cd apps/prototype-description-service && \
  uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py \
    scene/tests/test_eval_harness_report.py -q
# 127 passed
```

## Explicit non-work

- Did **not** change `_check_face_determinism_cross_process` or the `score-face` path.
- Did **not** touch frozen anchors under `docs/tasks/vlm/bakeoff-results/`.
- Did **not** mutate `scene/tests/seed/golden.json`.
- Did **not** address `VLM6-GATE-04` (empty `face_boxes`) or `VLM6-GATE-05` (determinism baseline vs on-disk report).
- Did **not** weaken, skip, or xfail any existing test (sr-001).
