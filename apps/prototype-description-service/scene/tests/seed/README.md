# Eval-harness golden seed (VLM-2A corpus, VLM-2C population)

`golden.json` (`manifest_version: 3`) is the golden manifest for the
caption-quality + face-recognition eval harness (`scripts/eval_harness/`): 37
scene images + a 10-name roster derived from 18 `entity-*` face crops. Per
entry: relative path, `sha256`, stable synthetic `media_id`, ground-truth
`face_count` (total human faces present, including non-roster strangers —
detection P/R scores against this, not just the named identities),
present-identity labels, a populated `context_pack` (name-injected WP
title/caption/description), a `base_caption` reference string naming every
confirmed present identity, Must-Right/Easy-Wrong rubric entries, and policy
flags. Version 2 added the optional `base_caption` field; the loader accepts
versions 2 and 3.

`face_count` counting rule (operator-confirmed): count each visible human face
region, **including** a mirror reflection that shows a face (a detector sees it
as a face), but **excluding** depicted faces (paintings, phone/screen images,
posters) and backs of heads. `face_count >= len(present_identities)` is enforced
at load; the difference is the stranger-face count feeding true-rejection. Ten
entries carry stranger deltas; `mock_images/muted-party.jpg` (`media_id` 38) is
the operator-designated stranger fixture (one roster identity + one genuine
non-roster face — the minimal mixed true-rejection case).

Rubrics are populated for all 37 entries (VLM-2C): `must_right` equals the
confirmed present identities and `easy_wrong` lists believable roster
confusions not in the scene. The Must-Right hard gate is active on the 34
entries with present identities (vacuously satisfied on the three
zero-identity scenes, whose `must_right` is necessarily empty); the Easy-Wrong
wrong-name trap is active corpus-wide. `must_right_defined_images: 37` counts
entries with either rubric defined, and the loader emits no
`RubricEmptyWarning`. Rubric lists are roster-closed by the loader. A
face-detection-annotated derivative (`auburn-boat_detected.jpg`) was removed
so no near-duplicate biases the metrics.

`phrase_boxes.json` (`phrase_boxes/v1`) is the E19-4a coordination fixture:
mock person-phrase bounding boxes plus authored face centers in normalized
`[0,1]` top-left-origin image fractions, keyed by stringified scene `media_id`,
with a self-checking `expected_containment` answer key (smallest containing box
wins; a face center in no box resolves to no name — the stranger case).
Authored in VLM-2C Slice 3 from the operator-located identities; covers scenes
12, 19, 21, 23, 30, and 38.

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
(`scripts.eval_harness.draft_labels`), then confirmed by an operator pass
(VLM-2A). VLM-2C added the caption fixtures and rubrics (agent visual pass over
every scene), corrected four operator-ratified `face_count` values, and
designated the stranger fixture; the confirmation log lives at
`docs/tasks/vlm/VLM-2C-confirmation-pass-20260706.md`. Recognition-side
seeding: `seed_roster.seed` labels crop clusters (CLI `seed-roster`);
`seed_roster.seed_scenes` (CLI `seed-scenes`, gated by `ACX_EVAL_LIVE=1`)
idempotently ingests the scene images under their golden `media_id`s so the
eval tenant holds server-side `MediaIdentity` face regions for E19-4a.
Zero-face scenes are skipped (they produce no identity rows or bboxes).

Deterministic scoring evidence:

- **Do not** use the committed seeded-stub / VLM-2A baseline run-records with
  `score --check-determinism` as a green copy-paste path. Both exit **1** today
  (`ReportError` on bare-string `identities` rows — greenfield requires dict
  rows). See `scripts/eval_harness/README.md` § Score gates, verdict, and
  `--check-determinism` (rg-006).
- **Working evidence today:** the unit suite
  `test_cli_score_check_determinism_runs_cross_process_guard` (matched
  run-record + score-time manifest, dict identities). Operator reference and
  pass-line format live in the eval-harness README.
- Historical seeded-stub score write-up (pre-gate system):
  `docs/tasks/vlm/VLM-2C-seeded-stub-score-20260707-report.md`.

Florence-2 benchmark note (pre-existing use of this directory): a real .jpg/.png
dropped here can serve as a checked-in fixture for `scripts/benchmark_local_vlm.py`;
it accepts arbitrary image paths as args. See the decision memo in docs/tasks/19.0/.

## Frozen evaluation split

`golden.json` retains the full 37-image canonical fixture used by regression
checks and split verification. `bakeoff_golden.json` contains model-selection
entries from the train half. `held_out_golden.json` contains the existing
20-image held-out reporting half, preserved without redrawing the split.
Use that held-out manifest for reported candidate and zero-rule comparisons;
do not treat full-corpus regression scores as held-out model-quality evidence.

`fusion_regression.json` preserves the pre-split attachment fixtures for
synthetic fusion regression tests, including adversarial context and
multi-person scenes. It is not a model-selection or held-out reporting set.
