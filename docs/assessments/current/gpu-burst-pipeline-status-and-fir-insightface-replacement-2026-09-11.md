# GPU burst description pipeline + InsightFace → in-house FIR replacement — status and recommended approach

> **Metadata**
>
> - **Date**: 2026-09-11
> - **Task ID**: `FIRPLAN-1` (branch `feature/firplan-1`)
> - **Base SHA**: `95e0ceb38a017b57ca8d40e5ec672b47f75b78a8` (main)
> - **Epic**: E22 Commercial Face Identity Replacement (`docs/epics/v0.5.0/commercial-face-identity-replacement-epic.md`)
> - **Grounding register**: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` ("QA v11", code snapshot `ee330e96141227bfc8bc4e92de34827514c11211`)
> - **Scope**: (1) end-to-end describe-from-WP-admin on the bursty A10 tier, (2) FIR replacement status, (3) recommended occlusion-robust approach

---

## 1. Bottom line

The **description** half of the pipeline is built end-to-end and is the healthier half: WP admin → PHP REST → FastAPI → `GpuRemoteDescriptionAdapter` → llama.cpp on a scale-to-zero A10, with start/reap lifecycle, warm-up gating and fail-closed error handling all implemented. Its open items are operational (quota, tfvars, live burn-in), not architectural.

The **identity** half is the blocker. InsightFace `buffalo_l` is still the production default. The in-house replacement (`face_pipeline`: YuNet 2026may → 5-point align → SFace 2021dec, 128D) is fully built, tested and *dark*. It cannot be switched on today — not because the code is missing, but because **there is no admissible measurement that would justify the switch**, and the historical numbers that looked like one have been withdrawn.

"Robust occlusion facial detection and recognition" is currently **not measurable, not merely unbuilt**. That ordering drives the whole recommendation: fix the measurement before spending on models.

---

## 2. Bursty GPU description pipeline — current status

### 2.1 The path, with anchors

| Stage | Anchor |
| --- | --- |
| Admin UI describe/regenerate control | `apps/prototype-wp-alt-context/js/admin/pages/workbench/MediaAltSuggest.tsx:850` (error path `:571`) |
| JS client | `js/admin/api/describeApi.ts:4` — `POST acx/v1/recognition/describe { media_id }` |
| PHP REST routes | `src/api/class-describe-controller.php:154-182` (single), `:262-286` (bulk `/describe/runs`) |
| PHP → backend proxy | `class-describe-controller.php:337-339` (`DescribeMediaService`), `:377-458` (bulk multipart, one `image_<media_id>` part per attachment) |
| Sync FastAPI route | `scene/interface_adapters/http/routers/describe.py:333-442`; tier selection `:371-376` (`envelope.tier == "gpu"` → `get_gpu_description_adapter()`) |
| Async route + worker | `describe.py:487-566` → `_run_async_describe_job_and_release` `:569-585` → `scene/application/describe_async_worker.py:126-363` (CPU-provisional pass, then GPU-final) |
| GPU adapter resolution + allowlist | `scene/interface_adapters/http/deps.py:84-111`; `_is_private_gpu_endpoint` `:58-81`, allowlist `localhost` / `acx-gpu-burst` / `*.oraclevcn.com` at `:18-22`; otherwise `UnavailableDescriptionAdapter` (fail-closed) |
| Warm-up gate | `scene/application/describe_run_worker.py:151-195` `_wait_for_gpu_ready` polls `{endpoint}/health` until `gpu_warmup_timeout_seconds`; policy built only for GPU adapters `:133-148` |
| GPU call | `gpu_remote_adapter.py:240-245` → `{endpoint}/v1/chat/completions`; connect 5 s / read 175 s (`:17-18`), process-wide semaphore default 4 (`:19`, `:248-261`) |
| Burst lifecycle | `infra/oci/gpu_lifecycle/controller.py` — `start_needed_instances:71-97`, `reap_idle_instances:111-135`, `lease_expired_instances:137-169`, `fence_stop_actions:171-188`; timers installed by `scripts/deploy/gpu-lifecycle-install.sh` (`acx-gpu-start`, `acx-gpu-reap`) |
| Self-stop safety net | `infra/oci/watchdog.tf:4-27` — dynamic group + `INSTANCE_POWER_ACTIONS` scoped to the instance's own OCID |
| Model pin | `scene/config/profiles.py:104-115` — `GPU_QWEN30B`, `available=True`, `unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF@0af19e7479857aa7f3246466a4ad16c7e7299639`, `Q4_K_M` |

### 2.2 What is genuinely solid

- **Fail-closed everywhere it matters.** Any transport/HTTP failure in the adapter is wrapped as `GpuRemoteAdapterError` (`gpu_remote_adapter.py:225-226`); there is no silent CPU substitution inside the adapter. Response parsing rejects empty captions, missing `choices[0].message`, and reasoning-only output (model stuck "thinking") at `:322-344`. A stopped A10 surfaces as 503/502/504 at the route (`describe.py:404-416`), not as a plausible-looking wrong caption.
- **Cost control is real, and double-fenced.** `reap_idle_instances` stops idle RUNNING instances; `lease_expired_instances` is an unconditional backstop that stops regardless of load, deliberately bypassing the load fence so a dead load-writer cannot strand a ~$2/hr A10 (`controller.py:143-154`). `fence_stop_actions` re-samples load immediately before actuating STOP, and an untrustworthy/stale load dump is fail-closed to *busy* (`reaper.py:94`, `_BUSY_LOAD`) — a broken snapshot writer prevents an accidental stop, it does not cause one. Hung START is bounded at ~5 min (`_DEFAULT_READY_MAX_CYCLES=30` × `_DEFAULT_READY_SLEEP_SECONDS=10.0`, `reaper.py:101-103`). Inline cost model: 100-image library ≈ 5 min boot+load + ~4 s/img ≈ 12 min ≈ $0.40 (`reaper.py:99`).
- **Identity names reach the VLM as context, not as a VLM capability.** The GPU model never performs face recognition. Confirmed faces and naming policy are loaded before the description call (`describe.py:364-370`), fusion resolves them (`scene/application/fusion/reconcile.py:290-347`, veto at `:274-287`), and the names are injected into the `<<<CONTEXT>>>` block of the prompt (`gpu_remote_adapter.py:73-101`, system instruction `:28-37`). HARM-02 guards the positional fallback from naming an identity Stage 2 already dropped (`describe.py:417-419`).

> **Consequence that drives §3:** identity quality in the final alt text is *entirely* upstream of the GPU. Improving the VLM cannot fix a misidentified face, and a wrong name injected into `<<<CONTEXT>>>` will be woven confidently into the caption. The face stack is the correctness surface.

### 2.3 What is red or unproven

| Item | State |
| --- | --- |
| A10 capacity | `gpu-a10-count = 1` in US-ASHBURN-AD-1 only; A100/L40S/BM-GPU all 0. Quota increases are console/support-only — the Limits API is read-only (`infra/oci/GPU-BURST-PROVISIONING.md`). |
| Terraform state | No backend block, no state, while `acx-vcn` / `acx-public-subnet` / `acx-backend` are live. A naive `terraform apply` would attempt to recreate them (`INFRA-TOPOLOGY.md` §Terraform). |
| `acx_private_subnet` (GPU target) | Defined in `main.tf`, **does not exist** in OCI. |
| `gpu_image_ocid` in production tfvars | Golden image exists and was used by the 2026-07-14 spike host; production tfvars wiring is still open. |
| Ephemeral bake host | Operator must confirm `acx-gpu-bake` was terminated (~$2/hr if not). |
| Latency floors | `_wait_for_gpu_ready` and the busy-biased load fence are both fail-closed. Correct, but a broken health probe or load writer costs the *full* warmup/lease timeout before a clean error surfaces. Worth a burn-in measurement against the 90 s warm-start target. |
| Release gate | `make test-infra-terraform` is mandatory before any A10 release (`GPU-BURST-PROVISIONING.md`). |
| Admin credential blast radius | `OCI_ADMIN_*` is a tenancy-admin key readable by `acx-backend-dg` — accepted greenfield trade-off [SEC-04], with an untested instance-principal round-trip. |

Not stubbed: the core GPU describe path. `florence_large` and `gpu_phi4` are explicit fail-closed stubs (`profiles.py:78-103`, `deps.py:164-165`) but are not the burst tier.

---

## 3. Face identity pipeline — InsightFace status and what blocks the flip

### 3.1 Ledger

| ID | Deliverable | State on `main` |
| --- | --- | --- |
| FIR-2 | Model-neutral seam (`FaceDetection`/`DetectedFace`, embedding-model provenance) | Merged |
| FIR-3 | YuNet detector + SFace embedder adapters, OpenCV golden-parity tests | Merged — `recognition/infrastructure/face_pipeline/{aligner,ort_adapters,opencv_ref,provenance}.py`, models `face_detection_yunet_2026may.onnx`, `face_recognition_sface_2021dec.onnx` |
| FIR-4 | Dark runtime integration (ORT bump, boot-time hash verification, ScanService observability) | Merged (S1); S2–S5 review docs present |
| FIR-5 | Bake-off harness extension (occlusion slices) | Docs only; no standalone code landing confirmed |
| FIR-6 | Calibration + quality rework + **gated switch-over** | S1 (quality factors, OACT scaffold) and S3a (calibration CLI) merged. **S2, S3b, S4, S5, S6 blocked** — S6 is "operator-gated; blocked until the MCP gate decision row exists" |
| FIR-7 | GPU/CUDA production path + occlusion adapters + licence policy | Merged (v6.2 plan carries the QA v8 re-gate block) |
| FIR-8 | Cross-stack bench orchestration | Bench tooling merged; **live E2E blocked** pending FIR23-STACK |
| FIR-9 | Workbench curation atlas | Merged |
| FIR-10 | — | Does not exist; number skipped |
| FIR-11 | Gate-corpus remediation + FIR re-baseline | Plan only (rev 7) |
| FIR-12 | Open-set identification eval harness | **Not on `main`.** Lives on `r7int/fir12-r7-int`; `scripts/eval_harness/` is absent from this checkout. The report is real; the code is unmerged. |
| FIR23-STACK | Isolated `acx-dev-fir` benchmarking backend | Same-space guards merged (`f1bb3918b`, `49c3ddf46`); **the stack itself was never stood up** |
| CVUP-1 | OpenCV 4.13 → 5.0 | Merged — `opencv-python==5.0.0.93` (`pyproject.toml:43`), headless pin `:110`, ADR `docs/adrs/ADR-ARCH-07-opencv-pin-for-face-pipeline-reference.md` |

### 3.2 Built but dark

`recognition/config/settings.py` resolves `RECOGNITION_FACE_PIPELINE_PROFILE` with **default `"insightface"`** and fails closed on unknown values (rg-008). `face_pipeline` is a fully selectable `Literal["insightface","face_pipeline"]` with unit/golden coverage across eight test modules (readiness, OpenCV reference parity, knobs, golden provenance, adapter, ORT parity, pure contracts, provenance). ONNX weights are fetched and sha256-verified by `scripts/fetch_face_pipeline_models.py`, not baked into the image.

The production Dockerfile still installs `.[bench]`, which carries `insightface>=0.7.3,<1.0.0` — deliberately, so the incumbent path stays available until FIR-6 (`pyproject.toml` bench extra comment).

### 3.3 Why it cannot simply be flipped

Five distinct gates, only one of which is code:

1. **Two flags, not one.** `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline` **and** `PGVECTOR_DIM=128` must move together (`.env.fir.example:87,89`). `PGVECTOR_DIM` is the sole dimension root — `RECOGNITION_EMBEDDING_DIMENSION` is deliberately ignored so it cannot create a second root (`recognition/config/settings.py`). Default is still `512` (`db/settings.py:216`).
2. **One embedding space per comparison [EMB-01].** A 512D buffalo vector and a 128D SFace vector are not comparable; a mixed-space query is meaningless [IDX-02]. This is enforced three ways — the three-way guard `assert_three_way_embedding_dimensions` (`face_pipeline_adapter.py:318-329`), the two-way pgvector guard (`settings.py:321-333`), and provenance tagging `opencv-sface@128d/l2/cosine` (`provenance.py:86-99`). **Two models therefore require two databases and two stacks**, which is exactly what FIR23-STACK / `acx-dev-fir` exists to provide — and it was never deployed.
3. **No admissible comparison exists.** FIR-12's instrument is unmerged and no bake-off has ever been run ("this is the instrument, not a result"). FIR-8's live leg is blocked on the same missing stack.
4. **The historical numbers are withdrawn.** Per the QA v8 re-gate in the FIR-7 plan: every pre-CVUP-1 artifact is invalidated as a comparison arm; M-12 (0.865 buffalo vs 0.321 v2 masked recovery) is **inadmissible externally**; detection recall 0.504 is **withdrawn as an estimand** because the Golden-150 ground truth is merge-only adjudication of buffalo's *own* proposals (98.4% buffalo output — positive-only verification). §0g's "the embedder leads" claim is withdrawn to a hypothesis, because M-11's margin was computed over crops aligned by detector-emitted landmarks, and landmark regression degrades under occlusion *before* the embedder does.
5. **An operator-recorded MCP gate decision is required** (E22 constraint: dark-until-gated). No such row exists.

### 3.4 Occlusion machinery that exists today

- `recognition/application/assignment/quality.py` + `recognition/infrastructure/embeddings/face_quality_factors.py` — quality factors including `compute_occlusion_severity`. It is **two fixed eye patches**: no occluder type, no spatial mask, no per-landmark visibility.
- The OACT coefficient defaults to **0.0 — "dark no-op until S4"** (`settings.py:380-381`), and the enrollment occlusion ceiling defaults to 1.0, "accepts full range until S4" (`:399-402`). Sign is constrained non-negative because a negative coefficient would *reward* occlusion (FIR6S1-M-02).
- `scripts/eval_harness/synthetic_occlusion.py` and `scripts/mine_fir_occlusion_candidates.py` are curation/eval tooling, manual, never in the request path.

**Read plainly:** there is no occlusion-aware detection, no visibility-aware matching, and the one occlusion signal that exists is disabled and — when enabled — *relaxes* the threshold rather than protecting against a bad match.

---

## 4. Recommended approach

Sequenced off the QA v11 D-01…D-10 / R0–R6 register. **The ordering is the recommendation.** Every step below is cheap and measurement-shaped until Phase C; nothing buys GPU time before D-01 resolves.

### Phase A — make the question answerable ($0 GPU, ~1–2 weeks)

**A1. Write the "what counts as a face" rubric (D-09, T-09, ~1 eng-h).** Hand-only, back-of-head, heavy occlusion and depictions have no written rule today. Adjudication cannot start without one; two annotators will silently apply two rubrics and the disagreement will be invisible. Retain pre-adjudication labels. *This is the single cheapest unblocking action in the program and it gates everything downstream.*

**A2. Declare D3 — the embedder leg's acceptance criterion (D-08, decision only).** D1/D2 govern detection only. The Golden-150 head-to-head that currently stands in for an embedder criterion is **rank-based**, which is inadmissible for an open-gallery system that must reject non-enrolled subjects. Declare it as **FNIR at a fixed FPIR with non-mated probes, at a score threshold** — the shape FIR-12's `open_set_identification.py` already implements. Report **FPI as an integer count, never a rate** (a rate improves when the detector emits *more* false detections, i.e. it rewards the failure it exists to catch).

**A3. Merge FIR-12 to `main`.** The instrument exists on `r7int/fir12-r7-int` and is absent from this checkout. Without it there is no way to report an open-set number at all. Carry its invariants intact: `IETPoint.measured: bool` so an unmeasured cell cannot render `0.000`; detection failure counts as an identification miss; coverage reported, not assumed.

**A4. Remediate the gate corpus (R1 / FIR-11).** Pool arithmetic is already worked: 150 − 7 celebrity − 3 scraped → 30 entries / 30 named probes / 17 identities worst case, with a Nam/Tango paired non-inferiority test and a Product A/B split. Until this lands, *every* comparison inherits buffalo-contaminated ground truth and is biased toward killing the challenger.

**A5. Stand up `acx-dev-fir` (FIR23-STACK).** Two embedding spaces mandate two databases. This is the prerequisite for any head-to-head, and it also unblocks FIR-8's live leg. Deploy via `scripts/deploy/recognition-service.sh` (`do_status()` already iterates `dev dev-fir staging prod`).

**A6. Re-baseline on the OpenCV 5.x stack.** CVUP-1 invalidated every pre-upgrade artifact as a comparison arm. The first re-baseline run after A3–A5 is the *only* legitimate reference point; treat all earlier numbers as unciteable.

### Phase B — attribute the error before choosing a fix ($0 GPU, ~1 day each)

**B1. D-02 / T-01: split alignment from embedder (FIRTRAIN-06).** Cheapest open row, needs no new labels, and is the one decision whose answer changes the entire plan. If the bulk of identity error is the **embedder** leg, D-01 becomes nearly moot and detector work is wasted spend. Do not skip this because §0g once asserted the answer — that assertion is withdrawn.

**B2. D-01 / T-14: union adjudication for the detection-gap upper bound.** Adjudicate the *union* of buffalo and candidate boxes; the sharp bound is (TP_b − TP_c)/U. If it sits below 0.05 the detector line closes without exhaustive annotation. **Honour the four T-14 conditions before accepting a kill** — the bound is identified on the curated 150-image slice only, not on the 646-image deployment frame, and the slice's own selection was buffalo-influenced, so the contamination biases the bound toward killing the challenger. A kill verdict on a contaminated bound is not a kill.

**B3. Oracle-before-predicted ladder.** Measure with oracle occlusion labels first. If recognition does not improve even with perfect occlusion knowledge, no occlusion *predictor* can help, and the entire adapter track is dead at zero cost. Only if the oracle gap is real does predicting occlusion become worth building.

### Phase C — build occlusion robustness, only on what B proved (gated)

Ordered by cost-to-benefit, to be taken **only** for the leg B identified:

1. **Visible-support matching (embedder leg, no training).** Per-landmark visibility → suppress occluded feature dimensions at match time (PDSN-style), or fall back to **periocular** matching (PLGSA) when the lower face is occluded. Masks/sunglasses are the dominant real-world cases and the periocular region survives both. No retraining, no A10 spend, no new corpus.
2. **Head-region rescue (detector leg, no training).** COCO pose → head region as a detection rescue when the face detector misses. Cheap, inference-only, and directly targets the failure mode where the subject is present but undetected.
3. **Fix the OACT direction.** The current occlusion coefficient *relaxes* the threshold under occlusion. Under an open-gallery criterion that trades a miss for a false identification — the worse error for alt text, since a wrong name is injected verbatim into the caption. Re-derive the direction against the D3 criterion during S4 calibration before enabling it, and keep the non-negativity invariant.
4. **Head/torso embeddings as a *secondary* channel.** Useful for within-image association, never as an identity claim on its own.
5. **Only then** consider a trained detector/embedder (SCRFD, AdaFace, DCFace-synthesised occlusion). **Explicitly NOT AUTHORISED today** per FIR-7 v6.2: the SCRFD + AdaFace-512D retrain campaign is out of scope, and A10 spend is gated behind D-01 via T-09 → T-14, where T-14 can kill Slices 1–2 unpriced at $0 GPU. Note also that AdaFace-512D would reopen the dimension question that `PGVECTOR_DIM=128` just closed.

### Phase D — flip the default

Only after: a re-baselined, admissible FNIR@FPIR head-to-head on the remediated corpus, run on `acx-dev-fir` with the OpenCV 5.x stack; thresholds **measured, never copied**; FIR-6 S4/S5 landed; an **operator-recorded MCP gate decision**; then `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline` + `PGVECTOR_DIM=128` together, followed by removal of the `.[bench]` InsightFace install from the production Dockerfile (FIR-6 S6).

### Licence hygiene running in parallel (cheap, blocking later)

- **D-04: no training on Open Images pixels** without per-image verification + attribution manifest (T-06). Annotations are CC BY 4.0; images are per-image CC BY 2.0 with warranty disclaimed. Hard gate.
- **D-05: COCO {4,5,7,8} pool** needs a replication script, a pinned JSON revision, and an explicit policy call on id 5 (BY-SA propagates to adapted material) — T-07, ~3 eng-h.
- **D-07: per-corpus licence read** for CrowdHuman, COCO-WholeBody, FDDB, AFLW, MAFA, UFDD with a lawful-substitute column (T-11, ~4 eng-h).
- **D-06: train/val `IsOccluded` mechanism** is unidentified with four live rivals; a dual-label pilot (T-15) must precede any SCRFD A/B, because if the mechanism is *population* rather than *calibration*, "never supervise on train `IsOccluded`" is the wrong rule.

---

## 5. What may not be claimed

Guardrails for anyone citing this program externally or in a product decision:

- **Do not cite** M-12 (0.865 vs 0.321 masked recovery) — inadmissible externally.
- **Do not cite** detection recall 0.504 — the estimand is withdrawn.
- **Do not cite** 2.73 faces/image as prevalence — it is an *apparent* YuNet positive fraction at t=0.30 with false positives mixed in, and the standard binary-proportion inversion cannot invert a per-image count.
- **Do not cite** any pre-CVUP-1 artifact as a comparison arm.
- **Do not treat** "the embedder leads" as established — it is a hypothesis pending T-01.
- **Do not treat** a rank-based Golden-150 head-to-head as an acceptance criterion for an open-gallery system.
- **Do not run** the SCRFD + AdaFace-512D retrain campaign — not authorised.
- **Do not spend** A10 hours on FIR training before D-01 resolves via T-09 → T-14.

---

## 6. Immediate next actions

| # | Action | Cost | Unblocks |
| --- | --- | --- | --- |
| 1 | Write the D-09 face-definition rubric (T-09) | ~1 eng-h | all adjudication |
| 2 | Declare D3 = FNIR@fixed FPIR, non-mated probes, score threshold (D-08) | decision only | every embedder comparison |
| 3 | Merge FIR-12 eval harness from `r7int/fir12-r7-int` to `main` | eng only | any reportable number |
| 4 | Run T-01 alignment-vs-embedder split (D-02) | $0, ~1 day | the choice of what to fix at all |
| 5 | Stand up `acx-dev-fir` (FIR23-STACK) | eng only | FIR-8 live leg, all head-to-heads |
| 6 | Land FIR-11 corpus remediation (R1) | ~1 week | admissible ground truth |
| 7 | Confirm `acx-gpu-bake` terminated; wire `gpu_image_ocid` into production tfvars; adopt live infra into one terraform root with a remote state backend | eng only | A10 burst release via `make test-infra-terraform` |

Items 1, 2 and 4 are collectively about two engineer-days and resolve the largest open uncertainty in the program. None of them requires a GPU.
