# VLM-6 S2A F1b — make legitimate records scorable (lane `vlm6-s2a-fix-gates`)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1-3 + F1-11 only (assignment #518)  
**Builds on:** F1a (rubric vacuity + truncation) already in tree  
**Sandbox base:** history-stripped lane sandbox on `master` (feature content present)

## Verdict

**merge_ready** — both blockers fixed; real-corpus RED/GREEN against `scene/tests/seed/golden.json` (37 entries); pytest **132 passed** (baseline 130 + 2 new guards).

## Defects

| ID | Defect | Pre-fix (real golden / anchor) | Post-fix |
| --- | --- | --- | --- |
| F1-3 | Gate compared fetch-time sha to **current** file sha → archived baselines un-rescorable after any `model_dump()` edit; message claimed "truncation" | anchor under today's golden: would exit non-zero on `manifest_matches_fetch=False` | exit **0** (sha drift allowed; media-id coverage still enforced) |
| F1-11 | `must_right_failed_images > 0` = 100% name-recall gate; seeded fails 34/34 at rate 1.0 | seeded/anchor: exit **1**, `score must-right failures gate: 34 image(s) failed` | exit **0** when rate==1.0 but `mean_gated_score != 0.0` |

## What changed

### `cli.py` — `_cmd_score` gates

**F1-3 `score manifest-mismatch gate`:** no longer exits when `manifest_matches_fetch is False`. That comparison stays **informational** in the report (`provenance.manifest_matches_fetch`). Gate now requires the run-record to carry its own fetch-time `manifest_sha256` (self-consistent / attributable provenance). Message no longer claims corpus truncation (F1a media-id multiset gate owns that).

**F1-11 `score must-right failures gate`:** conjunction only:

- rubric non-vacuous (`must_right_defined_images > 0`)
- must-right failure rate `== 1.0` (`failed == defined`)
- `mean_gated_score == CAPTION_COLLAPSE_MEAN_GATED_SCORE` (`0.0`)

Rationale (named constant + comment): zero-vs-nonzero is structural. Seeded/no-name models fail every must_right image (rate 1.0) but still score non-zero on images without must_right terms (golden: mean ≈ 0.0811). Total caption collapse zeros every image (mean 0.0). Class-unique message kept: `score must-right failures gate: … caption hard-gate (caption corruption / missing required names; …)`.

Did **not** touch determinism helpers or the score-face path. Did **not** edit `report.py` (fields already expose `mean_gated_score`, `must_right_*`, `manifest_matches_fetch`).

### Tests (`test_eval_harness_cli.py`)

- Rewrote corruption-3 guard: missing fetch-time sha → `manifest-mismatch` (no "truncation" claim).
- Added `test_score_allows_fetch_sha_drift_from_score_time_manifest` (F1-3 green).
- Docstring update on caption-collapse guard for F1-11 conjunction.
- Added `test_score_guard_seeded_name_misses_do_not_fire_must_right_gate` (rate 1.0 + non-zero mean → exit 0).

No tests weakened, skipped, or xfailed (sr-001).

## Real-corpus evidence (verbatim)

Corpus: `scene/tests/seed/golden.json` (37 entries; must_right defined 34; easy_wrong 37).  
Invoked via `uv run --extra dev python` calling `scripts.eval_harness.cli.main`.

### 1) Caption collapse → exit non-zero (F1-11 RED)

Total collapse: every caption names that entry's `easy_wrong` trap (zeros gated score on all 37, including the 3 no-must_right images). Plain garbage alone leaves mean 0.0811 — the same structural shape as seeded — so it is **not** caption collapse.

Report fields: `must_right_failed_images=34`, `must_right_defined_images=34`, `mean_gated_score=0.0`, `manifest_matches_fetch=True`.

```
=== F1-11 RED: total caption collapse on real golden.json ===
cmd: score --manifest scene/tests/seed/golden.json --run-record /tmp/vlm6-f1b-2o4rtu36/collapse-run.json
/tmp/vlm6-f1b-2o4rtu36/collapse-run-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0
EXIT non-zero: score must-right failures gate: 34 image(s) failed Must-Right caption hard-gate (caption corruption / missing required names; see /tmp/vlm6-f1b-2o4rtu36/collapse-run-report.json)
```

### 2) Seeded anchor under evolved golden → exit 0 (F1-11 GREEN + F1-3)

Built from `docs/tasks/vlm/bakeoff-results/S0-determinism-anchor-run-20260714.json` (probe copy only): bare-string `identities` normalised to `{"name": s}` dict rows; committed anchor **not** rewritten. Fetch sha `67040d45…` ≠ score-time golden sha `859a083e…` (`manifest_matches_fetch=False`).

Report fields: `must_right_failed_images=34`, `must_right_defined_images=34`, `mean_gated_score=0.0811`, `media_id_missing=0`, `media_id_extra=0`.

```
=== F1-11 GREEN + F1-3: seeded anchor under evolved golden sha ===
cmd: score --manifest scene/tests/seed/golden.json --run-record /tmp/vlm6-f1b-2o4rtu36/anchor-seeded-run.json
/tmp/vlm6-f1b-2o4rtu36/anchor-seeded-run-report.md
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0
EXIT 0
```

| state | must-right failure rate | mean gated score | exit |
| --- | --- | --- | --- |
| total caption collapse | 1.0 (34/34) | 0.0 | non-zero (must-right failures gate) |
| seeded anchor (names nobody) | 1.0 (34/34) | 0.0811 | **0** |

## Suite counts

| Suite | Baseline (F1a) | After F1b |
| --- | --- | --- |
| `test_eval_harness_cli.py` + `test_eval_harness_report.py` | **130 passed** | **132 passed** |

(+2: sha-drift green path, seeded-shape non-collapse). No skips/xfails.

## Verification command

```bash
cd apps/prototype-description-service && \
  uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py \
    scene/tests/test_eval_harness_report.py -q
# 132 passed
```

## Explicit non-work

- Did **not** change `_check_face_determinism_cross_process` or the `score-face` path.
- Did **not** touch frozen anchors under `docs/tasks/vlm/bakeoff-results/`.
- Did **not** mutate `scene/tests/seed/golden.json`.
- Did **not** attempt F1-4+ defects (separate passes).
- Did **not** weaken, skip, or xfail any existing test (sr-001).
