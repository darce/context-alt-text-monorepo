# VLM-1. CPU-Only Image Description Service MVP

> **Status**: scope (intake recorded 2026-06-13)  
> **Task ref**: `VLM-1`  
> **Parent epic**: proposed VLM / description epic; separate from [E16 public-demo follow-ons](../epics/v0.4.1/public-demo-followons-epic.md), which explicitly defers VLM/Phi captioning and GPU host migration  
> **Branch**: `feature/vlm-1-cpu-only-description-mvp-scope`  
> **Worktree**: `context-alt-text-monorepo-SCOPE-cpu-only-description-mvp-20260613`  
> **MCP intake decision**: `#804`

## Problem

Alt Context's visible public-demo path is currently recognition-only: it can identify and cluster faces, but it does not yet prove the core alt-text proposition that the system can extract useful image facts and combine them with site context. The earlier model plan assumed hosted/GPU options that are not available for the MVP demo, and the current live deployment target is still the existing OCI A1 host.

The first implementation should therefore prove a narrow service path, not the full authoring product: from the current headless WordPress installation, submit a seeded image to the backend and receive structured visual facts. The output should be intentionally factual and expandable, with placeholders for richer context and prose later.

## Intake Boundary

User-confirmed constraints:

- Seeded demo first.
- Visual facts only, with placeholders for later expansion.
- No first-pass UI.
- Minimal roundtrip from the current headless WordPress installation; do not provision a new WordPress install.
- CPU-only under current OCI constraints; no T4/L4/Hugging Face/OpenAI/Gemini dependency for the MVP path.

## MVP Scope

Build a single-image, CPU-safe image description path that can be called headlessly from WordPress:

1. WordPress reads an existing attachment from the current install.
2. The plugin sends the image bytes through the existing authenticated multipart proxy machinery.
3. The backend returns a `visual_facts` JSON document.
4. A WP-CLI smoke command or `eval-file` script prints the response and timing evidence.

The first pass may use a deterministic seeded adapter or cache-first fixture mode so the end-to-end contract can land before real model performance is fully trusted. Real local inference should plug into the same adapter boundary and be demo-gated until benchmarked on the live A1 shape.

## Output Contract

The response should stay factual and machine-checkable. A candidate shape:

```json
{
  "media_id": 123,
  "status": "completed",
  "cached": true,
  "model_id": "seeded-visual-facts-v0",
  "model_runtime": "fixture",
  "cache_key": "sha256:...",
  "visual_facts": {
    "caption": "A person standing at a podium.",
    "detailed_caption": "A person in a dark jacket stands behind a podium with microphones.",
    "objects": [
      { "label": "person", "confidence": null, "box": null },
      { "label": "podium", "confidence": null, "box": null }
    ],
    "regions": [],
    "ocr_text": [],
    "people_placeholders": [
      {
        "source": "recognition-context-follow-on",
        "identity_label": null,
        "box": null
      }
    ],
    "expansion_placeholders": {
      "contextual_alt_text": null,
      "roster_context": null,
      "segmentation_masks": null
    }
  },
  "timing_ms": {
    "total": 120,
    "adapter": 0
  }
}
```

The contract can change during task planning, but the first implementation should preserve these properties:

- No final alt-text prose yet.
- No person-name claims unless they come from the existing recognition/curation system.
- No hidden biometric inference beyond existing recognition scope.
- Stable `model_id`, `model_runtime`, and cache metadata so evidence can distinguish fixture, cached, and real-model results.

## Model Posture

Default local candidate remains `microsoft/Florence-2-base-ft`, preferably through `onnx-community/Florence-2-base-ft` if the ONNX path works on ARM64. It is MIT-licensed, smaller than Phi-3.5 Vision, and aimed at the primitives this MVP needs: caption, detailed caption, OCR, object detection, phrase grounding, and dense-region captioning.

Do not make the MVP depend on Phi-3.5 Vision, Florence-2-large, or a hosted GPU. Those may produce better prose or richer reasoning, but they are not the right first hosted-local path on the current 4-core ARM CPU. If Florence base is too weak, record benchmark evidence and decide whether to move the demo to a paid GPU worker or postpone prose quality work.

## OCI Deployment Boundary

Do not provision another VM for the first pass. The current safe assumption is one Oracle account and one useful OCI A1 budget. A second free A1 instance would draw from the same quota and boot-volume pool, and nested virtualization on the existing host would add overhead without adding GPU capability.

Recommended topology for the MVP:

- Same OCI host.
- Separate `acx-description-worker` process or container, disabled by default or demo-gated.
- CPU and memory limits so WordPress, MariaDB, Caddy, Postgres, and recognition stay protected.
- Cache-first seeded demo path.
- One worker concurrency by default.

If real model latency consistently exceeds the WordPress mutation timeout envelope, promote the adapter behind an async backend job before exposing real-model mode. Do not paper over model latency by making the WordPress REST request block for several minutes.

## Hosted Provider / BYOK Option

AltText.ai is the closest public benchmark for the WordPress workflow. Its WordPress docs show a hosted account API-key model, automatic generation on upload, single-image update, bulk media-library processing, WP-CLI generation/status commands, and shared credits for multisite. Its private-site setting is especially relevant: when a WordPress site is not publicly reachable, the plugin uploads image bytes directly for analysis instead of relying on a public image URL. Its docs also show SEO keywords, WooCommerce product data, multilingual generation, and a custom ChatGPT prompt step.

Public AltText.ai docs do not disclose the exact image model stack. The best inference is:

1. The plugin sends an image URL or uploaded image bytes plus WordPress context to AltText.ai's hosted service.
2. AltText.ai runs hosted vision inference to produce initial alt text.
3. SEO/ecommerce/language settings are incorporated either into that generation step or a text post-processing step.
4. Optional ChatGPT prompt customization rewrites the already-generated text; their docs explicitly say that ChatGPT does not see the image in that mode.

That means AltText.ai's model is not "local plugin inference"; it is a centralized service with account credits and hosted image processing. It is structurally similar to Alt Context's hosted API plan, except Alt Context's differentiator should be richer WordPress/roster context and auditable privacy controls rather than generic SEO alt text.

Provider-backed generation is technically viable for Alt Context, but should be treated as an opt-in adapter, not the default CPU-only MVP:

- **Alt Context pays provider API costs**: viable for demos and early hosted plans. Current public pricing makes raw model cost small relative to AltText.ai-style retail credits. OpenAI's pricing calculator shows a 512x512 image example at 210 image input tokens and about $0.000263 before output tokens. Anthropic's Claude Sonnet 4.6 examples put a 1000x1000 image at about $0.0039 input cost, with short text output billed separately. Even with retries, prompt overhead, and output tokens, a 100-image seeded demo should stay comfortably below human-review cost.
- **Bring-your-own OpenAI/Claude/Grok/Gemini key**: technically viable, but poor as the default product experience. It pushes billing setup, quotas, rate limits, provider support, and key security onto WordPress admins. It also fragments quality and latency by provider/model and turns the plugin into a high-value secret store. API usage is separate from consumer subscriptions, so this still requires users to create API accounts and billing.
- **Privacy posture**: provider mode weakens the "privacy-minimized hosted Alt Context" story because image bytes and prompts leave Alt Context for another processor. OpenAI and Anthropic commercial/API docs say API inputs/outputs are not used for training by default, but both still have endpoint/model-specific retention and control details. This must be explicit in product copy, tenant settings, and the public privacy policy before shipping.

Candidate hosted providers for a later benchmark:

| Provider | Why consider | Cautions |
| --- | --- | --- |
| OpenAI API / Azure OpenAI | Strong default quality/latency benchmark; mature structured output; direct OpenAI has public image-token pricing and data controls; Azure is useful for enterprise customers that already buy through Microsoft. | Direct OpenAI is another data processor; Azure adds deployment/procurement complexity and model availability varies by region. |
| Anthropic Claude API | Good prose, image understanding, and commercial privacy posture; Claude Sonnet image-cost examples are easy to estimate. | Higher output-token costs; model-specific retention/ZDR eligibility now matters, so provider metadata must record the exact model and retention setting. |
| xAI Grok API | Add to provider spike. xAI docs show image understanding through Grok 4.3 with base64 or public image URLs, OpenAI-compatible SDK usage, jpg/png up to 20 MiB, token-based visual-content analysis, and enterprise ZDR. | Grok Imagine is for image generation/editing, not alt-text description. Default API retention is 30 days; ZDR is enterprise only. Brand/safety posture may be more polarizing for privacy-sensitive customers. |
| Google Gemini API / Vertex AI | Worth benchmarking for cost and speed. Gemini Flash/Flash-Lite have very low text/image token rates, Gemini 3 Pro Image gives clear per-image input accounting, and paid-tier Gemini API traffic is marked as not used to improve products. | Free/unpaid quota can be used to improve Google products; terms require paid services for API clients in EEA/Switzerland/UK. Google Cloud/Vertex privacy posture differs from AI Studio/free tier. |
| Amazon Bedrock / Amazon Nova | Strong enterprise/privacy option. Bedrock states prompts and completions are not shared with model providers or used to train base models; Nova Lite/Pro support image understanding, classification, summarization, bounding boxes, 25 MB payloads, and S3 image inputs. | More AWS setup than a simple HTTP provider key; pricing and model access are region/account dependent. Best for enterprise posture, not first demo speed. |
| Mistral API | Worth a low-cost/EU-friendly benchmark. Current Mistral docs list several vision-capable chat models; Mistral Small is cheap and multimodal, and API data is not used for model training. | Vision quality for natural photos and accessibility alt text needs direct testing. Some older Pixtral docs are deprecated; pin current model IDs before benchmarking. |
| Replicate / Modal / Together / Fireworks / OpenRouter | Useful for quick open-model experiments and comparing hosted Florence/Phi/Qwen-style models. | Not first production choices for privacy/trust: model routing, retention, subprocessor chain, and SLA vary by aggregator/provider. |

Recommended positioning:

- Keep the CPU-only seeded path as the MVP proof and default plan.
- Add a `DescriptionAdapter` abstraction that can later support `local_cpu`, `altcontext_provider_paid`, and `customer_provider_key`.
- For the first provider experiment, use an operator-owned server-side key in the backend only. Do not add a WordPress UI field for OpenAI/Claude/Grok/Gemini keys in the first pass.
- If BYOK ships later, require an explicit per-tenant opt-in, provider disclosure, budget/rate controls, encrypted server-side key handling, purge/export coverage, and a clear statement that third-party provider terms apply.

Provider mode should be framed as a quality/latency escape hatch for customers who accept third-party processing, not as the core trust posture of the product.

Sources:

- AltText.ai WordPress docs: `https://alttext.ai/docs/integrations/wordpress/`
- AltText.ai developer/API positioning: `https://alttext.ai/solutions/custom`
- AltText.ai pricing / enterprise pricing: `https://alttext.ai/pricing`, `https://alttext.ai/enterprise`
- OpenAI pricing and image-token docs: `https://openai.com/api/pricing/`, `https://developers.openai.com/api/docs/guides/images-vision`
- OpenAI data controls: `https://developers.openai.com/api/docs/guides/your-data`
- Anthropic pricing, vision, and data retention docs: `https://platform.claude.com/docs/en/about-claude/pricing`, `https://platform.claude.com/docs/en/build-with-claude/vision`, `https://platform.claude.com/docs/en/manage-claude/api-and-data-retention`
- xAI Grok image understanding, pricing, and security docs: `https://docs.x.ai/developers/model-capabilities/images/understanding`, `https://docs.x.ai/developers/pricing`, `https://docs.x.ai/developers/faq/security`
- Google Gemini API pricing/terms and Google Cloud retention docs: `https://ai.google.dev/gemini-api/docs/pricing`, `https://ai.google.dev/gemini-api/terms`, `https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention`
- Amazon Nova / Bedrock image and privacy docs: `https://docs.aws.amazon.com/nova/latest/userguide/modalities-image.html`, `https://aws.amazon.com/bedrock/faqs/`
- Mistral vision, pricing, and privacy docs: `https://docs.mistral.ai/studio-api/conversations/vision`, `https://mistral.ai/pricing/`, `https://docs.mistral.ai/admin/security-access/privacy`

## Proposed Slices

### S1: Backend Visual-Facts Contract

- Add a description/visual-facts route under the existing authenticated backend surface, likely `/recognition/describe/multipart` or `/recognition/visual-facts/multipart` for the first pass.
- Accept exactly one image in multipart form plus a JSON request envelope containing `tenant_id`, `media_id`, optional image hash, and `mode=visual_facts`.
- Add typed request/response models and a `DescriptionAdapter` interface.
- Ship a deterministic seeded adapter for CI and headless demo proof.
- Add backend tests for auth, multipart validation, one-image limit, schema shape, and adapter failure mapping.

### S2: Cache and Local Adapter Boundary

- Compute a cache key from image bytes, tenant, `model_id`, adapter version, and optional context hash.
- Cache visual facts so repeated seeded demo calls return quickly and with `cached=true`.
- Add description settings for adapter mode, model id, worker concurrency, timeout, and feature enablement.
- Add the Florence-2-base-ft adapter behind an optional dependency/feature flag only after ARM64 install and runtime are proven.
- Keep CI on the deterministic adapter; real-model verification is manual evidence until the dependency is stable.

### S3: Headless WordPress Roundtrip

- Add a plugin REST/controller path with no admin UI, for example `POST /acx/v1/recognition/describe`.
- Reuse `AnalyzeMediaService` multipart mechanics: resolve attachment ids, read bytes from the current WordPress install, enforce image count and body-size caps, and call the backend through `AbstractRecognitionProxyController`.
- Add a WP-CLI `eval-file` smoke script and Makefile target similar to `localwp-batch-run-smoke`, but for one seeded attachment.
- Preserve current installation behavior: the smoke requires `WP_PATH` and refuses missing/non-current installs; it does not install WordPress or seed a new site.
- Add PHPUnit coverage for route registration, multipart proxy path, unreadable attachment handling, timeout/error mapping, and response pass-through.

### S4: Demo Evidence and Runbook

- Add a short runbook showing how to run the backend in seeded adapter mode and execute the WordPress headless smoke.
- Capture one successful JSON response, cache hit proof, and elapsed timing.
- Document the manual Florence benchmark command separately if real local inference is attempted.
- Record known limits: single image, seeded/cached first, visual facts only, no UI, no batch SLO.

### S5: Optional Provider Adapter Spike

- Implement only after S1-S4 prove the local contract.
- Add a backend-only provider adapter behind an operator-owned key for benchmarking OpenAI, Claude, Grok, Gemini, Bedrock/Nova, and Mistral quality, latency, and cost against Florence output.
- Do not expose BYOK in WordPress yet.
- Record per-image provider, model, prompt version, input-image dimensions, input token estimate, output token count, cost estimate, latency, and whether the provider retained/stored data under the selected endpoint/model.
- Use the spike to decide whether provider mode belongs in the first public plan, an enterprise opt-in, or a separate hosted-quality tier.

## Success Criteria

1. From the current WordPress installation, an operator can run one headless command against an existing attachment and receive `visual_facts` JSON from the backend.
2. The same command works with the deterministic seeded adapter in CI/local tests and produces stable output.
3. A repeated seeded call proves the cache path and reports `cached=true`.
4. The backend route is authenticated and tenant-bound through existing service auth.
5. The plugin path reuses the existing multipart proxy and does not require a new WordPress install, admin UI, or public media URL.
6. Real Florence inference is either benchmarked successfully on OCI A1 or explicitly left disabled with a recorded reason.

## Not Doing

- No admin UI, React Workbench integration, or visitor-facing page.
- No final alt-text prose generation.
- No GPU worker, Hugging Face Space, public API fallback, or paid inference provider dependency.
- No WordPress UI for customer OpenAI/Claude/Grok/Gemini/provider keys in the first pass.
- No new WordPress deployment.
- No multi-image batch workflow beyond a deliberately tiny seeded smoke.
- No new biometric recognition claims beyond the existing recognition system.
- No segmentation masks in the first pass; mask support stays behind the `segmentation_masks` placeholder.

## Assumptions

- The current WordPress installation already has at least one usable seeded attachment.
- The plugin has service URL, tenant id, and API key configured through the existing settings/constants path.
- A synchronous single-image route is acceptable for the seeded/cached proof. If uncached real-model mode breaches the existing mutation timeout, async job work becomes a prerequisite for real-model demo mode.
- The backend can safely add a new adapter boundary without changing the existing recognition scan job schema.
- The first useful product proof is "structured facts available for context-aware alt text later," not "best open-model caption quality today."

## Verification Plan

- Backend unit/API tests:
  - request validation rejects missing image, multiple images, invalid MIME, and unauthenticated requests;
  - seeded adapter returns the expected `visual_facts` schema;
  - adapter errors become structured 4xx/5xx responses;
  - cache hit returns the same facts with `cached=true`.
- WordPress PHPUnit tests:
  - REST route is registered and permissioned;
  - attachment bytes are serialized as multipart and sent to the backend description route;
  - unreadable files and oversized bodies fail locally;
  - backend JSON passes through unchanged enough for the smoke script.
- Headless smoke:
  - run against the current install with `WP_PATH`;
  - print attachment id, backend route, model id/runtime, cache status, timing, and the `visual_facts` object;
  - rerun once to demonstrate cache behavior.

## Next Step

Draft the VLM-1 task plan from this scope, starting with S1 and S3 so the backend contract and WordPress headless roundtrip land before investing in real-model optimization.
