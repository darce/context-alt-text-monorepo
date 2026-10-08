# EmbeddingGemma 2 repo-fit assessment (Qwen-grounded revision)

**Assessment date:** 2026-10-07; **Status:** Documentation assessment only; no model or deployment was changed.

## Decision

Do not add EmbeddingGemma 2 to the current caption-generation path yet. The operating baseline for
this assessment is the user-confirmed Qwen migration. The checked-in demo preflight example also
selects `gpu_qwen30b`, but that example is configuration evidence, not a live deployment probe. No
live runtime inspection or performance benchmark was performed.

EmbeddingGemma 2 is a multimodal embedding model: it maps content to vectors for retrieval or
similarity. It does not generate an alt-text caption. Keep Qwen as the generator. The three
plausible scopes, in priority order, are:

1. **Context selection experiment:** use image-to-text similarity to choose among already-approved
   context entries when real packs are long or noisy. First compare a deterministic short renderer;
   current packs are already bounded, so a retrieval model may be unnecessary for ordinary requests.
2. **Caption-consensus experiment:** consider semantic similarity only as a fallback in the existing
   four-view Qwen caption selector. This adds an encoder and selection behavior to a small
   deterministic function and cannot verify visual truth.
3. **Future semantic media search:** image/text search or related-asset discovery is the cleanest
   greenfield fit for a shared multimodal vector space. No current media-search baseline was
   inspected, so relative accuracy or speed claims are unavailable.

This revision supersedes the earlier Florence-default framing. The user-confirmed operating baseline
is Qwen; Florence remains in unset-environment fallbacks and stale descriptions/tests, which are
configuration drift rather than evidence of the current baseline. Earlier unsupported numerical
forecast probabilities are withdrawn.

## Repository evidence

The table records what the checked-out sources establish. It does not establish which process is
live in production.

| Source anchor | Direct finding | Scope of evidence |
| --- | --- | --- |
| [`infra/oci/demo/.env.example:83`](../../../infra/oci/demo/.env.example#L83) | The demo preflight sample sets `ACX_DESCRIPTION_ADAPTER=gpu_qwen30b`. | A checked-in operator sample; not live deployment state. |
| [`profiles.py:105`](../../../apps/prototype-description-service/scene/config/profiles.py#L105) | The raw and ensemble GPU profiles identify Qwen3-VL-30B-A3B-Instruct, the pinned `unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF` revision `0af19e7479857aa7f3246466a4ad16c7e7299639`, and Q4_K_M. | The source profile and artifact pin. |
| [`deps.py:187`](../../../apps/prototype-description-service/scene/interface_adapters/http/deps.py#L187), [`deps.py:262`](../../../apps/prototype-description-service/scene/interface_adapters/http/deps.py#L262) | The inline GPU resolver returns the raw adapter. The async GPU-final resolver wraps it only for the ensemble profile. | Sync and async routing are intentionally different. |
| [`ensemble_decode.py:61`](../../../apps/prototype-description-service/scene/infrastructure/vlm/ensemble_decode.py#L61), [`ensemble_decode.py:185`](../../../apps/prototype-description-service/scene/infrastructure/vlm/ensemble_decode.py#L185) | The default ensemble uses four views; it runs sequential GPU passes and selects one per-view caption verbatim. | The ensemble is optional and async-tier scoped; it is not the sync baseline. |
| [`gpu_remote_adapter.py:368`](../../../apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py#L368), [`gpu_remote_adapter.py:499`](../../../apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py#L499), [`gpu_remote_adapter.py:581`](../../../apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py#L581) | `GpuRemoteDescriptionAdapter` calls an in-tenancy GPU endpoint over the OpenAI-compatible chat-completions route. When enabled and within budget, each adapter pass can issue a separate phrase-box grounding follow-up. | Qwen generation and optional grounding are remote requests, not local Florence inference. |
| [`gpu_remote_adapter.py:225`](../../../apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py#L225), [`gpu_remote_adapter.py:242`](../../../apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py#L242) | `_render_context` includes each nonempty context key; `_user_text` puts it in an editorial-metadata fence. `context_applied` means context was injected, not that Qwen obeyed it. | No relevance ranking or token-budget selection happens in this renderer. |
| [`class-describe-media-service.php:1004`](../../../apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php#L1004), [`class-describe-media-service.php:1068`](../../../apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php#L1068), [`class-describe-media-service.php:1110`](../../../apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php#L1110), [`requests.py:84`](../../../apps/prototype-description-service/scene/interface_adapters/http/schemas/requests.py#L84) | WordPress applies tenant category policy, bounds attachment and public-parent fields, and builds identity context under its own policy. An absent category option permits supported categories; malformed policy fails closed to attachment only. The backend accepts typed attachment, post, taxonomy, product, and identity fields; taxonomy terms are capped at 20. | The candidate input is already privacy-filtered and structurally bounded. The public parent method includes only published parents. |
| [`reconcile.py:118`](../../../apps/prototype-description-service/scene/application/fusion/reconcile.py#L118) | Identity and brand attachment, conflict handling, and naming-policy checks are handled by the existing reconciliation stage. | Similarity scores must not replace identity, brand, or naming-policy decisions. |
| [`visual_facts_service.py:259`](../../../apps/prototype-description-service/scene/application/visual_facts_service.py#L259), [`ensemble_decode.py:220`](../../../apps/prototype-description-service/scene/infrastructure/vlm/ensemble_decode.py#L220), [`ensemble_decode.py:228`](../../../apps/prototype-description-service/scene/infrastructure/vlm/ensemble_decode.py#L228) | Cache lookup keys include tenant, image, adapter, model ID, model version, prompt/task version, and context hash. `EnsembleDescriptionAdapter` delegates its model and prompt/task identity to the wrapped adapter. | Any selected context must flow through this existing cache path. A later ranking-policy or caption-selector change must also version the cache namespace or prompt/policy identity so identical request inputs cannot reuse drafts selected under older behavior. |
| [`describe_run.py:298`](../../../apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py#L298), [`describe_run.py:358`](../../../apps/prototype-description-service/scene/interface_adapters/http/routers/describe_run.py#L358), [`scene-describe-run.schema.json:5`](../../../packages/shared-contracts/schemas/scene-describe-run.schema.json#L5) | The bulk `/describe/run` worker calls `VisualFactsService` with `context=None`; its multipart contract lists tenant, media IDs, recognition flag, idempotency key, and image parts, with no context/context-pack field. Identity inputs are separately supplied for naming. | A context selector can benefit existing contextual describe routes only. Bulk support needs a separately scoped request-contract change before threading context into the worker. |

### Configuration drift to keep visible

[`DescriptionSettings`](../../../apps/prototype-description-service/scene/config/settings.py#L73)
and [`_resolve_description_profile`](../../../apps/prototype-description-service/api/main.py#L285)
still fall back to `florence_small` when `ACX_DESCRIPTION_ADAPTER` is unset. The settings tests
assert that legacy behavior in
[`test_settings.py`](../../../apps/prototype-description-service/scene/tests/test_settings.py#L12)
and
[`test_description_profiles.py`](../../../apps/prototype-description-service/scene/tests/test_description_profiles.py#L133).
Meanwhile, the [`get_description_adapter`
docstring](../../../apps/prototype-description-service/scene/interface_adapters/http/deps.py#L187)
calls `seeded` the default. These are mismatched fallback and documentation signals; none overrides
the user-confirmed Qwen baseline or the explicit checked-in Qwen sample. Updating those production
defaults or tests is outside this documentation-only scope.

## Model and integration fit

The current [EmbeddingGemma 2 model card](https://huggingface.co/google/embeddinggemma-2) describes
an Apache-2.0 multimodal embedding model with a shared 768-dimensional vector space and an
8,192-token context. It has 740M parameters across modalities; selective text-plus-image loading is
440M, and text-only loading is 270M. The card documents 512-, 256-, and 128-dimensional truncation;
truncated vectors must be renormalized. It recommends BF16 or FP32, not FP16. The [Google developer
guide](https://developers.googleblog.com/en/embeddinggemma-2-the-developer-guide/) describes its
retrieval focus. These are model-card capabilities, not measurements on this repository or its Qwen
workload.

The repository’s Qwen adapter is a remote GGUF endpoint. The service’s [`[vlm]` dependency
group](../../../apps/prototype-description-service/pyproject.toml#L121) is for local Florence
inference, including Transformers and Torch. Adding EmbeddingGemma 2 would therefore need its own
packaging, loading, resource, and service/worker decision; it is not a drop-in upgrade of Florence
or a change to the existing Qwen endpoint. No weights were downloaded and no runtime dependency was
edited for this assessment.

## Candidate scopes and guardrails

### 1. Select approved context for Qwen

If real requests show large or distracting context packs, compare the current renderer with a cheap
deterministic renderer first. A later EmbeddingGemma experiment could embed the image and candidate
text entries in the same model space
([EMB-01](https://github.com/darce/heuristics-canon/tree/v0.25.6)), then rank only entries that
have already passed WordPress privacy/category filtering. The bounded per-request candidate set can
use an exact cosine scan; it does not require a vector database or approximate-nearest-neighbor
index. A tenant-scoped metadata-embedding cache may help if measurements justify it. Keep identity
facts, naming policy, and review constraints in their protected path; a relevance score must not
suppress or authorize them. Preserve the original source context and provenance for every included
field for auditability.
Pin the EmbeddingGemma model revision, preprocessing, output dimension, normalization, and ranking
policy in experiment provenance. Any ranking-policy change must version the cache namespace or
prompt/policy identity, even when request inputs are unchanged, so old drafts cannot be reused under
new selection behavior. On encoder, lookup, or score failure, fall back to the original bounded
approved pack. Pass the chosen context through normal normalization, cache hashing, and describe
execution. This is a future-scope requirement, not a request to implement a new cache now.

The current pack’s bounded fields and category filtering may already be sufficient, especially for
short clean packs. Measure the distribution and token cost of actual eligible packs before adding
model serving. Do not extend this proposal to `/describe/run` without a separate contract change.

### 2. Semantic fallback for caption consensus

[`_select_caption`](../../../apps/prototype-description-service/scene/infrastructure/vlm/ensemble_decode.py#L284)
already uses exact-string majority, then word-set Jaccard consensus when captions are unique; ties
go to the earliest view, which is the full-image pass. It always returns one candidate caption
verbatim. An embedding-based fallback might group paraphrases better, but adds model loading/caching
and selection complexity to this inexpensive function. For text-paraphrase consensus, compare the
text-only 270M loading option with the existing Jaccard selector; consider text-plus-vision 440M
only if caption reranking must use the image. Both model options add overhead against the cheap
existing Jaccard calculation. If evaluated, preserve exact majority, full-image tie behavior, and
verbatim candidate selection, and version the selector identity used by the cache. Similarity
between captions is not evidence that a caption is true, that a name is visible, or that identity
is correct. Do not assume it permits fewer Qwen views; each view remains a Qwen generation pass and
may also incur a grounding follow-up.

### 3. Future semantic media search

Cross-modal image/text retrieval is a direct match for EmbeddingGemma 2’s shared space. It is the
most natural greenfield use if product requirements call for searching or finding related media. No
current media-search implementation or evaluation baseline was inspected, so this assessment makes
no relative accuracy, speed, or adoption forecast for that product area.

## Evaluation and forecast contract

No performance benchmark has been run. Treat the following as directional hypotheses and future
acceptance criteria, not predicted outcomes:

| Hypothesis | Confidence in direction | What would resolve it |
| --- | --- | --- |
| Context selection can improve relevance for long/noisy approved packs; clean short packs may be unchanged or harmed by unnecessary filtering. | Medium for the mechanism; low for caption-quality impact. | Compare deterministic shortening, embedding selection, and full-pack Qwen outputs on representative paired cases. |
| End-to-end latency improves only when Qwen prefill saved by shorter context exceeds embedding, lookup, and contention cost. Image handling, Qwen generation, grounding, and four-view count remain. | Low without measurements. | Measure the entire request from cache lookup through response, including the encoder and optional grounding. |
| Semantic caption comparison may reduce paraphrase disagreement but cannot itself improve visual grounding or identity truth. | Low. | Blindly score the same fixed Qwen candidate captions with current and semantic selectors; retain image-level correctness checks. |
| Shared-space image/text retrieval is a direct fit for future semantic media search. | High for model/task fit; no performance confidence assigned. | Define the searchable corpus and relevance judgments, then evaluate retrieval slices before product forecasting. |

Use separate fixed baselines for raw Qwen and the optional four-view async Qwen ensemble. Include
warm and cold runs, cache hits and misses, paired context-injected and no-context cases, and
clean/noisy packs. Slice results by privacy/category policy, identity conflicts, OCR-heavy images,
and taxonomy conflicts. Score retrieval precision at k and whether the right approved context was
selected separately from blind caption acceptability, unsupported-detail rate, and unsupported-name
rate. A retrieval win is not a generation win.

Report endpoint p50 and p95, not averages or encoder-only timing. For later scoping, use these as
acceptance targets rather than predictions
([FORE-02](https://github.com/darce/heuristics-canon/tree/v0.25.6)): allow at most 5% p95 regression
when a measured quality improvement justifies it; claim a speed
improvement only at 10% or better p95 reduction; optionally require a 5 percentage-point
caption-acceptability gain. Predeclare sample sizes and report uncertainty intervals. Do not assign
numeric accuracy or speed probabilities before this evaluation.

## Evidence rules and provenance

This assessment follows the pinned, read-only [heuristics-canon
v0.25.6](https://github.com/darce/heuristics-canon/tree/v0.25.6) by stable ID and attributed
summary; no canon text was copied or changed. The coordinator verified the local checkout at
`/Users/daniel/Development/heuristics-canon-current`, resolved its release to `v0.25.6`, and
revalidated manifest hashes for the consulted `ml-systems`, `engineering`, and `epistemics` rows.
That canon checkout was not present in this lane VM, so this document uses the coordinator-verified
row summaries and links the pinned release rather than claiming a local read or copying canon text.
The relevant rows are:

| Rule | Canon row | Source attribution |
| --- | --- | --- |
| [`EMB-01`](https://github.com/darce/heuristics-canon/tree/v0.25.6) | One embedding space per comparison | *Foundations of Vector Retrieval*, ch. 1 |
| [`EVAL-01`](https://github.com/darce/heuristics-canon/tree/v0.25.6) | Require offline baselines | *Designing Machine Learning Systems* |
| [`EVAL-04`](https://github.com/darce/heuristics-canon/tree/v0.25.6) | Slice-based gate | *Designing Machine Learning Systems* |
| [`RAG-01`](https://github.com/darce/heuristics-canon/tree/v0.25.6) | Evaluate retrieval and generation separately | *AI Engineering* |
| [`PERF-01`](https://github.com/darce/heuristics-canon/tree/v0.25.6) | Percentiles, not averages | *Latency: Reduce Delay in Software Systems*, ch. 2; *Designing Data-Intensive Applications*, ch. 1 |
| [`FORE-02`](https://github.com/darce/heuristics-canon/tree/v0.25.6) | Resolvable forecast contract | *Superforecasting*, ch. 3 |

The evaluation applies [`EVAL-01`](https://github.com/darce/heuristics-canon/tree/v0.25.6) and
[`EVAL-04`](https://github.com/darce/heuristics-canon/tree/v0.25.6): compare against offline
baselines and retain predeclared slices. It applies
[`RAG-01`](https://github.com/darce/heuristics-canon/tree/v0.25.6) by scoring retrieval separately
from generation, and [`PERF-01`](https://github.com/darce/heuristics-canon/tree/v0.25.6) by
reporting endpoint percentiles. The claim trail applies canon Principle 9 (traceable claim inputs)
and Principle 13 (evidence before commitment). Earlier history and semantic retrieval snippets are
historical/advisory evidence only; they do not establish current runtime state. The prior
Florence-default conclusion is explicitly superseded by the user correction and current checked-in
source evidence above.

**Limits:** this is repo-fit analysis for future scoping, not a build or rollout plan. It records
source configuration and model-card capabilities, not live deployment state or benchmark results. No
production code, tests, deployment, model weights, or canon files were changed.
