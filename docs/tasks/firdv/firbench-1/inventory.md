# FIRBENCH-1 · W2 inventory (VM-measured)

## 0. Environment and provenance

| Item | Value | Command / source |
| --- | --- | --- |
| Host | acx-backend, aarch64, Linux 6.17.0-1011-oracle | `uname -a` |
| Python / uv | 3.12.7 / uv 0.11.21 | `python3 --version`, `uv --version` |
| Thread env for all probes | OMP/OPENBLAS/MKL = 1 | set per command |
| Brief SOURCE HEAD | `b6dcaad70f93c2d385d30b31b148e83265d43874`; equivalent history-stripped transport tree per recorded dispatch provenance | Recorded `git cat-file -t b6dcaad…` failure is expected: original commit object unavailable, not a source mismatch or blocker |
| Checkout HEAD | `439cc18` in the completed source artifact; adjudication transport base `97ffc24` | Recorded / current `git rev-parse --short HEAD`; commit IDs differ under history stripping |
| Lane branch | Source `feature/firbench-1-w2-inventory`; adjudication `feature/firbench-1-w2-inventory-adj` | Recorded / current `git branch --show-current` |
| Canon | v0.26.2, read-only pinned mirror `/home/gate/firbench-1-context/canon-0.26.2`; rule IDs cited at use | Present manifest-listed files verified against `meta/release-manifest.json` (16 digests); mirror is partial |
| Evidence scope | Completed W2 artifact copied from `/home/gate/firbench-1-context/w2-inventory/inventory.md`; original probes retained as records | Adjudication rechecks tracked manifests/arithmetic and explicit paths only; no inference, downloads, package changes, or other tasks' sandbox/private-file searches |
| Location correction, 2026-10-15 | FB1-LOC-INV-01; dispatch SOURCE `44e9c285b80575bd41634def2572c9e0e4a949ae` | Supplied source tree governs the history-stripped checkout; coordinator MCP16912 supplies the three verified weight locations in §1a. Historical probes do not establish VM-wide absence. |

## 1. Leg pins (VM)

### 1a. Model files

The three confirmed paths below supersede their historical not-found results as of 2026-10-15. Coordinator MCP16912 verified each file's full SHA-256 and byte count against these pins; this correction does not repeat that check. It establishes weight availability only, not live runtime, container configuration, model loading, or inference. The buffalo_l record retains its original probe scope.

| Leg | File | Pinned bytes | Pinned sha256 | Confirmed location / recorded scope | Evidence |
| --- | --- | --- | --- | --- | --- |
| sface | `face_recognition_sface_2021dec.onnx` (provenance.py:119–127) | 38,696,353 | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` | `/opt/acx-backend/data/dev-models/face_pipeline/face_recognition_sface_2021dec.onnx` | **confirmed**, MCP16912, 2026-10-15 |
| auraface | `glintr100.onnx` (HF `fal/AuraFace-v1` @ `af6d057c9b0ec4071d4c49c80e3539258798b609`; provenance.py:136–144) | 260,694,151 | `a7933ea5330113b01c9b60351d8f4c33003f145d8470ac5f0e52ee2effe25c60` | `/opt/acx-backend/data/dev-models/face_pipeline/glintr100.onnx` | **confirmed**, MCP16912, 2026-10-15 |
| yunet (context) | `face_detection_yunet_2026may.onnx` | 229,738 | `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` | `/opt/acx-backend/data/dev-models/face_pipeline/face_detection_yunet_2026may.onnx` | **confirmed**, MCP16912, 2026-10-15 |
| buffalo_l | `~/.insightface/models/buffalo_l/` (5 ONNX + zip; see 1b) | see 1b | see 1b | **found** | `sha256sum` |

| File | sha256 | Matches pin |
| --- | --- | --- |
| `LICENSE.sface` | `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` | yes |
| `LICENSE.auraface.md` | `609e2cb599f84aaa41d8ef29d8fdb04d164fab22e8d9292ca34a599d0f56a338` | yes |
| `LICENSE.yunet` | `c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958` | yes |

### 1b. buffalo_l (judge-side InsightFace root)

| File | Bytes | sha256 |
| --- | --- | --- |
| `buffalo_l.zip` (in `~/.insightface/models/`) | 288,621,354 | `80ffe37d8a5940d59a7384c201a2a38d4741f2f3c51eef46ebb28218a7b0ca2f` |
| `buffalo_l/w600k_r50.onnx` | 174,383,860 | `4c06341c33c2ca1f86781dab0e829f88ad5b64be9fba56e56bc9ebdefc619e43` |
| `buffalo_l/det_10g.onnx` | 16,923,827 | `5838f7fe053675b1c7a08b633df49e7af5495cee0493c7dcf6697200b85b5b91` |
| `buffalo_l/1k3d68.onnx` | 143,607,619 | `df5c06b8a0c12e422b2ed8947b8869faa4105387f199c477af038aa01f9a45cc` |
| `buffalo_l/2d106det.onnx` | 5,030,888 | `f001b856447c413801ef5c42091ed0cd516fcd21f2d6b79635b1e733a7109dbf` |
| `buffalo_l/genderage.onnx` | 1,322,532 | `4fde69b1c810857b88c64a335084f1c3fe8f01246c9a191b48c7bb756d6652fb` |

### 1c. Runtime versions and manifest dataclasses

| Item | Value |
| --- | --- |
| Probe | `uv run --directory apps/prototype-description-service --locked python -c …` (default env, no extras) |
| `opencv-python` | 5.0.0.93 |
| `opencv-python-headless` | not installed in default env (bench extra only) |
| `onnxruntime` | 1.28.0 |
| `onnxruntime-gpu` | not installed |
| `numpy` / `scipy` / `hdbscan` | 2.5.1 / 1.18.0 / 0.8.44 |
| `umap-learn` | not installed; not declared in `pyproject.toml` or `uv.lock` |
| `insightface` | not installed in default env (see §8) |
| `sface_embedding_model_manifest()` (face_pipeline_adapter.py:315) | `EmbeddingModelManifest(framework='opencv', name='sface+cv5.0.0/ort1.28/np2.5.1', dimensions=128, normalization='l2', metric='cosine')` |
| `auraface_embedding_model_manifest()` (face_pipeline_adapter.py:339) | `EmbeddingModelManifest(framework='insightface', name='auraface+cv5.0.0/ort1.28/np2.5.1', dimensions=512, normalization='l2', metric='cosine')` |
| `numeric_runtime_fingerprint()` | opencv 5.0.0, ort 1.28.0, numpy 2.5.1, scipy 1.18.0, pillow 12.3.0, hdbscan 0.8.44, pgvector 0.5.0 |

### 1d. AuraFace weight paths probed on the VM

Retained bounded observations from before the 2026-10-15 supersession in §1a; the original probe dates were not recorded here. These checks were not repeated for this correction. The historical `load_verified_model('sface')` and `load_verified_model('auraface')` calls raised `ModelMissingError`, and the default models-directory listing did not find YuNet. None tested the now-confirmed paths in §1a.

| Check | Result |
| --- | --- |
| `RECOGNITION_AURAFACE_MODELS_DIR`, `ACX_MODELS_PATH` | unset in this shell; `.env.auraface.example` points at a compose mount `/data/cache/face_pipeline` |
| `/data/cache/face_pipeline` | absent (`ls -d`) |
| `find` for `glintr100.onnx` under `~/.cache`, `/home/gate/dep-cache`, `/home/gate/cache-warm`, `/home/gate/models`, `~/.insightface` (maxdepth 7) | no hit outside pytest scratch dirs; scratch copies are not pinned or used |
| Default models dir (`provenance.py:36`) | `recognition/infrastructure/face_pipeline/models/`: 3 licence files, README, .gitignore; **no ONNX weights** |
| Result | **Historical: not found in the listed probed paths. Superseded 2026-10-15 for the three weights in §1a only.** The recorded maxdepth-7 search is bounded coverage, not a VM-wide absence claim; it does not resolve other locations or assets. |

## 2. Corpus on the VM

> **Supersession, 2026-10-15.** The probe rows in this section that report the 646-image corpus directory, the 646 unresolved entries, or missing sha256 correspondence as "not found" or "unestablished" are bounded historical records of the explicitly inspected paths. They are **superseded** as statements about the corpus. The laptop primary checkout holds the originals: 643 of 646 entries match `sha256_source` exactly, 0 mismatch, and 3 entries are absent per its local provenance file (named there, not here). The recorded probe found no `benchmarks/images/` in the inspected VM checkout; corpus availability elsewhere on the VM remains unknown. Corpus locator authority: logical ID `corpus646-originals` in the tracked catalog, resolved by the shared resolver. Canonical benchmark home, status, and read-only check: [`benchmarks/README.md` § Images](../../../../benchmarks/README.md#images). Counts in this section are dated observations, not live catalog facts.
>
> Remaining gap, not established by these records: no independently exhaustive human ground truth, no observation or QC record of measurement production, and no capture-occasion independence found (§10 flag 13). This is not a global-absence claim.

The private, ignored source archive is recorded as present on the laptop. It is not an active fallback or source of truth for the catalog; presence and authorized source-archive lineage do not confer benchmark eligibility or supply the missing evidence above. Follow the operator's existing authorization and explicit preference to keep pixels out of remote Git; private alias maps remain laptop-only.

| Item | Value | Command / source |
| --- | --- | --- |
| Corpus manifest (v3r, tracked) | `benchmarks/manifests/corpus-manifest-v3r-20260814.json`, 646 entries, sha256 `2d9d5ba3e04bcfa7ea29f960b2fdc05431bdae7993bd22042a5369ceee7d9bff` | `git ls-files \| grep corpus-manifest`; `sha256sum` |
| Corpus manifest (v3, tracked) | `benchmarks/manifests/corpus-manifest-v3.json`, sha256 `154eb2b735f947e5ce670886bb848fc2749aad5e952a448a4f1b75f3125abe7e` | same; this is the file Golden-150 selection names |
| v3r `images_root` | macOS laptop home path; does not establish a usable location in the probed VM paths. It points at a deleted worktree's derived cache: the resolver ignores it, and the frozen manifest is not rewritten | key read only |
| Hash basis | `sha256_space = downscaled`, `sha256_source_space = original`; `sha256` differs from `sha256_source` on 358 entries | key read, counts only |
| Catalog-resolved root, logical ID `corpus646-originals` | `<primary checkout>/benchmarks/images/corpus646/originals/<bucket>/<file>` (gitignored; checked against `sha256_source`; canonical locator and shared `show` / `check` commands in [`benchmarks/README.md` § Images](../../../../benchmarks/README.md#images)) | Primary checkout discovery and explicit `--corpus-root` override follow that resolver; layout alone does not establish VM presence |
| `benchmarks/images/` in the inspected VM checkout | **Historical: not found**: recorded `ls -d benchmarks/images` → absent in that checkout only; elsewhere on the VM unknown | — |
| `GOLDEN_IMAGES_DIR` | unset | `echo "$GOLDEN_IMAGES_DIR"` |
| 646-image corpus directory | **Superseded 2026-10-15:** present on the laptop primary checkout (see note above). On this VM, **not found in probed paths**: recorded `find` (repo maxdepth 4, `/home/gate` maxdepth 3) for `corpus646`, `originals`, `downscaled`, `mock_images`, `eval-fixtures`; other locations unresolved | Tried `find` retained as historical bounded coverage, not repeated across home/sandboxes; `~/Development/eval-fixtures` absent |
| Golden-150 image directory | **not found in probed paths**: same recorded search; location unresolved. Not covered by the v3r observation above | same bounded coverage |
| Files whose sha256 matches v3r | **Superseded for the laptop primary:** 643 exact `sha256_source` matches, 3 absent, 0 mismatched (dated 2026-10-15 observation; live counts from `check corpus646-originals`). **Unestablished in the recorded VM probe scope:** those probes located no corpus files for hashing; other VM locations and VM-wide match counts remain unknown | §2 explicit path probes only; no global zero-match or 646-mismatch claim |
| Unresolved image entries in measured scope | **Superseded:** 643 resolved on the laptop primary; 3 absent per its provenance file. The recorded VM probes established no source-hash correspondence for the 646 entries within their inspected paths; elsewhere on the VM unknown | no ids listed; not a global missing-ids claim |

## 3. Frame sources (keys only)

| Source | Top-level keys | Entry keys | Notes |
| --- | --- | --- | --- |
| Golden-150 manifest `benchmarks/manifests/golden150-draft-20260723.json` (sha256 `0dc89a1d0378630522a16080a176c1533357419fcfbe704a7c2bfc487580ac54`, manifest_version 2) | entries, manifest_version, roster | base_caption, context_pack, easy_wrong, face_boxes, face_count, media_id, must_right, path, policy, present_identities, provenance, sha256, tags | 150 entries; `roster` is a list of 54 non-dict items |
| Golden-150 sidecar `…golden150-draft-20260723.sidecar.json` | build_notes, celeb_provenance_skipped, clamp_log, counts, created, media, schema | media keyed by media id | `counts` keys: boxes_named, boxes_operator, boxes_stranger, boxes_total, provenance_celeb, provenance_operator |
| Corpus manifest v3r | built_at, consent, counts, derived_tag_caveat, derived_tag_rules, detector, dropped_from_source, duplicate_groups, entries, identities, images_root, manifest_version, naming_convention, sha256_source_space, sha256_space, sources | bucket, bytes, caption, detected_boxes, detected_face_count, flags, height, media_id, named_boxes, named_face_count, named_identities, path, policy, primary_identity, provenance, sha256, sha256_source, slice_tags, slice_tags_derived, slice_tags_known, slice_tags_source, slug, width; optional `duplicate_of` (6 entries) | `identities[]` keys: appearance_count, appears_in, bucket, name, naming, primary_count, primary_of, slug. `detected_boxes[]` keys: bbox, blur_var, eye_span_ratio, face_area_frac, face_min_side, interocular_ratio, landmarks, nose_offset, roll_deg, score, yaw_eye, yaw_mouth. `named_boxes[]` keys: h, name, source, w, x, y |
| Gate contract `benchmarks/manifests/fir-gate-contract-v1.json` (sha256 `22963fdc5ff6aa0dd9463ce6468d967783a0d998360d0f79e7ee2da456740573`) | max_fpi, metric, n_nonmated_declared, ratified_by_decision_id, rubric_version, t14_exhaustive_subset_count, t14_exhaustive_subset_sha256, t14_thresholds_declared, t14_thresholds_sha256 | — | verified null or empty: `max_fpi`, `n_nonmated_declared`, `t14_exhaustive_subset_count`, `ratified_by_decision_id`. These P0 values stay null. |
| fir-occ population draft | — | — | laptop-only: coordinator supplies a pseudonymized frame file |

## 4. PSU structure (corpus manifests)

| Item | Method |
| --- | --- |
| PSU components | union-find over the 646 images; edges = shared `named_identities` + 3 `duplicate_groups` (member paths resolved to entries); `session_id` / `synthetic_parent_id` are absent in both manifests, so they add no edge; actual independence remains unverified |
| Face count m / image count m | `named_face_count` (584 named GT boxes) / images per component; every image is a node, so an unidentified image is its own component |
| Conditional design effect | `deff = 1 + (M̃ − 1) × ICC`, `n_eff = n/deff`; face M̃ covers the 584 named boxes only, image M̃ the 646 images. Neither describes the complete unknown/background source-unit population. [AUDIT-11] Account for cluster design effect (*Sampling: Design and Analysis*, ch. 5). |

| Metric | v3r (tracked, the frame of record) | v3 (tracked, comparison) |
| --- | --- | --- |
| Image–identity components, duplicate edges applied | **231** | 230 |
| Components before duplicate merge | 232 | 231 |
| Largest component (images) | 79 | 79 |
| Image-count sizes, min / median / max | 1 / 1 / 79 | 1 / 1 / 79 |
| Face-count sizes over m ≥ 1, min / median / max (components) | 1 / 2 / 88 (116 components) | 1 / 2 / 88 (116 components) |
| Components with m = 0 (excluded from face stats; still their own PSU) | 115 | 114 |
| Named GT faces, Σm | 584 | 584 |
| **M̃ face count** = Σm²/Σm over m ≥ 1 (named-face S1 value only) | **24.401** | 24.401 |
| M̃ image count = Σm²/Σm (comparison only) | 18.192 | 18.195 |
| Report §0f image-count M̃ 12.925 | **not reproduced** (scope §"What the current corpus can resolve" says the same) | not reproduced |
| Tracked claim on v3r (231 / 79 / M̃ 18.19 / deff 2.72 at 0.10 / n_eff ≈ 238) | **reproduced** (231 / 79 / 18.192 / 2.719 / 237.6) | — |

| ICC assumption (unmeasured) | deff, named-face M̃ | Hypothetical 646/face-deff, not nonmated n_eff | Conditional n_eff, 584 named GT faces | deff, image M̃ (comparison) | Conditional n_eff, image M̃, 646 images |
| --- | --- | --- | --- | --- | --- |
| 0.05 | 2.170 | 297.7 | 269.1 | 1.860 | 347.4 |
| 0.10 (working project policy; not observed ICC) | 3.340 | 193.4 | 174.8 | 2.719 | 237.6 |
| 0.20 | 5.680 | 113.7 | 102.8 | 4.438 | 145.5 |

## 5. Non-mated frame count (v3r)

| Item | Value | Command / basis |
| --- | --- | --- |
| Exhaustive-annotation marker | **not found**: `grep -o -i exhaust` gives 0 matches in v3r, v3 and the Golden-150 draft; `t14_exhaustive_subset_count` is null | `grep -o -i exhaust <file> \| wc -l` |
| Faces with zero identity on exhaustively annotated images | **unestablished**: no exhaustive population to define them; unresolved identities cannot enter the nonmated pool | §5 row above |
| Detected boxes, total / named GT boxes, total | 1,763 / 584 | Σ `detected_boxes` / Σ `named_boxes` |
| Images with `detected_face_count` = 0 | 41 (`flags.no_faces` says 38; the two fields disagree and are not resolved here) | key read |
| Identities with `appearance_count` ≥ 2 | **76 of 130** (v3: 77 of 137) | `identities[].appearance_count` |
| Identities with `appearance_count` = 1 | 54 (v3: 60) | same |
| Structural background placeholders (one per manifest image) | 646; not an admissible nonmated calibration pool without independent exhaustive GT | Delegated source-unit policy: one background unit per exhaustive image plus verified nonmated GT faces; duplicate alarms add no units. [EVAL-19] Do not let detector alarms dilute FPIR (*IARPA Janus Benchmark-C*, § 2.3.4). |
| Non-mated GT faces | **unestablished**: independent exhaustive annotation/identity verification needed | detector boxes are not exhaustive GT |
| Admissible non-mated source units, N_units; nonmated n_eff | **unestablished**; no ≥646 admissible floor; unknown/background PSU sizes and their M̃/deff are unmeasured | Named-face M̃ 24.401 and image M̃ 18.192 cannot supply the missing population |
| FPIR resolvability, 3/n_nonmated_eff | **unestablished**; hypothetical arithmetic only: 3 / 193.409… = **0.0155**, using N=646 and named-face deff at working ICC 0.10 | §4; if deff were fixed and N≥646 established, this value would be an upper bound, not a floor. Neither premise establishes the real pool. |
| Same hypothetical calculation, image-M deff | 3 / 237.570… = 0.0126; not established nonmated resolvability or a bound on it | §4 comparison only |
| Real measurement evidence gate | Independent exhaustive GT, one-to-one spatial matching, detector-only comparison before recognition interpretation; no human observation or QC evidence supplied by this inventory; protocol/QC nulls stay null | [MEAS-29] Observe measurement production (*Seeing with Fresh Eyes: Meaning, Space, Data, Truth*, ch. 4); bounded contextual observation remains required, never fabricated |
| Provenance file for the current 207-probe non-mated set | **not found**: `git ls-files \| grep -i -E 'nonmated\|non-mated\|non_mated'` → 0 hits. "207" appears only in report prose: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` and `benchmarks/reports/fir-executive-summary-20260728.md` (line 57) | `git ls-files \| xargs grep -l` |

## 6. Reused API signatures (S0–S7 "Read first")

| Symbol | file:line | Def line (as read) | Status |
| --- | --- | --- | --- |
| `GateContract` | scripts/eval_harness/gate_contract.py:45 | `class GateContract:` | exists |
| `load_gate_contract` | gate_contract.py:163 | `def load_gate_contract(path: str \| Path) -> GateContract:` | exists |
| `select_gate_point` | gate_contract.py:190 | `def select_gate_point(` (multi-line) | exists |
| `threshold_sha256` | gate_contract.py:144 | `def threshold_sha256(value: Mapping[str, object]) -> str:` | exists |
| `Template` | scripts/eval_harness/gallery_split.py:68 | `class Template:` | exists |
| `GallerySplit` | gallery_split.py:77 | `class GallerySplit:` | exists |
| `build_disjoint_galleries` | gallery_split.py:396 | `def build_disjoint_galleries(` (kw-only `templates_by_subject`, `seed`) | exists |
| `probes_for` | gallery_split.py:474 | `def probes_for(split: GallerySplit, *, gallery: …)` | exists |
| `pilot_draw.GoldItem` | scripts/eval_harness/pilot_draw.py:106 | `class GoldItem:` | exists |
| `audit_sampling.py` | scripts/eval_harness/audit_sampling.py | file, 825 lines | exists (no named symbol in the briefs) |
| `sface_embedding_model_manifest` | recognition/infrastructure/embeddings/face_pipeline_adapter.py:315 | `def sface_embedding_model_manifest() -> EmbeddingModelManifest:` | exists |
| `auraface_embedding_model_manifest` | face_pipeline_adapter.py:339 | `def auraface_embedding_model_manifest(*, _fingerprint=None) -> EmbeddingModelManifest:` | exists |
| `FacePipelineRuntime` | face_pipeline_adapter.py:295 | `class FacePipelineRuntime:` | exists |
| `FacePipelineFaceDetector` | face_pipeline_adapter.py:762 | `class FacePipelineFaceDetector(FaceDetectorProtocol):` | exists |
| `decode_image_bytes` | face_pipeline_adapter.py:372 | `def decode_image_bytes(image_bytes: bytes) -> np.ndarray:` | exists |
| `xywh_to_corner_bbox` | face_pipeline_adapter.py:364 | `def xywh_to_corner_bbox(bbox: …) -> tuple[int, int, int, int]:` | exists |
| `assert_three_way_embedding_dimensions` | face_pipeline_adapter.py:402 | `def assert_three_way_embedding_dimensions(manifest: EmbeddingModelManifest) -> None:` | exists |
| `_load_face_pipeline_runtime` | face_pipeline_adapter.py:588 | `def _load_face_pipeline_runtime(` | exists |
| `get_shared_face_pipeline_runtime` | face_pipeline_adapter.py:640 | `def get_shared_face_pipeline_runtime(` | exists |
| `BuffaloFusedLeg` | scripts/eval_harness/buffalo_bench.py:287 | `class BuffaloFusedLeg:` | exists |
| **`BuffaloLeg`** | — | — | **does not exist** (no def, class or reference in the service tree). S2 names it; the existing class is `BuffaloFusedLeg`. Flagged. |
| `process_image_bgr_buffalo` | buffalo_bench.py:400 | `def process_image_bgr_buffalo(` | exists |
| `l2_normalize` | buffalo_bench.py:169 | `def l2_normalize(vectors: np.ndarray) -> np.ndarray:` | exists |
| `build_baseline_leg` | buffalo_bench.py:385 | `def build_baseline_leg(` | exists (placeholder aligner; S2 does not use it) |
| `build_landmark_cache` | scripts/eval_harness/landmark_cache.py:170 | `def build_landmark_cache(` | exists |
| `LandmarkCache` | landmark_cache.py:117 | `class LandmarkCache:` | exists |
| `LandmarkCacheProvenance` | landmark_cache.py:51 | `class LandmarkCacheProvenance:` | exists |
| `detection_pr_strict` | scripts/eval_harness/face_metrics.py:782 | `def detection_pr_strict(` | exists |
| `associate_detections` | scripts/eval_harness/face_assignment.py:215 | `def associate_detections(` | exists |
| `SearchResult` | scripts/eval_harness/open_set_identification.py:35 | `class SearchResult:` | exists |
| `IETPoint` | open_set_identification.py:56 | `class IETPoint:` | exists |
| `fnir_fpi_at_threshold` | open_set_identification.py:128 | `def fnir_fpi_at_threshold(` | exists |
| `iet_curve` | open_set_identification.py:170 | `def iet_curve(` | exists |
| `identity_fold_assignment` | scripts/eval_harness/calibrate_face_thresholds.py:376 | `def identity_fold_assignment(decisions: Sequence[Decision]) -> dict[str, int]:` | exists |
| `build_trials` | calibrate_face_thresholds.py:471 | `def build_trials(` | exists |
| `select_fit_trials` | calibrate_face_thresholds.py:505 | `def select_fit_trials(` | exists |
| `holm_bonferroni` | scripts/bench/score_report.py:311 | `def holm_bonferroni(` | exists |
| `bootstrap_paired_delta` | scripts/bench/score_report.py:178 | `def bootstrap_paired_delta(` | exists |
| `build_experiment_manifest` | scripts/eval_harness/experiment_manifest.py:73 | `def build_experiment_manifest(` | exists |
| `validate_experiment_manifest` | experiment_manifest.py:136 | `def validate_experiment_manifest(document: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:` | exists |
| `OutcomeLedger` | scripts/eval_harness/outcome_ledger.py:12 | `class OutcomeLedger:` | exists |
| `summarize_run` | outcome_ledger.py:32 | `def summarize_run(run_dir: Path \| str) -> dict[str, Any]:` | exists |
| `mk/evals.mk` | mk/evals.mk | file | exists |
| `prepare_cluster_caches` | recognition/application/orchestration/clustering/discovery_pipeline.py:247 | `async def prepare_cluster_caches(` (DB-coupled; S4 does not call it) | exists |
| `CentroidDiscovery` | recognition/application/discovery/centroid.py:17 | `class CentroidDiscovery:` | exists |
| `CentroidDiscovery._find_best_centroid_match` | centroid.py:62 | `def _find_best_centroid_match(` | exists |
| `best_similarity = 0.0` | centroid.py:78 | `best_similarity = 0.0` | **defect-shaped**: the initial 0.0 means a centroid with cosine ≤ 0 is never returned (`(None, 0.0)`). Reported, not fixed. |
| `firbench_contract.py`, `firbench_frames.py`, `firbench_clusters.py` | scripts/eval_harness/ | — | **not present, created by S0/S1/S4 by design** (not a missing dependency) |
| `FirBenchError` family, `UnsealToken`, `require_frame_read_allowed`, `reference_threshold_cluster`, `require_private_output_path` | — | — | **not present, created by S0/S4 by design** |

## 7. Historical artifacts for AE-6 legacy parity

| Artifact | Path | sha256 | Status |
| --- | --- | --- | --- |
| Holds `face_unknown_rejection` 0.986 = 204/207 (M-06 row) | `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (line 399) | `59bb9aac7a744604586fe89cf7ede11da898cb58ff2e78cb083ab95baad144f7` | tracked **report**, not raw bench output |
| Same value, executive summary | `benchmarks/reports/fir-executive-summary-20260728.md` (line 57) | `f71cda9e032566818601663d24893c7acd111fa2b48546342c6aae8dd388a2a1` | tracked **report** |
| Raw bench JSON carrying `face_unknown_rejection` | **not found**: 0 tracked `.json` files contain the string (14 tracked hits, none JSON) | `git ls-files \| xargs grep -l face_unknown_rejection` | — |
| Golden-150 FIR-8 bench output | **not found**: `benchmarks/results/` absent; 0 tracked files under it | `ls -d benchmarks/results`; `git ls-files \| grep -c '^benchmarks/results/'` | — |

## 8. Dependencies

| Check | Command | Result |
| --- | --- | --- |
| `umap` | `uv run --directory apps/prototype-description-service --locked --extra dev python -c 'import umap'` | ModuleNotFoundError (rc 1). `umap-learn` is not declared in `pyproject.toml` or `uv.lock`. |
| `scipy` | same, `import scipy` | OK, 1.18.0 |
| `hdbscan` | same, `import hdbscan` | OK, 0.8.44 |
| `insightface`, bench extra, flag set | `ACX_EVAL_BENCH=1 uv run --directory apps/prototype-description-service --locked --extra dev --extra bench python -c 'import insightface'` | OK, `insightface import OK 0.7.3`, rc 0 (built from sdist) |
| `insightface`, **without** bench, literal brief command | same, `--extra dev` only, warm venv | rc 0 (**false pass**): `uv run` syncs inexactly by default, so bench packages from the previous step stayed installed |
| `insightface`, without bench, `--exact` | `ACX_EVAL_BENCH=1 uv run --exact --directory apps/prototype-description-service --locked --extra dev python -c 'import insightface'` | **ModuleNotFoundError, rc 1** (exact sync uninstalled 33 packages). This is the valid negative control. |

| `bench` extra pin | Value |
| --- | --- |
| `insightface` | `>=0.7.3,<1.0.0` (uv.lock: 0.7.3) |
| `opencv-python-headless` | `==5.0.0.93` |
| `setuptools` | `>=68.0.0` |
| core `opencv-python` (shared cv2 dir) | `==5.0.0.93` |
| buffalo_l model root | `~/.insightface/models/buffalo_l/` (§1b) |

## 9. Renderer

| Check | Command | Result |
| --- | --- | --- |
| Only the `.uxmap.json` in `UX_MAPS_DIR` (the brief's literal copy) | `cd /tmp && UX_MAPS_DIR=<tmp> python3 <repo>/apps/prototype-wp-alt-context/docs/ux-maps/render_ux_maps.py --check` | **rc 1**: ENOENT on the sibling `febt-1-job-error-states.md` |
| `.uxmap.json` plus sibling `.md` | same | **rc 0**: `all UX-map artifacts are current (1 checked)` |
| Temp dir cleanup | `rm -rf` after each run | removed |

## 10. Flags for downstream lanes

| # | Flag | Owner / action |
| --- | --- | --- |
| 1 | Equivalent stripped source trees per recorded provenance; original `b6dcaad…` commit object unavailable as expected (§0), not a source mismatch | no history repair needed |
| 2 | Literal no-bench negative control gives a false pass in a warm venv; use `uv run --exact` for clean-env tests | S-lanes, README rule 9 |
| 3 | `BuffaloLeg` does not exist; the class is `BuffaloFusedLeg` | S2 |
| 4 | `best_similarity = 0.0` floor at centroid.py:78 drops negative-cosine matches | S4 / any reuse of centroid |
| 5 | **Confirmed 2026-10-15, MCP16912:** `/opt/acx-backend/data/dev-models/face_pipeline/glintr100.onnx`, `/opt/acx-backend/data/dev-models/face_pipeline/face_recognition_sface_2021dec.onnx`, and `/opt/acx-backend/data/dev-models/face_pipeline/face_detection_yunet_2026may.onnx`; full hashes and byte counts match §1a. Only these three weight-location uncertainties are superseded; §1d remains historical | any live leg run: use the confirmed paths; weight verification does not establish live runtime, loading, or inference |
| 6 | **Superseded 2026-10-15 (laptop primary):** 643 of 646 originals present, 0 mismatch, 3 absent per local provenance. The historical VM probes located no corpus files within the explicit paths in §2; elsewhere on the VM and VM-wide counts remain unknown | any corpus-hash check: run `check corpus646-originals` ([`benchmarks/README.md` § Images](../../../../benchmarks/README.md#images)) where the originals are present; follow existing operator authorization, keep pixels out of remote Git, and keep private alias maps laptop-only |
| 7 | Golden-150 selection names `corpus-manifest-v3.json` (sha `154eb2b7…`, matches), not v3r | S1 |
| 8 | Report §0f M̃ 12.925 reproduces on neither manifest (v3r 18.192, v3 18.195) | S5 comparison only |
| 9 | No exhaustive marker in inspected manifests; admissible nonmated N_units, n_eff and FPIR resolvability unestablished. Face M̃ 24.401 and image M̃ 18.192 are distinct conditional summaries (§4–§5). | S1/S3: exhaustive independent GT/PSU structure first; working ICC 0.10 is an assumption; no adequacy claim |
| 10 | Renderer needs the sibling `.md` as well as the `.uxmap.json` | W2-uxmap / S5 |
| 11 | Gate contract P0 values (`max_fpi`, `n_nonmated_declared`, `t14_exhaustive_subset_count`, `ratified_by_decision_id`) are null; they stay null | S0 |
| 12 | fir-occ population draft is laptop-only; coordinator supplies a pseudonymized frame file | coordinator |
| 13 | Remaining evidence gap, not established in the tracked records: no independently exhaustive human GT, no observation or QC record of measurement production, and no capture-occasion independence found. `named_boxes`/`detected_boxes` and the null signed subset contract do not establish these. Not a global-absence claim | later organization: supply these records or record their absence ([EVAL-19], [MEAS-29], [EXP-23]); §5 evidence gate applies |
