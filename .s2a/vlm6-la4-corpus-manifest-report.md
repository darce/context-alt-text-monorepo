# VLM-6 lane la4 — corpus strata + image hash pinning

**Lane:** `vlm6-la4-corpus-manifest`  
**Task:** `VLM-6`  
**Findings:** VLM6-R2-03, VLM6-R2-05  
**Branch (operator):** `feature/vlm-6-la4`  
**Sandbox branch:** `master` (history-stripped worker worktree)

## Verdict

**merge_ready** — both findings addressed in owned paths; lane gate **124 passed, 1 skipped**.

## Diff summary

| Path | Change |
| --- | --- |
| `scripts/eval_harness/manifest.py` | Default hash verify + opt-out; `inventory_corpus_fields` / `require_metric_backing` / `resolve_verified_image`; `SHIPPED_CORPUS_COVERAGE_GAPS` |
| `scene/tests/seed/golden.json` | Derivable `domain`/`difficulty`/`tags`/`provenance` on 37 entries; no fabricated facts/boxes |
| `scene/tests/test_eval_harness_manifest.py` | RED/GREEN tests for R2-03/R2-05; existing loads use `skip_hash_verification=True` |

**Not edited (owned but unchanged):** `test_eval_harness_strata.py`, `test_eval_harness_corpus_inventory.py` (existing suites still green; no strata/inventory module ownership needed for these findings).

## VLM6-R2-05 — hash pinning on every load by default

### Defect

`load_manifest` only called `_verify_hashes` when `images_dir` was passed. Only `_cmd_fetch` passed it. Score / score-face / determinism helpers loaded metadata with **silent** no-verify.

### Fix

- Hash verification is **default**.
- Resolve order: explicit `images_dir` → else `GOLDEN_IMAGES_DIR` → else require `skip_hash_verification=True` → else `ManifestError` naming the three remedies (OBS-04).
- `resolve_verified_image(entry, images_root)` for any future byte-read path.
- `_verify_hashes` now routes through `resolve_verified_image`.

### Later-wave `cli.py` lines (out of scope; must update)

Metadata-only callers need `skip_hash_verification=True` (or pass `images_dir` / set env when reading pixels):

| Approx line | Site |
| --- | --- |
| 1109 | `_check_*_determinism` baseline `load_manifest(str(resolved_manifest))` |
| 1137 | child script `man=load_manifest(sys.argv[2])` |
| 1193 | `_cmd_score` |
| 1536 | face path `load_manifest(args.manifest)` (also has images_dir nearby — should pass it) |
| 1638, 1653, 1693 | score-face / face determinism |

Fetch already passes `images_dir` (~631) — stays correct under the new default.

### RED (pre-fix, observed)

New tests against unfixed `manifest.py` (8 failed, 1 passed):

```
FAILED test_load_manifest_requires_hash_verification_by_default
  Failed: DID NOT RAISE <class 'scripts.eval_harness.manifest.ManifestError'>
  # silent load succeeded without images_dir / GOLDEN_IMAGES_DIR / skip

FAILED test_load_manifest_skip_hash_verification_allows_metadata_only
  TypeError: load_manifest() got an unexpected keyword argument 'skip_hash_verification'

FAILED test_resolve_verified_image_rejects_sha_drift
FAILED test_resolve_verified_image_returns_path_when_pin_matches
  ImportError: cannot import name 'resolve_verified_image'
```

### GREEN (post-fix)

```
cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_manifest.py \
  scene/tests/test_eval_harness_strata.py \
  scene/tests/test_eval_harness_corpus_inventory.py -q
→ 124 passed, 1 skipped in 3.48s
```

### DBG-11 (hash default)

- **With** default (no skip, no dir): `ManifestError` names `images_dir` / `GOLDEN_IMAGES_DIR` / `skip_hash_verification=True`.
- **Without** the check (opt-out): `skip_hash_verification=True` loads metadata.
- **With** `images_dir` or env: pins verified; tampered bytes → `sha256 mismatch` via `resolve_verified_image`.

## VLM6-R2-03 — corpus strata inventory + fail-loud empty backing

### Defect

Shipped golden-37: `difficulty`/`domain`/`tags`/`reference_facts`/`spatial_facts`/`face_boxes` all empty → every per-stratum metric silently single-bucket.

### Fix

1. **`inventory_corpus_fields(manifest)`** — per-field `populated/total` for stratification + rubric fields.
2. **`require_metric_backing(manifest, field)`** — raises when `populated==0` with field name, `0/N`, and remedy (or declared gap text).
3. **`SHIPPED_CORPUS_COVERAGE_GAPS`** — honest negatives with `owner=` + action for fields that cannot be invented without images.
4. **Populated golden.json** from **derivable** signals only:

| Field | Population | Source |
| --- | --- | --- |
| `domain` | 37/37 | filename tokens (mirror/occlusion/underexposed/painting/machiavelli); else face_count tiers (faces/people/crowds per strata.py) |
| `difficulty` | 37/37 | heuristic from tags + domain + face_count (not operator-labelled) |
| `tags` | 7/37 | filename → SliceTag: sunglasses, occlusion_other, blur |
| `provenance` | 37/37 | `source=fixture`, `license=fixture`, `publishable=false` |
| `reference_facts` | 0/37 | **gap** — needs visual fact authoring |
| `spatial_facts` | 0/37 | **gap** — needs curated relations |
| `face_boxes` | 0/37 | **gap** — phrase_boxes has centers only for 6 scenes, not w/h |
| `demographic_cohort` | 0/37 | **gap** — no cohort labels yet |

Domain counts after population: faces=19, crowds=6, people=4, occlusion=3, mirrors=2, art=2, low_light=1.

### RED (pre-fix, observed)

```
FAILED test_inventory_corpus_fields_reports_per_field_counts
  ImportError: cannot import name 'inventory_corpus_fields'
FAILED test_require_metric_backing_refuses_empty_corpus_field
  ImportError: cannot import name 'require_metric_backing'
FAILED test_seed_corpus_inventory_exposes_stratification_gaps_honestly
  ImportError: cannot import name 'SHIPPED_CORPUS_COVERAGE_GAPS'

# Pre-fix shipped corpus inventory (finding + local scan before population):
# difficulty 0/37, domain 0/37, tags 0/37, reference_facts 0/37,
# spatial_facts 0/37, face_boxes 0/37; only must_right 34/37, easy_wrong 37/37
```

### GREEN

Seed inventory test asserts non-zero domain/difficulty/tags/provenance, zero on honest gaps, `require_metric_backing(..., "face_boxes")` raises, `require_metric_backing(..., "domain")` passes.

## What we did NOT do (honest negatives)

1. **Did not invent** `reference_facts`, `spatial_facts`, or `face_boxes` — no image bytes in sandbox; phrase_boxes centers ≠ FaceBox w/h/source.
2. **Did not edit `cli.py`** — later wave must wire skip or images_dir (lines listed above).
3. **Did not edit** `report.py`, `caption_metrics.py`, `placement_metrics.py`, `describe_baseline.py`.
4. **Did not run live fetch** or hash-verify against real `GOLDEN_IMAGES_DIR` (unset here).
5. **Did not claim operator-confirmed difficulty** — values are deterministic heuristics from face_count/filename; operator may revise.
6. **Did not wire `require_metric_backing` into score gates** — that lives in report/cli (sibling lanes). API is ready for those lanes to call.

## Standing rules check

| Rule | Status |
| --- | --- |
| Exclusive ownership | Only owned files + this report |
| sr-001 | No weakened tests |
| TEST-15 | New tests observed RED then GREEN |
| DBG-11 | Default-verify fail vs skip/opt-in success |
| OBS-04 | Errors name images_dir / env / skip / gap owner |
| rg-015 | No fabricated metric denominators; inventory counts real fields |

## Gate command

```bash
cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_manifest.py \
  scene/tests/test_eval_harness_strata.py \
  scene/tests/test_eval_harness_corpus_inventory.py -q
# 124 passed, 1 skipped
```
