# Eval-harness golden seed (VLM-2A)

`golden.json` is the golden manifest for the caption-quality + face-recognition
eval harness (`scripts/eval_harness/`): 37 scene images + a 10-name roster
derived from 18 `entity-*` face crops. Per entry: relative path, `sha256`,
stable synthetic `media_id`, ground-truth `face_count` (total human faces
present, including non-roster strangers — detection P/R scores against this, not
just the named identities), present-identity labels, context-pack fixture,
Must-Right/Easy-Wrong rubric entries, policy flags.

`must_right`/`easy_wrong` are empty for every entry in this MVP corpus, so the
caption Must-Right hard gate and Easy-Wrong rubric are vacuous; the loader emits
a `RubricEmptyWarning` and the report shows `must_right_defined_images: 0` rather
than failing silently. A face-detection-annotated derivative
(`kirstie-boat_detected.jpg`) was removed so no near-duplicate biases the metrics.

Image bytes are **not vendored in git** (59 MB corpus). Bootstrap a local copy
and point `GOLDEN_IMAGES_DIR` at it:

```bash
rsync -av \
  /Volumes/Butter/archives/archived-recognition-service/scripts/mock_images \
  /Volumes/Butter/archives/archived-recognition-service/scripts/mock_entities \
  ~/Development/eval-fixtures/
export GOLDEN_IMAGES_DIR=~/Development/eval-fixtures
```

The loader (`scripts.eval_harness.manifest.load_manifest`) fail-fasts on
structure violations and verifies every entry's `sha256` against
`$GOLDEN_IMAGES_DIR/<path>` when an images dir is supplied. A missing dir
produces an actionable error naming `GOLDEN_IMAGES_DIR`.

Label provenance: drafts were generated from filename heuristics
(`scripts.eval_harness.draft_labels`), then confirmed by an operator pass. The
labels in `golden.json` are that confirmed operator ground truth — the earlier
draft review notes were consumed by the confirmation and removed once the labels
were finalized.

Florence-2 benchmark note (pre-existing use of this directory): a real .jpg/.png
dropped here can serve as a checked-in fixture for `scripts/benchmark_local_vlm.py`;
it accepts arbitrary image paths as args. See the decision memo in docs/tasks/19.0/.
