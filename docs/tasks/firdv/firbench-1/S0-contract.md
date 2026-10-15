# S0 · Decision contract, frame registry, shared names

- **Wave:** W3 batch A · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** W2 inventory merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_contract.py`
  - `apps/prototype-description-service/scripts/eval_harness/firbench_schemas/` (the five interchange schemas, Build 9)
  - `benchmarks/manifests/fir-bench-decision-v1.json`
  - `apps/prototype-description-service/scene/tests/fixtures/firbench_interchange_v1/` (synthetic fixtures, Build 9)
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_contract.py`

## Goal

Every other slice imports its enums, errors and binding values from here. Nothing downstream may hard-code τ, FPIR targets, δ, α, floors or seeds [rg-009, repo rule]. Two gates are kept apart. A sealed and ratified decision allows a verdict to be printed. Only an unspent unseal token allows a sealed frame to be read (EXP-22, CARD-27, EVAL-07).

## Read first

- `README.md` in this folder (shared names table and error raise conditions; implement every name exactly as listed)
- Task plan § "Scope and binding parameters"; scope doc § "Resolutions of the four open decisions"
- `scripts/eval_harness/gate_contract.py`: `GateContract`, `load_gate_contract`, `select_gate_point`, `threshold_sha256`. The FPIR operating point and `max_fpi` / `n_nonmated_declared` stay in `benchmarks/manifests/fir-gate-contract-v1.json`. The decision manifest references that file by path and sha256 and never copies its values.
- `benchmarks/manifests/fir-gate-contract-v1.json` (ratification fields are null today)

## Build

1. All names in the README shared-names table, with docstrings citing the canon row each guards. This includes `ArmStatus`, `SearchStage`, `IdentityStatus`, `SamplingArm`, `FoldRole`, `AlignmentMode` and the `Arm` members `gt_crop_redetect` and `cached_yunet_landmark_replay`. Implement every error in the README raise-conditions table, including `CalibrationLeakError` and `CanaryConfigError`.
2. `DecisionManifest` (frozen), loaded by `load_decision_manifest(path) -> DecisionManifest`, which rejects unknown keys and missing required keys at load time [rg-008, repo rule]. Fields:
   - `decision_id`, `schema_version`
   - `gate_contract_path`, `gate_contract_sha256`
   - `planning_icc` (number): the ICC that sets design effect and n_eff for planning (S1 Build 4 and 8). It is not the observed ICC.
   - `fold_protocol`: `{k, seed}`. Identity-disjoint rotating folds (S1 Build 6).
   - `gallery_lineage`: `{split_seed, templates_sha256}`. Gallery split (S1) and the template file it was built from.
   - `primary`: estimand string (paired ΔFNIR at FPIR `fpir_target` on the non-mated source-unit denominator), `comparison` (`["sface", "auraface"]`, Δ = first − second), `fpir_target` (number), `end_to_end` (true)
   - `secondary_fpir_targets` (list)
   - `hypotheses`: ordered list; list order is the Holm step order that S3 follows. Each entry is `{id, kind: superiority|non_inferiority, legs, margin, direction}`. H1 is `superiority` with legs `["sface", "auraface"]` and margin 0. H2 is `non_inferiority` with legs `[<in-house leg>, "insightface"]` and margin 0.05. The in-house leg is named here before the first run on the frame (default `"auraface"`, the H1 candidate). Exactly one in-house leg is allowed for H2; load rejects zero or two.
   - `alpha_family` (0.05, one-sided), `multiplicity` (`holm`: fixed-order step-down; the step levels are derived in S3 Build 6)
   - `interval`: `{method: paired_cluster_bootstrap, psu: image_identity_component, n_boot, seed}`. There is no level field; the two-sided levels follow from `alpha_family` and the step order.
   - Seal refuses a null in `planning_icc`, `fold_protocol.k`, `fold_protocol.seed`, `gallery_lineage.split_seed`, `gallery_lineage.templates_sha256`, `interval.n_boot` and `interval.seed`. Load accepts null in these fields so that an unfinished manifest can be read.
   - `guardrails`: list of `{id, metric, rule, cohort_scope, role}`, where `role` is `veto` or `report_only`. Every guardrail carries a role; a guardrail without one fails load.
   - `cell_floor_n_independent` (minimum independent PSUs before a pair cell is scored)
   - `boundary_semantics` (`BoundarySemantics`)
   - `frames`: list of `FrameSpec` entries (the frame registry)
   - `disconfirmers`: list of `{id, statement, review_date}`
   - `ratification`: `{decision_ref, ratified_at}`, both null until the operator ratifies
   - `seal`: `{sealed_at, sha256}`, null until sealed
3. `manifest_sha256(manifest)`: canonical JSON (sorted keys, no whitespace variance) excluding the `seal` block.
4. `seal(manifest, *, sealed_at) -> DecisionManifest` returns a new manifest whose `seal.sha256` equals `manifest_sha256`. Re-sealing a sealed manifest raises.
5. `require_verdict_allowed(manifest, *, frame: FrameSpec)` raises `UnratifiedDecisionError` if ratification or the seal is missing or the seal hash does not match. It raises `SealedFrameReadError` if `frame.sealed` and the manifest is not sealed. This check gates printing a verdict. It does not authorise any read of a sealed frame. Build 7 does.
6. `require_private_output_path(path, *, repo_root)` as in the README.
7. Frame-read authorisation.
   - `UnsealToken` is the frozen record `{frame_id, frame_sha256, decision_sha256, run_id, code_sha, scorer_sha, consumed_at}`. `run_id` is the basename of the run directory.
   - Tokens live in one append-only ledger, `benchmarks/private/firbench/unseal-ledger.jsonl`, outside every run directory. The ledger is local-only: never committed, never copied into a brief or report, never used as test data. `unseal` appends the token (S6b Build 3); a consumption appends a second row for the same token with `consumed_at` set.
   - `require_frame_read_allowed(frame, token)` is called before every sealed input read. It raises `SealedFrameReadError` unless the token is unspent and its `frame_id`, `frame_sha256`, `decision_sha256`, `run_id`, `code_sha` and `scorer_sha` match the current frame, decision, run directory name, code and scorer.
   - Consumption is an atomic `O_EXCL` create of `benchmarks/private/firbench/spent/<frame_id>.spent` at the first read. A failed create refuses the read with `SealedFrameReadError`. The marker is per frame, not per decision or run: a frame with a marker is spent for every decision and every run directory.
8. `benchmarks/manifests/fir-bench-decision-v1.json` filled with the binding defaults from the task plan table. `planning_icc` is 0.10 (the scope's working value; the operator confirms it before seal). `fold_protocol`, `gallery_lineage` and `interval.n_boot` and `interval.seed` are null: their values are operator decisions (task plan Open questions). H2 names the in-house leg `auraface`. Guardrail roles: per-cohort FPIR, false names per 1k mentions, worst pair-cell FNIR and p95 ms per face are `veto`; cost per accepted description is `report_only` until its source is wired. Gate-contract sha computed from the real file. Ratification and seal null. Frames: `golden150-v1` diagnostic, `corpus646-v3r` development, `fir-occ-v1-prob` development, `fir-occ-v1-chal` development, `confirm-v1` confirmatory with `sealed: true`. The three disconfirmers, each with a review date: AuraFace ΔFNIR CI lower bound ≤ 0 on fir-occ-v1-prob; per-cohort FPIR guardrail breached; the AE-5 canary not detected. The committed file never creates the unseal ledger; the ledger is created by the first unseal under `benchmarks/private/`.

9. **Interchange schemas and fixtures.** One versioned JSON Schema per payload: `frame-v1` (S1 `Frame`), `face-search-record-v1` (one `searches.jsonl` row, README table), `scores-v1` (S3 `scores.json`), `clusters-v1` (S4 `clusters.json`), `comparison-v1` (S6b `comparison.json`). Each has `schema_version: 1`, rejects unknown keys and carries required keys with types and enum values. `validate_interchange(name, payload) -> None` raises `FrameContractError` on any violation. Synthetic fixtures under `scene/tests/fixtures/firbench_interchange_v1/`, one valid payload per schema, use synthetic ids only (`id-0001`, `image-0001`).
10. **Entry-point signatures.** Fixed here before batch B. Each lane implements its row exactly and imports the others' rows by name.

| Entry point | Signature | Owner |
| --- | --- | --- |
| `firbench_cli.run_frame` | `run_frame(*, frame_id: str, decision_path: Path, legs: tuple[LegKind, ...], arms: tuple[Arm, ...], subset: int \| None, subset_seed: int \| None, out_dir: Path, repo_root: Path) -> Path` (returns `out_dir`) | S6a |
| `firbench_cli.score_run` | `score_run(run_dir: Path, *, repo_root: Path) -> Path` (returns the `scores.json` path) | S6a |
| `firbench_cli.compare_runs` | `compare_runs(run_a: Path, run_b: Path, *, out_dir: Path, treatment: str \| None, repo_root: Path) -> Path` (returns the `comparison.json` path) | S6b |
| `firbench_report.render_report` | `render_report(run_dir: Path, *, out_dir: Path, include_crops: bool = False) -> Path` (returns `index.html`) | S5 |
| `firbench_frames.build_psu_components` | `build_psu_components(images: Sequence[ImageUnit], faces: Sequence[GtFace]) -> dict[str, str]` (image_id → psu_id) | S1 |
| `firbench_frames.identity_disjoint_folds` | `identity_disjoint_folds(component_map: Mapping[str, str], identity_to_component: Mapping[str, str], *, k: int, seed: int) -> dict[str, int]` (psu_id → fold) | S1 |
| `firbench_frames.build_nonmated_pool` | `build_nonmated_pool(faces: Sequence[GtFace], images: Sequence[ImageUnit], folds: Mapping[str, int], *, fold: int) -> NonMatedPool` | S1 |
| `firbench_score.finish_outcomes` | `finish_outcomes(records: Sequence[FaceSearchRecord], tau: float, boundary: BoundarySemantics) -> tuple[FaceOutcome, ...]` | S3 |
| `firbench_score.calibrate_tau` | `calibrate_tau(records: Sequence[FaceSearchRecord], *, units: Sequence[NonMatedUnit], calibration_folds: frozenset[int], fpir_target: float, boundary: BoundarySemantics) -> float` | S3 |
| `firbench_score.decide` | `decide(manifest: DecisionManifest, results: LegResults) -> Verdict` | S3 |
| `firbench_clusters.reference_threshold_cluster` | `reference_threshold_cluster(vectors: np.ndarray, *, similarity_threshold: float) -> np.ndarray` (int labels; `-1` marks noise, S4 Build 1) | S4 |

`NonMatedPool` and `NonMatedUnit` are frozen dataclasses defined by S1 Build 7. `LegResults` is a frozen dataclass defined by S3 Build 6: for each leg, the finished outcomes and the PSU-indexed arrays that `decide` reads. `Verdict` is defined by S3 Build 6. `ImageUnit` and `GtFace` are defined by S1 Build 1, and `FaceSearchRecord` by the README table.

## RED tests (commit first; they must fail on missing module or names)

- Every enum has exactly the README members. `SearchStage` has no `fused_internal` or `unavailable_fused` member.
- Each interchange schema accepts its fixture, and rejects that fixture with an unknown key added and with one required key removed.
- Seal refuses a manifest whose `planning_icc`, `fold_protocol` or `interval.seed` is null. Load accepts the committed manifest with those nulls.
- Load rejects an unknown key, a missing `interval.seed`, an `interval.level` field, an H2 entry with zero or two in-house legs, and a guardrail without `role`.
- `manifest_sha256` is stable under key reordering and changes when `fpir_target` changes.
- `require_verdict_allowed` raises for unratified, unsealed, tampered-after-seal, and sealed frame with unsealed manifest.
- `require_frame_read_allowed` refuses a sealed read with no token, a token bound to another `run_id`, a token for another `decision_sha256`, and a second read after the spent marker exists. A new decision sha cannot reopen a spent frame.
- Two concurrent first reads of one frame: exactly one `O_EXCL` create succeeds.
- `require_private_output_path` accepts `benchmarks/private/x/y.html` and rejects `benchmarks/reports/x.html`, a `..` escape and a symlink pointing out of `benchmarks/private/`.
- The committed decision JSON loads, and its `gate_contract_sha256` matches the real gate-contract file.
- A grep test: no numeric literal equal to the manifest's `fpir_target`, `margin` or `alpha_family` appears in `firbench_contract.py`.

## Done when

All tests above pass on the VM. The schemas (Build 9) and the entry-point table (Build 10) are merged before batch B starts. This slice owns part of AE-9 (unratified refusals, sealed-frame read refusals, and the spent-frame refusal).

## Out of scope

Ratifying anything; editing `fir-gate-contract-v1.json`; scoring code.
