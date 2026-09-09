# VLM-6 S2A F7 — de-vacate synthetic face freeze + coverage_gaps + mismatch path

**Lane:** `vlm6-s2a-fix-gates`  
**Task:** `VLM-6`  
**Branch:** `feature/vlm-6` (sandbox: history-stripped)  

**Scope (owned):**
- `scripts/eval_harness/generate_face_determinism_anchor.py` — multi-regime corpus + `coverage_gaps`
- four committed `S2A-face-determinism-anchor-*` artifacts (regenerated)
- `scene/tests/test_eval_harness_face_determinism_anchor.py` — gap guard + TEST-15/DBG-11
- `scripts/eval_harness/cli.py` — **only** mismatch-artifact output path (F7-01)
- `scripts/eval_harness/README.md` — face freeze coverage sentence + out/ diagnostics
- root `Makefile` — `eval-anchor-check` (F5-02 carry-over)
- caption/cli test path assertions updated for out/ artifact home (shared derivation)

**Did not touch:** `report.py`, `test_eval_harness_pipeline.py` (pinned),
`golden.json`, legacy `*run-record*.json`, the three caption
`S2A-determinism-anchor-run-20260811*` artifacts (no regenerate),
`describe_baseline.py` (B-11 residual). **No file moved out of `out/`.**

## Verdict

**merge_ready** for F7. Face freeze de-vacated for every hard cell that can
execute without tripping score-face's `counts.failed>0` hard exit; honest
`coverage_gaps` declared and guarded; mismatch diagnostics land in
`scripts/eval_harness/out/`; offline `make eval-anchor-check` exists.

## Item 4 first — F7-01 mismatch artifact path

**Defect:** ANCHOR_MISMATCH (and seed FAILED) wrote
`determinism-anchor-mismatch-*.diff.txt` under `artifact_dir=resolved_record.parent`.
Operator workflow uses the committed freeze as `--run-record`, so red gates
dirtied `docs/tasks/vlm/bakeoff-results/`.

**Fix (caption + face share the derivation — both fixed):**
- New `_determinism_artifact_dir()` → always `scripts/eval_harness/out/` (gitignored, PROV-01).
- Absolute path printed in ANCHOR_MISMATCH message (`artifact=…`).
- Does **not** derive from anchor/run-record location.

**Test:** red gate against corrupt expect → exit 1, artifact under `out/`, no new
file under `docs/tasks/vlm/bakeoff-results/`.

## Item 1 — corpus extension (before → after)

All vectors hand-authored dim=8 unit vectors (PROV-01). No private embeddings.

| slice / field | at F6 freeze (3 items / 1 id / 1 cohort) | after F7 | status |
| --- | --- | --- | --- |
| `slices.occlusion.masked` | `n_eligible=0`, `accuracy=null` | `n_eligible=1`, `accuracy=1.0` | **live** |
| `slices.occlusion.sunglasses` | `n_eligible=0`, nulls | still `n_eligible=0` | **gap declared** |
| `slices.occlusion.occlusion_other` | `n_eligible=0`, nulls | still `n_eligible=0` | **gap declared** |
| `slices.clustering` | `n_faces=2 n_clusters=1 p_diff=0 false_merge=0.0` | `n_faces=5 n_clusters=2 p_diff=6 false_merge=0.5` | **live** |
| `slices.demographic.by_cohort` | one cohort (`cohort_a`) | `cohort_a` + `cohort_b` | **live** |
| `slices.full_corpus_identification` | `fp=0 fn=0 missed_gt=0 unmatched=0 wrong_names=[]` | `fp=1 fn=1 missed_gt=1 unmatched=1 wrong_names=[Alice→Bob]` | **live** |
| `slices.headline_identification` | all zeros / empty wrong_names | `fp=1 fn=1 missed_gt=1 wrong_names=[Alice→Bob]` | **live** |
| `detection` | `tp=3 fp=0 fn=0` | `tp=6 fp=1 fn=1` | **live** |
| `failures` | `[]` | `[]` | **gap declared** (see note) |

**failures[] not exercised:** score-face hard-exits when `counts.failed > 0`, which
would make the documented green freeze path non-zero. Item 6 was optional; the
gap is declared in `provenance.coverage_gaps` (AUDIT-07 / EVAL-04).

**Embeddings (PROV-01):**

| Role | Construction | dim |
| --- | --- | --- |
| Alice A / B | unit(`[1,0,…]`) / unit(`[0.98,0.1,…]`) | 8 |
| Bob A / B | unit(`[0,0,1,…]`) / unit(`[0,0.05,0.98,…]`) | 8 |
| Alice wrong-name probe | unit(`[0,0,0.99,0.1,…]`) — Bob axis | 8 |
| Stranger | unit(`[0,1,0,…]`) | 8 |
| FP unmatched det | unit(`[0,0,0,1,…]`) | 8 |
| Occlusion twin (masked) | Alice A embedding on media_id=1 | 8 |

## Item 2 — coverage_gaps + guard (AUDIT-07)

- Generator scores once, runs `compute_coverage_gaps(report)`, stamps
  `provenance.coverage_gaps` on the run-record, re-scores so the freeze carries
  the same list (rg-015 — never hand-typed).
- Frozen gaps: `["failures", "occlusion.occlusion_other", "occlusion.sunglasses"]`
- Test enumerates freeze slices via `compute_coverage_gaps` and asserts every
  tracked cell is live XOR named; fails if a gap is under-declared or names a
  live cell.
- README: one sentence — green face gate proves byte-stable re-score + live
  cells execute; does **not** prove ship-ready floors; remaining vacuous cells
  listed in `coverage_gaps`.

## Item 3 — `make eval-anchor-check` (F5-02)

Separate offline target (not `eval-captions` / `bakeoff-face-score`):

```makefile
.PHONY: eval-anchor-check
eval-anchor-check:
	# score --check-determinism --expect-report  (caption freeze)
	# score-face --check-determinism --expect-report  (face freeze)
```

## Evidence

### Before/after coverage table

See table above (field-by-field).

### TEST-15 new cells + DBG-11 old corpus

| cell | corruption | new freeze | old 1-id corpus |
| --- | --- | --- | --- |
| clustering | Bob embeddings → Alice axis | **ANCHOR_MISMATCH** | `p_diff` stays 0 under Alice-only nudge |
| detection.fp | drop media_id=7 faces | **ANCHOR_MISMATCH** | `fp` stays 0 (no unmatched det exists) |

Also retained F6 controls: report-side red, embedding red, without-expect silent pass.

### Generator twice-run byte-identical

```text
$ uv run --extra dev python -m scripts.eval_harness.generate_face_determinism_anchor --out-dir /tmp/vlm6-f7-a
$ uv run --extra dev python -m scripts.eval_harness.generate_face_determinism_anchor --out-dir /tmp/vlm6-f7-b
$ diff -q /tmp/vlm6-f7-a /tmp/vlm6-f7-b → BYTE_IDENTICAL_OK
# digests match committed freeze
```

### Frozen digests

| file | sha256 |
| --- | --- |
| `S2A-face-determinism-anchor-manifest-20260811.json` | `1209733ed2b62e837449855690c15931dc0e76fcb24be8a715668020e05c8958` |
| `S2A-face-determinism-anchor-run-20260811.json` | `38a5168d051bc830ec1503a59858ff76e532807b9fbb7a8ccb1aaafadf7c10ff` |
| `S2A-face-determinism-anchor-run-20260811-face-report.json` | `dcee8efa6aa0846c2ef22f054030bc5ee921093f20043f0d498247d471c29442` |
| `S2A-face-determinism-anchor-run-20260811-face-report.md` | `212c46a0cb615432b87b3d2e0b7acaeb31429df51873aeea7d93daf6e8420368` |

### Documented face gate green

```text
$ uv run --extra dev python -m scripts.eval_harness.cli score-face \
    --manifest ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-manifest-20260811.json \
    --run-record ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811.json \
    --check-determinism \
    --expect-report ../../docs/tasks/vlm/bakeoff-results/S2A-face-determinism-anchor-run-20260811-face-report.json
determinism check passed [score-face]: … matches --expect-report …
scored=8/8 matched_faces=6 occlusion_n_eligible=1 directional_excluded=6
EXIT:0
# git status clean under bakeoff-results (no mismatch artifact there)
```

### Gap-guard red when under-declared

`test_coverage_gaps_guard_fails_when_gap_list_under_declares` — dropping a real
gap makes `compute_coverage_gaps(report) != declared`.

### Heuristics

| ID | How satisfied |
| --- | --- |
| **MLDATA-09** | 3-item filter removed; multi-regime corpus executes hard cells |
| **AUDIT-07** | `coverage_gaps` inventory + README coverage sentence |
| **EVAL-04** | null/zero cells not claimed as gated; declared or live |
| **FAIR-02** / **MLDATA-02** | Bob in `cohort_b` → two demographic cells |
| **EVAL-16** | detection FP/FN + missed_gt/unmatched live |
| **PROV-01** | all dim=8 hand-authored; nothing promoted from `out/` |
| **rg-015** | `coverage_gaps` + `manifest_sha256` computed at generation |
| **TEST-15** / **DBG-11** | clustering + FP red; old 1-id corpus cannot see them |
| **OBS-04** | mismatch artifact absolute path under out/ |
| **sr-001** | no test weakened/skipped/xfailed; passed count increased |

## Suite

```text
$ cd apps/prototype-description-service && uv run --extra dev pytest scene/tests/ -k eval_harness -q
714 passed, 4 skipped, 408 deselected, 25 warnings in 105.15s
```

Baseline was **709 passed, 3 skipped** (linux host: 708 passed, 4 skipped).
This run: **714 passed, 4 skipped, 0 failed** — greater than baseline, 0 failed.

### `make eval-anchor-check` (rg-006)

```text
$ make eval-anchor-check
determinism check passed [score]: … matches --expect-report …/S2A-determinism-anchor-run-20260811-report.json
scored=37/37 insertion_rate=0.0 wrong_names=0 verdict=pass_ungated …
determinism check passed [score-face]: … matches --expect-report …/S2A-face-determinism-anchor-run-20260811-face-report.json
scored=8/8 matched_faces=6 occlusion_n_eligible=1 directional_excluded=6
EXIT:0
```

No mismatch artifacts under `docs/tasks/vlm/bakeoff-results/` after green or red runs;
diagnostics land in `apps/prototype-description-service/scripts/eval_harness/out/`.
