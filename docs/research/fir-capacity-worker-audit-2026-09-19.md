# FIR capacity and worker audit (2026-09-19)

## Scope and conclusion

This is a repository-record audit only. No OCI tenancy, GPU, private corpus, or
media was contacted. “Recorded” below means a dated repo snapshot; it is not a
live capacity assertion. The short answer is: a 512-D head is not a four-times
accuracy promise; FIR-7’s own-weight path is designed around a 24-GB A10, but
is not currently executable in this checkout; and the existing FIR plans can
guarantee measurement and fail-closed release conditions, not improvement.

## Recorded hardware and feasibility boundary

| Recorded resource | Evidence in repo | What it supports |
| --- | --- | --- |
| Operator laptop | `docs/runbooks/oci-vlm-batch-compute-learnings.md`, §TL;DR and §Compute placement: 8 GB RAM, near-zero free RAM, no torch/model inference | Control plane only. It is not a training or inference host. |
| Always-on ARM box, `acx-backend` | `docs/runbooks/oci-instance-state-and-cost.md`, §Expected steady state and §Tenancy inventory snapshot: `VM.Standard.A1.Flex`, 4 OCPU/24 GB, ARM, no GPU | CPU orchestration, offline eval/data preparation, and the roadmap’s CPU-only gates. It is not evidence that full FIR training is CPU-feasible. |
| Burst GPU, `acx-gpu-burst` | Same runbook, §Expected steady state: `VM.GPU.A10.1`, 1× A10/24 GB VRAM, 30 OCPU/240 GB host; §Tenancy inventory snapshot records STOPPED and START blocked by “Out of host capacity” since 2026-07-16 | This is FIR-7’s specified primary training target. The recorded shape fits the planned fp16, batch-managed adapter/custom-generation envelope, but availability was not verified for this audit. |
| Dedicated x86 CPU VM | `docs/runbooks/oci-vlm-batch-compute-learnings.md`, §Working solution: E4.Flex, 16 OCPU/32 GB, Florence CPU batch | A proven VLM comparison shape, not a FIR trainer result. Do not transfer its VLM timings to face training. |
| Larger rental GPU | OCI runbook §1 records bare-metal A100/H100 as reliable across stop but scarce at provision and 8-GPU minimum; FIR-7 §Slice 2 names a specialist single A100 only if wall-clock requires it | A possible operator-selected wall-clock escape hatch. No repo result establishes that a larger rental is necessary, affordable, or quality-improving for FIR. |

The records conflict over quota state: the 2026-07-16 opportunistic plan
claims AD-2/AD-3 headroom, while the 2026-09-11 GPU/FIR assessment records
`gpu-a10-count = 1` in AD-1 and A100/L40S/BM-GPU limits at zero. The later note
also leaves the production image wiring, Terraform state, and live burn-in
open (§2.3). Treat both as historical evidence and re-check before spend;
neither is a live verification in this lane.

## Training readiness and the 512-D question

FIR-7 is an adaptation ladder: config/inference levers first, then a clean,
parameter-efficient YuNet detector adapter and a frozen-base SFace adapter.
`FIR-7-occlusion-adapters-task-plan.md`, §Target Outcome and §Slice 2, pins
PEFT/partial-freeze, clean validation, multiple seeds, ONNX/model-card output,
and an A10-first cloud runbook. §Slice 3 keeps the embedding space at 128-D
with a zero-initialized `128→r→128` residual adapter. The plan’s recorded A10
budget is 2–12 GPU-hours; that is a plan envelope, not a completed run.

The implementation boundary is material: `scripts/train/occlusion/` contains
`license_policy.py`, its tests, and mutation-guard utilities, but no
`train_yunet_occ.py`, `train_sface_adapter.py`, `data_pipeline.py`, pack
builder, or SAM factory. FIR-7 §Current State Analysis explicitly says no
training/adaptation harness or cloud training runbook exists. The 2026-09-11
roadmap §Current State reports FIR-7 at 0/43 checklist items, with training
slices frozen behind `TRAINING_DECISION`. Therefore “A10-feasible” currently
means architecturally sized and planned, not runnable or live-proven. The A1
box can host CPU eval/preparation; FIR-7’s UMAP note names a classical-UMAP
fallback if TensorFlow on aarch64 is infeasible. Its plan rejects CPU-bound
diffusion generation, so CPU availability does not substitute for GPU
training capacity.

512-D is four times the coordinate count, not four times accuracy. The FIR-7
§Escalation & Non-Goals section assigns 512-D to a future SCRFD + AdaFace-style
retrain campaign, keeps FIR-7 at 128-D, and rejects 768/1024-D on retrieval
concentration/index-decay grounds. The roadmap’s design decisions separately
require own-threshold calibration for 128-D SFace and 512-D buffalo spaces;
they are not comparable at one threshold. No recorded benchmark here measures
a 4× accuracy gain, and the 512-D campaign is explicitly not authorised.

## Existing license/provenance controls

`scripts/train/occlusion/license_policy.py` is a policy layer, not a trainer.
It registers named commercial-ingest entries for YuNet/SFace and the proposed
BlazeFace, RT-DETR, D-FINE, and PP-PicoDet alternatives; denies Ultralytics;
keeps DCFace operator-cleared only with its clearance decision; leaves Vec2Face
pending; and requires registered source/license/photo-clearance fields for
training rows and occluder assets. `audit_provenance_row`,
`audit_derived_from_model`, `audit_source`, `audit_model_ingest`,
`audit_occluder_asset`, and `audit_synthetic_source` fail closed on NC model
lineage, research-only sources, unknown/unregistered identities, uncleared
assets, and missing clearance. This blocks buffalo outputs from becoming
training data, but cannot prove model quality or training completion.

The configured witness smoke in `test_license_policy.py`,
`TestGate31OperatorOwnedSourcePassWitnesses`, covers exact PASS tokens
`operator-phone` and `operator-render` plus rejecting variants. It passed
6/6 in this lane. Planned pack-disjointness, leakage, independent-renderer,
model-card, and rollback proofs remain FIR-7 work; they are not present merely
because the policy module exists.

## Can FIR guarantee improvement?

No. FIR-7 §Re-gate against QA v8 and §What may not be claimed withdraw every
pre-CVUP-1 comparison arm, M-12 masked recovery, and detection recall 0.504;
the “embedder leads detector” ordering is only a hypothesis. The 2026-09-11
GPU/FIR assessment §3.3 repeats that no admissible head-to-head has run and
that the isolated `acx-dev-fir` stack was never stood up. Synthetic `a_s` is
diagnostic, not a robustness certificate; independent-signal/real-occlusion
evidence, clean-floor non-inferiority, FP/IoU bounds, and train/eval provenance
are required. A failed gate ends FIR-7 at “no-pass within budget” and files an
escalation; it does not authorize deeper adapters or the 512-D campaign.

This audit applies the [heuristics canon](https://github.com/darce/heuristics-canon):
separate measured results from plans (EVAL-10/EVAL-15), require deployment
holdout evidence (MLDATA-20), preserve lineage/model-card provenance
(PROV-01/PROV-02), and calibrate each embedding space independently (CAL-07).
