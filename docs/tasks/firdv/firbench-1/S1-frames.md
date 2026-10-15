# S1 · Frames, PSU components, folds, non-mated source units, design effect

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_frames.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_frames.py`

## Goal

Turn a frame source into the units every interval depends on. The independent unit is the image–identity connected component, not the image (AUDIT-11, EXP-23). Folds are assigned to whole components, so no identity leaks across calibration and test (CAL-07). The non-mated source-unit inventory is fixed by the exhaustive frame and never depends on detector output (EVAL-18, EVAL-19).

## Read first

- README shared names, the non-mated source unit definition, `FaceSearchRecord` fields, error raise conditions; S0 `FrameSpec`, `Admissibility`, `FrameContractError`
- `scripts/eval_harness/gallery_split.py`: `build_disjoint_galleries(*, templates_by_subject, seed)`, `Template`, `GallerySplit`, `probes_for`. It partitions subjects into G1 and G2. It does not assign fit or test roles; Build 8 does.
- `scripts/eval_harness/pilot_draw.py` and `audit_sampling.py` (bounded reads) for how arms and inclusion probabilities are represented
- W2 inventory § "Frame sources" for the exact field names of the Golden-150 manifest, corpus manifest v3r and the fir-occ population file

## Build

1. `FrameSource` records: `ImageUnit(image_id, sha256, arm, inclusion_probability | None, duplicate_group | None, session_id | None, synthetic_parent_id | None)` and `GtFace(face_id, image_id, box, identity_status, identity_id | None)`. `identity_status` is `named`, `unknown` or `unresolved`. `session_id` and `synthetic_parent_id` are optional; a missing field adds no edge.
2. Loaders: `load_golden_manifest(path)`, `load_corpus_manifest(path)`, `load_population_draft(path)`. Each validates structure at load time and raises `FrameContractError` with the offending key [rg-008, repo rule].
3. `build_psu_components(images, faces) -> dict[image_id, psu_id]`: union-find over one graph whose edges are: image–identity for named faces; exact-duplicate groups; shared `session_id`; and `synthetic_parent_id`, which joins a synthetic sibling to its parent image. Unknown and unresolved faces add no identity edge, so an unknown face in a shared image joins nothing; the image still joins through its named identities. An image with no GT face is its own component. psu_id is the sorted smallest image_id in the component, so it is deterministic. Components are computed before any fold is assigned.
4. Sizes and design effect, all in face counts.
   - PSU size m = number of GT faces in the component. Components with m = 0 are excluded from the size statistics below and still resample as their own PSU.
   - `size_weighted_mean(psu_sizes)`: M̃ = Σm² / Σm over components with m ≥ 1. This is the face-count M̃.
   - `design_effect(psu_sizes, icc)`: 1 + (M̃ − 1)·icc, with the face-count M̃.
   - `effective_n(n, deff)`: n / deff, a float used for sizing and for `n_nonmated_eff` only. It is never passed to a binomial function as n.
   - The image-count M̃ from the corpus manifest (report §0f: 12.925 on v3) is reported on the S8 frames screen (S5) for comparison only. It never enters `design_effect` or `effective_n`.
5. `estimate_icc(outcomes_by_psu)`: one-way ANOVA estimator on binary face-level outcomes (one value per GT face), grouped by psu_id through the face → image → component map. The ANOVA runs on faces, not images. The estimator is floored at 0 and returned with the number of PSUs. If all outcomes are equal (all zero or all one), the observed ICC is undefined and is returned as null. The planning ICC is a manifest input and sets deff and n_eff; this function supplies the observed one after a run, for reporting only.
6. `identity_disjoint_folds(component_map, identity_to_component, *, k, seed)`: assigns whole PSU components to k folds. Every identity of a component shares that component's fold, and no PSU is split across folds. Identities are never assigned on their own. Each rotation names one held-out test fold; the other folds are calibration (fit) folds.
7. `build_nonmated_pool(faces, images, folds, *, fold)`: returns the immutable non-mated source-unit inventory for `fold`, built from the exhaustive frame only.
   - Non-mated GT faces: `identity_status == unknown` with the frame's `exhaustive` flag set, and faces of identities held out in `fold`.
   - One background unit per frame image, id `background:<image_id>`.
   - Each unit carries the fold of its component.
   - The inventory is never derived from detector output, and the function takes no detector argument.
   - `unresolved` faces are refused as non-mated; passing one raises `FrameContractError`.
   - Returns the units, `N_units` (their count) and `n_nonmated_eff` = N_units / deff of the units' PSU structure, computed with Build 4.
8. `Frame` (frozen): spec, images, faces, psu map, folds, `identity_fold` (identity_id → fold), `gallery_sha256` per fold, deff at the manifest ICC, n_eff, `N_units` and `n_nonmated_eff` (from Build 7), per-arm counts. Per rotation, each fold has a role: calibration folds are `fit`, the held-out fold is `test`. Arms stay separate; the probability arm carries inclusion probabilities for IPW in S3. S3 reads `n_nonmated_eff` to decide whether the primary FPIR is resolvable; a frame does not decide admissibility by itself.

## RED tests

- Sizes [1, 1, 2, 4] (face counts): M̃ = 22/8 = 2.75; deff at ICC 0.10 = 1.175.
- One image with three GT faces in one component gives face-count m = 3 and image-count m = 1, and `design_effect` uses the face count.
- All-zero outcomes: `estimate_icc` returns null, and deff and n_eff still come from the manifest ICC.
- Two images sharing identity A, and one image sharing identity B with the second image, form one PSU. A duplicate pair joins the same PSU.
- Identities co-occurring in one image land in one fold.
- An unknown face in a shared image adds no identity edge and does not change the component.
- A synthetic sibling (`synthetic_parent_id` set) lands in its parent's component and fold.
- An `unresolved` face never enters the non-mated pool. Requesting it raises `FrameContractError`.
- Folds are identity-disjoint, and a PSU is never split across folds.
- The non-mated pool is identical with and without any detector output passed in (the function takes none). A no-face image contributes exactly one background unit.
- Loader rejects a manifest missing an identity field.
- Same inputs and seed give byte-identical `Frame` JSON.

## Done when

Tests pass on the VM. Owns AE-1 parts (PSU and deff known answers) and AE-9 (detector-dependent denominator refusal).

## Out of scope

Reading real private files in tests; selecting samples (the population draft already exists); calibration-probe checks, which are in S3 Build 3.
