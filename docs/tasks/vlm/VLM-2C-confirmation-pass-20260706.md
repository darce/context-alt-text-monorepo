# VLM-2C Slice 1 — Confirmation Pass (2026-07-06)

Ground-truth provenance: `present_identities` and `face_count` for all 37 entries are **inherited unchanged from the VLM-2A operator pass** (see `scene/tests/seed/README.md` counting rule). This pass adds (a) a draft-regeneration reconciliation, (b) a visual review of the six stranger-delta entries against the roster crops, and (c) the stranger-fixture designation.

Visual pass performed by agent (Claude Fable 5) against `mock_entities/` roster crops; **designation pending operator ratification** — flag any correction and the manifest/tests will be updated before Slice 3 consumes it.

## Draft reconciliation

`draft_labels.generate_draft_manifest(~/Development/eval-fixtures)` vs `golden.json`:

- Draft scans 38 files; golden keeps 37. Sole difference: `mock_images/kirstie-boat_detected.jpg`, the detection-annotated near-duplicate VLM-2A deliberately removed — exclusion upheld.
- All 37 shared paths: `sha256` and `media_id` identical (zero drift). Full-corpus hash verification via `load_manifest(images_dir=…)` passes.
- 21 identity differences are all draft-heuristic under-matches (filename tokens like `ccqw`, `mcm`, `k.mcc` unresolved); the operator-confirmed golden labels stand. One inverse case: `liam-maloney-painting.jpg` draft-guesses Liam from the filename, golden correctly labels `[]` (depicted painting — excluded per counting rule).

## Stranger-delta visual review (6 entries)

| media_id | path | face_count / ids | counted face regions (visual pass) |
| --- | --- | --- | --- |
| 5 | ccqw-erika.jpg | 4 / 2 | Foreground woman (large, image rotated), one face far right edge, two smaller faces in mirror/background group. Delta 2 = background persons, neither matching a roster crop. |
| 28 | maria-cocktail.jpg | 4 / 1 | Four women posed at a formal table; rightmost = Maria Correonero (matches crop). Other three match no roster crop. Delta 3 genuine strangers. |
| 29 | maria-party.jpg | 3 / 1 | Foreground Maria eating cake; background couple (man in beanie, red-haired woman). Phone-screen image of Maria correctly excluded as depicted. Delta 2 genuine strangers. |
| 35 | rrw-mirror.jpg | 2 / 0 | One woman + her mirror reflection (reflection counted per rule). She matches no roster crop (dark-haired; not Ryann Wiseman despite `rrw-` filename) → both faces non-roster. All-stranger scene. |
| 37 | ryann-group-party.jpg | 6 / 1 | Six party faces; one blonde consistent with Ryann Wiseman crop. Remaining five match no roster crop. Delta 5 genuine strangers. |
| 38 | ryann-party.jpg | 2 / 1 | Two women on a couch: blonde matches Ryann Wiseman crop (long blonde hair, brown eyes); dark-haired woman matches no roster crop (checked against Maria, Kirstie, Cristina, Bea — all clearly different). Wall photos/posters excluded as depicted. Delta 1 genuine stranger. |

No delta is an unlabeled roster member or a depicted face; all six sit on `recognition_enabled: true` scenes. No `face_count` was changed by this pass.

## Designation

**Designated stranger fixture: `mock_images/ryann-party.jpg` (media_id 38).**

Rationale: exactly one roster identity (Ryann Wiseman) plus exactly one genuine non-roster face — the minimal *mixed* true-rejection case (`face_metrics.py` S2-05 branch) and precisely the phrase-box stranger template in the task plan (one phrase box, two face centers, one resolving to `null`). `ryann-group-party.jpg` (media_id 37, delta 5) is the natural candidate for the stretch-goal second stranger entry; `rrw-mirror.jpg` (media_id 35) covers the all-stranger/empty-roster shape already exercised by unit tests.

Pinned by `test_seed_corpus_has_designated_stranger_entry` and `test_seed_corpus_reconciles_with_fixture_scan` (`scene/tests/test_eval_harness_manifest.py`).

## Addendum (Slice 2 visual pass): possible face_count undercounts — operator review requested

While authoring caption fixtures the agent viewed all 37 scenes. Four entries appear to show more visible face regions than their recorded `face_count`; per the never-fabricate rule the recorded values were **left unchanged**. Operator: confirm or correct.

| media_id | path | recorded | agent count | note |
| --- | --- | --- | --- | --- |
| 12 | ccqw-running.jpg | 1 | 2 | second marathoner (male, bib 967) runs beside Caitlin, face clearly visible |
| 17 | cristina-1.jpg | 1 | 3 | three costumed women posed together, all faces visible |
| 19 | k.mcc-1.jpg | 1 | 2 | two women under the balloon arch, both faces visible |
| 21 | kirstie-boat.jpg | 1 | 3 | friend in red swimsuit beside Kirstie + boat driver behind windshield |

Ambiguous (left as recorded): media_id 11 `ccqw-running-2.jpg` — blurred spectator faces behind the barricade; countability per the README rule is an operator judgment call. If any count changes, `stranger_faces` deltas and detection P/R shift; re-run the seeded-stub score after correcting.
