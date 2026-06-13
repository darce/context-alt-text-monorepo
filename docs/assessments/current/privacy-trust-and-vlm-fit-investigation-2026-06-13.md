# Privacy, Trust, and OCI VLM Fit Investigation - 2026-06-13

**Status:** Active follow-up assessment
**Task:** `MAINT-privacy-vlm-fit-20260613`
**Source assessment:** `docs/assessments/current/portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md`
**Scope:** Correct the privacy/trust moat claim for hosted Alt Context; evaluate biometric litigation/compliance risk; expand public privacy-policy actions; assess current efficient CV/VLM options for an OCI A1 v1 demo.

This is product and engineering risk analysis, not legal advice. Get privacy counsel before public claims such as "BIPA compliant", "GDPR compliant", or "EU AI Act compliant".

## Executive Finding

The 2026-06-11 assessment is right that privacy/trust can be a structural moat, but the line "self-hosted/privacy-minimized recognition service" is wrong for the MVP. Alt Context's current proposition is a hosted recognition service running centrally on OCI. The defensible claim is narrower:

> Alt Context is a hosted, tenant-scoped recognition service for site-owned media. It minimizes retained biometric state, does not train shared models on customer biometric data, keeps names and curation decisions WordPress-authoritative, and gives the site owner export, purge, and audit controls. Self-hosted/customer-controlled recognition is a future tier, not the launch claim.

Litigation risk is not avoided by centralizing in OCI. It is created by collecting, storing, and using face geometry/templates at all. The risk is manageable for a controlled, consented, non-surveillance accessibility workflow, but it must be marketed and operated as biometric processing with consent/notice/retention obligations, not as a generic "AI alt text" feature.

For VLM/CV: a one-image v1 demo is feasible on the existing OCI A1 host with a small MIT/permissive model, especially Florence-2 for caption/object/region outputs. A local CPU-only stack will not beat public vision APIs on both quality and latency. It can, however, prove the core proposition cheaply: same image, generic caption versus roster/context-aware caption.

## Local Evidence Read

- `portfolio-quadrant-mvp-strategy-assessment-2026-06-11.md` says no description generation exists and the product is currently recognition + clustering + curation only; it also names the self-hosted/privacy moat line that needs correction.
- `recognition-privacy-hybrid-roadmap-2026-03-06.md` already states the correct posture: MVP is privacy-minimized remote processing, not full sovereignty; privacy claims must be narrower unless embeddings are genuinely customer-controlled.
- `literature/marketing/feature-list-v1.md` already says face detection/clustering run on the Alt Context hosted service and self-hosted deployment is future-only.
- `public-demo-launch-readiness-epic.md` fixes the current OCI constraint: Always Free `VM.Standard.A1.Flex`, 4 ARM cores, 24 GB RAM, 200 GB disk, and recognition-only CPU inference for the current milestone.
- Current code has retention routes and services: policy read/update/preset, async export, purge, and audit. Export emits `schema_version` and intentionally serializes detection/cluster metadata without raw embedding vectors.
- Local recognition literature reinforces that face embeddings and clustering are mature, commodity techniques; Apple's reference architecture is private on-device person recognition, which is a useful contrast because Alt Context is not yet on-device.

## Corrected Moat Language

Replace this:

> A self-hosted/privacy-minimized recognition service with auditable purge/export occupies ground incumbents cannot follow onto.

With this:

> A privacy-minimized hosted recognition service with tenant isolation, WordPress-authoritative curation, no training reuse, explicit retention modes, auditable export/purge, and a future customer-controlled tier occupies narrower ground than consumer platforms can comfortably enter. The moat is not self-hosting at launch; it is trustable handling of consented, site-specific identity context.

Do not use "self-hosted" in public MVP copy unless the customer can actually run the recognition backend and control embedding authority.

## Litigation and Compliance Risk

### Risk rating

Risk is medium-high if the product handles real people in U.S. or EU media libraries without explicit customer notice/consent workflows. Risk drops to medium for controlled beta/demo use with provenance-tracked images, customer terms, no public uploads, purge/export controls, and no cross-tenant or training reuse.

The riskiest fact pattern is not "hosted in OCI"; it is "Alt Context receives or creates face geometry templates for people who never received notice or gave consent."

### Meta 2021

Meta's 2021 exit is directly relevant because Meta said it would shut down Facebook Face Recognition, delete more than one billion templates, and noted that Automatic Alt Text would stop naming recognized people. Meta explicitly cited societal concerns and unsettled regulation.

Implication for Alt Context: naming people in alt text is valuable, but the public lesson is that "automatic people naming" is sensitive. The product should make identity naming human-in-the-loop, site-roster-bound, and consent/provenance-bound.

Source: [Meta, "An Update On Our Use of Face Recognition"](https://about.fb.com/news/2021/11/update-on-use-of-face-recognition/).

### BIPA / Illinois

Illinois BIPA is the most concrete U.S. class-action risk. Section 15 requires a public retention/destruction policy, written notice of collection/storage, purpose and retention-term notice, and a written release before collecting/obtaining biometric identifiers or biometric information. It also restricts sale/profit, disclosure, and requires protective security controls.

The 2024 amendment reduced repeated-scan damages exposure by treating repeated collection from the same person using the same method as a single violation for recovery, and recognized electronic signature in "written release". It did not remove the private right of action, statutory damages, notice, retention, consent, disclosure, or security obligations.

Implications:

- Alt Context can be a defendant even as a vendor/processor because BIPA covers receiving or obtaining biometric information, not only first-party collection.
- Customer contracts do not cure missing subject notice or written release.
- "Public, versioned retention policy" is not nice-to-have. For BIPA-shaped risk, it is foundational.
- Export/purge features reduce damages narrative and trust risk, but they are not substitutes for pre-collection notice and release.

Sources: [740 ILCS 14/15](https://www.ilga.gov/documents/legislation/ilcs/documents/074000140K15.htm), [Public Act 103-0769](https://www.ilga.gov/Legislation/publicacts/view/103-0769).

### GDPR

Under GDPR Article 4, biometric data is personal data from specific technical processing that allows or confirms unique identification, including facial images. Article 9 prohibits processing biometric data for uniquely identifying a natural person unless an exception applies, such as explicit consent or another Article 9 condition.

Implications:

- Alt Context should assume face embeddings/templates used to cluster/name people are special-category biometric data in EU/UK-style analysis.
- "Legitimate interests" alone is likely too weak for unique identification. Customers need a documented Article 9 condition, commonly explicit consent, unless a narrow alternative applies.
- Alt Context likely acts as processor for customer media/rosters and controller for its own account/security telemetry. That means DPA, subprocessors, transfer basis, retention, breach, and deletion terms matter.
- If EU customers are allowed while OCI processing is outside the EU, transfer and region claims need counsel. Do not imply EU data residency unless deployed.

Sources: [GDPR Article 4](https://gdpr-info.eu/art-4-gdpr/), [GDPR Article 9](https://gdpr-info.eu/art-9-gdpr/).

### EU AI Act

The EU AI Act does not ban every biometric workflow. It prohibits specific practices, including untargeted scraping to build facial-recognition databases, sensitive biometric categorisation, and real-time remote biometric identification in publicly accessible spaces for law enforcement subject to narrow exceptions. Annex III classifies permitted remote biometric identification systems as high-risk, excluding systems used solely for biometric verification of a claimed identity.

Implications:

- Central OCI hosting is not the same thing as "remote biometric identification" under the AI Act. But identifying people in uploaded photos can still look like biometric identification rather than mere verification.
- Alt Context should avoid prohibited categories entirely: no scraping, no public/CCTV face database, no law-enforcement/surveillance use, no sensitive attribute inference, no emotion recognition.
- If offered in the EU, counsel should classify whether the system is high-risk biometric identification. If yes, the issue is not just privacy policy; it is risk management, documentation, logging, human oversight, accuracy, and post-market monitoring.
- Product copy should frame the workflow as customer-supplied media organization and accessibility context, not remote identification, surveillance, security, access control, fraud, school/workplace monitoring, or public-space recognition.

Sources: [EU AI Act Article 5](https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-5), [EU AI Act Annex III](https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3).

## Product Positioning to Stay Inside the Guardrails

Position Alt Context as:

- Accessibility and media-library curation software, not surveillance or generic face search.
- Site-owned, tenant-scoped, human-reviewed identity context, not cross-site identity resolution.
- Roster-bound clustering: the system groups recurring faces in one customer's library and the customer confirms names.
- Processor-like hosted service with strict purpose limitation: generate recognition context for that site and accessibility outputs.
- Privacy-minimized by default: no training reuse, no raw face-crop retention as a product feature, no sale/sharing of biometric data, no cross-tenant galleries.
- Customer-controlled lifecycle: export, purge, retention mode, and audit log are front-stage product features.

Do not position as:

- "Self-hosted" for MVP.
- "Fully sovereign" for MVP.
- "GDPR/BIPA compliant" without counsel and customer-side consent workflows.
- "Recognize anyone" or "identify people automatically".
- Public upload or public face lookup.
- Public-figure/person search across the web.
- Security, access-control, fraud, workplace, school, or law-enforcement biometric tooling.

## Public Policy Action: What To Publish

The assessment action should mean a public, versioned page plus product UI hooks. Publish a page such as `/privacy/recognition-data-policy` with a visible version/date, changelog, and archived prior versions.

Minimum commitments:

- **Purpose limitation:** customer media is processed only to provide face grouping, roster curation, and context-aware accessibility outputs for that customer.
- **No training reuse:** customer images, face crops, embeddings, clusters, names, and curation decisions are not used to train shared models.
- **No cross-tenant recognition:** no shared face gallery, no cross-customer matching, no public search.
- **No scraping:** no internet/CCTV scraping and no enrichment from public face databases.
- **Human-in-the-loop naming:** the system may suggest clusters, but customers choose names and final alt text.
- **Data location and subprocessors:** name hosted processing topology, OCI region if true, and subprocessors.
- **Data classes retained:** raw uploaded image handling, face detections, thumbnails/representatives, embeddings, centroids, clusters, labels, audit events, logs.
- **Retention defaults:** explain default retention mode, TTLs, and what is durable versus purgeable.
- **Purge semantics:** define what purge deletes, what audit/security records remain, expected completion time, and failure/retry behavior.
- **Export semantics:** define what export contains and does not contain. If raw vectors are excluded, explain that human-readable detection/cluster metadata is exported while model vectors are deleted/purged under policy.
- **Security controls:** tenant isolation, API keys, rate limiting, encryption in transit, encryption at rest if true, access logging, least privilege.
- **Customer obligations:** customers must have rights/consent/notice for media they submit and must not use the service for prohibited biometric use cases.
- **Jurisdiction controls:** where the service is available, which use cases are blocked, and how a customer requests DPA/deletion/support.

## Retention and Purge as Marketed Features

"Retention + purge as marketed features, not internals" means these controls should be visible in the buying story and in the UI, not buried in API docs.

Product surfaces:

- Settings card: "Recognition data retention" with current mode and last updated date.
- Pre-scan disclosure: "This scan sends images to the hosted recognition service and creates biometric templates for clustering."
- Scan completion summary: "N faces detected; N embeddings retained; N disposed after projection; next purge window."
- Export button: "Download recognition data JSON" with schema version and timestamp.
- Purge button: "Delete hosted recognition data" with scoped choices and irreversible confirmation.
- Audit timeline: policy changes, export started/completed, purge started/completed, disposal after projection.
- Marketing copy: "Export and delete hosted recognition data on demand" belongs next to "identity-aware alt text."
- Buyer FAQ: "Where does biometric data live?" and "What can I delete?" should be first-class.

Engineering gates before public claim:

- Verify live demo tenant can read retention policy, trigger export, trigger purge, and view audit.
- Add public policy URL to plugin settings and scan confirmation.
- Add or verify tests for no raw embedding vectors in export.
- Add exact default retention mode to docs. Avoid saying "minimum data" if `retain_all` is still the shipped default.
- If `dispose_after_ack` is marketed as default, make it default and prove clustering/representative continuity after disposal.

## VLM / CV Options for OCI A1

### Constraints

Current public-demo docs set the runtime as OCI Always Free A1, 4 ARM cores, 24 GB RAM, 200 GB disk, with current milestone recognition-only CPU inference. A VLM worker must be resource-capped and bulkheaded from API/DB pools.

For a v1 demo, prefer one seeded image or a tiny image set, async worker, bounded queue, one worker process, image downsample, timeout, and cached outputs. Do not promise batch captioning performance until benchmarked.

### Shortlist

| Candidate | License | Fit | Recommendation |
| --- | --- | --- | --- |
| Florence-2-base-ft / large-ft | MIT | 0.23B/0.77B, caption, detailed caption, object detection, dense region caption, OCR, phrase grounding. Best fit for MIT-preferred demo. | First local probe. Use base-ft first; compare large-ft only if latency acceptable. |
| Phi-3.5-vision-instruct ONNX | MIT | 4B-class VLM; ONNX card lists CPU with 16 GB RAM minimum. More general but likely slow on A1 CPU. | Benchmark as fallback if Florence output is too weak. Not first choice. |
| MobileSAM or SAM 2 / SAM 2.1 | Apache-2.0 | Strong promptable segmentation. Useful for masks from boxes, but not necessary for alt text v1. | Use only if visual mask overlay is needed. For text generation, boxes/regions are enough. |
| SmolVLM2-2.2B | Apache-2.0 | Lightweight image/video VLM; card says 5.2 GB GPU RAM for video inference. Good future video probe candidate. | Keep for post-demo video/image experiments, not first OCI CPU demo. |
| Qwen2.5-VL-3B-Instruct | License not clearly surfaced in this check | Strong visual reasoning/localization/JSON, but license needs product review before MVP use. | Avoid for commercial MVP until license is reviewed. |

Primary sources:

- [Florence-2 model card](https://huggingface.co/microsoft/Florence-2-large)
- [Phi-3.5 Vision ONNX model card](https://huggingface.co/microsoft/Phi-3.5-vision-instruct-onnx)
- [SAM 2 repository](https://github.com/facebookresearch/sam2)
- [MobileSAM repository](https://github.com/ChaoningZhang/MobileSAM)
- [SmolVLM2 model card](https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct)
- [Qwen2.5-VL-3B model card](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct)

### Does a local option beat public APIs?

Probably not on both time and quality. Public APIs have GPU-backed latency, high-quality vision reasoning, and very low per-image cost. Gemini 2.5 Flash-Lite is listed at $0.10 per 1M text/image/video input tokens and $0.40 per 1M output tokens standard; OpenAI's pricing page shows image inputs tokenized and charged per model, with a sample 512x512 low-resolution calculation around fractions of a cent. A local A1 CPU model can have zero incremental API spend, but it pays in latency, ops complexity, and lower quality.

The better framing:

- Use local Florence-2 as the privacy/cost-controlled demo path and fallback.
- Optionally compare against one hosted API offline for quality evidence.
- Do not send biometric face crops, names, or customer rosters to third-party VLM APIs without explicit policy and opt-in.
- For the public demo, cache seeded outputs and show the context delta rather than live-benchmarking under load.

Sources: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing), [OpenAI API pricing](https://openai.com/api/pricing/).

## Recommended V1 Demo Architecture

1. Keep InsightFace for face detection/identity clustering.
2. Add a separate `describe` worker behind an async job queue, not inline API work.
3. Start with Florence-2-base-ft local inference for:
   - generic caption
   - object/dense-region labels
   - optional OCR
4. Inject existing roster context after face clustering:
   - recognized person labels from WordPress-authoritative roster
   - face boxes/counts
   - image metadata/customer-provided context
5. Generate two outputs:
   - generic visual caption
   - context-aware alt text draft
6. Show side-by-side in the demo. This buys down the largest portfolio risk: whether identity context improves alt text.

Acceptance bar for the probe:

- Single 1024px image completes within a tolerable async demo window, target under 20 seconds on OCI A1 CPU.
- Worker memory stays below a configured cap and does not starve API/Postgres.
- Output shows a visible quality difference when roster context is available.
- No raw embeddings leave the service.
- Results are cached per image/model/context hash for demo repeatability.

## Decision

Privacy/trust remains a plausible moat, but only if public language tracks runtime reality. For MVP, say "hosted privacy-minimized recognition", not "self-hosted". Treat biometric notice, consent, retention, export, purge, and audit as product primitives.

For VLM, run a small Florence-2 probe on OCI for the demo and compare quality against a hosted API offline. Do not schedule a broader local VLM platform until measured latency, memory, and output quality justify it.

## Immediate Actions

1. Draft public `Recognition Data Policy v0.1` from the commitments above.
2. Add scan-time consent/notice copy and customer attestation language before any public beta with real media.
3. Verify retention policy/export/purge/audit on the demo tenant and record evidence.
4. Correct the 2026-06-11 moat line in the next strategy revision.
5. Create a timeboxed Florence-2-base-ft OCI benchmark: latency, memory, CPU, output quality, one seeded image.
6. Keep third-party VLM APIs out of the live biometric path until policy, DPA/subprocessor, and opt-in terms are explicit.

## Follow-Up: Hosted GPU Inference Viability - 2026-06-13

### Question answered

Yes, Hugging Face still offers rentable GPU time. The T4 class specifically still exists:

- Hugging Face Spaces lists `Nvidia T4 - small` at $0.40/hour and `Nvidia T4 - medium` at $0.60/hour.
- Hugging Face Inference Endpoints lists T4 endpoints at $0.50/hour on AWS and GCP, billed by the minute.
- Hugging Face Jobs lists T4 hardware at the same $0.40/hour and $0.60/hour rates, billed by the minute, but Jobs require a Pro user or Team/Enterprise organization.

The important update to the older self-hosting plan is that HF is no longer just "free Space with painful cold starts" versus "persistent VPS". Paid GPU Spaces remain available, upgraded Spaces run indefinitely by default, and Spaces can now attach Storage Buckets/volumes for persistent data. That softens the old model-cache problem, though it does not remove cold-start, build, privacy, or idle-billing concerns.

Sources:

- [Hugging Face Spaces GPU hardware](https://huggingface.co/docs/hub/spaces-gpus)
- [Hugging Face pricing](https://huggingface.co/pricing)
- [Hugging Face Inference Endpoints pricing](https://huggingface.co/docs/inference-endpoints/pricing)
- [Hugging Face Jobs pricing](https://huggingface.co/docs/hub/jobs-pricing)
- [Hugging Face Jobs guide](https://huggingface.co/docs/huggingface_hub/en/guides/jobs)
- [Hugging Face Spaces storage](https://huggingface.co/docs/hub/en/spaces-storage)

### Local docs update

The project docs currently say:

- E15 public demo is recognition-only on OCI A1: no VLM/Phi-3.5 in the current launch milestone.
- E16 explicitly defers "VLM/Phi-3.5 captioning rollout" and "GPU host migration".
- E14 self-hosting notes treated Hugging Face Spaces as a cold-start-prone demo host and recommended persistent VPS for the first production backend.
- E15-5a Hetzner fallback is a recognition-service fallback, not a GPU/VLM plan.

Those docs are still directionally right for the live backend, but they are incomplete for a v1 description demo. The current GPU proposal should be a separate async VLM worker path, not a replacement for the OCI recognition service.

### Current hosting options

| Option | Current cost | Fit | Cost/image estimate |
| --- | ---: | --- | ---: |
| HF Space `t4-small` | $0.40/hour | Cheapest interactive demo GPU. Use for Florence-2-base/large or a quantized small VLM. | Warm 5-12s/image: ~$0.0006-$0.0013. One 1h demo window costs $0.40 regardless of image count. |
| HF Space `l4x1` | $0.80/hour | Better v1 demo hardware. 24 GB VRAM gives headroom for Phi-3.5 Vision or SmolVLM2. | Warm 5-20s/image: ~$0.0011-$0.0044. One 1h demo window costs $0.80. |
| HF Inference Endpoint T4 | $0.50/hour, billed by minute | Managed endpoint, autoscaling, better production shape than Spaces. Use for async worker calls. | Warm 5-12s/image: ~$0.0007-$0.0017. Isolated single-image wake can cost at least one billed minute: ~$0.0083 before cold-start overhead. |
| HF Inference Endpoint L4 | $0.70-$0.80/hour, billed by minute | Best HF production candidate for small VLM serving. Scale-to-zero can control idle cost. | Warm 5-20s/image: ~$0.0010-$0.0044. Always-on is ~$511-$584/month before storage/traffic. |
| HF Jobs T4 | $0.40/hour, billed by minute | Batch benchmark/backfill, not user-facing API. Requires Pro/Team/Enterprise. | 100 images in 20 minutes: ~$0.0013/image. 10 images in 10 minutes: ~$0.0067/image. |
| Google Cloud Run L4 | GPU $0.0001867/sec = ~$0.672/hour, plus CPU/RAM | Good non-HF productized burst path. Fully managed, scale-to-zero, container-native. | Example 4 vCPU + 16 GiB + L4 is roughly ~$1.05/hour; 5-20s/image: ~$0.0015-$0.0058. |

Notes:

- These are compute-only estimates. They exclude model download/build time, container image storage, egress, request overhead, queue retries, and engineering time.
- Hugging Face Endpoints support scale-to-zero, but cold starts are real. The request path can return a temporary 503/502 while a replica starts, so Alt Context should hide that behind its own async job queue and status UI.
- Always-on GPU is not viable for the current budget: even a $0.40/hour T4 is about $292/month at 730 hours. GPU must be scheduled, paused, scaled to zero, or used only for demo windows until there is paid usage.
- Public APIs will usually win at low volume. Hosted GPU becomes competitive only when the GPU is kept busy, when batching amortizes cold starts, or when privacy/model-control needs justify the operational cost.

Cloud Run sources:

- [Cloud Run GPU support](https://docs.cloud.google.com/run/docs/configuring/services/gpu)
- [Cloud Run pricing](https://cloud.google.com/run/pricing)

### Model-to-hardware match

| Model path | License | Hardware | Recommendation |
| --- | --- | --- | --- |
| Florence-2-base-ft / Florence-2-large-ft | MIT | HF T4 Space or T4 Endpoint | Best first GPU demo. Cheap, small, supports captioning, object detection, dense region captions, OCR, and phrase grounding. Use large if latency is acceptable; otherwise base. |
| Phi-3.5-vision-instruct | MIT | Prefer L4/A10G 24 GB. T4 only with quantization/ONNX benchmark proof. | Best MIT-preferred candidate for richer natural-language description. Use after Florence if the demo needs better prose and reasoning. |
| SmolVLM2-2.2B-Instruct | Apache-2.0 | T4 or L4 | Strong small-VLM fallback. Less aligned with MIT preference but permissive and likely practical. |
| MobileSAM / SAM 2 | Apache-2.0 | T4/L4 if mask overlays are required | Segmentation only. Use to enrich regions/masks, not to generate alt text. |
| Qwen2.5-VL-3B-Instruct | License not clearly surfaced in this check | L4/A10G | Technically attractive, but avoid for commercial MVP until license is cleared. |

### Recommended deploy proposal

Use a three-step GPU path:

1. **Benchmark via HF Jobs, not production.**
   - Run the same 10-25 seeded demo images through Florence-2-large-ft, Florence-2-base-ft, and Phi-3.5 Vision on `t4-small` and `l4x1` if quota allows.
   - Record wall time, billed minutes, cold-start/model-load time, peak VRAM, and output quality.
   - Budget: one 30-minute T4 run is about $0.20; one 30-minute L4 run is about $0.40.

2. **Ship the public v1 demo on a controlled HF Space window.**
   - Use `t4-small` + Florence-2-large-ft first.
   - Keep the Space private or access-gated, attach persistent storage/bucket if model-cache rebuilds are hurting demo reliability, and pause it outside demo windows.
   - Route live demo images from OCI to the GPU worker only after biometric policy/subprocessor language is explicit. Safer first pass: seeded/provenance-controlled demo images only.
   - Budget: 10 demo hours/month on T4 is $4; 30 demo hours/month is $12.

3. **Move to a managed endpoint only after quality proves the proposition.**
   - If Florence is good enough: HF Inference Endpoint T4 is the cheapest managed endpoint candidate.
   - If richer description is needed: HF Inference Endpoint L4 + Phi-3.5 Vision is the better product candidate.
   - Keep `min_replicas=0`/scale-to-zero and call it from an Alt Context async worker. Never block WordPress admin UI on endpoint wake-up.
   - Cache outputs by image hash + model id + roster-context hash.

### Viability decision

For a v1 demo, hosted GPU exists and is viable. The strongest near-term proposal is:

> OCI remains the recognition/control-plane host. A separate Hugging Face GPU worker runs Florence-2-large-ft on `t4-small` for scheduled demo windows. Estimated compute is $0.40/hour, roughly $0.0006-$0.0013 per warm image at 5-12 seconds/image, or $4-$12/month for 10-30 demo hours. If Florence quality is insufficient, rerun the benchmark on L4 with Phi-3.5 Vision; expect $0.80/hour and roughly $0.0011-$0.0044 per warm image.

This is viable as a demo and benchmark path. It is not yet a proof that local/open VLM inference beats public APIs on cost. For low-volume production, public APIs are likely cheaper and operationally easier. The product reason to use hosted GPU is control over model/data path and a credible migration toward privacy-minimized open-model inference, not raw per-image price at small scale.

## Follow-Up: HF Cold Starts and Model Quality - 2026-06-13

### Is the Hugging Face startup problem still real?

Yes. It is still product-blocking for a synchronous customer-facing workflow.

The current HF story is more nuanced than the old "Spaces always sleep" concern:

- Upgraded GPU Spaces run indefinitely by default, so a paid T4/L4 Space can be kept hot.
- A Space can be configured to sleep, paused, or downgraded to stop billing. Once that happens, wake-up cost returns.
- Attached Storage Buckets/volumes can preserve model files and avoid repeated downloads, but they do not remove container startup, GPU allocation, Python import, CUDA initialization, or model load into VRAM.
- Inference Endpoints also support scale-to-zero, but HF documents cold start on first request and says scale-from-zero can take minutes depending on model size. HF recommends not relying on request-driven scale-from-zero when the application needs responsiveness.

Cost makes "just keep it warm" unattractive before revenue:

| Hardware | Hourly | Always-on 730h/month |
| --- | ---: | ---: |
| HF Space T4 small | $0.40 | ~$292/month |
| HF Space T4 medium | $0.60 | ~$438/month |
| HF Space L4 | $0.80 | ~$584/month |

Decision: do not use a sleeping HF Space in the live WordPress click path. Use one of these patterns instead:

- **Scheduled demo window:** start/warm the GPU worker before a demo, shut it down after.
- **Async job flow:** WordPress enqueues description work, shows pending status, and polls for completion.
- **Operator prewarm button:** explicit "Start description worker" action with readiness state.
- **Batch/backfill:** use HF Jobs or a paid Space for seeded images and cache results.
- **Always-on only after revenue:** keep one endpoint/Space warm only when monthly usage justifies the floor.

Sources:

- [HF Spaces GPU hardware and sleep behavior](https://huggingface.co/docs/hub/spaces-gpus)
- [HF Spaces storage and attached volumes](https://huggingface.co/docs/hub/en/spaces-storage)
- [HF Inference Endpoints autoscaling](https://huggingface.co/docs/inference-endpoints/en/guides/autoscaling)
- [HF pricing](https://huggingface.co/pricing)

### Florence-2 vs Florence-2-large vs Phi-3.5

For Alt Context, "quality" means two different things:

1. **Grounded visual facts:** objects, regions, OCR, boxes, phrase grounding.
2. **Readable alt-text prose:** instruction following, context use, concise human language.

Florence-2-large-ft is better than Florence-2-base-ft for Florence-style tasks. The Florence model card reports large-ft ahead of base-ft on captioning, TextVQA, VizWiz, object detection, grounding, and referring-expression segmentation. Use the fine-tuned variants for the demo, not the pretrained-only variants.

Phi-3.5 Vision is probably better than Florence for prose and reasoning. It is a 4B MIT-licensed multimodal model intended for compute-constrained, latency-bound scenarios, general image understanding, OCR, chart/table understanding, multi-image comparison, and video clip summarization. Its benchmark table is strong for a small model, but the model card's tested GPU list is A100/A6000/H100, so T4 suitability must be proven with quantization or ONNX. L4/A10G is the safer hosted GPU class.

Practical recommendation:

- If the demo needs **fast, grounded visual primitives on T4**, start with `microsoft/Florence-2-large-ft`.
- If the demo needs **best open-model prose from image + roster context**, benchmark `microsoft/Phi-3.5-vision-instruct` on L4 or A10G.
- If only one low-cost T4 model can be used, compare `Florence-2-large-ft`, `SmolVLM2-2.2B-Instruct`, and `Moondream2` on the same 10-25 seeded images. Do not assume Florence wins for final prose.
- A strong architecture is two-stage: Florence extracts caption/OCR/regions; Alt Context injects roster/face context; a small text/VLM rewriter produces the alt-text draft.

Sources:

- [Florence-2-large model card](https://huggingface.co/microsoft/Florence-2-large)
- [Florence-2-large-ft model card](https://huggingface.co/microsoft/Florence-2-large-ft)
- [Phi-3.5 Vision model card](https://huggingface.co/microsoft/Phi-3.5-vision-instruct)
- [Phi-3.5 Vision ONNX model card](https://huggingface.co/microsoft/Phi-3.5-vision-instruct-onnx)

### Comparable models to benchmark

| Candidate | License | T4/L4 fit | Why consider it | Caution |
| --- | --- | --- | --- | --- |
| `microsoft/Florence-2-large-ft` | MIT | T4-friendly | Best grounded primitive extractor: caption, OCR, boxes, dense regions, phrase grounding. | Less conversational; may need a rewriter for polished alt text. |
| `microsoft/Phi-3.5-vision-instruct` | MIT | L4/A10G preferred; T4 only after quantized proof | Better instruction following and prose than Florence; useful for context-aware alt-text drafting. | 4B BF16 model; T4 latency/VRAM uncertain. |
| `HuggingFaceTB/SmolVLM2-2.2B-Instruct` | Apache-2.0 | T4/L4 | Lightweight image/video/text model; model card says 5.2 GB GPU RAM for video inference and provides vision benchmarks. | Not MIT, but permissive. Benchmark prose quality against Phi/Gemma. |
| `vikhyatk/moondream2` / pinned Moondream 2 release | Apache-2.0 | T4-friendly, possibly CPU-tolerable | Small VLM built for efficient captioning, VQA, object detection, and pointing. Good latency candidate. | Previous-generation model; pin revision because upstream updates frequently. |
| `OpenGVLab/InternVL3-2B` | MIT project; uses Apache-2.0 Qwen component | T4/L4 benchmark required | Advanced 2B MLLM with strong multimodal reasoning claims and permissive licensing. | Heavier dependency/runtime surface; likely needs `trust_remote_code` and careful container proof. |
| `google/gemma-4-E2B` / `gemma-4-E4B` | Apache-2.0 | E2B likely T4 candidate; E4B safer on L4 | New small multimodal/omnimodal line: text, image, audio, video; strong reasoning orientation. | Very new. Treat as exploratory until local serving and latency are proven. |
| `Qwen/Qwen2.5-VL-3B-Instruct` | License not clearly surfaced in this check | L4/A10G | Technically strong for document/layout, localization, video/image, JSON-like structured output. | Do not use commercially until license is reviewed and recorded. |
| SigLIP 2 / OpenCLIP | Mixed, model-specific | CPU/T4-friendly | Useful for image-text retrieval, zero-shot classification, dedupe, and semantic search over media. | Not generative. Cannot produce alt text by itself. |

### Revised recommendation

The viable v1 path is not "HF Space as product backend". It is:

1. Keep recognition and state on OCI.
2. Add an async description-worker contract.
3. Benchmark `Florence-2-large-ft`, `SmolVLM2-2.2B`, `Moondream2`, `Phi-3.5 Vision`, `InternVL3-2B`, and `Gemma 4 E2B` on the same seeded images.
4. Use T4 only for Florence/Smol/Moondream-class models unless the benchmark proves Phi/Gemma/InternVL fit.
5. Cache outputs and never make first-user interaction pay the HF wake-up penalty.

Near-term bet:

> Use `Florence-2-large-ft` as the T4-safe visual-facts extractor. If the resulting alt text feels too mechanical, move prose generation to `Phi-3.5 Vision`, `Gemma 4 E2B`, or `SmolVLM2` on L4 after a measured benchmark. HF Spaces remains acceptable for scheduled demos and batch jobs, but not for an always-available product unless the GPU is already warm or the UI is fully async.

Additional sources:

- [SmolVLM2-2.2B model card](https://huggingface.co/HuggingFaceTB/SmolVLM2-2.2B-Instruct)
- [Moondream2 model card](https://huggingface.co/vikhyatk/moondream2)
- [Moondream pinned Apache-2.0 release](https://huggingface.co/moondream/moondream-2b-2025-04-14)
- [InternVL3-2B model card](https://huggingface.co/OpenGVLab/InternVL3-2B)
- [Gemma 4 E2B model card](https://huggingface.co/google/gemma-4-E2B)
- [Qwen2.5-VL-3B model card](https://huggingface.co/Qwen/Qwen2.5-VL-3B-Instruct)
- [SigLIP 2 model card](https://huggingface.co/google/siglip2-base-patch16-224)
- [OpenCLIP on Hugging Face](https://huggingface.co/docs/hub/open_clip)
