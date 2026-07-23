# Task Plan — FIR-7. Occlusion-Robustness Adapters for YuNet + SFace

> **Metadata**
>
> - **Date**: 2026-07-23 05:15 EST
> - **Author**: Claude Fable 5
> - **Owning Epic**: `docs/epics/v0.3.1/self-hosting-epic.md` (E22 face pipeline lineage; FIR series)
> - **Epic Short ID**: FIR
> - **Task ID**: FIR-7
> - **Target Branch**: `feature/fir-7`
> - **Review Coverage Target**: 2
>
> Review counts/finding totals live in the handoff DB, not this file.

---

## FIR-7. Occlusion-Robustness Adapters for YuNet + SFace

## Objective

Raise the face pipeline's occlusion robustness — measured on Golden-150 as masked synthetic recovery `a_s` 0.321 / sunglasses 0.226 and 54/84 masked re-detect misses — by producing **owned, commercially-clean adapted weights** for the detector and recognizer, without full retraining and without any clean-face regression. Deliver two sequenced adaptations: a targeted YuNet detector fine-tune, then a frozen-base SFace mask-invariant adapter, each gated by a Golden-150 re-run.

## Intake (new-feature scope pass)

- **Key Q&A decisions**: `decision #2939` (FIR-7 scope intake).
- **Scope**: both models, sequenced — detector adapter first (holds ~80% of the measured loss), then recognizer adapter.
- **Training data**: synthetic / self-only. Golden-150 twin renders on the consented corpus + license-checked synthetic-identity sets. NO research-only datasets (WIDERFace occlusion subset, MFR/RMFRD masked corpora are excluded — they would taint the weights' commercial use).
- **Success bar**: advisory targets, empirical gate. Plan proposes `a_s` masked > 0.55 and masked re-detect miss at least halved with **zero clean-face floor regression**; the actual pass/fail is the operator's call on the Golden-150 re-gate.
- **Not-Doing**: (a) no from-scratch FR training on WebFace-scale data; (b) no InsightFace/buffalo weights in the shipped path (non-commercial); (c) no new occlusion strata capture (mirrors gap, real-occlusion n) — this task consumes the existing corpus; (d) no production rollout/switch-over decision — that is FIR-6's gated S6; this task delivers candidate weights + evidence only.

## Problem Statement

The shipped candidate pipeline (YuNet detect + SFace embed, Apache-2.0, 128-D) is occlusion-weak. Golden-150 (v6.1, run `face-run-20260723-074749`) measured, at leg=candidate:

- Detection recall 0.504 on clean human-verified boxes (186/375 faces missed) — the detector is the dominant failure even before occlusion.
- Synthetic occlusion recovery `a_s`: masked 0.321 (54/84 re-detect miss), sunglasses 0.226 (49/84), occlusion_other 0.643 (5/84). Real-occlusion legs at floor-limited n.

The failure is concentrated in **detection**: an occluded face YuNet never finds never reaches SFace, so recognizer-only work is capped. The commercial ceiling reference (InsightFace/buffalo) is non-commercial-weights; buying a license or retraining from scratch are both heavier than warranted when a targeted, parameter-efficient adaptation of the already-owned Apache stack can attack the measured gap directly and yield **weights we own outright**.

## Constraints

- **Proprietary-clean provenance (legal gate).** Adapted weights must remain commercially usable: Apache-2.0 base (YuNet/SFace from OpenCV Zoo) + synthetic/self-generated training data + our own training code. Apache permits proprietary derivatives (attribution + modification notice retained). Any research-only dataset in the training path voids this and is prohibited. A written license-provenance audit is a slice deliverable, not an afterthought.
- **PEFT, not full retrain (FM-07).** Prefer frozen-base + small adapter / partial fine-tune over full-weight training. The recognizer adapter MUST freeze the SFace backbone (the frozen base is the forgetting guard, see AdaFace FAIR-NN below).
- **CACE — Changing Anything Changes Everything.** Any weight change ripples through detection → clustering → assignment → thresholds. Every adaptation is gated by a full Golden-150 re-run proving clean-face floors are unchanged; a clean-face regression fails the slice regardless of occlusion gain.
- **PROV-01 / FIR23 lineage.** Each produced model gets a new `embedding_model` (and detector-model) identifier; the recognition read-path already filters on per-row `embedding_model` (merged FIR23-01). Mixed-space comparison is forbidden — adapted embeddings must not be compared against base-model embeddings without a re-embed.
- **Training runs in the cloud, not on-prem.** Operator laptop is 8 GB M1 (orchestration only). Rent a single A100/H100 for the campaign; synthetic identities carry no privacy constraint, so cloud training is clean. Do not buy hardware for a one-off campaign.
- **Exhaust cheaper levers first (FM-05).** No weight training until Slice 0's config/pooling levers are measured; if they close the gap, later slices may be descoped.
- **Determinism + reproducibility (rg-015, EVAL).** Training is seeded and logged; produced weights are content-hashed and carry a model card (PROV-02). Eval is the existing Golden-150 harness — do not invent a parallel scorer.

## Workflow Principles

- **Measure before, after, and against a frozen baseline.** Every slice reports the Golden-150 delta vs the frozen v6.1 candidate baseline, not vs the previous slice alone.
- **The eval harness is the source of truth.** Reuse `scripts/eval_harness` (twin renderer, `score-face`, floors, DIRECTIONAL logic). The training-data generator is the SAME twin machinery (`build_occlusion_twin_pairs` / `synthetic_occlusion.py`) used for evaluation — with a strict train/eval identity split to prevent leakage.
- **Frozen base for the recognizer.** SFace weights are never updated; only the adapter trains. This makes "LQ↑ without HQ↓" true by construction.
- **One legal owner of the data manifest.** A single dataset-provenance manifest declares every training source and its license; nothing enters training that is not in it.
- **No silent capability inflation.** Candidate weights and their gate evidence ship together; no demo or claim references adapted-model numbers until the re-gate passes.

## Terminology

- **Adapter**: a small trainable module (residual/bottleneck branch or low-rank conv delta) added to a frozen backbone; trained on the narrow occlusion target while the base is unchanged.
- **Mask-invariant adapter**: recognizer adapter trained so `embed(occluded_face) ≈ embed(clean_face)` for the same identity (consistency/distillation objective), producing occlusion-invariant embeddings.
- **Twin**: a synthetic occluded render of a clean base face (mask / sunglasses / other) generated by `synthetic_occlusion.py` from a frozen landmark cache; the (clean, occluded) pair is the training and eval unit.
- **Re-detect miss**: an occluded twin the detector fails to re-detect after occlusion is applied; the dominant candidate failure mode.
- **`a_s`**: synthetic occlusion recovery accuracy — fraction of eligible occluded twins correctly identified at the per-identity held-out τ.
- **Train/eval identity split**: Golden-150 identities are partitioned; occlusion training uses only train-split identities so the Golden-150 eval (built on eval-split + all strata) never sees a trained identity as a probe. (Non-negotiable — training on eval identities would inflate `a_s`.)

## Current State Analysis

- **Works**: YuNet+SFace candidate leg runs end-to-end on Golden-150; twin pipeline generates 300 pairs; `score-face` emits per-tag occlusion `a_s`, re-detect miss, floors, DIRECTIONAL logic; per-row `embedding_model` provenance + fail-closed read-path (FIR23-01) already on main.
- **Broken/weak**: detection recall 0.504; masked/sunglasses recovery low with detection as the bottleneck; no training/adaptation harness exists (the harness is eval-only); no cloud training runbook.
- **Misleading if untouched**: occlusion caption mining is "text-suggested" (operator overturned 13 in the sweep) — training-data occlusion labels must come from the *rendered* twins (ground-truth by construction), NOT caption mining.
- **Adjacent**: FIR-6 owns calibration/switch-over (S4-S6, operator-gated). FIR-7 produces candidate weights + evidence that feed FIR-6's decision; it does not itself flip production.

## Target Outcome

Two owned, Apache-clean adapted artifacts with model cards and Golden-150 evidence:

1. **YuNet-occ** — detector fine-tuned to re-detect masked/occluded faces; masked re-detect miss at least halved (target ≤ ~27/84), clean detection recall not regressed.
2. **SFace-occ-adapter** — frozen-SFace + mask-invariant adapter; occlusion `a_s` masked > 0.55 (advisory), all clean-face floors (detection, unknown-rejection, clustering, full-corpus ID) unchanged within noise.

Both integrated behind the existing model-swap seam with a working rollback to the base weights, each stamped with a distinct `embedding_model`/detector id. Final ship decision deferred to FIR-6's gate.

## Context Loading

> Minimum authoritative surfaces for the implementer.

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/development-workflow.md`.
- Heuristics (v0.12.2 canon + distilled): `~/Development/heuristics-canon/lexicons/ml-systems.md` rows FM-05/FM-07, EMB-02/03/04/09, EVAL-16/18, CAL-07, AUDIT-11, PROV-01/02, DRIFT-01/02; `~/Development/heuristics-canon-research/distilled/ml-systems/{adaface,handbook-face-recognition,hidden-technical-debt-ml,janus-benchmark-c}.md`.
- Harness: `apps/prototype-description-service/scripts/eval_harness/{synthetic_occlusion,face_bakeoff,face_assignment,report,manifest,cli}.py`.
- Runtime seam: `apps/prototype-description-service/recognition/infrastructure/embeddings/face_pipeline_adapter.py`, `.../recognition/application/embedding/manifest.py`, FIR23 read-path (`label_inference.py`, `cluster_repository.py`, `health.py`).
- Corpus + evidence: `benchmarks/manifests/golden150-draft-20260723.json` (+ sidecar), `benchmarks/results/golden150-fir-{v2,final}-20260723/`.
- Handoff: FIR-7 (decision #2939), FIR-5 findings (BUFREV-*, FIR5GL-01 twin-wiring @9b33bca2), FIR-6 state.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `embedding_model` id | recognition backend | per-row model provenance (FIR23-01) | +2 new ids (`yunet-occ-*`, `sface-occ-adapter-*`) registered in the model manifest | yes — mixed-space guard must reject cross-model compares; re-embed on switch | `test_fir23_embedding_model_read_paths.py` + a new adapter-model registration test |
| face pipeline model loader | recognition backend | loads pinned YuNet/SFace ONNX | load adapted ONNX by id; rollback to base by id | yes — rollback path (RLSE-10) names the previous-good artifact | boot smoke + health readiness with each id; rollback test |
| eval-harness leg | eval tooling | candidate (YuNet+SFace), buffalo (bench) | +adapted-candidate leg selectable by model id | no (additive; bench-gated pattern from FIR-5 buffalo leg) | Golden-150 run with `--leg` / model-id selection |

## Proposed Solution

Five slices, cheapest-first, each independently gated:

- **Slice 0** exhausts non-training levers (detector threshold/resolution/tiling, crop margin, template pooling, feature-norm quality weighting, uncertainty-penalized similarity) and re-measures — establishing whether training is even needed and by how much.
- **Slice 1** builds the clean occlusion training-data pipeline (reusing the twin renderer) with a legal-provenance manifest and a strict train/eval identity split.
- **Slice 2** fine-tunes YuNet on occluded detection (cloud GPU) → `yunet-occ`.
- **Slice 3** trains the frozen-base SFace mask-invariant adapter (cloud GPU) → `sface-occ-adapter`.
- **Slice 4** integrates both behind the model-swap seam with rollback and re-gates the full pipeline.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| eval tooling | `scripts/eval_harness/cli.py` | `--leg adapted` / model-id selection for detector+embedder (mirror FIR-5 buffalo dispatch) |
| eval tooling | `scripts/eval_harness/config_levers.py` (new) | Slice 0 lever sweeps (threshold/resolution/crop-margin/pooling) as reproducible harness options |
| training (new) | `scripts/train/occlusion/data_pipeline.py` (new) | clean (clean,occluded) pair generation from twin renderer + synthetic-identity ingest; dataset-provenance manifest |
| training (new) | `scripts/train/occlusion/train_yunet_occ.py` (new) | YuNet detector fine-tune (cloud), seeded, checkpoint + model card |
| training (new) | `scripts/train/occlusion/train_sface_adapter.py` (new) | frozen-SFace mask-invariant adapter train (consistency loss) |
| training (new) | `scripts/train/occlusion/README.md` (new) | cloud GPU runbook (rent → train → export ONNX → download) |
| runtime | `recognition/application/embedding/manifest.py` | register `yunet-occ-*` / `sface-occ-adapter-*` model ids |
| runtime | `recognition/infrastructure/embeddings/face_pipeline_adapter.py` | load adapted ONNX by id; adapter compose for SFace; rollback path |
| docs | `docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md` | this plan |
| provenance | `benchmarks/manifests/occlusion-training-data-provenance.json` (new) | license audit of every training source |

## Related Files

| File | Note |
| --- | --- |
| `scripts/eval_harness/synthetic_occlusion.py` | twin renderer — reused as the training-data generator; enforce train/eval identity split here |
| `scripts/eval_harness/face_bakeoff.py` | `build_occlusion_twin_pairs` (FIR5GL-01 @9b33bca2) — the pair-generation seam |
| `recognition/application/suggestions/label_inference.py` | FIR23 embedding_model read-path — must reject mixed-space compares |
| `benchmarks/results/golden150-fir-v2-20260723/` | frozen baseline for all deltas |

## Verification Strategy

- **Deterministic tests**:
  - `cd apps/prototype-description-service && uv run --extra dev pytest scene/tests -k "eval_harness" -q` (harness stays green; +new lever/leg tests, mocked training).
  - `uv run --extra dev pytest recognition/tests/unit/test_fir23_embedding_model_read_paths.py` (mixed-space guard + new ids).
  - New: adapter-model registration + rollback unit test; dataset-provenance manifest schema test (fails on any research-license source).
- **Runtime-parity / environment checks**:
  - `make check-remote` (full gate) at each integration point.
  - Golden-150 re-run on the VM per adapted artifact: `python -m scripts.eval_harness.cli face-bakeoff --leg adapted --manifest ... && score-face --check-determinism`.
- **Contract/fixture verification**:
  - Boot smoke + health readiness with each model id; rollback to base verified fail-closed.
- **Manual verification**:
  - Operator reviews the Golden-150 delta table per slice (advisory-target judgment).

## Slice Delivery

### Slice 0: Cheap-lever baseline (no training)

**Goal**: Measure every non-training occlusion lever against Golden-150 and decide how much training is actually required.

Changes:

- Add `config_levers.py` harness options: YuNet `det_threshold` sweep, input-resolution / tiling, alignment crop-margin (0/20/40% context), recognition-side template pooling (per-identity quality-weighted aggregate, EMB-02/EMB-07), AdaFace pre-normalization feature-norm quality weighting (EMB-03), uncertainty-penalized similarity (EMB-09).
- Run each lever (and stacked best combo) on Golden-150; produce a delta table vs the frozen v6.1 baseline.

Proof:

- `benchmarks/results/golden150-levers-*/` delta table: per-lever detection R, masked/sunglasses `a_s`, re-detect miss, and any clean-floor movement. Explicit "training still needed for X" statement (or descope note if a lever closes the gap).

### Slice 1: Clean occlusion training-data pipeline

**Goal**: Produce (clean, occluded) same-identity training pairs with proven clean provenance and a strict train/eval identity split.

Changes:

- `data_pipeline.py`: generate training pairs from the twin renderer over **train-split identities only**; ingest license-checked synthetic-identity faces (Vec2Face/DCFace — license verified before ingest); emit a dataset-provenance manifest listing every source + license.
- Dataset-provenance manifest schema test: rejects any source whose license is research-only.

Proof:

- `occlusion-training-data-provenance.json` with a passing license audit; pair-count + per-tag + per-identity report; a leakage check proving no eval-split identity appears in training.

### Slice 2: YuNet detector occlusion fine-tune → `yunet-occ`

**Goal**: Halve masked re-detect misses without regressing clean detection recall.

Changes:

- `train_yunet_occ.py`: seeded fine-tune of YuNet on occluded-face detection (synthetic occluders over clean bases + synthetic-identity faces), export ONNX, emit model card (base weights, data manifest, seed, metrics).
- Cloud GPU runbook (rent single A100/H100 → train → export → download; teardown).
- Register `yunet-occ-*` id.

Proof:

- Golden-150 re-gate: masked re-detect miss ≤ ~27/84 (advisory), clean detection recall within noise of 0.504 baseline (CACE gate: no clean regression). Model card + content hash committed to `benchmarks/`.

### Slice 3: SFace frozen-base mask-invariant adapter → `sface-occ-adapter`

**Goal**: Raise occlusion `a_s` with the SFace backbone frozen and clean-face embeddings preserved.

Changes:

- `train_sface_adapter.py`: freeze SFace; train a small adapter with a consistency/distillation loss `L = ||embed_adapted(occluded) − embed_base(clean)||` (+ optional margin term on identity separation); no base-weight updates. Export composed ONNX / adapter module; model card.
- Register `sface-occ-adapter-*` id; enforce it produces a distinct `embedding_model`.

Proof:

- Golden-150 re-gate: occlusion `a_s` masked > 0.55 (advisory); clean-face floors (unknown-rejection, clustering purity/pairs, full-corpus ID P/R) unchanged within noise vs baseline (AdaFace FAIR-NN "LQ↑ without HQ↓" verified). Adapter is genuinely frozen-base (test asserts base weights unchanged).

### Slice 4: Runtime integration + rollback + full re-gate

**Goal**: Load both adapted artifacts behind the model-swap seam with a working rollback, and produce the final head-to-head.

Changes:

- Load adapted ONNX by id in `face_pipeline_adapter.py`; SFace adapter compose; rollback-to-base path (RLSE-10, names the previous-good artifact).
- Final Golden-150 head-to-head: base candidate vs `yunet-occ` vs `yunet-occ + sface-occ-adapter`.

Proof:

- Boot smoke + health readiness green per id; rollback test; `make check-remote` green; final delta table in `benchmarks/results/golden150-fir-adapted-*/`; handoff decision records candidate weights + evidence for FIR-6's gate.

## Lane Decomposition (Multi-Agent)

> Slices are largely sequential (0 → 1 → {2,3} → 4). Slices 2 and 3 can run as parallel lanes once Slice 1's data pipeline exists.

### Lanes

| Lane ID | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- |
| `fir7-levers` | `scripts/eval_harness/config_levers.py` | none | `pytest scene/tests -k eval_harness` |
| `fir7-data` | `scripts/train/occlusion/data_pipeline.py`, provenance manifest | none | provenance-schema test |
| `fir7-yunet` | `scripts/train/occlusion/train_yunet_occ.py` | fir7-data | Golden-150 detector re-gate |
| `fir7-sface` | `scripts/train/occlusion/train_sface_adapter.py` | fir7-data | Golden-150 recognizer re-gate |
| `fir7-integrate` | `recognition/.../face_pipeline_adapter.py`, `manifest.py` | fir7-yunet, fir7-sface | boot smoke + rollback + `make check-remote` |

### Merge Order

`fir7-levers` (may descope downstream) → `fir7-data` → `fir7-yunet` ∥ `fir7-sface` → `fir7-integrate`.

### Manifest

```bash
make lane-manifest-init TASK=FIR-7 LANE_IDS='fir7-levers fir7-data fir7-yunet fir7-sface fir7-integrate' TASK_PLAN=docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md
```

### Orchestration Mode

- **Remote grok lanes (preferred)**: training scripts + data pipeline are well-bounded grunt work; dispatch to grok lanes per the offload recipe, gated by adversarial review (≥1 local + remote grok reviewers).
- **Shell fallback**: repo lane helpers / manual worktrees preserving ownership + evidence.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, heuristics (v0.12.2 + distilled), harness, and runtime seam before editing.
- [ ] Recorded the `embedding_model`/detector-id boundary ownership and mixed-space compatibility expectation.

### Checklist for Slice 0: Cheap-lever baseline

- [ ] Lever sweeps implemented as reproducible harness options.
- [ ] Golden-150 delta table per lever + stacked combo captured.
- [ ] Explicit "training needed / descope" decision recorded.

### Checklist for Slice 1: Clean training-data pipeline

- [ ] (clean, occluded) pairs generated over train-split identities only.
- [ ] Dataset-provenance manifest with passing license audit (schema test rejects research-only sources).
- [ ] Train/eval identity-leakage check passes.

### Checklist for Slice 2: YuNet detector fine-tune

- [ ] Seeded fine-tune + ONNX export + model card + content hash.
- [ ] Cloud GPU runbook executable as written.
- [ ] Golden-150 re-gate: masked re-detect miss halved, no clean-detection regression.

### Checklist for Slice 3: SFace mask-invariant adapter

- [ ] Frozen base verified (base weights unchanged by test).
- [ ] Consistency-loss adapter trained + exported + model card.
- [ ] Golden-150 re-gate: `a_s` up, clean-face floors unchanged.

### Checklist for Slice 4: Integration + rollback + re-gate

- [ ] Adapted ONNX loads by id; SFace adapter composes; rollback-to-base works.
- [ ] Boot smoke + health readiness green per id; `make check-remote` green.
- [ ] Final head-to-head delta table + handoff decision for FIR-6's gate.

## Review Readiness

- [ ] No boundary-touching change without matching contract/model-id/rollback evidence.
- [ ] Runtime-parity (Golden-150 re-gate + boot smoke) included where unit tests can mask real behavior.
- [ ] Handoff decision records each adapted artifact, its provenance, and its gate delta.

## Stretch Goals

- [ ] Occluded-stranger false-accept slice (FIR5RR-09 / EVAL-18) once stranger-occlusion members are boxed.
- [ ] Body/context embedding for association when the face is undetectable (Apple-style larger recognition area).

## Success Criteria

- [ ] Two owned, Apache-clean adapted artifacts (`yunet-occ`, `sface-occ-adapter`) with model cards, content hashes, and passing license audits.
- [ ] Golden-150 re-gate shows masked re-detect miss at least halved and `a_s` masked > 0.55 (advisory), with ZERO clean-face floor regression (CACE gate).
- [ ] Both integrated behind the model-swap seam with a verified rollback to base weights; distinct `embedding_model` ids stamped and mixed-space compares rejected.
- [ ] Candidate weights + evidence handed to FIR-6 for the switch-over gate; no production flip in this task.
