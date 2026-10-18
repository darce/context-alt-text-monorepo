# VLM-2C Slice 1 — Confirmation Pass (2026-07-06)

Ground-truth provenance: `present_identities` and `face_count` for all 37 entries were initially **inherited from the VLM-2A operator pass** (see `scene/tests/seed/README.md` counting rule); the Slice-2 visual pass then flagged four undercounts, which the operator **ratified and corrected on 2026-07-07** (media 12/17/19/21 — see the resolved addendum below). This pass adds (a) a draft-regeneration reconciliation, (b) a visual review of the six original stranger-delta entries against the roster crops, and (c) the stranger-fixture designation.

Visual pass performed by agent (Claude Fable 5) against `mock_entities/` roster crops; the media_id 38 stranger designation was **ratified by the operator on 2026-07-07** together with the face_count corrections.

## Draft reconciliation

`draft_labels.generate_draft_manifest(~/Development/eval-fixtures)` vs `golden.json`:

- Draft scans 38 files; golden keeps 37. Sole difference: `mock_images/auburn-boat_detected.jpg`, the detection-annotated near-duplicate VLM-2A deliberately removed — exclusion upheld.
- All 37 shared paths: `sha256` and `media_id` identical (zero drift). Full-corpus hash verification via `load_manifest(images_dir=…)` passes.
- 21 identity differences are all draft-heuristic under-matches (filename tokens like `ccqw`, `mcm`, `k.mcc` unresolved); the operator-confirmed golden labels stand. One inverse case: `linen-kestrel-painting.jpg` draft-guesses Linen from the filename, golden correctly labels `[]` (depicted painting — excluded per counting rule).

## Stranger-delta visual review (6 entries)

| media_id | path | face_count / ids | counted face regions (visual pass) |
| --- | --- | --- | --- |
| 5 | ccqw-candid.jpg | 4 / 2 | Foreground woman (large, image rotated), one face far right edge, two smaller faces in mirror/background group. Delta 2 = background persons, neither matching a roster crop. |
| 28 | slate-cocktail.jpg | 4 / 1 | Four women posed at a formal table; rightmost = Slate Willow (matches crop). Other three match no roster crop. Delta 3 genuine strangers. |
| 29 | slate-party.jpg | 3 / 1 | Foreground Maria eating cake; background couple (man in beanie, red-haired woman). Phone-screen image of Maria correctly excluded as depicted. Delta 2 genuine strangers. |
| 35 | rrw-mirror.jpg | 2 / 0 | One woman + her mirror reflection (reflection counted per rule). She matches no roster crop (dark-haired; not Muted Yarrow despite `rrw-` filename) → both faces non-roster. All-stranger scene. |
| 37 | muted-group-party.jpg | 6 / 1 | Six party faces; one blonde consistent with Muted Yarrow crop. Remaining five match no roster crop. Delta 5 genuine strangers. |
| 38 | muted-party.jpg | 2 / 1 | Two women on a couch: blonde matches Muted Yarrow crop (long blonde hair, brown eyes); dark-haired woman matches no roster crop (checked against Slate, Auburn, Tidal, Quiet — all clearly different). Wall photos/posters excluded as depicted. Delta 1 genuine stranger. |

No delta is an unlabeled roster member or a depicted face; all six sit on `recognition_enabled: true` scenes. No `face_count` was changed by this pass.

## Designation

**Designated stranger fixture: `mock_images/muted-party.jpg` (media_id 38).**

Rationale: exactly one roster identity (Muted Yarrow) plus exactly one genuine non-roster face — the minimal *mixed* true-rejection case (`face_metrics.py` S2-05 branch) and precisely the phrase-box stranger template in the task plan (one phrase box, two face centers, one resolving to `null`). `muted-group-party.jpg` (media_id 37, delta 5) is the natural candidate for the stretch-goal second stranger entry; `rrw-mirror.jpg` (media_id 35) covers the all-stranger/empty-roster shape already exercised by unit tests.

Pinned by `test_seed_corpus_has_designated_stranger_entry` and `test_seed_corpus_reconciles_with_fixture_scan` (`scene/tests/test_eval_harness_manifest.py`).

## Addendum (Slice 2 visual pass): face_count undercounts — RESOLVED by operator (2026-07-07)

Four entries showed more visible face regions than recorded. The operator confirmed the agent counts and located each identity; `golden.json` was corrected in Slice 3:

| media_id | path | face_count | operator ruling |
| --- | --- | --- | --- |
| 12 | ccqw-running.jpg | 1 → 2 | Russet Fathom left; runner on right is a stranger |
| 17 | tidal-1.jpg | 1 → 3 | Tidal Harbor far right; two women on left are strangers |
| 19 | k.mcc-1.jpg | 1 → 2 | Auburn Current left; woman on right is a stranger |
| 21 | auburn-boat.jpg | 1 → 3 | Auburn Current right; two others are strangers |

Stranger-delta entries: 6 → 10. Ambiguous media_id 11 `ccqw-running-2.jpg` (blurred spectator crowd) stays as recorded (`face_count: 1`). The operator also ratified the media_id 38 stranger designation (Slice 3 proceeds).
