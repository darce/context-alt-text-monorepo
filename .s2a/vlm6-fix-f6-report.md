# VLM-6 S2A F6 — synthetic face determinism anchor + score-face --expect-report

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6` (sandbox: history-stripped)  
**Scope:**
- `scripts/eval_harness/generate_face_determinism_anchor.py` — generator
- `docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-*` — freeze quadruple
- `scripts/eval_harness/cli.py` — score-face `--expect-report` + shared helper param
- `scene/tests/test_eval_harness_face_determinism_anchor.py` — face TEST-15 / DBG-11
- `scene/tests/test_eval_harness_determinism_anchor.py` — F5-01 caption input-side
- `scripts/eval_harness/README.md` — face freeze operator path
- this report

**Did not touch:** `report.py`, `test_eval_harness_pipeline.py` (pinned),
`golden.json`, legacy `*run-record*.json`, the three caption
`S2A-determinism-anchor-run-20260811*` artifacts (no regenerate),
`describe_baseline.py` (B-11 residual). **No file moved out of `out/`.**

## Verdict

**merge_ready** for F6. Synthetic face anchor is regenerable and bit-stable;
`score-face --check-determinism --expect-report` green against the freeze;
report-side and run-record-side corruption both red with `ANCHOR_MISMATCH`;
same run-record corruption without the flag still seed-passes (DBG-11);
caption F5-01 input-side control landed; suite green above baseline.

## Manifest choice (settled)

**Dedicated synthetic face manifest** committed next to the anchor:

`docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json`

**Why not `golden.json`:** score-time face assignment is IoU over
`entry.face_boxes`. `golden.json` has 37 entries with `face_count` /
`present_identities` / roster but **`total_gt_boxes == 0`**. Against golden,
every detection is unmatched and slices are vacuous — not a useful freeze.
`golden.json` is out of scope (other gates pin its sha). Manifest sha of the
synthetic file is **computed** at generation via `cli._manifest_sha` →
`e7004f3b2355d8c46943acffa3d3ea8c85c068985494962d0c48c5d12e8ccc0e` (rg-015).

## Synthetic embeddings (PROV-01)

| Role | Construction | dim |
| --- | --- | --- |
| Alice A | unit(`[1,0,0,0,0,0,0,0]`) | 8 |
| Alice B | unit(`[0.98,0.1,0,…]`) | 8 |
| Stranger | unit(`[0,1,0,…]`) | 8 |

- bbox_px `[20,20,40,40]` on image_size `[100,100]` ↔ GT centre box `(0.4,0.4,0.4,0.4)`
- Built only via `build_face_run_record` / `build_face_detection` / `build_face_run_item`
- `model_id=synthetic-face-anchor`; no detector, no image, no real person
- `head_sha` / `started_at` are **byte-stability sentinels** (commented at definition)

## Design

Reused F5 machinery — **no helper fork**:

- `_check_expect_report` gains optional `regen_cmd` (default caption generator;
  face passes `_FACE_DETERMINISM_ANCHOR_REGEN_CMD`)
- `_check_face_determinism_cross_process(..., expect_report=)` same three
  outcomes, deferred pass announce, label=`score-face`
- `--expect-report` on score-face parser; hard exit without `--check-determinism`

## Corruption field (honest)

| Field | Changes certified JSON? | Notes |
| --- | --- | --- |
| `landmarks_px` | **No** | score-invisible; cannot drive ANCHOR_MISMATCH |
| `det_score` | **No** | score-invisible |
| `embedding` | **Yes** | used for open-set ID; sole post-determinism face gate is `failed-items` — does not fire first |

Input-side control mutates `items[0].faces[0].embedding` (re-unit). Gate that
fires with `--expect-report`: **`ANCHOR_MISMATCH [score-face]`**. Without flag:
seed-stability **passed** (DBG-11).

## Heuristics

| ID | How satisfied |
| --- | --- |
| **PROV-01** | Synthetic dim=8 only; no `out/` promotion; stated construction above |
| **OBS-04** | ERROR / FAILED / ANCHOR_MISMATCH / passed; face regen cmd in mismatch text |
| **TEST-15** | Report-side red + run-record-side red + clean green; caption F5-01 input red |
| **DBG-11** | Same embedding corruption without `--expect-report` exits 0, `determinism check passed [score-face]` |
| **rg-015** | `manifest_sha256` from `_manifest_sha(load_manifest(...))` at generation |
| **sr-001** | No test weakened/skipped/xfailed; passed count increased |

## Evidence

### Generator twice-run byte-identical

```text
$ uv run --extra dev python -m scripts.eval_harness.generate_face_determinism_anchor --out-dir /tmp/vlm6-f6-a
$ uv run --extra dev python -m scripts.eval_harness.generate_face_determinism_anchor --out-dir /tmp/vlm6-f6-b
$ sha256sum /tmp/vlm6-f6-a/* /tmp/vlm6-f6-b/*
f41a93d7…  …/S2A-face-determinism-anchor-manifest-20260811.json   (both)
3fb8628a…  …/S2A-face-determinism-anchor-run-20260811.json
6c696a54…  …/S2A-face-determinism-anchor-run-20260811-face-report.json
6d066e5b…  …/S2A-face-determinism-anchor-run-20260811-face-report.md
# diff -q a vs b → BYTE_IDENTICAL_OK; digests match committed files
```

### Face gate green

```text
$ uv run --extra dev python -m scripts.eval_harness.cli score-face \
    --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json \
    --check-determinism \
    --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json
determinism check passed [score-face]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42); matches --expect-report …/S2A-face-determinism-anchor-run-20260811-face-report.json
…/S2A-face-determinism-anchor-run-20260811-face-report.md
scored=3/3 matched_faces=3 occlusion_n_eligible=0 directional_excluded=6
EXIT:0
```

### Red / green pairs (tmp copies; gate that fired named)

```text
=== RED: corrupt --expect-report ===
determinism check ANCHOR_MISMATCH [score-face]: … (baseline=randomized; child_seeds=0,1,42; …)
  remedy names generate_face_determinism_anchor
EXIT_RED_REPORT:1
# gate: ANCHOR_MISMATCH (report-side)

=== RED: corrupt run-record embedding ===
determinism check ANCHOR_MISMATCH [score-face]: …
EXIT_RED_RECORD:1
# gate: ANCHOR_MISMATCH (input-side); not failed-items

=== DBG-11: same corrupt run WITHOUT --expect-report ===
determinism check passed [score-face]: cross-process re-score is bit-identical under varied PYTHONHASHSEED (baseline=randomized; child_seeds=0,1,42)
EXIT_NO_EXPECT:0

=== GREEN: clean ===
determinism check passed [score-face]: …; matches --expect-report …
EXIT_GREEN:0
```

`git status --short docs/tasks/vlm/bakeoff-results/` after runs: only the four
new untracked face anchor files (digests stable; caption triple untouched).

### Frozen digests

| file | sha256 |
| --- | --- |
| `S2A-face-determinism-anchor-manifest-20260811.json` | `f41a93d771cad4cfc9baa9553c8fd42e3ea512f5baa3c3e4a3edaa699cde669f` |
| `S2A-face-determinism-anchor-run-20260811.json` | `3fb8628a2f6b5594e724b365684f37ff01173aac420035f3bbcfeaa037b0a751` |
| `S2A-face-determinism-anchor-run-20260811-face-report.json` | `6c696a5450236fce3ed7ba66acbcc7982b3263d6ad8b7f49fa260d57bca59dca` |
| `S2A-face-determinism-anchor-run-20260811-face-report.md` | `6d066e5be26f1b20663fb381038affdfd883656bcf641170a6cc47849e7fb88b` |

### Gate

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
708 passed, 4 skipped, 408 deselected, 19 warnings in 97.76s (0:01:37)
```

Baseline was **696 passed, 3 skipped, 0 failed** (linux host note: 695/4). This run:
**0 failed**, passed **708** (> baseline). Net + face freeze pins, both
corruption sides, DBG-11, CLI coupling, F5-01 caption input control.

## Residual

- **B-11** `describe_baseline.py` secrets under `oci_vault` — still open; not F6 scope.
  Premise correction stands: default `env` backend makes provider and raw-env
  identical; residual risk is oci_vault fail-open only.

## Files changed (content summary)

| File | Change |
| --- | --- |
| `generate_face_determinism_anchor.py` | new offline synthetic generator |
| bakeoff-results `S2A-face-determinism-anchor-*` | manifest + run + face-report.json/md |
| `cli.py` | score-face `--expect-report`; regen_cmd param on helper; face guard wiring |
| `test_eval_harness_face_determinism_anchor.py` | face freeze pins + both corruption sides + DBG-11 + CLI |
| `test_eval_harness_determinism_anchor.py` | F5-01 caption run-record alt_text_draft control |
| `README.md` | face freeze command + PROV-01 note |
| `.s2a/vlm6-fix-f6-report.md` | this report |

No commit SHA recorded here (lane sandbox SHAs are not destination objects).
