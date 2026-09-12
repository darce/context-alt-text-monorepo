# Task Plan

> **Metadata**
>
> - **Date**: 2026-09-11
> - **Author**: Claude Fable 5.1 (claude-fable-5-1) via sonnet drafting agent
> - **Status**: draft
> - **Owning Epic**: [docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Epic Short ID**: FIR
> - **Task ID**: `FIR-16`
> - **Target Branch**: `feature/fir-16`
> - **Review Coverage Target**: 2

---

## FIR-16. Open-set head-to-head: face_pipeline vs buffalo_l on acx-dev-fir

## Objective

Extend FIR-8's cross-stack bench with an open-set FNIR@FPIR leg — the headline gate metric D3 (decision #10843) — that scores candidate `face_pipeline` (acx-dev-fir) against incumbent `buffalo_l` (acx-dev) at their own swept thresholds, reports a paired non-inferiority verdict under FIR-11 R1's power ceiling, and hands the operator a propose-gate CLI plus decision template. The instrument (S1–S3) is Phase C work; the live run (S4) is Phase D, gated on FIR23-STACK standing up and on FIR-6 S4 calibration.

## Intake

- **Scope one-pager**: none new — decomposed from the 2026-09-11 program re-plan (decision #10843, session firplan-1-replan-20260911).
- **Key Q&A decisions**: decision #10843 (D3 = FNIR@FPIR; acx-dev-fir must exist before any head-to-head; Golden-150 locked at FIR-11 R1; no epic rewrite).
- **Not-Doing**: standing up acx-dev-fir (FIR23-STACK's own task); corpus remediation or labeling (FIR-11's own task); the FIR-6 S6 switch-over flip itself; removing the `.[bench]` pyproject extra (also FIR-6 S6, after the flip).

## Problem Statement

FIR-8's `scripts/bench/` package (v6.7, 56/59 checklist items done) scores detection precision/recall and cluster-label identification precision/recall across two isolated stacks with `CrossbenchTier` (CONFIRMATORY/DIRECTIONAL/DIAGNOSTIC), but has no open-set FNIR@FPIR leg — the metric decision #10843 makes the headline gate. FIR-12's `open_set_identification.py` / `fir_bakeoff_run.py` already implement FNIR@FPIR scoring but have never been wired to a live two-stack export. FIR-13's `gate_contract.py` (planned, not yet implemented) will define the ratified D3 operating point once it lands. This task is the wiring: an open-set leg in the bench, a head-to-head report with a non-inferiority verdict, an operator gate-proposal CLI, and — gated behind FIR23-STACK and FIR-6 S4 — the actual live run.

## Constraints

- Both stacks are scored at their OWN swept tau — never share a threshold across the 512-D (buffalo_l) and 128-D (face_pipeline) embedding spaces [EMB-01, IDX-02].
- FPI is always reported as an integer count, never a rate [EVAL-19].
- The FIR-11 R1 corpus (30 entries / 30 probes / 17 identities) is consumed, never restated or re-derived here.
- `propose-gate` refuses to act on a `GateContract` whose `ratified_by_decision_id` is `None` — a hard refusal (non-zero exit), never a warning.
- Withdrawn numbers (M-12 0.865/0.321, recall 0.504, 2.73 faces/image, every pre-CVUP-1 artifact) may not be cited as evidence anywhere in this task's artifacts or reports. "Embedder leads detector" stays a hypothesis pending FIR-15.
- `sr-007`: report tiers and dead-zone/verdict values are `StrEnum`, never string comparisons.
- `rg-015`: the export→`SearchResult` mapping must not invent a similarity score the export does not carry — this plan adds the missing field explicitly (S1a) rather than fabricating one downstream.
- No A10/GPU spend; no SCRFD/AdaFace retrain; occlusion work stays inference-only until D-01 [decision #10843].
- The S4 live run touches acx-dev-fir/acx-dev only over their public HTTP APIs, never direct DB access — the FIR-8 pattern.

## Workflow Principles

- Measure before optimising [PRINCIPLE #15] — this task instruments and (in Phase D) runs a measurement; it draws no conclusion about which detector/embedder wins.
- [AUDIT-04]: never synthesize a measured point from an unmeasured cell — `score_open_set` and `select_gate_point` propagate `measured=False` / `None` rather than defaulting to 0.
- [PROV-01]: every report row carries stack provenance (profile, dimension, toolchain) so a reader can never conflate the two stacks' numbers.
- [rg-009]: no task-specific literals in generic modules — S1 imports FIR-13's `GateContract` / `select_gate_point` rather than re-deriving a threshold rule inline.

## Terminology

- **D3**: headline gate metric, FNIR at a fixed FPIR (decision #10843).
- **FNIR@FPIR**: False Negative Identification Rate at a fixed False Positive Identification Rate, score threshold swept; FPI is an integer count, never a rate [EVAL-19].
- **Golden-150 R1**: FIR-11's remediated corpus — 30 entries / 30 probes / 17 identities usable for the paired non-inferiority check.
- **acx-dev-fir**: the isolated `face_pipeline` stack (FIR23-STACK): `PGVECTOR_DIM=128`, `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline`.
- **Non-inferiority (NI)**: Nam/Tango (1998) paired score test comparing candidate FNIR to incumbent FNIR; `H0: Δ ≤ −δ`, one-sided α=0.025, `π₀ = (p_d − δ)/(2·p_d) = 0.25` at p_d=0.20/δ=0.10 [FIR-11 rev 7].
- **Power ceiling**: FIR-11 R1's 30 probes fall far short of the ≈290 paired-subjects/stratum the locked k=8 / per-test power≈0.97249 design needs — every NI result from this task is reported under the under-powered banner and is DIRECTIONAL tier at best, never REPORTABLE.
- **DIAGNOSTIC / DIRECTIONAL / REPORTABLE**: program-wide evidentiary tiers for this task's own `open_set` report section (distinct from the bench's existing `CrossbenchTier`, see Current State Analysis).
- **pre-CVUP-1**: any artifact produced before the OpenCV 5.x provenance pin (FIR-14); such artifacts are withdrawn and never cited as evidence.

## Current State Analysis

- FIR-8's `scripts/bench/` package exists on disk (verified 2026-09-11 via `search_graph`/`get_code_snippet`, `check_index_coverage` reports `full`/`generation_matches: true`): `cross_stack_bench.py` (`main` 16–50; `_cmd_preflight` 53–62, `_cmd_run` 65–76, `_cmd_status` 79–82, `_cmd_score` 85–90), `driver.py` (`init_run_dir` 79–125, `run_leg` 163–352, `run_pair` 355–429, `run_cluster_phase` 128–160, `evaluate_cluster_gate`/`cluster_gate_admits` 54–76, `AnalyzeOutcome`, `ClusterGateDecision`, `read_status` 432–470), `export_map.py` (`export_leg` 47–77, `require_cluster_success` 36–44, `load_leg_exports` 80–92, `map_cluster_labels_primary` 261–275, `map_cluster_labels_optimistic` 339–421, `to_face_metric_inputs` 424–531, `match_detection_boxes` 146–200, `DetectionMatchResult` 125–132, `LegExport` 28–33), `score.py` (`hungarian_iou_matches` 60–83, `iou_tl` 44–57, coordinate helpers — no open-set scoring today), `score_report.py` (`CrossbenchTier{CONFIRMATORY,DIRECTIONAL,DIAGNOSTIC}` 73–76, `compute_accepted_set` 535–655, `write_accepted_set` 658–675, `write_attrition` 678–730, `build_dual_frames` 733–743, `score_head_to_head` 857–1233, `assign_tier` 305–335, `AcceptedSet` 103–120, `BootstrapInterval` 87–99, `SAMPLING_FRAME_CROSSBENCH_NATIVE`/`SAMPLING_FRAME_E2E` 44–45, `LABEL_MAP_PRIMARY`/`LABEL_MAP_OPTIMISTIC` 46–47), plus `stack_pair.py` (`StackPairConfig`, `StackEndpoint`, `load_stack_pair` 206–253, `validate_stack_pair_config` 153–203, `FIR23_STACK_ALLOWLIST` 77–90), `preflight.py`, `corpus.py`, `status.py`, `production_shaped_guard.py`.
- Test-file naming convention (verified — corrects Brief F's guess): `scripts/bench/tests/test_<topic>.py`, NOT `scripts/bench/test_*.py`. Existing files: `conftest.py`, `test_dag_score.py`, `test_dag_ingest.py`, `test_detection_localization.py`, `test_e2e_frame.py`, `test_export_map_rg015.py`, `test_manifest_version_seam.py`, `test_media_pin_public_unicast.py`, `test_remote_dns_deadline.py`, `test_remote_fetch_bounds.py`, `test_score_head_to_head.py`, `test_stack_pair_consumption.py` (14 files total; two — `test_dag_score.py`, `test_dag_ingest.py` — postdate FIR-8's v6.7 plan text).
- None of `score.py`'s machinery is open-set: zero references to `open_set_identification` or `fir_bakeoff_run` anywhere under `scripts/bench/` (confirmed via `search_code`). This is entirely new work.
- FIR-12's `open_set_identification.SearchResult` (35–52: `detected`, `top1_score`, `top1_name`, `true_name`, `gallery`, `media_id`) and `fir_bakeoff_run.score_run` (410–536, keyword-only `plan`, `searches`, `tau`, `n_enrolled_gallery_subjects=None`, `overall_nonmated=None`, `closed_set=False` → `RunReport`) are merged and stable. `score_run` requires a real `top1_score: float | None` per search: `_is_fpi`/`_is_fnir_miss` (`open_set_identification.py:102–125`) treat `top1_score is None` as an unconditional FNIR miss that can never register FPI.
- **Confirmed gap** (this deviates from the packet's FIR-16 skeleton, which assumed "per-face scores" are already in the export): `export_map._identities_list` reads `export["media_identities"]` rows shaped `{media_id, identity_id, bbox, cluster_label, is_auto_label}` (`export_map.py:222–258`, `_primary_name_for_row` 250–258) — no score field. The production `TenantExportService._serialize_identity` (`recognition/application/services/export_service.py:295–317`) does emit a `confidence` field, but it is `MediaIdentity.confidence` (`db/models/identity.py:56`, `CheckConstraint confidence >= 0 AND confidence <= 1`) — detector confidence, not a gallery-match similarity score. No raw 1:N search/identify HTTP route exists under `recognition/interface_adapters/http/routers/` (confirmed via `search_graph`: zero matches for a search/identify/match endpoint). There is therefore no persisted per-face identification score anywhere in the current export chain; S1a below adds one.
- FIR-13 (`docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md`, drafted 2026-09-11) specifies `scripts/eval_harness/gate_contract.py` — **not yet implemented** (`check_index_coverage` on that path reports `freshness: missing` per FIR-13's own Current State Analysis): `GateContract` (`metric`, `max_fpi: int | None`, `n_nonmated_declared: int | None`, `rubric_version`, `ratified_by_decision_id: str | None`), `GateContractError`, `load_gate_contract(path: str | Path) -> GateContract`, `GateSummary`, `select_gate_point(points: Sequence[IETPoint], *, max_fpi: int) -> IETPoint | None`. Every reference to `gate_contract.*` in this plan is **new, per FIR-13** until that task lands.
- FIR23-STACK (`docs/tasks/fir23-stack/FIR23-STACK-task-plan.md` rev 2): Slices 1–3 unmerged, stack never stood up — S4 of this task is hard-blocked until that changes.
- `benchmarks/manifests/golden150-selection-v1.json` carries a `probe_only_identities` key (packet-verified anchor) — identities enrolled in the gallery but never probed as themselves — this is the non-mated/"stranger" population for the open-set leg. (FIR-11's own plan text does not use this term in prose; it is a manifest JSON key, not a FIR-11 code symbol — Brief F's phrasing conflated the two.)

## Target Outcome

`scripts/bench/score.py` gains a `score_open_set` leg both stacks can be scored through; `score_report.py` gains an `open_set` report section with a paired NI verdict, the FIR-11 power-ceiling banner, and the retained InsightFace licence banner; `cross_stack_bench.py` gains a `propose-gate` subcommand that prints a fixed-format proposal and the exact operator decision the FIR-6 S6 switch-over depends on; and — once acx-dev-fir exists and FIR-6 S4 has calibrated the candidate's knobs — an operator runbook drives one real, reported head-to-head run.

## Context Loading

- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Contracts: `docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md` (`GateContract`), `docs/tasks/fir23-stack/FIR23-STACK-task-plan.md` (stack coordinates, DB reset).
- Handoff/MCP state: task ref `FIR-16`; upstream decision #10843; FIR-8's closing decisions for `scripts/bench/` house style (frozen dataclass + `StrEnum` + fail-closed loader conventions already used by `stack_pair.py`/`score_report.py`).

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Bench ↔ recognition public export | `scripts/bench/` (client) / recognition service (server) | FIR-8 consumption table: `/ready`, `/health/detailed`, tenant export routes; `media_identities` rows `{media_id, identity_id, bbox, cluster_label, is_auto_label}` | S1a adds one additive field, `match_score: float | None`, to the exported identity row | Yes — additive-only; existing FIR-8 consumers (`to_face_metric_inputs` etc.) must not break on the new key | `scene/tests/test_export_service_match_score.py`; extend `test_export_map_rg015.py`-style envelope-honesty coverage for the new field |
| Bench export → `open_set_identification.SearchResult` | `scripts/bench/score.py` (new) → `scripts/eval_harness/` (existing, unchanged) | None today | New `to_open_set_searches` / `score_open_set` translate bench exports into `SearchResult` / `RunReport` | No — internal to this repo | `scripts/bench/tests/test_score_open_set.py` |
| `propose-gate` → FIR-13 `GateContract` | `scripts/bench/cross_stack_bench.py` (new subcommand) | None today | Reads a ratified `benchmarks/manifests/fir-gate-contract-v1.json`; refuses if unratified | No | `scripts/bench/tests/test_propose_gate.py` |

## Proposed Solution

S1a adds the one missing field — a persisted per-face match score — to the production export so an open-set score exists to sweep. S1b wires `scripts/bench/score.py::score_open_set` from that field through `fir_bakeoff_run.score_run`, once per stack (never pooling the two embedding spaces). S2 renders the result as an `open_set` report section carrying the NI verdict and both banners. S3 gives the operator a `propose-gate` CLI and the exact `record_event` decision template. S4 is the live runbook, hard-gated on FIR23-STACK existing and on FIR-6 S4 calibration having run.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| recognition (production) | `apps/prototype-description-service/db/models/identity.py` | `MediaIdentity` (41–105) gains `match_score: Mapped[float \| None] = mapped_column(Float, nullable=True)` — the best-centroid similarity `CentroidDiscovery._find_best_centroid_match` (`recognition/application/discovery/centroid.py` 62–87) returns for the face, persisted for EVERY detected face whether or not the confidence gate accepted it (an open-set sweep needs the score below the production threshold too, or the IET curve is truncated at the deployed tau); `NULL` only when no centroid existed to compare against. Greenfield: edit `001_identity_schema.py` directly, no migration chain. |
| recognition (production) | `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py` | `ConfidenceCheck.evaluate` (91–242) surfaces the raw similarity score computed ahead of `final_threshold` (176) so the persistence call can write it to `MediaIdentity.match_score`. |
| recognition (production) | `apps/prototype-description-service/recognition/application/services/export_service.py` | `_serialize_identity` (295–317) adds `"match_score": identity.match_score` to the emitted dict. |
| eval-harness | `apps/prototype-description-service/scripts/bench/export_map.py` | New `to_open_set_searches(export: LegExport, manifest, join: dict[int, dict], *, roster: Sequence[str], gallery: GalleryName) -> list[SearchResult]` (see Slice 1). |
| eval-harness | `apps/prototype-description-service/scripts/bench/score.py` | New `score_open_set(searches: Mapping[str, list[SearchResult]], *, plan_by_stack: Mapping[str, RunPlan], tau_grid: Sequence[float]) -> dict[str, RunReport]`. |
| eval-harness | `apps/prototype-description-service/scripts/bench/score_report.py` | New `score_open_set_report(run_dir: Path \| str) -> Path`, `render_open_set_section(reports: dict[str, RunReport], *, contract: GateContract) -> dict[str, Any]`, `PowerCeilingBanner` dataclass + `format_power_ceiling_banner(...)`, reuse of the existing licence banner text. |
| eval-harness | `apps/prototype-description-service/scripts/bench/cross_stack_bench.py` | New `propose-gate` subcommand (argparse) + `_cmd_propose_gate(args)`. |
| tests | `apps/prototype-description-service/scripts/bench/tests/test_score_open_set.py` | New. |
| tests | `apps/prototype-description-service/scripts/bench/tests/test_score_report_open_set.py` | New. |
| tests | `apps/prototype-description-service/scripts/bench/tests/test_propose_gate.py` | New. |
| tests | `apps/prototype-description-service/scene/tests/test_export_service_match_score.py` | New — production export field round-trip. |
| docs | `docs/runbooks/fir-16-open-set-head-to-head-acx-dev-fir.md` | New — S4 operator runbook. |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/scripts/eval_harness/open_set_identification.py` | `SearchResult` (35–52), `IETPoint` (56–99), `fnir_fpi_at_threshold` (128–167), `iet_curve` (170–186). |
| `apps/prototype-description-service/scripts/eval_harness/fir_bakeoff_run.py` | `score_run` (410–536), `RunReport` (183–260), `MatedSearchUnit` (151–163), `GALLERY_STRATUM`/`PROBE_STRATA`, `build_run_plan` (263–288). |
| `apps/prototype-description-service/scripts/eval_harness/gallery_split.py` | `GalleryName` StrEnum (`G1`, `G2`) — this task uses `G1` only (Golden-150 R1 is single-gallery per its `golden150-selection-v1.json` shape; `[UNVERIFIED — confirm via codemap]` whether a `G2` split is ever required here). |
| `docs/tasks/fir/FIR-13-open-set-gate-contract-task-plan.md` | `GateContract`/`select_gate_point` this task consumes (planned, not yet implemented). |
| `docs/tasks/fir/FIR-11-gate-corpus-remediation-and-fir-rebaseline-task-plan.md` rev 7 | Corpus (30/30/17), Nam/Tango NI procedure, power ceiling — cited, not restated. |
| `docs/tasks/fir23-stack/FIR23-STACK-task-plan.md` rev 2 | Stack coordinates, DB reset command. |
| `docs/tasks/fir/FIR-8-recognition-profile-bench-toggle-task-plan.md` v6.7 | Consumption table, `/ready`/`/health/detailed` preflight, export shapes, existing `CrossbenchTier`. |
| `docs/tasks/fir/FIR-6-calibration-quality-switchover-task-plan.md` | S4 calibration this task's live run (S4) must run after. |

## Verification Strategy

- Deterministic tests:
  - `uv run --extra dev pytest scripts/bench/tests/test_score_open_set.py scripts/bench/tests/test_score_report_open_set.py scripts/bench/tests/test_propose_gate.py -q` (run from `apps/prototype-description-service`)
  - `uv run --extra dev pytest scene/tests/test_export_service_match_score.py -q`
- Runtime-parity / environment checks: S4 only — live acx-dev-fir + acx-dev over public HTTP, per FIR-8's consumption table; no direct DB access.
- Contract/fixture verification: a `score_open_set` fixture asserts a `top1_score=None` search never becomes FPI (mirrors `open_set_identification._is_fpi`'s own invariant); a `propose-gate` fixture asserts non-zero exit when `contract.ratified_by_decision_id is None`.
- Manual verification: S4 runbook walkthrough on acx-dev-fir once FIR23-STACK ships and FIR-6 S4 has run.

## Slice Delivery

### Slice 1: Open-set leg in the cross-stack bench (Phase C)

**Goal**: Both stacks can be scored for FNIR@FPIR from their exports, each at its own swept tau.

Changes:

- **S1a — persisted match score (prerequisite)**: `db/models/identity.py` `MediaIdentity` gains `match_score: Mapped[float | None]` (nullable, no check constraint; written for every detected face from the best-centroid similarity regardless of the accept decision; `NULL` only when the gallery had no centroids); `001_identity_schema.py` edited directly (greenfield, no migration chain); `confidence.py::ConfidenceCheck.evaluate` (91–242) surfaces the raw similarity score to the caller that persists `MediaIdentity`; `export_service.py::_serialize_identity` (295–317) adds `"match_score": identity.match_score`.
- **S1b — field-by-field export → `SearchResult` mapping**, implemented as new `export_map.to_open_set_searches`:

  | `media_identities` row field (post-S1a) | `SearchResult` field | Mapping rule |
  | --- | --- | --- |
  | `media_id` (int) | `media_id: int` | direct; `SearchResult.__post_init__` rejects non-int/bool. |
  | presence of a row matched to the probe's GT box via `match_detection_boxes` (`export_map.py:146–200`) | `detected: bool` | `True` iff the probe's face box has a matched prediction index (`match.matched_gt_indices`, same logic `to_face_metric_inputs` already uses at 424–531). |
  | `match_score` (new, S1a) | `top1_score: float | None` | direct, independent of the accept decision (rejected faces keep their best-centroid score); `None` only when absent (undetected) or no centroid existed. |
  | `cluster_label` mapped through `_primary_name_for_row` (250–258) or `map_cluster_labels_optimistic` (339–421) per the run's declared `label_map` | `top1_name: str | None` | same primary/optimistic choice `to_face_metric_inputs` already makes; `None` when no roster name resolves. |
  | manifest entry's declared identity for this probe, OR `None` if the probe's identity is listed only in `golden150-selection-v1.json`'s `probe_only_identities` | `true_name: str | None` | `None` marks a non-mated (stranger) search — never invented, always read from the manifest. |
  | fixed per run | `gallery: GalleryName | str` | `GalleryName.G1` (see Related Files). |

  `score.py::score_open_set(searches: Mapping[str, list[SearchResult]], *, plan_by_stack: Mapping[str, RunPlan], tau_grid: Sequence[float]) -> dict[str, RunReport]` builds one `RunPlan`/`RunReport` **per stack** (never pooled — 512-D and 128-D are separate embedding spaces, EMB-01/IDX-02) by calling `fir_bakeoff_run.score_run(plan=plan_by_stack[stack_id], searches=..., tau=tau, ...)` once per candidate `tau` in `tau_grid`, keeping the `IETPoint` sequence per stack for `gate_contract.select_gate_point` (S2) to consume.

Proof:

- `scripts/bench/tests/test_score_open_set.py` — fixtures: (a) a mated search with `top1_score=None` never registers FPI/FNIR-pass (mirrors `open_set_identification._is_fpi`); (b) two stacks scored from the same manifest never share a `tau`; (c) `to_open_set_searches` round-trips a synthetic export with `probe_only_identities` correctly producing `true_name=None` rows.
- `uv run --extra dev pytest scripts/bench/tests/test_score_open_set.py -q`
- `uv run --extra dev pytest scene/tests/test_export_service_match_score.py -q`

### Slice 2: Head-to-head report (Phase C)

**Goal**: One report renders both stacks' D3 numbers, a paired non-inferiority verdict, and the mandatory banners.

Changes:

- `score_report.py::score_open_set_report(run_dir: Path | str) -> Path` reads both stacks' `RunReport`s (S1) and the ratified `GateContract` (FIR-13), calls `gate_contract.select_gate_point` per stack, and writes `benchmarks/results/crossbench-<stamp>/open_set.json` + `.md`.
- `render_open_set_section(reports: dict[str, RunReport], *, contract: GateContract) -> dict[str, Any]` emits, per stack: `{fnir_at_gate, tau, fpi, n_mated, n_nonmated, coverage_gaps, toolchain, contract, measured}` — `measured=False` cells render `fnir_at_gate: null`, never `0.0` [AUDIT-04].
- Paired NI verdict: candidate vs incumbent FNIR at their respective gate points, via FIR-11 rev 7's Nam/Tango paired score test (`paired_ni_score_test`, `H0: Δ ≤ −δ`, one-sided α=0.025) — **not implemented by this task**; this section calls it as a dependency once FIR-11's `scripts/eval_harness/face_metrics.py` symbol lands (`[UNVERIFIED — confirm via codemap]`: `paired_ni_score_test` is listed "new" in FIR-11 rev 7's Files table but is not yet on disk under `scripts/eval_harness/`; verified absent via `search_graph`).
- `PowerCeilingBanner` dataclass (`stratum: str`, `n_available: int`, `n_required: int`, `verdict: Literal["under_powered"]`) + `format_power_ceiling_banner(...)` — stamped whenever `n_available < n_required` (always true for Golden-150 R1's 30 probes against the ≈290/stratum design) and forces the section's tier to at most `DIRECTIONAL`, never `REPORTABLE`.
- Retain the existing InsightFace licence banner text (already emitted by `driver.py::LICENSE_BANNER`, 35–37) in the `open_set` section's rendered Markdown.

Proof:

- `scripts/bench/tests/test_score_report_open_set.py` — fixtures: (a) an under-powered stratum always renders the banner and caps the tier at DIRECTIONAL; (b) an unmeasured cell renders `null`, never `0.0`; (c) the licence banner text is present verbatim in the rendered `.md`.
- `uv run --extra dev pytest scripts/bench/tests/test_score_report_open_set.py -q`

### Slice 3: Gate proposal + operator decision (Phase C)

**Goal**: The operator gets one fixed-format proposal and records one decision that FIR-6 S6 can cite.

Changes:

- `cross_stack_bench.py`: new `propose-gate` subcommand — `propose-gate --report <path/to/open_set.json> --contract <path/to/fir-gate-contract-v1.json>`. Prints: candidate FNIR@FPIR vs incumbent FNIR@FPIR, the NI margin δ and its CI, the section tier (DIAGNOSTIC/DIRECTIONAL/REPORTABLE), coverage gaps, and a withdrawn-artifact statement (naming M-12/recall-0.504/2.73-faces-per-image as withdrawn and excluded from the comparison).
- Refuses (exit code 1, no proposal printed) when `GateContract.ratified_by_decision_id is None` — an unratified D3 operating point can never be proposed against.
- Prints the exact `record_event` call the operator runs to close the loop:

  ```python
  record_event(event={
      "event_kind": "decision",
      "decision": "fir_gate_decision_<date>",
      "actor": {...},
      "details": {
          "candidate_fnir_at_gate": ...,
          "incumbent_fnir_at_gate": ...,
          "ni_verdict": ...,
          "tier": ...,
          "contract_decision_id": contract.ratified_by_decision_id,
      },
  })
  ```

  This decision id is what the FIR-6 S6 switch-over task plan cites as its gating input.

Proof:

- `scripts/bench/tests/test_propose_gate.py` — fixtures: (a) unratified contract → non-zero exit, no proposal text; (b) ratified contract → proposal block contains all six required fields; (c) withdrawn-artifact statement is present verbatim.
- `uv run --extra dev pytest scripts/bench/tests/test_propose_gate.py -q`

### Slice 4: Live run runbook on acx-dev-fir (Phase D)

**Goal**: One real, reported open-set head-to-head run, executed only after its gates clear.

**Ordering constraint (must be stated verbatim in the runbook)**: FIR-6 S4 (calibration on the FIR-11 R1 remediated corpus, incorporating FIR-17's OACT direction fix) MUST run and complete BEFORE this slice executes, so the candidate `face_pipeline` stack is scored with its calibrated knobs (`face_similarity_threshold`, `face_complete_link_threshold`, `oact_coefficient`) rather than defaults. This slice also requires FIR23-STACK's Slices 1–3 merged and acx-dev-fir standing (currently unmerged, stack never stood up).

Changes:

- New `docs/runbooks/fir-16-open-set-head-to-head-acx-dev-fir.md`:
  1. Stack-pair YAML per FIR-8's consumption table: `stack_id` allowlist entries `acx-dev-insightface` (buffalo_l/512) and `acx-dev-fir` (face_pipeline/128); env keys `ACX_BENCH_DEV_TENANT_ID`/`ACX_BENCH_FIR_TENANT_ID`, `ACX_BENCH_DEV_API_KEY`/`ACX_BENCH_FIR_API_KEY`.
  2. Preflight: `GET {base_url}/ready` (dimension via the `name=="database"` entry's `detail` regex `pgvector_dimension=(\d+)`), authenticated `GET {base_url}/health/detailed` (profile via `body["model_cache"]["profile"]`) — per FIR-8's preflight contract; fail-closed error codes `preflight_auth_failed`, `preflight_endpoint_missing`, `profile_or_dim_drift`, `opencv_major_unattested`.
  3. DB reset (acx-dev-fir only, if a clean slate is needed before the run): `ENV=dev-fir CONFIRM=RESET scripts/deploy/db-reset-remote.sh` (or `make db-reset-remote ENV=dev-fir CONFIRM=RESET`) — confirmed via direct read of `scripts/deploy/db-reset-remote.sh:73-78`: `PG_CONTAINER=acx-dev-fir-postgres-1`, `API_CONTAINER=acx-dev-fir-api-1`, `PG_USER=acx_dev_fir`, `PG_DB=alt_context_dev_fir`, `HEALTH_URL=https://fir.dev.api.altcontext.com/health`. Documented FIR23-STACK command — not invented.
  4. `cross_stack_bench.py run` → ingest → analyze → cluster → export on both stacks (`driver.run_pair`).
  5. `cross_stack_bench.py score` (existing detection/cluster legs) + the new open-set leg (S1/S2 of this task).
  6. `cross_stack_bench.py propose-gate` (S3) → operator reviews → records `fir_gate_decision_<date>`.
  7. `render_handoff(kind='dashboard')` after the decision is recorded.
  8. Failure routing: preflight failure → do not run; cluster-gate failure → do not score; NI section under-powered → tier capped at DIRECTIONAL, proposal still permitted but flagged.

Proof:

- Runbook walkthrough on acx-dev-fir once FIR23-STACK Slices 1–3 merge and the stack is up; no automated test (infrastructure-gated). Verification checklist embedded in the runbook mirrors FIR-8's Slice 3 checklist pattern.

## Lane Decomposition (Multi-Agent)

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `fir-16-l1` | `apps/prototype-description-service/db/models/identity.py`, `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`, `apps/prototype-description-service/recognition/application/assignment/checks/confidence.py`, `apps/prototype-description-service/recognition/application/services/export_service.py`, `apps/prototype-description-service/scripts/bench/export_map.py`, `apps/prototype-description-service/scripts/bench/score.py`, `apps/prototype-description-service/scripts/bench/tests/test_score_open_set.py`, `apps/prototype-description-service/scene/tests/test_export_service_match_score.py` | FIR-13 (`gate_contract.py`), FIR-8 (merged) | `python3 -m pytest scripts/bench/tests/test_score_open_set.py scene/tests/test_export_service_match_score.py -q` |
| `fir-16-l2` | `apps/prototype-description-service/scripts/bench/score_report.py`, `apps/prototype-description-service/scripts/bench/cross_stack_bench.py`, `apps/prototype-description-service/scripts/bench/tests/test_score_report_open_set.py`, `apps/prototype-description-service/scripts/bench/tests/test_propose_gate.py` | `fir-16-l1` (needs `score_open_set`/`RunReport` output shape) | `python3 -m pytest scripts/bench/tests/test_score_report_open_set.py scripts/bench/tests/test_propose_gate.py -q` |
| `fir-16-l3` | `docs/runbooks/fir-16-open-set-head-to-head-acx-dev-fir.md` | `fir-16-l2` (cites its CLI/report shapes) | none (doc-only; reviewed, not tested) |

### Merge Order

`fir-16-l1` → `fir-16-l2` → `fir-16-l3`.

### Manifest

```bash
make lane-manifest-init TASK=FIR-16 LANE_IDS='fir-16-l1 fir-16-l2 fir-16-l3' TASK_PLAN=docs/tasks/fir/FIR-16-open-set-head-to-head-task-plan.md
```

### Orchestration Mode

- **Codex subagent (preferred when available)**: Use MCP worker lifecycle tools with the declared lane ownership and verification boundaries.
- **Shell fallback**: Use repo lane helpers or manual worktrees while preserving the same ownership and evidence requirements.

---

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"FIR-16"})` or read from `DASHBOARD.txt`.

## Context and Ownership

- [ ] Loaded FIR-13's `GateContract`/`select_gate_point` shape and FIR-11 rev 7's NI procedure/power-ceiling numbers before writing `score_open_set`/`render_open_set_section`.
- [ ] Confirmed the export-schema gap (no persisted match score) and implemented S1a rather than assuming a field that does not exist.

### Checklist for Slice 1: Open-set leg in the cross-stack bench

- [ ] `MediaIdentity.match_score` added; `confidence.py` surfaces the raw score; `export_service.py` emits `match_score`.
- [ ] `export_map.to_open_set_searches` implemented per the field-by-field mapping table.
- [ ] `score.py.score_open_set` scores each stack independently, never pooling embedding spaces.
- [ ] `top1_score=None` never registers FPI or an FNIR pass (test asserted).

### Checklist for Slice 2: Head-to-head report

- [ ] `score_open_set_report` writes `open_set.json` + `.md` under `benchmarks/results/crossbench-<stamp>/`.
- [ ] Unmeasured cells render `null`, never `0.0`.
- [ ] Power-ceiling banner renders whenever `n_available < n_required` and caps the tier at DIRECTIONAL.
- [ ] Licence banner text present verbatim in the rendered report.

### Checklist for Slice 3: Gate proposal + operator decision

- [ ] `propose-gate` refuses (non-zero exit) on an unratified `GateContract`.
- [ ] Proposal block contains all six required fields plus the withdrawn-artifact statement.
- [ ] `fir_gate_decision_<date>` decision template printed verbatim and matches what `record_event` expects.

### Checklist for Slice 4: Live run runbook on acx-dev-fir

- [ ] Runbook states the FIR-6 S4-before-head-to-head ordering constraint verbatim.
- [ ] DB reset step cites the exact `db-reset-remote.sh` `dev-fir` invocation, not an invented one.
- [ ] Failure routing table covers preflight, cluster-gate, and under-powered NI cases.

## Review Readiness

- [ ] No boundary-touching implementation (S1a's production export field) is left without matching contract/doc/fixture evidence.
- [ ] Every open-set report cell that is unmeasured renders `null`, never a fabricated `0.0` or default.
- [ ] Handoff decision records the change, verification, and the fact that S4 remains gated on FIR23-STACK + FIR-6 S4.

## Stretch Goals

- [ ] A `--tau-grid-from-contract` flag on `propose-gate` that reads the sweep grid from the ratified contract instead of a CLI argument.
- [ ] `score_open_set_report` emits a small ASCII table comparing both stacks' IET curves for quick operator scanning.

## Success Criteria

- [ ] `score_open_set`, `to_open_set_searches`, `score_open_set_report`, and `propose-gate` exist, are imported by the bench CLI, and pass their test suites.
- [ ] The `open_set` report section always carries the power-ceiling and licence banners and never claims REPORTABLE tier against Golden-150 R1.
- [ ] `propose-gate` cannot be made to print a proposal against an unratified `GateContract`.
- [ ] The S4 runbook is ready to execute the moment FIR23-STACK ships and FIR-6 S4 completes, with no further design decisions left open.
