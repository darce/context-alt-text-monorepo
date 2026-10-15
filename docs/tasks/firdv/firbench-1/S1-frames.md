# S1 · Frames, PSU components, folds, non-mated source units, design effect

- **Wave:** W3 batch B · **Depends on:** S0
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

1. `FrameSource` records: `ImageUnit(image_id, sha256, sampling_arm: SamplingArm, inclusion_probability | None, duplicate_group | None, session_id | None, synthetic_parent_id | None)` and `GtFace(face_id, image_id, box, identity_status: IdentityStatus, identity_id | None, cohort | None)`. `cohort` holds `sex`, `age_band` and `origin` when the frame carries them, each a string or None. The current `GtFace` also carries `annotation: FaceAnnotation`, with occluders, visibility, tier, exhaustiveness, provenance/rule IDs and observation/QC references; preserve that evidence at the runtime boundary. `session_id` and `synthetic_parent_id` are optional; a missing field adds no edge. `inclusion_probability` is set on the `probability` sampling arm and None on `challenge`. `ImageUnit` has no persisted `data_origin` member. The scores IO derives `data_origin` from the image and explicit run provenance: `synthetic` when `synthetic_parent_id` is set, `real` only with explicit real-origin provenance, and `unknown` otherwise. Absence never means real. It is not a `frame-v1` field, so `schema_version` stays 1 (MCP 16810).
2. Loaders: `load_golden_manifest(path)`, `load_corpus_manifest(path)`, `load_population_draft(path)`. Each validates structure at load time and raises `FrameContractError` with the offending key [rg-008, repo rule]. Persisted Golden manifests are document-homogeneous: `annotation_mode` belongs to `GoldenManifest`, never `GoldenEntry`. Only flattened raw score mappings receive parent stamps; mixed, missing or empty modes fail closed, and requesting exhaustive cannot upgrade roster-only evidence (MCP 16763). The S1 Golden loader rejects per-entry modes; callers must preserve the parent contract through the existing manifest/report consumers.
3. `build_psu_components(images, faces) -> dict[image_id, psu_id]`: union-find over one graph whose edges are: image–identity for named faces; exact-duplicate groups; shared `session_id`; and `synthetic_parent_id`, which joins a synthetic sibling to its parent image. Unknown and unresolved faces add no identity edge, so an unknown face in a shared image joins nothing; the image still joins through its named identities. An image with no GT face is its own component. psu_id is the sorted smallest image_id in the component, so it is deterministic. Components are computed before any fold is assigned.
4. Inventory sizes and design effect, in GT-face counts. Nonmated pool sizing separately counts source units (Build 7); S3 inference separately counts actual available mated queries. Every planning design effect and n_eff uses the manifest `planning_icc` (S0 Build 2).
   - PSU size m = number of GT faces in the component. Components with m = 0 are excluded from the size statistics below and still resample as their own PSU.
   - `size_weighted_mean(psu_sizes)`: M̃ = Σm² / Σm over components with m ≥ 1. This is the face-count M̃.
   - `design_effect(psu_sizes, icc)`: 1 + (M̃ − 1)·icc, with the face-count M̃.
   - `effective_n(n, deff)`: n / deff, a float used for sizing and reporting the explicitly named inventory, mated-query or nonmated source-unit denominator. It is never passed to a binomial function as n.
   - The image-count M̃ from the corpus manifest (report §0f: 12.925 on v3) is reported on the S8 frames screen (S5) for comparison only. It never enters `design_effect` or `effective_n`.
5. `estimate_icc(outcomes_by_psu)`: one-way ANOVA estimator on binary face-level outcomes (one value per GT face), grouped by psu_id through the face → image → component map. The ANOVA runs on faces, not images. The estimator is floored at 0 and returned with the number of PSUs. If all outcomes are equal (all zero or all one), the observed ICC is undefined and is returned as null. The planning ICC is a manifest input and sets deff and n_eff; this function supplies the observed one after a run, for reporting only.
6. `identity_disjoint_folds(component_map, identity_to_component, *, k, seed)`: assigns whole PSU components to k folds. Every identity of a component shares that component's fold, and no PSU is split across folds. Identities are never assigned on their own. Each rotation names one held-out test fold; the other folds are calibration (fit) folds. The primary rotation's test fold is `fold_protocol.seed % fold_protocol.k` (0 for the committed values). The run driver derives it, and no field is added (MCP 16810).
7. `build_nonmated_pool(faces, images, folds, *, fold, component_map, exhaustive, planning_icc, enrolled_identity_ids: frozenset[str])`: returns the immutable non-mated source-unit inventory for `fold`, built from the exhaustive frame, the declared enrollment and the fixed PSU map only (MCP 16756, 16810).
   - `enrolled_identity_ids` is a required keyword with no default. Omitting it raises `TypeError`. A value that is `None`, not a `frozenset`, or has a non-string member raises `FrameContractError`. An explicit `frozenset()` is a declared empty gallery and is accepted.
   - Non-mated GT faces: `identity_status == unknown` with the frame's `exhaustive` flag set and the face's PSU in `fold`; or `named` with the identity in `fold` and absent from `enrolled_identity_ids` (MCP 16810). Fold membership and enrollment are separate axes, so neither implies the other.
   - One background unit per frame image, id `background:<image_id>`.
   - Each unit carries the fold of its component.
   - The inventory is never derived from detector output, and the function takes no detector argument.
   - `unresolved` faces are refused as non-mated; passing one raises `FrameContractError`.
   - Returns a `NonMatedPool` (frozen): `units` (tuple of `NonMatedUnit`, each with `unit_id`, `fold`, `psu_id`, `cohort` or None for background units), `n_units` (their count) and `n_nonmated_eff` = n_units / deff of the units' PSU structure, computed with Build 4 at `planning_icc`.
8. `Frame` (frozen) and `build_frame` (required `enrolled_identity_ids: frozenset[str]` keyword for the test gallery, MCP 16810): spec, images, faces, psu map, folds, `identity_fold` (identity_id → fold), `gallery_sha256_by_fold` per fold, deff at `planning_icc`, n_eff, `n_units` and `n_nonmated_eff` (from Build 7), per-`SamplingArm` counts. Per rotation, each fold has a `FoldRole`: calibration folds are `fit`, the held-out fold is `test`. Sampling arms stay separate; the `probability` arm carries inclusion probabilities for IPW in S3. S3 reads `n_nonmated_eff` to decide whether the primary FPIR is resolvable; a frame does not decide admissibility by itself. `Frame` is written as `frame-v1` (S0 Build 9).
   - `enrolled_identity_ids` is the test gallery for this frame. It goes to Build 7 and is never inferred from folds, predictions or detections (MCP 16810).
   - Primary rotation: `test_fold = fold_protocol.seed % fold_protocol.k`, preregistered and derived by the run driver (0 for the committed values). The other folds pool as `fit`. Other rotations are unsealed development diagnostics. They are not pooled into a confirmatory CV verdict and never read the sealed frame (MCP 16810).
   - `n_eff` is `effective_n(len(faces), deff)` over the whole GT inventory. S3 inference uses actual mated query counts, and `Frame.n_eff` is never a binomial n (MCP 16810).
   - `gallery_sha256_by_fold` keeps its `frame-v1` shape (one caller-supplied hash per fold, chosen from a declared primary native leg whose basis is persisted). It does not define the searched gallery. The searched membership and each leg's gallery hash are in `manifest.firbench.gallery_membership` (README run artifacts).
   - `frame.json` is the validated `frame-v1` payload. The run driver writes it with the membership record before any search, ledger or score output (MCP 16810).

## Current producer and runtime handoff

`firbench_frames` implements these enrollment keywords, PSU components/folds, annotation records and frame serialization today. `Frame.n_eff` remains whole-GT inventory; score inference uses actual mated queries. The file scorer, legs and default CLI runtime binding are implemented. The following MCP 16848/16855 contracts describe the landed binding, not measured private inputs:

- Resolve the [README runtime binding](README.md#run-artifacts-layout-the-cli-writes-semantic-files-immutable-once-written) at `benchmarks/private/firbench/inputs/<frame_id>.json`, schema `firbench-inputs/v1`. It names query kind/path/SHA and separate template document path/SHA. Verify against `FrameSpec.source_sha256`/`GalleryLineage.templates_sha256`. The landed `firbench_runtime.InputBinding` and `TemplateRow` define exact fields; no automatic sample fallback, new CLI flag, operator choice or downloads. Refuse query/enrollment media or hash overlap rather than dropping queries; missing context/assets/hash/GT is a named refusal.
- Known identity folds come from canonical S1 PSUs. Template-only identities use a declared full map or deterministic pre-outcome seed binding; persist the full map. No pending operator rule is needed. Per query fold, use only its identity-eligible template roster and actual `gallery_split.build_disjoint_galleries` with the manifest split seed, fixed G1 direction. G2/nonenrolled identities are non-mated; never infer identities from model predictions.
- All native legs share per-fold membership, with their own vectors/hashes. Registry rows cover every leg key/fold, including attribution with shared native membership. Choose and persist the primary native hash basis for `Frame.gallery_sha256_by_fold`. Persist full validated `frame.json` and registry before query outcomes; templates/membership can be prepared first without query scores.
- DRIVER authorization precedes source/GT/template/pixel reads; cache authorized pixels in RAM, never reopen for scoring. Default collaborators are lazy. Real tier-a rows must pass `fir_occ_labels.require_real_analysis_rows` and qualified QC/observation evidence before annotation loss; reference strings alone are insufficient. Query failure retains immutable declarations and failure evidence, without invalid outcomes; static refusals known before protected reads write/spend nothing. Qualification requiring sealed GT/source reads stays after S0 token consumption; refusal is then a failed attempt without refund. S7 freezes the exact read closure into run-local evidence before query outcomes, and the report requalifies it against the actual frame bytes.

The primary test remains `seed % k`, the remaining folds pooled fit, and other rotations unsealed diagnostics without pooled confirmatory claims. Required enrollment context, explicit empty galleries, exhaustive-GT/nonmated units, timestamp/receipt boundaries and every numeric gate remain in force.

## GT inventory, source authority and remaining evidence

Source locators: [S1 producer](../../../../apps/prototype-description-service/scripts/eval_harness/firbench_frames.py) `build_psu_components`, `build_nonmated_pool`, `build_frame`, `frame_json`; [score IO](../../../../apps/prototype-description-service/scripts/eval_harness/firbench_score_io.py) `_inventory`, `_records`, `_face_outcomes`. These named-path reads establish the following contracts.

Keep every independently annotated GT face, including upstream detection misses, fit rows and unresolved identities. `build_psu_components` uses the full inventory; unknown/unresolved faces add no identity edge. The strict `build_nonmated_pool` API refuses unresolved input, and `build_frame` currently passes its entire face sequence to that API, so that builder also refuses an unresolved face. Do not work around this refusal by erasing GT or relabelling it unknown. In contrast, the landed file scorer's `_inventory` retains full GT and passes only identity-resolved faces to pool construction. Its optional `face_outcomes` view retains unresolved rows with null membership/outcome, and fit rows with null outcomes and named reasons; other eligible scored rows remain usable. See [S3 output contract](S3-score.md#build). This distinction records actual producer behavior, not a new loader capability.

`Frame.n_eff` describes whole-GT inventory. Mated inference n_eff uses the actual available mated queries in the primary-test probability arm, including upstream misses. Nonmated n_eff uses the fixed source-unit PSU sizes, including backgrounds, independently of detections. Adding negatives cannot raise mated power; neither inventory n_eff nor the global 50-PSU floor establishes adequacy. Preserve canonical `image_id` plus exact `ImageUnit.sha256` and the duplicate-unit PSU rule when joining media aliases.

Canon v0.26.2: [AUDIT-11] **Account for cluster design effect**, *Sampling: Design and Analysis*, ch. 5; [EXP-23] **Pseudoreplication check**, *Statistics Done Wrong*, ch. 3; [EVAL-16] **Upstream failure counts against the end-to-end metric**, [EVAL-19] **Do not let detector alarms dilute FPIR**, both *IARPA Janus Benchmark-C*, § 2.3.4. These govern separate sizing and independent GT accounting; they do not supply project floor/ICC constants. Detector-independent exhaustive GT and detector-only comparison preserve the MAINT-FIR-DETECTION-20260919 correction.

Implemented readers, materialization and S7 proof replay establish software mechanisms only. Real source/template bindings, exhaustive independent GT, admissible counts, human observation/QC, ratification, seal and budget evidence remain unestablished. Existing software receipts are prior overlapping evidence as recorded in [S0](S0-contract.md#adjudication-evidence-and-limits); S9 implementation remains unaccepted.

## RED tests

- Sizes [1, 1, 2, 4] (face counts): M̃ = 22/8 = 2.75; deff at ICC 0.10 = 1.175.
- One image with three GT faces in one component gives face-count m = 3 and image-count m = 1, and `design_effect` uses the face count.
- All-zero outcomes: `estimate_icc` returns null, and deff and n_eff still come from the manifest ICC.
- Two images sharing identity A, and one image sharing identity B with the second image, form one PSU. A duplicate pair joins the same PSU.
- Identities co-occurring in one image land in one fold.
- An unknown face in a shared image adds no identity edge and does not change the component.
- A synthetic sibling (`synthetic_parent_id` set) lands in its parent's component and fold.
- An `unresolved` face never enters the `NonMatedPool`. Requesting it raises `FrameContractError`.
- Folds are identity-disjoint, and a PSU is never split across folds.
- The `NonMatedPool` is identical with and without any detector output passed in (the function takes none). A no-face image contributes exactly one background unit.
- Loader rejects a manifest missing an identity field.
- Same inputs and seed give byte-identical `Frame` JSON, and that JSON validates against `frame-v1`.
- With `planning_icc` = 0.10 the design effect uses it, and changing only the observed ICC from `estimate_icc` leaves `deff` and `n_eff` unchanged.
- `build_nonmated_pool` and `build_frame`: an omitted `enrolled_identity_ids` raises `TypeError`. A value that is `None`, not a `frozenset`, or has a non-string member raises `FrameContractError`. An explicit `frozenset()` builds, and every named face in the fold is then non-mated (MCP 16810).
- A named face in the fold is excluded from the pool when its identity is in `enrolled_identity_ids` and included when it is absent, with its fold unchanged. Fold membership alone does not decide enrollment (MCP 16810).
- The pool is unchanged when enrolled identities with no GT face in the frame are added or removed (MCP 16810).
- `Frame.n_eff` equals `effective_n(len(faces), deff)` over the whole GT inventory, including faces that are mated for the primary test fold (MCP 16810).
- `build_frame` with `test_fold = seed % k` marks that fold `test` and every other fold `fit` (MCP 16810).
- `data_origin` is `synthetic` when `synthetic_parent_id` is set, `real` only with explicit provenance, and `unknown` otherwise. A missing field never yields `real` (MCP 16810).

## Done when

Tests pass on the VM. Owns AE-1 parts (PSU and deff known answers) and AE-9 (detector-dependent denominator refusal). The MCP 16810 enrollment and primary-rotation tests above also pass on the VM.

## Out of scope

Reading real private files in tests; selecting samples (the population draft already exists); calibration-probe checks, which are in S3 Build 3.
