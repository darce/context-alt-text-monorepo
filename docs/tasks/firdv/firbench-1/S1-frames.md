# S1 · Frames, PSU components, folds, non-mated pool, design effect

- **Wave:** W3 batch B · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** S0
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_frames.py`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_frames.py`

## Goal

Turn a frame source into the units every interval depends on. The independent unit is the image–identity connected component, not the image (AUDIT-11, EXP-23). The non-mated population is fixed and never depends on detector output (EVAL-18, EVAL-19).

## Read first

- README shared names; S0 `FrameSpec`, `Admissibility`, `FrameContractError`
- `scripts/eval_harness/gallery_split.py`: `build_disjoint_galleries(*, templates_by_subject, seed)`, `Template`, `GallerySplit`, `probes_for`
- `scripts/eval_harness/pilot_draw.py` and `audit_sampling.py` (bounded reads) for how arms and inclusion probabilities are represented
- W2 inventory § "Frame sources" for the exact field names of the Golden-150 manifest, corpus manifest v3r and the fir-occ population file

## Build

1. `FrameSource` records: `ImageUnit(image_id, sha256, arm, inclusion_probability | None, duplicate_group | None)` and `GtFace(face_id, image_id, box, identity_status, identity_id | None)`. `identity_status` is `named`, `unknown` or `unresolved`.
2. Loaders: `load_golden_manifest(path)`, `load_corpus_manifest(path)`, `load_population_draft(path)`. Each validates structure at load time and raises `FrameContractError` with the offending key [rg-008].
3. `build_psu_components(images, faces) -> dict[image_id, psu_id]`: union-find over the bipartite image–identity graph plus exact-duplicate groups. Unknown and unresolved faces never join components through identity. psu_id is the sorted smallest image_id in the component, so it is deterministic.
4. `size_weighted_mean(psu_sizes)`: M̃ = Σm² / Σm. `design_effect(psu_sizes, icc)`: 1 + (M̃ − 1)·icc. `effective_n(n, deff)`.
5. `estimate_icc(outcomes_by_psu)`: one-way ANOVA estimator on binary outcomes, floored at 0, returned with the number of PSUs. The planning ICC is a manifest input; this function supplies the observed one after a run.
6. `identity_disjoint_folds(identity_ids, *, k, seed)`: identities, never images, assigned to folds; a PSU never spans folds.
7. `build_nonmated_pool(faces, folds, *, fold)`: verified zero-identity faces (`identity_status == unknown` with the frame's `exhaustive` flag set) plus the identities held out in `fold`. `unresolved` faces are refused as non-mated (raise if a caller passes one explicitly). Returns the pool and `n_nonmated_eff` from the PSU structure.
8. `Frame` (frozen): spec, images, faces, psu map, folds, deff at the manifest ICC, n_eff, per-arm counts. Arms stay separate; the probability arm carries inclusion probabilities for IPW in S3.

## RED tests

- Sizes [1, 1, 2, 4]: M̃ = 22/8 = 2.75; deff at ICC 0.10 = 1.175.
- Two images sharing identity A and one sharing identity B with the second image form one PSU. A duplicate pair joins the same PSU.
- An `unresolved` face never enters the non-mated pool. Requesting it raises `FrameContractError`.
- Folds are identity-disjoint, and a PSU is never split across folds.
- The non-mated pool is identical with and without any detector output passed in (the function takes none).
- Loader rejects a manifest missing an identity field.
- Same inputs and seed give byte-identical `Frame` JSON.

## Done when

Tests pass on the VM. Owns AE-1 parts (PSU and deff known answers) and AE-9 (detector-dependent denominator refusal).

## Out of scope

Reading real private files in tests; selecting samples (the population draft already exists).
