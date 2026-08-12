# VLM6-lb1: classify `load_manifest()` call sites (cli / anchors)

Lane: `vlm6-lb1-cli-hash-callsites` · Task: `VLM-6` · Actor: `grok-4.5`

> **fx5 correction (VLM6-D-07):** re-anchored the call-site table on
> **function names + distinguishing kwargs** instead of line numbers. Line
> anchors in the prior revision pointed at unrelated statements after later
> edits (`rg-005`). Each row re-verified against `cli.py` at this lane's branch HEAD.

## Summary

Classified every owned `load_manifest()` call site against default-on hash
verification (VLM6-R2-05). Pixel-reading paths pass `images_dir=`;
metadata-only paths pass `skip_hash_verification=True` with a one-line
field/rationale comment. Added permanent TEST-15 spy that fails if
face-bakeoff ever blanket-skips. Regenerated stale caption determinism freeze
(pre-existing golden/schema drift unmasked once load succeeded).

## Gate counts

| Phase | Result |
| --- | --- |
| RED-before | **78 failed**, 50 passed, 17 warnings in 21.33s |
| GREEN-after | **129 passed**, 23 warnings in 107.32s (includes +1 TEST-15 control) |

Command:
```bash
cd apps/prototype-description-service && uv run --extra dev pytest \
  scene/tests/test_eval_harness_cli.py \
  scene/tests/test_eval_harness_determinism_anchor.py \
  scene/tests/test_eval_harness_face_determinism_anchor.py \
  scene/tests/test_eval_harness_phrase_boxes.py \
  -q -p no:randomly
```

## Call-site classification table (function + kwargs; no line numbers)

| Site | Decision | Distinguishing call | Downstream that does/does not open bytes |
| --- | --- | --- | --- |
| `_cmd_fetch` | **images_dir** | `load_manifest(args.manifest, images_dir=images_dir)` | `fetch_run_record` → `image_path.read_bytes()` + `Image.open` |
| `_check_score_determinism_cross_process` | **skip** | `load_manifest(str(resolved_manifest), skip_hash_verification=True)` | `build_reports` — rubrics/roster/policy only |
| score-determinism embedded `python -c` child | **skip** | `load_manifest(sys.argv[2], skip_hash_verification=True)` inside child argv string | child re-score via `build_reports` — no image open |
| `_cmd_score` | **skip** | `load_manifest(args.manifest, skip_hash_verification=True)` | `score_run_record` / `build_reports` — must_right/easy_wrong/roster; bytes already in run-record |
| `_cmd_face_bakeoff` | **images_dir** | `load_manifest(args.manifest, images_dir=images_dir)` | face-bakeoff walk + occlusion twins → `image_path.read_bytes()` / decode BGR |
| `_check_face_determinism_cross_process` | **skip** | `load_manifest(str(resolved_manifest), skip_hash_verification=True)` | `_face_score_once` → `build_face_reports` — tags/face_count/record embeddings |
| face-determinism embedded `python -c` child | **skip** | `load_manifest(sys.argv[2], skip_hash_verification=True)` inside child argv string | child face re-score — no image open |
| `_cmd_score_face` | **skip** | `load_manifest(args.manifest, skip_hash_verification=True)` | `score_face_run_record` / `build_face_reports` — metadata + record-side embeddings |
| `generate_determinism_anchor` writer | **skip** | `load_manifest(str(manifest_path), skip_hash_verification=True)` | synthetic bytes from path/sha/media_id (`_synthetic_image_bytes`); module doc: no GOLDEN_IMAGES_DIR |
| `generate_face_determinism_anchor` writer | **skip** | `load_manifest(str(manifest_path), skip_hash_verification=True)` | synthetic face manifest; score uses roster/face_count/tags only |
| tests: `_write_score_manifest`, build_reports baselines, golden helpers, phrase_boxes `_seed_manifest`, face-anchor sha checks | **skip** | `skip_hash_verification=True` on helpers | all metadata/sha/score fixtures; never open fixture pixels |
| face-bakeoff fixture writers | **images_dir path** (real sha pins) | tests write images then pin `hashlib.sha256(path.read_bytes())` | so bakeoff verify passes |

## TEST-15 discrimination control

`test_face_bakeoff_passes_images_dir_not_skip` spies on `cli.load_manifest`
kwargs from `face-bakeoff`. Asserts `images_dir=` is the resolved
`GOLDEN_IMAGES_DIR` and `skip_hash_verification is False`.

### RED-before (temporary blanket skip on pixel path)

```
F                                                                        [100%]
=================================== FAILURES ===================================
_________________ test_face_bakeoff_passes_images_dir_not_skip _________________
scene/tests/test_eval_harness_cli.py:3687: in test_face_bakeoff_passes_images_dir_not_skip
    assert call["images_dir"] == str(images), (
E   AssertionError: pixel path must pass images_dir= (got {'path': '.../man.json', 'images_dir': None, 'skip_hash_verification': True}); skip_hash_verification alone re-opens VLM6-R2-05
...
1 failed in 1.23s
```

### GREEN-after (correct `images_dir=`)

```
.                                                                        [100%]
1 passed in 1.13s
```

## Freeze regeneration (boundary note)

Unblocking `write_anchor` revealed pre-existing caption freeze drift:

- freeze `manifest_sha256` was `859a083e…`
- current golden `model_dump` sha is `83bfdc4e…`

Cause (2) of ANCHOR_MISMATCH: freeze stale vs current golden/schema. Regenerated via owned generator:

```bash
python -m scripts.eval_harness.generate_determinism_anchor
```

Updated:

- `docs/tasks/vlm/bakeoff-results/S2A-determinism-anchor-run-20260811.{json,report.json,report.md}` (outside strict owned_paths — required for owned generator/tests to stay coherent)
- digest pins + sha prefix in `test_eval_harness_determinism_anchor.py`

## What we did NOT do

- Did **not** edit `manifest.py` (VLM6-R2-05 checker stays default-on).
- Did **not** edit `report.py` or its tests.
- Did **not** xfail/skip/delete any existing test.
- Did **not** blanket-apply `skip_hash_verification=True` on pixel paths.
- Did **not** touch sibling-lane modules (`bakeoff.py`, `fusion_runner.py`, etc.).

## Unsure / residual

- None remaining on the lane gate (129/129 green).
- Freeze path is a soft owned-path stretch: needed so owned anchor tests and digests match regenerated output. Orchestrator should confirm freeze commit is acceptable for this lane.

## Canon

- sr-001: no weakened tests
- TEST-15: spy goes red under skip, green under images_dir
- OBS-04: missing-dir/hash errors still name GOLDEN_IMAGES_DIR remedy (unchanged in manifest.py)
- DBG-11: red-before 78 ManifestErrors; green-after after caller classification
