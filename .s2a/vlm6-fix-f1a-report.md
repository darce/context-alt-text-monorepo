# VLM-6 S2A F1a — rubric vacuity + truncation (lane `vlm6-s2a-fix-gates`)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1-1 + F1-2 only (assignment #517)  
**Sandbox base:** history-stripped clone (sandbox-only object; not present here).
<!-- history-stripped sandbox clone; the base object does not exist here -->
**Destination-reachable parent base:** `6b50ddde`

## Verdict

**merge_ready** — both blockers fixed; real-corpus RED/GREEN against `scene/tests/seed/golden.json` (37 entries); pytest **130 passed** (baseline 127 + 3 new guards/assertions).

## Defects

| ID | Defect | Pre-fix (real golden) | Post-fix |
| --- | --- | --- | --- |
| F1-1 | `must_right_defined_images` OR'd with `easy_wrong` → emptying only `must_right` silent | exit **0** | exit non-zero, names `must_right` |
| F1-2 | `counts.total = len(items)` never compared to manifest → `fetch --limit N` silent | exit **0**, `scored=5/5` | exit non-zero, `missing=32, extra=0` |

## What changed

### `report.py`

- Split rubric counters: `must_right_defined_images` counts only non-empty `must_right`; new `easy_wrong_defined_images` for `easy_wrong` (independent vacuity).
- Media-id multiset coverage on every score: `counts.manifest_entries`, `counts.media_id_missing`, `counts.media_id_extra` (Counter asymmetry vs score-time manifest).
- MD warnings name Must-Right and Easy-Wrong vacuity separately.

### `cli.py` — `_cmd_score` gates

Order after report write:

1. `score failed-items gate` (unchanged)
2. **`score truncation gate`** — `media_id_missing || media_id_extra` (F1-2)
3. `score manifest-mismatch gate` (unchanged; stale-sha shape)
4. **`score empty-rubric gate`** — independent `must_right` then `easy_wrong` vacuity (F1-1)
5. `score must-right failures gate` / `score wrong-name floor gate` (unchanged)

### Tests

- Rewrote `test_score_guard_empty_must_right_fails_empty_rubric_gate` to empty **only** `must_right` (matches docstring; easy_wrong kept).
- Added `test_score_guard_empty_easy_wrong_fails_empty_rubric_gate`.
- Added `test_score_guard_fetch_limit_truncation_fails_coverage_gate` (5-of-37 + matching full-corpus sha).
- Green-path fixtures given non-empty `easy_wrong` where independent vacuity would otherwise fire before the intended gate (audience + failed-items fixtures).
- Report unit tests updated for new count/caption fields.

Did **not** touch determinism helpers or score-face path.

## Real-corpus RED evidence (pre-fix HEAD)

Proven against `scene/tests/seed/golden.json` **before** the code change (same defect surface as review base). Commands invoked via `uv run --extra dev python` calling `scripts.eval_harness.cli.main`.

### F1-1 RED — empty only `must_right` (easy_wrong kept on all 37)

Corpus stats: `must_right` non-empty **34/37**, `easy_wrong` non-empty **37/37**. Corruption: set every entry's `must_right=[]`, keep `easy_wrong`, full 37-item run-record with matching score-time sha.

```
=== empty-must-right-only ===
manifest_entries=37 items=37
…/empty-must-right-only-run-report.md
scored=37/37 insertion_rate=1.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0
EXIT 0 (false green)
```

Why silent: OR'd `must_right_defined_images == 37` (from easy_wrong), `must_right_failed_images == 0`.

### F1-2 RED — 5-of-37 record + full golden + matching fetch sha

```
=== trunc-5-of-37 against real golden.json ===
manifest=scene/tests/seed/golden.json entries=37 items=5 msha=859a083ee2594b99…
…/trunc-run-report.md
scored=5/5 insertion_rate=1.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0
EXIT 0 (false green)
```

`manifest_matches_fetch=True` (sha matches); `counts.total` self-referential → scored=5/5.

## Real-corpus GREEN evidence (post-fix)

Same corruptions after the fix.

### F1-1 GREEN

Report fields: `must_right_defined_images=0`, `easy_wrong_defined_images=37`, `must_right_failed_images=0`.

```
=== F1-1 empty must_right only (easy_wrong kept) ===
cmd: score --manifest <tmp>/empty-mr-golden.json --run-record <tmp>/empty-mr-run.json
scored=37/37 … verdict=pass …
EXIT non-zero: 'score empty-rubric gate: must_right is vacuous corpus-wide (must_right_defined_images=0); caption hard gate is vacuous (see …/empty-mr-run-report.json)'
```

### F1-2 GREEN

Report fields: `total=5`, `scored=5`, `manifest_entries=37`, `media_id_missing=32`, `media_id_extra=0`, `manifest_matches_fetch=True`.

```
=== F1-2 trunc 5-of-37 vs real golden.json ===
cmd: score --manifest scene/tests/seed/golden.json --run-record <tmp>/trunc-run.json
scored=5/5 … verdict=pass …
EXIT non-zero: 'score truncation gate: run-record media-id multiset differs from manifest (missing=32, extra=0; record_items=5, manifest_entries=37; see …/trunc-run-report.json)'
```

## Tests

```bash
cd apps/prototype-description-service && \
  uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py \
    scene/tests/test_eval_harness_report.py -q
```

**Result:** `130 passed, 7 warnings` (baseline 127; +3 new coverage for independent vacuity + truncation multiset). No skips/xfails/weakened assertions (sr-001).

## Out of scope (later F1 passes)

Manifest-mismatch Slice 2 blockers, schema-drift fail-open, wrong-name floor vacuity, persisted verdict vs exit code, rounding, rubric over scored set, audience test weakening, describe_baseline scope — **not** this lane.
