# S0 · Decision contract, frame registry, shared names

- **Wave:** W3 batch A · **Model:** current routing in [README](README.md#dispatch-order) · **Depends on:** W2 inventory merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_contract.py`
  - `apps/prototype-description-service/scripts/eval_harness/firbench_schemas/` (the five interchange schemas, Build 9)
  - `benchmarks/manifests/fir-bench-decision-v1.json`
  - `apps/prototype-description-service/scene/tests/fixtures/firbench_interchange_v1/` (synthetic fixtures, Build 9)
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_contract.py`

## Goal

Every other slice imports its enums, errors and binding values from here. Nothing downstream may hard-code τ, FPIR targets, δ, α, floors or seeds [rg-009, repo rule in CLAUDE.md]. Two gates are kept apart. A sealed and ratified decision allows a verdict to be printed. Only an unspent unseal token allows a sealed frame to be read (EXP-22, CARD-27, EVAL-07).

## Read first

- `README.md` in this folder (shared names table and error raise conditions; implement every name exactly as listed; its delegated decisions section overrides stale defaults and signatures, and MCP 16733, 16734, 16736 and 16756 are cited beside each changed item below)
- Task plan § "Scope and binding parameters"; scope doc § "Resolutions of the four open decisions"
- `scripts/eval_harness/gate_contract.py`: `GateContract`, `load_gate_contract`, `select_gate_point`, `threshold_sha256`. The FPIR operating point and `max_fpi` / `n_nonmated_declared` stay in `benchmarks/manifests/fir-gate-contract-v1.json`. The decision manifest references that file by path and sha256 and never copies its values.
- `benchmarks/manifests/fir-gate-contract-v1.json` (ratification fields are null today)

## Build

1. All names in the README shared-names table, with docstrings citing the canon row each guards. This includes `ArmStatus`, `SearchStage`, `IdentityStatus`, `SamplingArm`, `FoldRole`, `AlignmentMode` and the `Arm` members `gt_crop_redetect` and `cached_yunet_landmark_replay`, and `InconclusiveReason.insufficient_independent_psus` (MCP 16736). Implement every error in the README raise-conditions table, including `CalibrationLeakError` and `CanaryConfigError`.
2. `DecisionManifest` (frozen), loaded by `load_decision_manifest(path) -> DecisionManifest`, which rejects unknown keys and missing required keys at load time [rg-008, repo rule in CLAUDE.md]. Fields:
   - `decision_id`, `schema_version`
   - `gate_contract_path`, `gate_contract_sha256`
   - `planning_icc` (number) = 0.10: the ICC that sets design effect and n_eff for planning (S1 Build 4 and 8). It is not the observed ICC. It is a declared design assumption and project policy (MCP 16733; AUDIT-11). S3 reports sensitivity at 0.05, 0.10 and 0.20.
   - `fold_protocol`: `{k, seed}` = `{5, 2406466110}`. Identity-disjoint rotating folds (S1 Build 6; CAL-07; MCP 16733).
   - `gallery_lineage`: `{split_seed, templates_sha256}` = `{2468935812, null}`. Gallery split (S1) and the template file it was built from. The template hash stays null until it is measured (MCP 16733).
   - `primary`: estimand string (paired ΔFNIR at FPIR `fpir_target` on the non-mated source-unit denominator), `comparison` (`["sface", "auraface"]`, Δ = first − second), `fpir_target` (number), `end_to_end` (true)
   - `secondary_fpir_targets` (list)
   - `hypotheses`: ordered list; list order is the Holm step order that S3 follows. Each entry is `{id, kind: superiority|non_inferiority, legs, margin, direction}`. H1 is `superiority` with legs `["sface", "auraface"]` and margin 0. H2 is `non_inferiority` with legs `[<in-house leg>, "insightface"]` and margin 0.05. The in-house leg is named here before the first run on the frame (default `"auraface"`, the H1 candidate). Exactly one in-house leg is allowed for H2; load rejects zero or two.
   - `alpha_family` (0.05, one-sided), `multiplicity` (`holm`: fixed-order step-down; the step levels are derived in S3 Build 6)
   - `interval`: `{method: paired_cluster_bootstrap, psu: image_identity_component, n_boot, seed}`. There is no level field; the two-sided levels follow from `alpha_family` and the step order. `n_boot` = 10000 and `seed` = 2429382368 (MCP 16733; project policy).
   - Seal refuses a null in `planning_icc`, `fold_protocol.k`, `fold_protocol.seed`, `gallery_lineage.split_seed`, `gallery_lineage.templates_sha256`, `interval.n_boot`, `interval.seed`. Required `p_d`, `power`, `min_n_independent` and `cell_floor_n_independent` must be valid at load. Load accepts null in the listed nullable seal inputs so that an unfinished manifest can be read. The committed manifest has unresolved `gallery_lineage.templates_sha256`, every frame's `source_sha256` and `exhaustive`, ratification fields and `seal`; guardrail rules are also unresolved. These unknowns are not evidence of exhaustive GT or admissible nonmated counts. Seal and real-evaluation gates must continue to refuse absent evidence.
   - `guardrails`: list of `{id, metric, rule, cohort_scope, role}`, where `role` is `veto` or `report_only`. Every guardrail carries a role; a guardrail without one fails load.
   - `min_n_independent` = 50: the global floor on distinct independent PSUs in the scored frame, checked before FPIR eligibility or any interval (S3 Build 6). Project policy (MCP 16733, 16736). It does not replace power, MDE, FPIR resolvability or exhaustive ground truth.
   - `cell_floor_n_independent` = 30: minimum independent PSUs before a pair cell is scored (S3 Build 7). Project policy (MCP 16733). It is separate from `min_n_independent`.
   - `p_d` = 0.15: discordance in the power formula (scope § Power). A design assumption, not an observed value. S3 reads it from here, with no code default (MCP 16756).
   - `power` = 0.80: required target power (scope § Power), read by S3 alongside `p_d`; no implicit default (MCP 16756; current S0 manifest).
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
   - `require_frame_read_allowed(frame: FrameSpec, token: UnsealToken | None, *, decision_sha256: str, run_id: str, code_sha: str, scorer_sha: str, repo_root: Path, consumed_at: str) -> UnsealToken` is called once before the sealed frame load (MCP 16756; current S0 producer). `FrameSpec` has only `frame_id`, `admissibility`, `sealed`, `source_sha256` and `exhaustive`, so the runtime context is passed as explicit keywords. `run_id` is the basename of the run directory, and `repo_root` locates `benchmarks/private/firbench/spent/`. It raises `SealedFrameReadError` unless the token is not `None` and is unspent, its `frame_id` equals `frame.frame_id`, its `frame_sha256` equals `frame.source_sha256`, and its `decision_sha256`, `run_id`, `code_sha` and `scorer_sha` equal the matching keywords. The caller passes `consumed_at` explicitly from the non-replayable attempt-receipt boundary, recording the actual consumption attempt (MCP 16773); an old seal or ratification time or semantic `created_at` must never stand in for it. The helper returns the consumed token after spending and appending the ledger row. It never compares a token with itself and never reads a global, the environment or the wall clock. Reuse the loaded frame within the run; another load is refused.
   - Consumption is an atomic `O_EXCL` create of `benchmarks/private/firbench/spent/<frame_id>.spent` at the first read. A failed create refuses the read with `SealedFrameReadError`. A ledger-write failure after spending also refuses the read and leaves the frame spent. The marker is per frame, not per decision or run: a frame with a marker is spent for every decision and every run directory.
8. `benchmarks/manifests/fir-bench-decision-v1.json` filled with the binding defaults from the task plan table. `planning_icc` is 0.10. `fold_protocol` is `{k: 5, seed: 2406466110}`, `gallery_lineage` is `{split_seed: 2468935812, templates_sha256: null}`, and `interval` has `n_boot: 10000` and `seed: 2429382368`. `p_d` is 0.15 and `power` is 0.80 (MCP 16756); `min_n_independent` is 50 and `cell_floor_n_independent` is 30 (MCP 16736). These are declared project policy (MCP 16733), validated by AE-2 to AE-4 before real gating. They replace the earlier operator-pending nulls, and the task plan's open questions are superseded until its next revision. The template hash, every frame's `source_sha256` and `exhaustive`, ratification and seal stay null until they are measured or ratified. H2 names the in-house leg `auraface`. Guardrail roles: per-cohort FPIR, false names per 1k mentions, worst pair-cell FNIR and p95 ms per face are `veto`; cost per accepted description is `report_only` until its source is wired. Gate-contract sha computed from the real file. Ratification and seal null. Frames: `golden150-v1` diagnostic, `corpus646-v3r` development, `fir-occ-v1-prob` development, `fir-occ-v1-chal` development, `confirm-v1` confirmatory with `sealed: true`. The three disconfirmers, each with a review date: AuraFace ΔFNIR CI lower bound ≤ 0 on fir-occ-v1-prob; per-cohort FPIR guardrail breached; the AE-5 canary not detected. The committed file never creates the unseal ledger; the ledger is created by the first unseal under `benchmarks/private/`.

9. **Interchange schemas and fixtures.** One versioned JSON Schema per payload: `frame-v1` (S1 `Frame`), `face-search-record-v1` (one `searches.jsonl` row, README table), `scores-v1` (S3 `scores.json`), `clusters-v1` (S4 `clusters.json`), `comparison-v1` (S6b `comparison.json`). Each has `schema_version: 1`, rejects unknown keys and carries required keys with types and enum values. `validate_interchange(name, payload) -> None` raises `FrameContractError` on any violation. Synthetic fixtures under `scene/tests/fixtures/firbench_interchange_v1/`, one valid payload per schema, use synthetic ids only (`id-0001`, `image-0001`).
10. **Entry-point signatures.** Fixed here before batch B. Each lane implements its row exactly and imports the others' rows by name.

| Entry point | Signature | Owner |
| --- | --- | --- |
| `firbench_cli.run_frame` | `run_frame(*, frame_id: str, decision_path: Path, legs: tuple[LegKind, ...], arms: tuple[Arm, ...], subset: int \| None, subset_seed: int \| None, out_dir: Path, repo_root: Path, created_at: str \| None = None) -> Path` (returns `out_dir`) | S6a |
| `firbench_cli.score_run` | `score_run(run_dir: Path, *, repo_root: Path) -> Path` (returns the `scores.json` path) | S6a |
| `firbench_cli.compare_runs` | `compare_runs(run_a: Path, run_b: Path, *, out_dir: Path, treatment: str \| None, repo_root: Path) -> Path` (returns the `comparison.json` path) | S6b |
| `firbench_report.render_report` | `render_report(run_dir: Path, *, out_dir: Path, include_crops: bool = False) -> Path` (returns `index.html`) | S5 |
| `firbench_frames.build_psu_components` | `build_psu_components(images: Sequence[ImageUnit], faces: Sequence[GtFace]) -> dict[str, str]` (image_id → psu_id) | S1 |
| `firbench_frames.identity_disjoint_folds` | `identity_disjoint_folds(component_map: Mapping[str, str], identity_to_component: Mapping[str, str], *, k: int, seed: int) -> dict[str, int]` (psu_id → fold) | S1 |
| `firbench_frames.build_nonmated_pool` | `build_nonmated_pool(faces: Sequence[GtFace], images: Sequence[ImageUnit], folds: Mapping[str, int], *, fold: int, component_map: Mapping[str, str], exhaustive: bool, planning_icc: float) -> NonMatedPool` | S1 (MCP 16756) |
| `firbench_contract.require_frame_read_allowed` | `require_frame_read_allowed(frame: FrameSpec, token: UnsealToken \| None, *, decision_sha256: str, run_id: str, code_sha: str, scorer_sha: str, repo_root: Path, consumed_at: str) -> UnsealToken` | S0 Build 7 (MCP 16756; current producer) |
| `firbench_score.finish_outcomes` | `finish_outcomes(records: Sequence[FaceSearchRecord], tau: float, boundary: BoundarySemantics) -> tuple[FaceOutcome, ...]` | S3 |
| `firbench_score.calibrate_tau` | `calibrate_tau(records: Sequence[FaceSearchRecord], *, units: Sequence[NonMatedUnit], calibration_folds: frozenset[int], fpir_target: float, boundary: BoundarySemantics) -> float` | S3 |
| `firbench_score.decide` | `decide(manifest: DecisionManifest, results: LegResults) -> Verdict` | S3 |
| `firbench_clusters.reference_threshold_cluster` | `reference_threshold_cluster(vectors: np.ndarray, *, similarity_threshold: float) -> np.ndarray` (int labels; `-1` marks noise, S4 Build 1) | S4 |

`NonMatedPool` and `NonMatedUnit` are frozen dataclasses defined by S1 Build 7. `LegResults` is a frozen dataclass defined by S3 Build 6: for each leg, the finished outcomes and the PSU-indexed arrays that `decide` reads. `Verdict` is defined by S3 Build 6. `ImageUnit` and `GtFace` are defined by S1 Build 1, and `FaceSearchRecord` by the README table.

**`build_nonmated_pool` seam (MCP 16756).** The earlier signature cannot enforce `exhaustive`, apply the planning ICC or recover PSU ids from faces, images and folds alone. The signature therefore takes `component_map` (image_id → psu_id, from `build_psu_components`), `exhaustive` and `planning_icc` as keywords. It raises `FrameContractError` for `exhaustive=False` and for malformed component or fold coverage. Its inputs carry no detector output, so source units stay detector-independent. The old signature is superseded only at this seam. The signatures are fixed before batch B so that each lane can run concurrently against an explicit contract (GRPH-33, practice label).

**`created_at` seam (MCP 16736, clarified by MCP 16773).** `run_frame` accepts `created_at: str | None = None`, and the CLI takes `--created-at` as an ISO 8601 literal. The run's semantic `created_at`, written to `manifest.json`, selects `seal.sealed_at` when present, else `ratification.ratified_at` when present, else the explicit literal. Sealing and ratification are different events and their timestamps may differ. Only a supplied explicit literal must match the selected derived timestamp, comparing parsed instants rather than string spellings. With no derived timestamp, the explicit literal is required. An invalid timestamp, no timestamp source, or a mismatched explicit literal raises the existing `FrameContractError`. Semantic writers never read the wall clock; tests supply fixed literals. Actual attempt and private unseal-ledger consumption timestamps come from the separate non-replayable receipt boundary (Build 7), which is an explicit exception to semantic clock scans. Those scans do not ban harmless set operations, seeded RNG or receipt timing. `timings.json` remains non-replayable; full scores/report byte replay requires the same pinned receipt because its SHA and p95 veto state are assessment inputs (README run-artifacts clarification; MCP 16777).

11. **S7-owned cross-reference: label QC record fields (MCP 16734, 16736).** S7 owns the private queue QC config, record, loader and behavior tests; none is an S0 implementation or completion prerequisite. The private queue QC record that S7 writes before any import carries these fields. Their values are loaded from a versioned config and validated at load (rg-008, repo rule in CLAUDE.md), with no module-level constant (rg-009, repo rule in CLAUDE.md). `gold_share` 0.10; `repeat_fraction` 0.10; `repeat_percent_agreement_floor` 0.90, per field; `kappa_floor` 0.80, per field, Cohen's kappa; `annotator_gold_accuracy_floor` 0.90, against independent gold; `min_gold_decisions_per_annotator` 20; `min_repeat_decisions_per_field` 20. These are pre-data project QC policies, not accuracy guarantees from the canon. Alpha near 0.8 is a rule of thumb and is not a kappa equivalence (HITL-05). Gold mixes random, batch-matched and hard items, with answers from an SME author independent of the labelling operator (HITL-03). Pre-adjudication labels are kept (MLDATA-03). A field below a floor, uncertain or eval-critical, or with undefined kappa, routes to SME adjudication or repair (HITL-07); it is never fixed by deleting a worker. A batch below the support floors exports but cannot import. Real tier-(a) imports stay gated on a bounded observation reference (MEAS-29), which this lane does not create.

## RED tests (S0-owned only; commit first for code)

These tests import only the S0 contract/schema surface and use synthetic contract fixtures. They must not import absent S1, S6a or S7 implementations or private queue QC; those consumers depend on S0. Freeze their signatures here and leave their behavior tests to their owning lanes.

- Every enum has exactly the README members. `SearchStage` has no `fused_internal` or `unavailable_fused` member.
- Each interchange schema accepts its fixture, and rejects that fixture with an unknown key added and with one required key removed.
- Seal refuses a manifest whose `planning_icc`, `fold_protocol.k`, `fold_protocol.seed`, `interval.seed`, `gallery_lineage.templates_sha256` or another nullable seal input is null. Load rejects null or missing required `p_d`, `power`, `min_n_independent` or `cell_floor_n_independent`. Load accepts the unfinished committed manifest with unresolved template/frame hashes, frame exhaustiveness, ratification fields, seal and guardrail rules. The committed values are `k` 5, the seeds in the README table, `n_boot` 10000, `planning_icc` 0.10, `p_d` 0.15, `power` 0.80, `min_n_independent` 50 and `cell_floor_n_independent` 30. Each seed equals the first 32 bits, big-endian, of SHA-256 over `FIRBENCH-1/v1/<purpose>`.
- Load rejects an unknown key, a missing `interval.seed`, an `interval.level` field, an H2 entry with zero or two in-house legs, and a guardrail without `role`.
- `manifest_sha256` is stable under key reordering and changes when `fpir_target` changes.
- `require_verdict_allowed` raises for unratified, unsealed, tampered-after-seal, and sealed frame with unsealed manifest.
- `require_frame_read_allowed` refuses a sealed read with no token, a token bound to another `run_id`, a token for another `decision_sha256`, and a second read after the spent marker exists. A new decision sha cannot reopen a spent frame. It also refuses a token whose `frame_sha256` differs from the frame's `source_sha256`. The O_EXCL spend, exact binding, and first and second read tests stay unchanged (MCP 16756). Include all explicit runtime bindings, a fixed `consumed_at` literal and the returned consumed token in the S0 tests.
- Two concurrent first reads of one frame: exactly one `O_EXCL` create succeeds.
- `require_private_output_path` accepts `benchmarks/private/x/y.html` and rejects `benchmarks/reports/x.html`, a `..` escape and a symlink pointing out of `benchmarks/private/`.
- The committed decision JSON loads, and its `gate_contract_sha256` matches the real gate-contract file.
- A grep test: no numeric literal equal to the manifest's `fpir_target`, `margin` or `alpha_family` appears in `firbench_contract.py`.

## Consumer verification (owning lanes; not S0 prerequisites)

- S1 tests `build_nonmated_pool`: refuse `exhaustive=False` and malformed component/fold coverage; identical inputs produce identical pools (MCP 16756).
- S6a tests `run_frame` timestamp precedence with different seal and ratification times; equivalent parsed instants in an explicit override; refusal of invalid timestamps, a missing literal when neither derived source exists, and an explicit literal mismatching the selected derived instant; and no semantic wall-clock read, using fixed literals (MCP 16736, 16773; Build 10). A separate attempt-receipt fixture supplies actual `consumed_at`, distinct from the old seal time, through the frozen helper signature (Build 7).
- S7 tests the seven versioned QC fields and missing-field load refusal, support floors and real-import observation gates (MCP 16734, 16736; Build 11).

## Done when

All S0-owned tests above pass on the VM. The schemas (Build 9) and the entry-point table (Build 10) are merged before batch B starts. This slice owns part of AE-9 (unratified refusals, sealed-frame read refusals, and the spent-frame refusal).

## Out of scope

Ratifying anything; editing `fir-gate-contract-v1.json`; scoring code.
