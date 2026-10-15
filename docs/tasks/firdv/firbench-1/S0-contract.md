# S0 · Decision contract, frame registry, shared names

- **Wave:** W3 batch A · **Model:** gpt-6.1-sol xhigh, standard tier · **Depends on:** W2 inventory merged
- **Owned paths:**
  - `apps/prototype-description-service/scripts/eval_harness/firbench_contract.py`
  - `benchmarks/manifests/fir-bench-decision-v1.json`
  - `apps/prototype-description-service/scene/tests/test_eval_harness_firbench_contract.py`

## Goal

Every other slice imports its enums, errors and binding values from here. Nothing downstream may hard-code τ, FPIR targets, δ, α, floors or seeds [rg-009]. A decision cannot be read as a verdict until its manifest is sealed and ratified (EXP-22, CARD-27, EVAL-07).

## Read first

- `README.md` in this folder (shared names table; implement every name exactly as listed)
- Task plan § "Scope and binding parameters"; scope doc § "Resolutions of the four open decisions"
- `scripts/eval_harness/gate_contract.py`: `GateContract`, `load_gate_contract`, `select_gate_point`, `threshold_sha256`. The FPIR operating point and `max_fpi` / `n_nonmated_declared` stay in `benchmarks/manifests/fir-gate-contract-v1.json`. The decision manifest references that file by path and sha256 and never copies its values.
- `benchmarks/manifests/fir-gate-contract-v1.json` (ratification fields are null today)

## Build

1. All names in the README shared-names table, with docstrings citing the canon row each guards.
2. `DecisionManifest` (frozen), loaded by `load_decision_manifest(path) -> DecisionManifest`, which rejects unknown keys and missing required keys at load time [rg-008]. Fields:
   - `decision_id`, `schema_version`
   - `gate_contract_path`, `gate_contract_sha256`
   - `primary`: estimand string, `comparison` (`["sface", "auraface"]`, Δ = first − second), `fpir_target` (number), `end_to_end` (true)
   - `secondary_fpir_targets` (list)
   - `hypotheses`: list of `{id, kind: superiority|non_inferiority, legs, margin, direction}`
   - `alpha_family`, `multiplicity` (`holm`)
   - `interval`: `{method: paired_cluster_bootstrap, psu: image_identity_component, level: 0.95, n_boot, seed}`
   - `guardrails`: list of `{id, metric, rule, cohort_scope}`
   - `cell_floor_n_independent` (minimum independent units before a pair cell is scored)
   - `boundary_semantics` (`BoundarySemantics`)
   - `frames`: list of `FrameSpec` entries (the frame registry)
   - `disconfirmers`: list of `{id, statement, review_date}`
   - `ratification`: `{decision_ref, ratified_at}`, both null until the operator ratifies
   - `seal`: `{sealed_at, sha256}`, null until sealed
3. `manifest_sha256(manifest)`: canonical JSON (sorted keys, no whitespace variance) excluding the `seal` block.
4. `seal(manifest, *, sealed_at) -> DecisionManifest` returns a new manifest whose `seal.sha256` equals `manifest_sha256`. Re-sealing a sealed manifest raises.
5. `require_verdict_allowed(manifest, *, frame: FrameSpec)` raises `UnratifiedDecisionError` if ratification or the seal is missing or the seal hash does not match. Raises `SealedFrameReadError` if `frame.sealed` and the manifest is not sealed.
6. `require_private_output_path(path, *, repo_root)` as in the README.
7. `benchmarks/manifests/fir-bench-decision-v1.json` filled with the binding defaults from the task plan table. Gate-contract sha computed from the real file. Ratification and seal null. Frames: `golden150-v1` diagnostic, `corpus646-v3r` development, `fir-occ-v1-prob` development, `fir-occ-v1-chal` development, `confirm-v1` confirmatory with `sealed: true`. The three disconfirmers, each with a review date: AuraFace ΔFNIR CI lower bound ≤ 0 on fir-occ-v1-prob; per-cohort FPIR guardrail breached; the AE-5 canary not detected.

## RED tests (commit first; they must fail on missing module or names)

- Every enum has exactly the README members.
- Load rejects an unknown key and a missing `interval.seed`.
- `manifest_sha256` is stable under key reordering and changes when `fpir_target` changes.
- `require_verdict_allowed` raises for unratified, unsealed, tampered-after-seal, and sealed frame with unsealed manifest.
- `require_private_output_path` accepts `benchmarks/private/x/y.html` and rejects `benchmarks/reports/x.html`, a `..` escape and a symlink pointing out of `benchmarks/private/`.
- The committed decision JSON loads, and its `gate_contract_sha256` matches the real gate-contract file.
- A grep test: no numeric literal equal to the manifest's `fpir_target`, `margin` or `alpha_family` appears in `firbench_contract.py`.

## Done when

All tests above pass on the VM. This slice owns part of AE-9 (unratified and sealed-frame refusals).

## Out of scope

Ratifying anything; editing `fir-gate-contract-v1.json`; scoring code.
