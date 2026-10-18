# VLM-6 Slice 2A — `vlm6-s2a-corruption-guards` lane report (item 4)

**Lane:** `vlm6-s2a-corruption-guards`  
**Task:** `VLM-6`  
**Scope:** Freeze the four adversarial corruptions as discrimination guards (TEST-15, second clause)  
**Base:** items 1–3 already on branch (`score` failed-items + wrong-name floor + cross-process determinism)

> **fx5 correction (VLM6-D-06):** the original message table quoted gate strings
> that no longer appear in `cli.py` / tests at HEAD. Re-derived below from the
> live gate stems and the **permanent discrimination test names**. Prefer the
> test names as the stable contract — sibling lane `fx1` may rephrase operator
> text without invalidating the guard.

## Verdict

**merge_ready** — three new named gates + four discrimination-guard tests + this report committed.

## Empirical diagnosis at item-3 HEAD (before this lane)

| # | Corruption | Pre-lane exit | Distinguishing signal? | Action |
| --- | --- | --- | --- | --- |
| 1 | every caption corrupted | **0** (false green) | no — metrics only | **add** must-right failures gate |
| 2 | wrong human names on every image | non-zero (after item 2) | yes — wrong-name floor | **cite existing** gate; freeze as guard test |
| 3 | corpus truncated / fetch-sha inconsistency | **0** (false green) | mismatch recorded, not gated | **add** manifest-mismatch gate |
| 4 | `must_right` emptied | **0** (false green) | warning only | **add** empty-rubric gate |

## What changed

### `cli.py` — `_cmd_score` additive gates (named)

Order after report write / score (HEAD; later residual lanes inserted
aborted/zero-scored/truncation around these — see reconstructed lc2 report):

1. `score failed-items gate` (pre-existing)
2. **`score manifest-mismatch gate`** — missing fetch-time `manifest_sha256` in run-record provenance
3. **`score empty-rubric gate`** — independent Must-Right / Easy-Wrong vacuity
4. **`score must-right failures gate`** — hard-gate failures under enforce
5. `score wrong-name floor gate` (pre-existing, item 2)

### Message table — **stable identity = test name**, not quoted literals

| Corruption | Gate stem (HEAD) | Permanent discrimination test | Notes on actual message shape at reconstruction |
| --- | --- | --- | --- |
| every caption corrupted | `score must-right failures gate:` | `test_score_guard_caption_corruption_fails_must_right_gate` | Names failed Must-Right image count + report path |
| wrong human names | `score wrong-name floor gate:` | `test_score_guard_wrong_names_fails_wrong_name_floor_gate` | Names `wrong_name_rate` vs floor |
| missing fetch-time sha / not self-consistent record | `score manifest-mismatch gate:` | `test_score_guard_missing_fetch_sha_fails_manifest_mismatch_gate` | **HEAD text** is about **missing** fetch-time `manifest_sha256` on the run-record (`run-record provenance missing fetch-time manifest_sha256…`), **not** a score-vs-fetch digest inequality string. Score-vs-fetch mismatch stays informational (`manifest_matches_fetch`). |
| `must_right` emptied | `score empty-rubric gate:` | `test_score_guard_empty_must_right_fails_empty_rubric_gate` | **HEAD text** is the independent vacuity form: `must_right is vacuous corpus-wide` (and sibling `easy_wrong is vacuous corpus-wide` via `test_score_guard_empty_easy_wrong_fails_empty_rubric_gate`). There is **no** combined "Must-Right/Easy-Wrong rubric entries; caption hard gate is vacuous" single string at HEAD. |

### Tests (`test_eval_harness_cli.py`)

Four permanent guards (tmp fixtures only — never mutate `scene/tests/seed/golden.json`):

- `test_score_guard_caption_corruption_fails_must_right_gate`
- `test_score_guard_wrong_names_fails_wrong_name_floor_gate`
- `test_score_guard_missing_fetch_sha_fails_manifest_mismatch_gate`
  (name reflects the HEAD discrimination shape: strip fetch-time sha)
- `test_score_guard_empty_must_right_fails_empty_rubric_gate`

Each asserts **non-zero exit** and a message substring unique to its class
(and absence of the other class tokens). Additional residual guards
(`test_score_guard_empty_easy_wrong_fails_empty_rubric_gate`,
`test_score_guard_fetch_limit_truncation_fails_coverage_gate`) were added by
later lanes and are out of this item's original scope but live on the same surface.

## RED / GREEN evidence (original lane)

Temporarily stripped the discrimination gates (kept failed-items only). Guards
failed with `DID NOT RAISE SystemExit` (exit 0 false greens). Restored gates →
all four permanent guards PASSED. (Original suite counts: 123 → 127 passed;
subsequent residual lanes grew the file further.)

## Explicit non-work

- Did **not** change `_check_face_determinism_cross_process` or the `score-face` path.
- Did **not** touch frozen anchors under `docs/tasks/vlm/bakeoff-results/`.
- Did **not** mutate `scene/tests/seed/golden.json`.
- Did **not** weaken, skip, or xfail any existing test (sr-001).
