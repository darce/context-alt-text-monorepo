# VLM-6 S2A F1c-1 — hard-key three fail-open gate inputs (lane `vlm6-s2a-fix-gates`)

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Scope:** F1-4 only (assignment #523) — hard-key three gate inputs  
**Builds on:** F1a + F1b + F1b-2 already in tree  
**Sandbox base:** history-stripped lane sandbox (feature content present)

## Verdict

**merge_ready** — three soft-default gate inputs hard-keyed; missing/wrong-type exits non-zero with class-unique `score schema error:` token naming the dotted path; real-corpus RED/GREEN against `scene/tests/seed/golden.json` (37 entries); pytest **136 passed** (baseline 133 + 3 new schema-error tests).

## Defect

Three gate inputs in `_cmd_score` silently disabled their gate (or passed) when the key was missing or renamed (TEST-15 purest form):

| Input | Soft default | Fail-open effect |
| --- | --- | --- |
| `provenance.manifest_matches_fetch` | `.get(...) is False` → False when absent | gate / check skipped |
| `caption.must_right_failed_images` | `int(... or 0)` → 0 when None/absent | must-right gate skipped |
| `verdict.wrong_name_rate` | `float(..., 0.0)` → 0.0 when absent | wrong-name floor passes |

A rename in `report.py` therefore turned a hard gate off with no signal.

## What changed

### `cli.py`

- Added `_hard_key` / `_score_schema_error` / `_is_bool` / `_is_number` helpers.
- Message token: `score schema error: <dotted.path> missing or not a <bool|number>` — class-unique vs every existing gate token.
- Before must-right / wrong-name gates, hard-key:
  1. `provenance.manifest_matches_fetch` → must be `bool` (informational post-F1-3, still required so schema drift cannot go silent)
  2. `caption.must_right_failed_images` → must be number (not bool)
  3. `verdict.wrong_name_rate` → must be number (not bool)
- Gate bodies now use the hard-keyed values (no soft defaults).

Did **not** edit `report.py`. Did not touch determinism, score-face, empty-rubric, truncation, or audience paths.

### Tests (`test_eval_harness_cli.py`)

Three real-corpus tests (37-entry `scene/tests/seed/golden.json`):

- `test_score_schema_error_when_manifest_matches_fetch_missing`
- `test_score_schema_error_when_must_right_failed_images_missing`
- `test_score_schema_error_when_wrong_name_rate_missing`

Each builds a clean full-corpus run-record (dict-row identities; caption in `describe.alt_text_draft` / `named_draft` / `generic_draft`), monkeypatches `score_run_record` to drop the key (simulating report schema drift), asserts non-zero exit + `score schema error` + dotted path + absence of other gate tokens.

No tests weakened, skipped, or xfailed (sr-001).

## Real-corpus evidence (verbatim)

Corpus: `scene/tests/seed/golden.json` (37 entries).  
Probe: full 37-item run-record with must_right names in captions; matching score-time `manifest_sha256`.  
Corruption: post-process `score_run_record` output to drop/retype the target key (simulates report.py rename / type drift).  
Invoked via `uv run --extra dev python` calling `scripts.eval_harness.cli.main`.

### RED-before (soft defaults — pre-fix code)

```
=== drop-manifest_matches_fetch === EXIT 0 (return=None)  << FAIL-OPEN
=== drop-must_right_failed_images === EXIT 0 (return=None)  << FAIL-OPEN
=== drop-wrong_name_rate === EXIT 0 (return=None)  << FAIL-OPEN
=== retype-manifest_matches_fetch === EXIT 0 (return=None)  << FAIL-OPEN
=== retype-must_right_failed_images === ValueError: invalid literal for int() with base 10: 'zero'
=== retype-wrong_name_rate === ValueError: could not convert string to float: 'high'
```

Drops exited **0** (certified nothing). Retypes raised raw `ValueError` — not a named schema error, not a gate token.

### GREEN-after (hard-keys — post-fix)

Clean baseline still exits 0:

```
=== CLEAN baseline === EXIT 0 (return=None)
scored=37/37 insertion_rate=1.0 wrong_names=0 verdict=pass wrong_name_rate=0.0 wrong_name_rate_floor=0.0 rubric_gate=enforce
```

Three required drop pairs (RED-before exit 0 → GREEN-after non-zero):

```
=== drop-manifest_matches_fetch === EXIT non-zero: score schema error: provenance.manifest_matches_fetch missing or not a bool
=== drop-must_right_failed_images === EXIT non-zero: score schema error: caption.must_right_failed_images missing or not a number
=== drop-wrong_name_rate === EXIT non-zero: score schema error: verdict.wrong_name_rate missing or not a number
```

Retype pairs (also non-zero with same schema token):

```
=== retype-manifest_matches_fetch === EXIT non-zero: score schema error: provenance.manifest_matches_fetch missing or not a bool
=== retype-must_right_failed_images === EXIT non-zero: score schema error: caption.must_right_failed_images missing or not a number
=== retype-wrong_name_rate === EXIT non-zero: score schema error: verdict.wrong_name_rate missing or not a number
```

| corruption | RED-before | GREEN-after |
| --- | --- | --- |
| drop `provenance.manifest_matches_fetch` | **0** | non-zero, schema error names path |
| drop `caption.must_right_failed_images` | **0** | non-zero, schema error names path |
| drop `verdict.wrong_name_rate` | **0** | non-zero, schema error names path |

## Suite counts

| Suite | Baseline (F1b-2) | After F1c-1 |
| --- | --- | --- |
| `test_eval_harness_cli.py` + `test_eval_harness_report.py` | **133 passed** | **136 passed** |

(+3 schema-error tests). No skips/xfails.

## Out of scope / not fixed

- Empty-rubric, truncation, wrong-name floor vacuity, verdict-vs-exit contradiction, audience tests, describe_baseline — other F1 items / sibling lanes.

## Verification command

```bash
cd apps/prototype-description-service && \
  uv run --extra dev pytest \
    scene/tests/test_eval_harness_cli.py \
    scene/tests/test_eval_harness_report.py -q
# 136 passed
```
