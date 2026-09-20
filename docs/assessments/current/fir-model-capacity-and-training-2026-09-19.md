# FIR embedding capacity, alternatives and training feasibility

Date: 2026-09-19 · Follow-up to E24/FIRDV · Status: research and proposed experiments, no model run

**512 dimensions does not mean four times the recognition accuracy of 128 dimensions.** The current FIR implementation assembles YuNet, alignment, SFace and ACX identity logic. Its 128D limit belongs to the selected SFace checkpoint and adapter contract, not to the concept of an in-house FIR pipeline. A different properly integrated embedder can emit 512D while remaining independent of InsightFace runtime and buffalo weights.

Companions: [development assessment](fir-development-wave-assessment-2026-09-19.md), [corpus population allocation](fir-corpus-population-allocation-2026-09-19.md), [capacity spike plan](../../tasks/firdv/FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md).

## What embedding dimensionality means

An embedding is a learned numerical description, not a count of correctly recognized features or people. At float32, 128 components occupy 512 raw bytes and 512 components occupy 2,048 raw bytes, excluding database/index overhead. Neither recognition quality nor whole-model runtime scales by that same factor.

A simple counterexample: concatenate a unit 128D vector with itself four times and divide by two. The result is a unit 512D vector with exactly the same pairwise cosine similarities. It has gained no identity information. Padding, duplicating or linearly expanding the existing SFace output cannot recover information that the encoder discarded.

The original FaceNet paper includes a controlled same-backbone 64/128/256/512D experiment. Its Table 5 reports no statistically significant performance difference across those settings; 512D did not dominate 128D. This refutes a universal multiplier, but it does **not** prove SFace equals buffalo_l or that larger embeddings can never help. [FaceNet §5.4/Table 5](https://arxiv.org/pdf/1503.03832).

Compare named checkpoints under the same gallery, reviewed probes, false-identification budget and failure accounting. Training data, backbone, loss, preprocessing/alignment and the surviving facial evidence all vary between SFace and buffalo_l; their dimension ratio cannot isolate any of those effects. Also avoid the opposite overstatement in older QA prose: higher dimensions are not automatically harmful, and 512 is not a mathematical maximum number of identities or a universal best dimension.

## Higher-dimensional candidates and artifact licensing

| Candidate | Dimensions / role | What is actually established | Recommendation |
| --- | --- | --- | --- |
| OpenCV SFace | 128D; current baseline | Existing FIR adapter and current model-space contract | Keep as reproducible baseline, not as a permanent architectural ceiling |
| **fal/AuraFace-v1** | **512D**, ResNet100/ArcFace-style recognizer | Publisher model card and artifact repository declare Apache-2.0. Publisher describes commercial training sources, without publishing a complete dataset inventory | First bounded pretrained challenger, conditional on exact artifact/preprocessing and provenance review; quality still unmeasured on ACX |
| **AdaFace / CVLFace IR18/IR50/IR101 or ViT** | Common 512D output; quality-aware training loss and recipes | MIT code is available. The examined official WebFace12M model card explicitly directs users to the training dataset's license; the code license alone does not establish a cleared checkpoint | Good own-weight training route with approved data; do not label all downloaded weights “MIT-commercial” |
| **FaceNet InceptionResnetV1 via facenet-pytorch** | 512D | MIT implementation; published pretrained options originate from CASIA-WebFace/VGGFace2 | Technical comparator only after exact checkpoint/data-use provenance review; not a preferred occlusion solution merely because it is 512D |

Primary sources: [AuraFace model card](https://huggingface.co/fal/AuraFace-v1), [AuraFace license](https://huggingface.co/fal/AuraFace-v1/blob/main/LICENSE.md), [AdaFace code](https://github.com/mk-minchul/AdaFace), [CVLFace model card](https://huggingface.co/minchul/cvlface_adaface_ir101_webface12m), [facenet-pytorch](https://github.com/timesler/facenet-pytorch). These findings distinguish code, distributed checkpoint and training-source claims; they do not adjudicate undisclosed source rights.

AuraFace artifact inspected: revision `af6d057c9b0ec4071d4c49c80e3539258798b609`, file `glintr100.onnx`, publisher-advertised SHA256 `a7933ea5330113b01c9b60351d8f4c33003f145d8470ac5f0e52ee2effe25c60`, size 260,694,151 bytes. An 8 KiB HTTP range read of that pinned file's tail exposes ONNX input `[None,3,112,112]` and output `[1,512]`. This confirms the artifact's output width without running it. The complete file was **not** downloaded, hashed or inference-tested here; its advertised hash must be verified before use.

The [primary-source register](../../research/fir-capacity-primary-source-register-2026-09-19.json) preserves the revision, byte-range checksum and complete serialized output-shape metadata inspected.

The publisher's example imports InsightFace and downloads a multi-model pack. Do not copy that application path into this FIR installation. A candidate adapter should load only the explicitly approved recognition ONNX through the existing runtime abstraction, retain YuNet or another separately approved detector, and implement/test the required alignment, channel order and normalization. Unrequested landmark/gender-age files are not dependencies. Equal 512D shape does not make AuraFace vectors compatible with buffalo_l.

## Are the existing steps sufficient?

**The plans describe a sound development and measurement process, but it must still be implemented and validated; they cannot guarantee that SFace will meet the final quality requirement.** Most of the planned work repairs deployment, labels, score export, calibration and error attribution. Those changes can remove preventable failures and make improvement measurable, but they do not invent facial information hidden by an occluder.

Keep four explicit exits from the measurement phase:

1. Existing SFace meets the requirement after validated alignment/gallery/assignment improvements: retain it.
2. A permitted pretrained challenger produces a worthwhile paired gain at the same false-name budget and acceptable latency: qualify that checkpoint in a separate embedding space.
3. Oracle evidence indicates a recoverable representation/visibility deficit, and data rights/diversity are sufficient: propose a bounded fine-tune or adapter experiment.
4. Neither approach meets the requirement: abstain on those cases, improve capture/enrollment or collect better data. A more permissive threshold is not evidence of recovered identity.

The earlier FIRDV-2 configuration grid needed an explicit checkpoint challenger and a training-feasibility exit; [FIRDV-3](../../tasks/firdv/FIRDV-3-embedder-capacity-and-training-feasibility-task-plan.md) now supplies them. Production acceptance remains gated. PostgreSQL 19 is unnecessary for either 128D or a separately stored 512D candidate.

## Training with existing or larger hardware

Recorded hardware: [benchmarks/HARDWARE.md](../../../benchmarks/HARDWARE.md) lists an M1 MacBook Air with 8 GB as orchestration-only, remote ARM/x86 CPU hosts, and an OCI `VM.GPU.A10.1` with one A10/24 GB VRAM and 240 GB system RAM. These are recorded capabilities, not a current capacity reservation. The remote worker audits configuration separately; this task does not start a GPU or check live quota.

[Oracle's current shape table](https://docs.oracle.com/en-us/iaas/Content/Compute/References/computeshapes.htm) confirms A10.1 as 15 OCPU, 24 GB GPU memory and 240 GB host memory. The cost runbook's “30 OCPU” entry conflicts with this; do not propagate that unit error into training sizing. Current source inspection also finds provenance policy/tests under `scripts/train/occlusion/`, but no `train_yunet_occ.py` or `train_sface_adapter.py` there. A planned A10 target is not an implemented training harness.

| Experiment | Existing A10/24 GB | Larger GPU allocation | Main prerequisite |
| --- | --- | --- | --- |
| Recalibrate thresholds, compare galleries/clustering | GPU unnecessary for much of the analysis; reuse frozen embeddings | Little benefit | Correct labels, complete scores and independent validation |
| Train a small projection/adapter on frozen features | Plausible bounded experiment; CPU may suffice for small heads | Usually unnecessary initially | Representation must contain useful surviving identity signal; prevent memorizing the tiny roster |
| Fine-tune a compact trainable face backbone | Plausible with measured batch size, mixed precision and suitable optimizer | 48/80 GB class hardware can allow larger batches/backbones | Trainable implementation/checkpoint, verified conversion, diverse approved data, regression control |
| Train a 512D recognizer from random initialization | Technically possible for an appropriately sized model; time/data/classifier memory may make a useful campaign impractical | Multi-GPU training can improve throughput and class/batch capacity | A substantially larger identity-labeled training corpus and measured scaling/cost |
| Train an occlusion-aware detector | Small experiments may fit; separate target from recognizer | Scale only after a detector deficit and data supply are established | Exhaustive/ignore-region annotation policy and an independent detector evaluation |

These are engineering feasibility judgments, **not measured fit or runtime estimates**. Do not co-reside a training job with the current large VLM and assume the A10's 24 GB is free. Fine-tuning SFace is also not an ONNX configuration switch: identify a trainable equivalent and establish preprocessing/weight-conversion parity, or select another approved trainable base. Changing learned weights creates a new model space even if dimensionality stays 128.

The data limitation is more serious than the GPU limitation. This manifest contains 130 recorded identities total; only 87 appear in the personal partition, and 15 of those appear in only one image before session verification. The 600+ images are useful for evaluation, enrollment and a small overfitting-risk pilot, not a credible foundation corpus for broad new-person recognition. Generating thousands of masks on those same people adds occlusion variation, not thousands of independent identities. The AdaFace paper's reference training runs use millions of facial images; that is context about the experiment scale, not permission to reuse those datasets. [AdaFace §4.1](https://arxiv.org/pdf/2204.00964).

A label classifier that recognizes the current 87 people is also a different product from an embedding that generalizes to future enrollments. Report unseen-identity performance separately. Detector labels from Open Images are not identity labels; its annotation source can help detection without solving recognizer training. Handoff **3333** corrects older “no usable detector corpus exists” claims, while warning that unannotated training regions cannot simply be treated as background.

Before purchasing larger capacity, prepare a bounded throughput/memory probe: chosen trainable backbone, data size/identity count, sampler, image size, optimizer, AMP policy, classifier strategy, checkpoint/restart behavior and held-out protocol. On an authorized later run measure steady-state examples/s, peak VRAM, input stalls and validation overhead. Estimate campaign time as `epochs × training examples / measured examples per second`, then add startup, evaluation, checkpointing and retries. Price the actual available resource at execution time; old hourly rates and synthetic-generation estimates are not a training budget.

## Research lineage and next decision

Semantic handoff retrieval confirmed prior decisions **2943/2949** (AuraFace and dimension evidence), **3132/3133** (own-weight AdaFace/CVLFace route and generator provenance limits), **3333** (Open Images correction), and **3347** (training tied to evidence gates). The requested v11 QA report retains the governing distinction between measurement and a separately justified training campaign. No old claim of 512D superiority, fixed GPU cost or synthetic-data cleanliness is reinstated here.

Recommended order: complete isolated 128D installation → valid corpus and detector-only localization comparison → remedy the measured upstream deficit → controlled SFace/AuraFace checkpoint comparison → bounded training feasibility only if a specific recoverable deficit remains. Do not fund a broad retrain solely to increase dimension.

Requested remote audit: `codex-remote / gpt-5.6-luna / max`, FIRCAP-90, produced a research commit and passed its six selected provenance witness tests. Its automatic review did not converge: two medium findings and one low finding concerned overstated enforcement/readiness and conflated provenance fields. The branch was not merged. This assessment retains independently verified hardware/readiness facts, corrects the OCPU unit error, and does not treat a policy unit test as proof of end-to-end training enforcement. Detailed receipt: primary-source register.
