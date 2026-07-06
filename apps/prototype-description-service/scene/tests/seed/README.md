# Eval-harness golden seed (VLM-2A)

`golden.json` is the golden manifest for the caption-quality + face-recognition
eval harness (`scripts/eval_harness/`): 38 scene images + a 10-name roster
derived from 18 `entity-*` face crops. Per entry: relative path, `sha256`,
stable synthetic `media_id`, present-identity labels, context-pack fixture,
Must-Right/Easy-Wrong rubric entries, policy flags.

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
(`scripts.eval_harness.draft_labels`); see `golden-draft-review-notes.md` for
the operator confirmation checklist. Labels are ground truth only after that
pass; until then treat `present_identities` as unconfirmed.

Florence-2 benchmark note (pre-existing use of this directory): a real .jpg/.png
dropped here can serve as a checked-in fixture for `scripts/benchmark_local_vlm.py`;
it accepts arbitrary image paths as args. See the decision memo in docs/tasks/19.0/.
