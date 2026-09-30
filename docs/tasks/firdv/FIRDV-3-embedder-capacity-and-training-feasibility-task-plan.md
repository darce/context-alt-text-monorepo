# Task Plan

> **Metadata**
>
> - **Date**: 2026-09-19
> - **Author**: Codex
> - **Status**: draft 512D development delivery and feasibility extension; no model or live result
> - **Owning Epic**: [E24/FIRDV](../../epics/v0.5.0/fir-development-and-measurement-epic.md)
> - **Epic Short ID**: FIRDV
> - **Task ID**: `FIRDV-3`
> - **Target Branch**: `feature/firdv-3`
> - **Review Coverage Target**: 2

## Objective and boundary

Deliver a permitted 512D recognizer through the in-house FIR runtime and new LocalWP development route, measure whether it improves the required FIR behavior, and assess a small own-weight experiment only if a recoverable deficit remains. This answers the user's capacity/training follow-up; it does not assert that more dimensions improve accuracy or authorize a broad training campaign. Grounding: [capacity assessment](../../assessments/current/fir-model-capacity-and-training-2026-09-19.md), [corpus allocation](../../assessments/current/fir-corpus-population-allocation-2026-09-19.md).

The 2026-09-21 operator choice makes AuraFace512 the development delivery path. A separately reproducible 128D SFace installation remains the comparison baseline, not a mandatory predecessor to provisioning the candidate. FIRDV-2 owns common corpus/run/scoring/visualization contracts. This task adds the named checkpoint adapter/comparison, actual 512D LocalWP route and an explicit train-or-stop decision; no second harness. The [consolidated implementation guide](../../roadmaps/fir-localwp-512d-implementation-roadmap-2026-09-19.md) makes 512D development delivery mandatory while keeping quality adoption evidence-gated. Existing FIR-7/15/17 ownership and training evidence gates remain in force.

## S1 — artifact and adapter feasibility, no model execution

Verify a pinned AuraFace `glintr100.onnx` artifact, publisher license and required preprocessing. Scope the recognizer alone, not automatic loading of its multi-model pack. Record downloaded full-file checksum, ONNX input/output graph metadata, channel order, normalization, alignment template, expected output normalization and runtime/provider compatibility. The research register's 8 KiB metadata read is not full-file verification.

Identify the smallest extension of the existing FIR runtime/model manifest that selects this recognizer while preserving current YuNet/alignment behavior where compatible. There must be no InsightFace runtime/weight download or fallback. Do not merely change `PGVECTOR_DIM` to 512 while continuing to load SFace. Keep a separately named model/preprocessing space and isolated 512D candidate store; re-extract enrollment/probe vectors.

Separate RED dispatch first: approved artifact manifest accepted; wrong dimension, preprocessing/model hash, missing license record, mixed store and automatic foreign-pack loading rejected; SFace128 behavior unchanged. Then implement only the reviewed adapter/manifest slice. Use `codex-remote`, `gpt-5.6-luna`, `max`; apply existing branch/offload review discipline.

## S2 — controlled checkpoint comparison

First consume FIRDV-2 S3a detector/localization findings. Artifact preparation in S1 may proceed concurrently, but an encoder change cannot repair faces that were never detected. Prioritize a detector remedy when that stage is limiting; do not infer a clustering or dimension bottleneck from surviving embeddings alone. Use FIRDV-2 expected-unit ledger and reviewed annotations. Run both:

- Recognizer comparison using the same verified face regions and explicitly recorded candidate-compatible preprocessing, to reduce detector confounding.
- End-to-end comparison preserving each model's actual preprocessing and counting detection/alignment failures.

Calibrate each checkpoint on the calibration groups; freeze thresholds before scoring. Report FNIR/TPIR at the common declared false-identification budget, FPI and fixed nonmated denominator, wrong-name/merge errors, clean/mask/sunglasses/mixed cells and latency/memory. More components, prettier UMAP clusters or LFW scores do not select a winner. Use FIRDV-2 paired cluster views. Legacy data gives a diagnostic comparison; independently collected test groups are required for a confirmatory claim.

## S3 — training data and implementation feasibility

Inventory only approved training sources and exact use rights. Distinguish face-detection boxes from stable identity labels. Keep the 646-image legacy inventory out of any automatic training assignment; preserve explicit training/calibration/test identity/session separation. Consent metadata for evaluation is not proof of training scope. Synthetic descendants remain with their source group, and generator/teacher provenance is recorded.

Choose a specific trainable implementation: compact backbone with approved initialization, or random initialization plus an approved AdaFace/CVLFace code recipe. SFace ONNX inference weights do not establish a usable trainer. If converting weights, require layer/output parity on fixtures. Specify augmentation that preserves recognizable identity, balanced identity sampling, clean-data replay/regression control, optimizer/classifier memory and checkpoint recovery. Do not imitate buffalo outputs in the training loop under the existing provenance policy.

Deliver a go/no-go packet with actual usable training identity/capture counts, missing strata, label cost and failure criterion. A frozen-feature classifier for today's roster is labeled closed-set adaptation, not a generally useful recognizer.

## S4 — bounded hardware probe plan, execution separately gated

Prepare a 100–1,000-step memory/throughput probe with an explicit maximum GPU lease and price source, starting on recorded A10/24 GB capacity if available. No concurrent VLM serving. CPU-only preparation checks config, manifest and restart contracts. Execute only after evidence/data/budget prerequisites are satisfied; numerical step range is a proposed probe bound, not a quality target or spending approval.

Measure examples/s after warmup, peak allocated/reserved VRAM, host memory, I/O stalls, loss/finite gradients and checkpoint restart. Scale epochs/data to a time estimate with validation/retry overhead. Compare a larger-memory or multi-GPU quote only if measured memory/throughput is the limiting factor. Larger hardware cannot resolve insufficient independent identities or uncertain labels.

## S5 — decision and handoff

Choose the quality recommendation: retain SFace for the better-quality use case; qualify the pretrained challenger; draft a bounded fine-tune/adapter task; or park training and collect better data. A retain-SFace recommendation does not cancel the requested functional 512D development route in S6; it marks that route experimental/unqualified for production until evidence changes. Training produces a new model space and requires re-enrollment/recalibration and clean-cell regression tests. No production switch, training success or occlusion gain can be inferred from the feasibility packet.

## Current implementation decomposition (2026-09-21)

Use the reviewed [next-wave DAG](../../scopes/next-wave-gpu-ui-fir512-dag.md): F1a pins and F1b evidence run independently; their frozen identity/preprocessing packet unblocks F1c embedder, F1d validator and F1r production routing/active-ID in parallel; F1e real-artifact inference joins them before provisioning. FT detector env resolvers precede quality tuning/A-B. Gating `/ready` alone does not demonstrate inference. All remote implementation and grunt lanes are explicitly `codex-remote / gpt-5.6-luna / max`, with no fallback. Unknown mean/scale/alignment remains a blocker to dependent implementation, not permission to guess.

## S6 — isolated 512D service and LocalWP delivery

This slice completes the user's requested 512D development instance. It depends on S1 artifact/adapter correctness and the FIRDV-1 isolation/evidence foundation. Record available S2 quality findings and missing evidence; a superiority claim is not a prerequisite for a clearly experimental development route. S3–S4 training feasibility/probe work does not block S6, and no training run is required.

First dispatch RED tests for the expected approved model-space contract and routing. Reuse FIRDV-1's validator with an explicit expected model/preprocessing/weight identity: the original SFace128 expectation must still reject 512D, while a separately approved candidate512 expectation validates only that exact artifact. Tests must reject a 512D SFace configuration, same-dimension buffalo/foreign weights, wrong centroids, API/worker disagreement and fallback to the baseline endpoint. Merely accepting any vector of length 512 is invalid.

Then implement the smallest runtime/manifest and collector extension, reusing the existing factories and deployment scripts referenced by FIRDV-1; name exact change symbols after codemap discovery in the dispatch brief. No second evidence schema or deployment framework. Provision a separately named DB/role/volume/blob namespace and pinned service image for the 512D candidate. Check collisions and preserve existing contents. Apply the correct vector dimension and inspect actual schema across embeddings/centroids/derived stores; record observed provenance and runtime output width. Re-extract the authorized smoke gallery from pixels and create fresh clusters. Never alter the 128D baseline DB in place or import incompatible vectors.

Configure the new LocalWP site's explicit development endpoint/tenant to the 512D service. Verify bytes upload, scan, human roster confirmation, actual self-hosted remote description and saved WP output with correlated run IDs. Exercise unknown, multi-person attachment, missing landmarks, unavailable service, retry and restart. Record model/DB/image identities and prove no InsightFace runtime route. Keep the baseline endpoint for deliberate comparisons, never automatic fallback.

Deliver a redacted readiness report and reversible site-setting/service rollback procedure. Scope SC-11 requires the actual 512D route, not a mocked dimension or an unconnected experiment. <u>Human operator: confirm smoke identities and inspect saved descriptions; supply missing access through the normal secret mechanism.</u> Apply existing compute authorization; present a bounded cost/lease packet before any new unapproved paid allocation. No production endpoint change.

## Consolidated checklist

- [ ] S1 exact artifact/preprocessing/provenance contract verified and separate RED/implementation reviewed
- [ ] S2 checkpoint comparison uses complete outcomes, frozen calibration and separate stores
- [ ] S3 trainable implementation and sufficient approved data identified, or explicit no-go recorded
- [ ] S4 priced bounded probe prepared; any later execution records memory/throughput/restart and teardown
- [ ] S5 evidence-based retain/challenger/train/collect decision recorded; no dimension-only winner
- [ ] S6 approved 512D API/worker/model/DB and LocalWP path demonstrated; baseline isolated, no cross-model fallback, rollback and limitations recorded (SC-11)
