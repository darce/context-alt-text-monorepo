# S0 · Decision contract, frame registry, shared names

- **Wave:** W3 batch A · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** W2 inventory merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_contract.py`
  - `benchmarks/manifests/fir-bench-decision-v1.json`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_contract.py`

## Goal

Every other slice imports its enums, errors and binding values from here. Nothing downstream may hard-code τ, FPIR targets, δ, α, floors or seeds [rg-009, repo rule]. Two gates are kept apart. A sealed and ratified decision allows a verdict to be printed. Only an unspent unseal token allows a sealed frame to be read (EXP-22, CARD-27, EVAL-07).

## Read first

- `README.md` in this folder (shared names table and error raise conditions; implement every name exactly as listed)
- Task plan § "Scope and binding parameters"; scope doc § "Resolutions of the four open decisions"
- `scripts/eval_harness/gate_contract.py`: `GateContract`, `load_gate_contract`, `select_gate_point`, `threshold_sha256`. The FPIR operating point and `max_fpi` / `n_nonmated_declared` stay in `benchmarks/manifests/fir-gate-contract-v1.json`. The decision manifest references that file by path and sha256 and never copies its values.
- `benchmarks/manifests/fir-gate-contract-v1.json` (ratification fields are null today)

## Build

1. All names in the README shared-names table, with docstrings citing the canon row each guards. This includes `ArmStatus`, `LedgerStage` and the `Arm` members `gt_crop_redetect` and `cached_yunet_landmark_replay`. Implement every error in the README raise-conditions table, including `CalibrationLeakError` and `CanaryConfigError`.
2. `DecisionManifest` (frozen), loaded by `load_decision_manifest(path) -> DecisionManifest`, which rejects unknown keys and missing required keys at load time [rg-008, repo rule]. Fields:
   - `decision_id`, `schema_version`
   - `gate_contract_path`, `gate_contract_sha256`
   - `primary`: estimand string (paired ΔFNIR at FPIR `fpir_target` on the non-mated source-unit denominator), `comparison` (`["sface", "auraface"]`, Δ = first − second), `fpir_target` (number), `end_to_end` (true)
   - `secondary_fpir_targets` (list)
   - `hypotheses`: ordered list; list order is the Holm step order that S3 follows. Each entry is `{id, kind: superiority|non_inferiority, legs, margin, direction}`. H1 is `superiority` with legs `["sface", "auraface"]` and margin 0. H2 is `non_inferiority` with legs `[<in-house leg>, "insightface"]` and margin 0.05. The in-house leg is named here before the first run on the frame (default `"auraface"`, the H1 candidate). Exactly one in-house leg is allowed for H2; load rejects zero or two.
   - `alpha_family` (0.05, one-sided), `multiplicity` (`holm`: fixed-order step-down; the step levels are derived in S3 Build 6)
   - `interval`: `{method: paired_cluster_bootstrap, psu: image_identity_component, n_boot, seed}`. There is no level field; the two-sided levels follow from `alpha_family` and the step order.
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
8. `benchmarks/manifests/fir-bench-decision-v1.json` filled with the binding defaults from the task plan table. H2 names the in-house leg `auraface`. Guardrail roles: per-cohort FPIR, false names per 1k mentions, worst pair-cell FNIR and p95 ms per face are `veto`; cost per accepted description is `report_only` until its source is wired. Gate-contract sha computed from the real file. Ratification and seal null. Frames: `golden150-v1` diagnostic, `corpus646-v3r` development, `fir-occ-v1-prob` development, `fir-occ-v1-chal` development, `confirm-v1` confirmatory with `sealed: true`. The three disconfirmers, each with a review date: AuraFace ΔFNIR CI lower bound ≤ 0 on fir-occ-v1-prob; per-cohort FPIR guardrail breached; the AE-5 canary not detected. The committed file never creates the unseal ledger; the ledger is created by the first unseal under `benchmarks/private/`.

## RED tests (commit first; they must fail on missing module or names)

- Every enum has exactly the README members.
- Load rejects an unknown key, a missing `interval.seed`, an `interval.level` field, an H2 entry with zero or two in-house legs, and a guardrail without `role`.
- `manifest_sha256` is stable under key reordering and changes when `fpir_target` changes.
- `require_verdict_allowed` raises for unratified, unsealed, tampered-after-seal, and sealed frame with unsealed manifest.
- `require_frame_read_allowed` refuses a sealed read with no token, a token bound to another `run_id`, a token for another `decision_sha256`, and a second read after the spent marker exists. A new decision sha cannot reopen a spent frame.
- Two concurrent first reads of one frame: exactly one `O_EXCL` create succeeds.
- `require_private_output_path` accepts `benchmarks/private/x/y.html` and rejects `benchmarks/reports/x.html`, a `..` escape and a symlink pointing out of `benchmarks/private/`.
- The committed decision JSON loads, and its `gate_contract_sha256` matches the real gate-contract file.
- A grep test: no numeric literal equal to the manifest's `fpir_target`, `margin` or `alpha_family` appears in `firbench_contract.py`.

## Done when

All tests above pass on the VM. This slice owns part of AE-9 (unratified refusals, sealed-frame read refusals, and the spent-frame refusal).

## Out of scope

Ratifying anything; editing `fir-gate-contract-v1.json`; scoring code.
