# Vector-Store & VLM Upgrade Evaluation — Clustering, FIR, VLM, GPU Lanes, Embedding Storage

> **Metadata**
>
> - **Date**: 2026-07-18
> - **Task**: `VECVLM-1` (branch `feature/vecvlm-1`)
> - **Type**: Feasibility / decision-input assessment. Not an epic or task plan.
> - **Question**: Can the clustering, FIR face pipeline, VLM pipeline, GPU burst tier, or production embedding storage benefit from (a) turbovec / qdrant / faiss; (b) benchmarking Qwen3.6 / Qwen3.5 / MTP quantizations and client fine-tunes; (c) the larger GLM-5.2 / Inkling / DeepSeek-V4 tier? What hardware would the larger models need, and is the benefit worth it?
> - **Method**: 3 parallel web-research subagents (specs verified against Unsloth docs + HuggingFace cards + GitHub/registries, 2026-07-18) + local codebase/infra inventory.
> - **Companion docs**: [commercial-face-pipeline-replacement-assessment-2026-07-15.md](./commercial-face-pipeline-replacement-assessment-2026-07-15.md) · [segmentation-vlm-pipeline-feasibility-2026-06-15.md](./segmentation-vlm-pipeline-feasibility-2026-06-15.md) · [GPU-BURST-PROVISIONING.md](../../../infra/oci/GPU-BURST-PROVISIONING.md)

---

## Verdict (TL;DR)

Three questions, three answers:

1. **Vector stores (turbovec / qdrant / faiss) — no adoption.** The embedding store is not an ANN-at-scale problem. It is **incremental online clustering of hundreds-to-low-thousands of 128-dim unit vectors per tenant (≤1000 clusters), done transactionally beside RLS/jobs in the same Postgres**. At that size exact cosine is sub-millisecond; pgvector `ivfflat` is already sufficient and arguably over-indexed. Every external option adds a second store (or a non-transactional index file) to keep consistent with Postgres for **zero measurable latency gain**. Revisit only if a single tenant credibly crosses **~100k–1M** vectors. The one narrow near-term use is **`faiss.Kmeans` as an in-process algorithm helper** if hand-rolled clustering is ever outgrown — not as storage.

2. **VLM quantizations (Qwen3.6 / Qwen3.5 / MTP) — yes, benchmark, into the existing harness.** Qwen3.6-27B (dense VLM) and Qwen3.6/3.5-**35B-A3B** (MoE VLM) are real image-in→text-out models that fit the tiers we already run. They are legitimate upgrade candidates over the current `Qwen3-VL-30B-A3B @ Q4_K_M`, and the repo **already has the bake-off harness** (`scripts/eval_harness/bakeoff.py`, `infra/oci/incidents/a10-multimodel-bakeoff.sh`) to score them. Benchmark **caption quality on ACX images + s/img + cost/image**, not spec sheets — because **no vendor vision benchmarks exist** for these families. **MTP is worth a throughput leg** (llama.cpp-native, GGUF, 1.4–2.2× claimed, no accuracy loss) but is memory-bandwidth-bound, so measure it on the A1 CPU, not just the A10. Client fine-tunes are viable (Qwen3.5 VLM LoRA) but **out of scope for general use** — pull them in per paying client, bf16 LoRA only (never QLoRA-4bit on Qwen3.5).

3. **Larger models (GLM-5.2 / Inkling / DeepSeek-V4) — no.** None fit a single A10 at any quant (smallest viable 90–295 GB). **GLM-5.2 is text-only** and **DeepSeek-V4 has no reliable API image path** — both disqualified for alt-text outright. **Inkling** is the only true VLM but is 975B/~280 GB-smallest-quant, needs a multi-GPU tier (~8×H100, tens of $/hr), i.e. **~10–30× the current VLM footprint for a short caption**. Stay on the ~30B-class VLM on the A10.

**One-line strategy:** keep Postgres for vectors; spend the effort on a **bounded Qwen3.6 + MTP bake-off leg** inside the existing harness; ignore the 700B–1.6T tier.

---

## Hardware envelope (the binding constraint)

Every recommendation is gated by two shapes. Sources: `infra/oci/main.tf`, `docs/runbooks/oci-instance-state-and-cost.md`, `infra/oci/GPU-BURST-PROVISIONING.md`.

| Host | Shape | Compute | Memory | Cost | Role |
| --- | --- | --- | --- | --- | --- |
| `acx-backend` | `VM.Standard.A1.Flex` (Always-Free) | 4 OCPU **ARM/Ampere aarch64**, no GPU | 24 GB (≈5–8 GB free headroom after PG + face pipeline + worker) | $0 | Prod recognition + inline CPU path |
| `acx-gpu-burst` | `VM.GPU.A10.1` | 1× NVIDIA A10 **24 GB VRAM**, 30 OCPU / 240 GB host RAM | 24 GB VRAM / 240 GB system | ~$2.00/GPU-hr **while running**; boot vol ~$15–20/mo standing; **STOPPED at rest** | Scale-to-zero VLM burst tier |

Headroom shapes exist (`VM.GPU.A100.1` 40 GB, `VM.GPU.A10.2` 48 GB, and A100/H100/B200 tiers) but each needs its **own** OCI service-limit increase (console-only, 1–3 business days, capacity-gated). This is why "just rent a bigger GPU" is not a config flip.

**Implication:** the deployable VLM budget is **24 GB VRAM (A10)** or **24 GB shared CPU RAM (A1, slow)**. Anything whose smallest quant exceeds that is a procurement project, not a profile flip.

---

## Part A — Vector stores for clustering & embedding storage

### A.1 What the workload actually is

- **Storage/index**: 128-dim unit-normalized embeddings in Postgres via `pgvector`, `ivfflat` + `vector_cosine_ops` (`db/models/identity.py:98-99`, `001_identity_schema.py:1093,1198,1778`). Dimension is single-rooted through `PGVECTOR_DIM` (`db/settings.py`).
- **Access pattern**: **incremental online clustering** — representatives loaded per cluster (`RepresentativeCache`), in-memory cosine comparison, assign / merge / split (`recognition/application/tasks/clustering.py`, `.../suggestions/label_inference.py`). Batch surfacing bounded to `limit=1000` clusters, `chunk_target=1000` identities.
- **Scale**: hundreds-to-low-thousands of vectors per tenant, **≤1000 clusters/tenant**. Not high-QPS ANN over millions.
- **Coupling**: assign/merge/split are **transactional beside RLS, tenants, jobs** in the same Postgres. ACID + row-level security + joins in one store is a feature, not an accident.

At this size an **exact** cosine scan over a tenant's vectors is well under a millisecond. ANN indexes (HNSW/IVF/PQ) exist to avoid O(n) at *millions* of rows; at our n they add approximation error and index-maintenance cost for no latency benefit. `ivfflat` at ~1000 vectors/list is actually mis-tuned relative to a plain scan.

### A.2 Per-project verdict

| Project | License | In-proc / server | aarch64 | Index model | Verdict | Threshold to reconsider |
| --- | --- | --- | --- | --- | --- | --- |
| **pgvector** (incumbent) | permissive | in Postgres | ✅ | ivfflat / HNSW | **Keep — sufficient** | — (consider ivfflat→HNSW, or drop the index for exact scan, before anything external) |
| **turbovec** | MIT | in-process (Rust+PyO3) | ✅ NEON first-class | **flat quantized scan only** (2/4-bit; no HNSW/IVF), v0.1.x experimental | **No** | Never for transactional clustering; its niche is RAM-bound flat scan over **many millions** of high-dim (768–3072d) vectors. We have 24 GB and a few thousand 128-d vectors — nothing to compress. |
| **faiss** (CPU) | MIT | in-process | ✅ manylinux aarch64 wheels | broadest: Flat/IVF/HNSW/PQ + **`faiss.Kmeans`** | **No for storage; maybe `Kmeans` helper** | Only if hand-rolled clustering is outgrown and we want a mature in-process k-means; still adds a non-transactional index beside PG. |
| **qdrant** | Apache-2.0 | **separate server** | ✅ | HNSW + scalar/PQ/binary quant; GPU optional (index-only) | **No — operational overkill** | ~tens of millions of vectors and/or sustained high ANN QPS, or wanting vector search as its own scalable service decoupled from PG. |

**Benchmark reality check** (third-party blogs, indicative not peer-reviewed): at 100k vectors both pgvector-HNSW and Qdrant-HNSW are sub-5 ms; the dedicated engines only pull decisively ahead at **tens of millions** of vectors. We sit 3–4 orders of magnitude below that.

### A.3 Recommendation (Part A)

- **Do nothing to the store now.** pgvector covers it.
- **Cheap, optional pgvector tune** if a tenant grows: switch `ivfflat`→`hnsw` (higher recall, no list-tuning below 1M), or drop the index entirely and let PG do exact cosine until ~100k vectors/tenant.
- **File `faiss.Kmeans`** as the fallback *algorithm* (not store) if clustering quality/purity ever needs a library instead of the current bespoke path — consistent with the FIR assessment's `chinese-whispers` note as a clustering alternative at 128-D.
- **No benchmark spend** on turbovec/qdrant/faiss-as-store at current scale; the migration + dual-write consistency cost dominates any negligible latency delta.

---

## Part B — VLM quantization benchmarking (Qwen3.6 / Qwen3.5 / MTP / fine-tune)

### B.1 Current VLM state

- Production inline CPU path: **Florence-2-base-ft** (~14 s/img on A1), `florence_large` (~39 s, async-only stub), `gpu_phi4` (~900 s on CPU, GPU-only stub) — `scene/config/profiles.py`.
- GPU burst tier winner: **`Qwen3-VL-30B-A3B-Instruct @ Q4_K_M`** GGUF via llama.cpp on the A10 (`GPU_QWEN30B` profile; `a10-interleave-646.sh`).
- The repo **already has** a candidate-swap bake-off harness (`scripts/eval_harness/bakeoff.py` + `a10-multimodel-bakeoff.sh`) whose shortlist is Qwen3-VL-8B, MiniCPM-V-4.5, gemma-4-12b, gemma-3-27b. Adding the Qwen3.x candidates is an **incremental to work already built**, not a new subsystem.

### B.2 Fit table (verified GGUF sizes; add mmproj ~0.7–0.9 GB + KV-cache)

All Qwen3.6/3.5 variants below are **confirmed VLMs** (ship `mmproj-*.gguf`, HF `image-text-to-text` tag).

| Model / variant | Smallest viable quant | Weights+mmproj | A10 24 GB VRAM | A1 24 GB CPU RAM (shared, slow) |
| --- | --- | --- | --- | --- |
| Qwen3.5-4B | Q4_K_M | ~3.4 GB | ✅ huge headroom | ✅ **fastest CPU pick** |
| Qwen3.5-9B | Q4_K_M / Q6_K_XL | ~6.6 / ~9.7 GB | ✅ | ✅ usable, moderate |
| Qwen3.6-35B-A3B (MoE, 3B active) | UD-Q2/IQ2_M | ~12–14 GB | ✅ | ✅ **standout for CPU** — 3B active keeps decode tractable |
| Qwen3.6-27B (dense) | UD-Q4_K_XL | ~18.5 GB | ✅ (modest context) | ⚠️ fits RAM but dense 27B on 4 OCPU = very slow |
| Qwen3.6-35B-A3B (MoE) | UD-Q4 (doc 23 GB total) | ~23 GB | ⚠️ tight | ❌ too big for 24 GB shared |

**Reading of the table:**
- **A10 upgrade candidate**: **Qwen3.6-27B @ UD-Q4 (~18.5 GB)** is the strongest single-image caption quality option that fits 24 GB with context room — a like-for-like challenger to the current 30B-A3B control.
- **A1 CPU quality-jump candidate** (over Florence-2-base, if the inline path wants better captions): a **Qwen3.5 VLM** — 4B for throughput, 9B Q4/Q6 for quality, or the **35B-A3B MoE at Q2/Q3** where dense 27B won't run. Latency must be measured against the 20 s inline / 30 s adapter budgets that killed `florence_large`.

### B.3 Should the quantizations be benchmarked? — Yes, but measure the right thing

**Yes.** But the open question is **not** "what are the specs" — it is **caption quality on ACX WordPress media**, because **neither family publishes vision benchmarks** (DocVQA/ChartQA/MMMU/captioning). Quant-degradation data that does exist is text-only (KLD/PPL: Q4 near-lossless vs Q8, Q3 starts degrading) and cannot be assumed to transfer to vision.

Run it through the **existing** harness, as a bounded leg on a caught A10:

- **Candidates**: `Qwen3.6-27B @ UD-Q4_K_XL` and `Qwen3.6-35B-A3B @ UD-Q4/Q3`, against the current `Qwen3-VL-30B-A3B @ Q4_K_M` **control** (control run-record already exists). The **27B candidate is folded into `a10-multimodel-bakeoff.sh`** (exact `Qwen3.6-27B-UD-Q4_K_XL.gguf` + `mmproj-F16.gguf` URLs wired, 2026-07-18). **Caveat**: Qwen3.6 (qwen3_5 arch) needs a **newer llama.cpp build than the box's b6887** for vision — verify before the run.
- **Metrics** (per house rule — every report carries total cost + **cost/image**; A10 ~$2/GPU-hr): caption quality vs the golden manifest (v3 two-pass interleave, names bound to face-box order), **s/img**, **cost/1k-img**, p95 latency.
- **Quant sweep discipline**: if dropping below Q4 for any VLM, verify caption quality holds — vision-quality-vs-quant is undocumented, so it must be observed, not assumed.

### B.4 MTP (Multi-Token Prediction) — worth a throughput leg

- Merged in **llama.cpp**, **GGUF-native** (prebuilt `*-MTP-GGUF` repos), ~**1.4–2.2× faster**, **no accuracy change** (speculative-decode: only verified tokens kept), ~1–2 GB extra RAM/VRAM.
- **Caveat that changes where to test it**: gains are **memory-bandwidth-bound**; the doc warns low-bandwidth hardware sees smaller speedups. The A1 CPU is exactly that class — so **benchmark MTP on the A1**, not just the A10, before crediting the headline number. On the A10 expect closer to published.
- Cheap to add: it is a decoding flag + a swapped GGUF on candidates already in the bake-off.

### B.5 Client fine-tuning — viable, but out of scope for general use

- Qwen3.5 supports **VLM LoRA** fine-tuning (select vision / language / attention layers). 4B/9B fit LoRA within 24 GB (9B ~22 GB bf16 — tight on A10). Export-to-GGUF path exists (Ollama/llama.cpp).
- **Hard rule from the vendor**: **do NOT QLoRA-4bit train Qwen3.5** (esp. MoE) — bf16 LoRA only.
- **Disposition**: pull in **per paying client requirement**, as its own scoped task with the client's data-governance constraints; not a general-use track. A per-client GGUF adapter is a deployable artifact behind the existing profile/provenance machinery.

---

## Part C — Larger models (GLM-5.2 / Inkling / DeepSeek-V4)

### C.1 Fit & disposition

| Model | Params (total/active) | VLM (image input)? | Smallest quant → memory | Min hardware to serve | Fits A10? |
| --- | --- | --- | --- | --- | --- |
| **GLM-5.2** | ~744B / ~40B MoE | **No — text-only** | 2-bit ~245 GB | multi-GPU (≈8×H100) or 256 GB-RAM MoE offload | ❌ any quant |
| **Inkling** (Apache-2.0) | 975B / 41B MoE | **Yes** (text+image+audio) | 1-bit ~280–295 GB | multi-GPU; no single OCI GPU holds it | ❌ any quant |
| **DeepSeek-V4** | Pro 1.6T/49B · Flash 284B/13B | **Contested** — HF card text-only; **no API image path** | Flash 1-bit ~92 GB (Pro ~400 GB+) | A100 80 GB (Flash, tight) → multi-GPU (Pro) | ❌ any quant |

### C.2 Hardware needed & cost reality

- Smallest viable quant of each is **90–295 GB** — beyond a single A10 (24 GB), beyond a single A100 80 GB for most, beyond even a single B200 (192 GB) for GLM-5.2/Inkling. Serviceable throughput needs a **multi-GPU tier** (e.g. 8×H100 ≈ 640 GB, roughly ~$10/GPU-hr → **~$80/hr**), each requiring a fresh OCI limit increase.
- OCI's A10 host ships ~240 GB system RAM, so GLM-5.2-2bit or DeepSeek-Flash-low-bit could *technically* load via MoE CPU-offload — at **single-digit tok/s**, which is not a serviceable alt-text backend.

### C.3 Verdict (Part C)

- **GLM-5.2**: text-only → cannot caption images. **Reject.**
- **DeepSeek-V4**: no reliable programmatic image input today. **Reject** for alt-text (revisit only if an image API path is confirmed, and even then it's the wrong size).
- **Inkling**: the only genuine VLM, MMMU-Pro 73.3 — but at ~10–30× the current VLM's infra footprint and a multi-$10s/hr tier, a modest caption-quality gain over a 30B-class VLM **does not justify** the jump for short alt-text strings. **Reject now; note as the frontier watch item** if a future feature needs frontier multimodal reasoning (not captioning) and the economics change.

Stay on the ~30B-class VLM on the A10. The right upgrade axis is **within** that tier (Qwen3.6), not above it.

---

## Part D — Qwen3.6 architecture & unquantized weights (does it change pipeline design?)

### D.1 Is there an unquantized Qwen3.6, and is it worth benchmarking?

Yes — `unsloth/Qwen3.6-27B-GGUF` ships **BF16 (53.8 GB)** and **Q8_0 (28.6 GB)**; base weights at `Qwen/Qwen3.6-27B`. **Neither fits the A10's 24 GB VRAM.** Only ≤~20 GB quants (UD-Q4 ~18.5 GB) are deployable on current hardware.

**So the unquantized version is not benchmarkable on the A10 — and it is not the point.** Its only value is as a **quality-ceiling reference** to answer the one real open risk (undocumented **vision-quant degradation** — Part B.3, and [caption-context-enrichment §13](./caption-context-enrichment-assessment-2026-07-05.md)): *how much caption quality does Q4 lose vs full precision?* That reference needs an **A100 40 GB** (holds Q8 28.6 GB + mmproj + KV) or A100 80 GB (BF16) — a headroom shape requiring its own OCI limit increase.

**Recommendation**: run the **Q4 bake-off on the A10 first** (already folded in). Escalate to a **one-off Q8 reference leg on a rented A100 only if** Q4 underperforms the 30B-A3B control and you need to know whether the culprit is the *quant* or the *model*. Do **not** stand up an A100 tier for a standing unquantized deployment — Q4 is the deployable ceiling, and the eval harness (caption-context-enrichment §6) is the instrument.

### D.2 Does the Qwen3.6 architecture influence pipeline design? — No redesign

Qwen3.6-27B is a **dense hybrid** — Gated DeltaNet (linear attention) interleaved with periodic Gated Attention (`16 × (3×[DeltaNet→FFN] → 1×[GatedAttn→FFN])`, 64 layers), 262K native context (→1M YaRN). Architecture implications for *our* pipelines:

- **VLM tier**: it is a **drop-in candidate behind the existing `DescriptionAdapter` port** (`scene/`), not an architecture change. The ports-and-adapters seam ([caption-context-enrichment §7](./caption-context-enrichment-assessment-2026-07-05.md)) makes it a one-adapter swap. No change to the visual-facts pass, identity merge, or fusion contract.
- **Long context (262K)** relaxes the pressure that motivated the Stage-2 *relevance filter* / CIAN summarize-before-inject — you *could* inject a full post body + large roster without truncation. **But the disciplined-injection contract still wins**: dumping raw context is a documented quality regression (CIAN; MosAIC free-form enrichment *dropped* correctness). So long context is a mild convenience, not a redesign lever.
- **Linear-attention (Gated DeltaNet)** mainly buys cheaper long-context decode → a throughput edge, which is measured in the **bake-off + MTP leg** (Part B), not an architectural input to the pipeline.

**Verdict**: the architecture is interesting but pipeline-neutral. It is measured as a model candidate; it does not reshape clustering, FIR, the describe pipeline, or storage.

## Part E — GraphRAG & agentic architecture (NeoConverse / Graph-R1) for `prototype-description-service`

Inputs: [NeoConverse GraphRAG](https://neo4j.com/blog/developer/graphrag-and-agentic-architecture-with-neoconverse/) (single-agent LLM orchestrating Neo4j graph traversal / vector / Text2Cypher tools, grounding answers on graph nodes to cut hallucination) and [Graph-R1 (2507.21892)](https://arxiv.org/html/2507.21892v2) (agentic GraphRAG trained end-to-end with RL — knowledge-hypergraph + multi-turn *think-retrieve-rethink-generate* — for multi-hop **text QA**).

### E.1 The core insight is already implemented here — without a graph DB

The value both projects sell is **node-anchored grounding: attach generated text to specific, source-tagged graph facts so the model cannot free-associate** (NeoConverse's WeWork-vs-Palantir hallucination example). **The describe service already does exactly this, and it built it deliberately** (see [caption-context-enrichment](./caption-context-enrichment-assessment-2026-07-05.md) + [anti-hallucination-caption-generation-scope](../../scopes/anti-hallucination-caption-generation-scope.md)):

- **Pre-resolved, node-anchored context**: `ContextPack` + roster-bound `IdentityContextItem(name, identity_id, cluster_id, source)`; identities join to face-boxes (`scene/application/identity_merge/join.py`), not retrieved by fuzzy similarity.
- **Constrain-then-map naming** (Eluvio, deployed): no stage *generates* a name; detectors emit only roster-checkable IDs, names are mapped deterministically — the strongest possible anchoring, stronger than a Text2Cypher lookup.
- **Source-precedence fact arbitration** (RE-VLM): every fact carries its source; identity facts only from the roster, appearance only from the VLM. **Merge-only fusion** (CoTalk `units_out ⊆ units_in`) — machine-checkable, which a free-form agentic loop is not.
- **Analyze-in-isolation visual prior** (`scene/application/visual_facts_pass.py`): the anti-hallucination equivalent of Graph-R1's "rethink" — pixels anchor before context text can override them.

In short: the grounding these architectures promise is **already present in a higher-precision, deterministic form** appropriate to a per-tenant, single-image workload.

### E.2 Why not adopt Neo4j / NeoConverse

- **Second stateful service.** NeoConverse needs Neo4j (graph + full-text + vector indices) beside Postgres. This directly contradicts **Part A's** conclusion (keep one transactional store; a second store means hand-rolled consistency for no gain) — and the "graph" here (one tenant's roster + photos + co-occurrence) is **tiny** and already relational.
- **No native use case.** The product is image→caption, not natural-language querying of a knowledge graph. Text2Cypher, community detection, multi-hop traversal solve problems we don't have.
- **The one genuinely graph-shaped signal — identity co-occurrence** ("photographed together with X", relationship context) — is a **Postgres recursive-CTE / junction-table query**, or **PG19's SQL/PGQ property-graph queries** (already earmarked in [caption-context-enrichment §8](./caption-context-enrichment-assessment-2026-07-05.md)). If the eval harness ever shows relationship context lifts caption quality, model it in Postgres — **not** a Neo4j adoption.

### E.3 Why not adopt Graph-R1's agentic loop

- **Wrong task**: multi-hop **text QA**, not single-image captioning. The "complex query needs multi-turn retrieval" premise doesn't hold when the query is one image and the context is a small, pre-resolved pack.
- **Training-heavy**: end-to-end **RL (GRPO)** + hypergraph construction — off-mission for a small alt-text product; the caption corpus already rejected LoRA/RL tuning as GPU-gated non-goals.
- **Multi-pass latency/cost**: an agentic think-retrieve-rethink loop multiplies VLM passes — the exact economics ruled **prohibitive** for this hardware in [segmentation-vlm-pipeline-feasibility](./segmentation-vlm-pipeline-feasibility-2026-06-15.md) and where MosAIC multi-agent captioning *hurt* correctness. The **bounded** version of "iterate to reduce hallucination" that survives the cost gate already exists as scoped work: the analyze-in-isolation prior + **bounded-N ensemble decoding** (`VLM-4`, N≈4 hard cap), gated on the eval harness.

**Verdict (Part E)**: **Reject Neo4j/NeoConverse and Graph-R1's framework.** The grounding benefit is already implemented deterministically; the only borrowable idea (relationship/co-occurrence context) is Postgres-native and gated on the caption eval harness. No pipeline redesign, no new service.

---

## Consolidated recommendations (prioritized)

1. **Vector store**: no change. pgvector is sufficient. Keep `faiss.Kmeans` on the shelf as an algorithm fallback; keep `ivfflat→hnsw` / drop-index as cheap levers for a >100k-vector tenant. (COST-06: eliminate work before buying.)
2. **Bench leg (do this one)**: add `Qwen3.6-27B UD-Q4` + `Qwen3.6-35B-A3B` to the existing A10 bake-off vs the 30B-A3B control; score **caption quality + s/img + cost/img** on the golden manifest. Bounded, rides built harness. (PERF-06: measure, don't guess.)
3. **MTP leg**: add an MTP GGUF throughput measurement on **both A1 and A10** — cheap, llama.cpp-native, potential 1.4–2.2× with no quality cost.
4. **A1 inline VLM**: if the CPU inline caption path wants better quality than Florence-2-base, benchmark **Qwen3.5-9B (Q4/Q6)** and **35B-A3B (Q2/Q3 MoE)** against the 20 s/30 s budgets before adopting.
5. **Client fine-tune**: keep out of general scope; instantiate per paying client as its own task, bf16 LoRA, never QLoRA-4bit, GGUF export behind the profile/provenance seam.
6. **Frontier tier (GLM-5.2/Inkling/DeepSeek-V4)**: no action. Watch Inkling only as a future frontier-multimodal item, not an alt-text upgrade.
7. **Unquantized Qwen3.6**: don't deploy (won't fit A10). Only run a **Q8 reference leg on a rented A100** if the A10 Q4 bake-off underperforms the control and the quant-vs-model cause needs isolating.
8. **GraphRAG / agentic (Neo4j / Graph-R1)**: no adoption. Grounding is already deterministic in `identity_merge`/`ContextPack`. If relationship/co-occurrence context is ever wanted, model it **in Postgres** (recursive CTE / PG19 SQL/PGQ), gated on the caption eval harness — never a second graph service.

## What would flip each verdict

- **Vector store / graph DB → adopt**: a single tenant's embedding count credibly heading to **~100k–1M+**, or vector search becoming a latency/QPS-bound service in its own right (then pgvector-HNSW / pgvectorscale first, Qdrant only if it must decouple from PG); **or** relationship queries growing beyond what PG recursive-CTE / SQL/PGQ can serve (a scale we are nowhere near) before a graph DB is worth its second-service cost.
- **Larger VLM → adopt**: a confirmed **image API path** on a right-sized model, *and* a feature that needs frontier multimodal **reasoning** (not captioning), *and* an OCI GPU tier + budget that makes multi-GPU serving economic. None hold today.
- **Qwen3.6 upgrade → ship**: the bake-off leg shows a real caption-quality win over the 30B-A3B control at equal-or-better s/img and cost/img on ACX images.

## Heuristics applied

- **PERF-06 / PERF-01 / PERF-07** (measure, don't guess; throughput/latency/cost are measured): the entire Part B recommendation is "benchmark on our images/hardware," never "the model card says." No published vision benchmarks exist for the Qwen3.x families — quality is empirical.
- **COST-06** (eliminate work before buying/building): reject external vector stores and the 700B–1.6T tier on cost-vs-need grounds before any migration/procurement.
- **ARCH-08** (boring-first): keep Postgres for vectors; upgrade within the running VLM tier before reaching for new runtimes or GPU shapes.
- **REF-12** (YAGNI): no ANN service, no second store, no multi-GPU tier for a scale/feature we do not have.
- **Reports carry cost + cost/image** (house rule): the bake-off metrics are quality + s/img + cost/1k-img, with spend stamped at batch start/end.
- **rg-015** (adapters must not invent contract semantics): a per-client fine-tune ships as a provenance-tagged profile, model identity recorded, never a silent swap.

## Sources

**Vector stores**: [turbovec](https://github.com/RyanCodrai/turbovec) (MIT, TurboQuant flat scan) · [qdrant v1.18.3](https://github.com/qdrant/qdrant) (Apache-2.0) · [faiss v1.14.3](https://github.com/facebookresearch/faiss) (MIT, aarch64 wheels) · [pgvector vs Qdrant (Tiger Data)](https://www.tigerdata.com/blog/pgvector-vs-qdrant) · [pgvector 0.8 vs dedicated (steezr)](https://www.steezr.com/en/blog/pgvector-08-vs-dedicated-vector-db-when-postgres-is-enough).

**VLM quant / MTP / fine-tune**: [Qwen3.6 doc](https://unsloth.ai/docs/models/qwen3.6) · [Qwen3.6-27B-GGUF](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF) · [Qwen3.6-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF) · [MTP doc](https://unsloth.ai/docs/models/mtp) · [Qwen3.5 fine-tune doc](https://unsloth.ai/docs/models/qwen3.5/fine-tune) · [Qwen3.5-9B-GGUF](https://huggingface.co/unsloth/Qwen3.5-9B-GGUF).

**Larger models**: [GLM-5.2 doc](https://unsloth.ai/docs/models/glm-5.2) · [Inkling doc](https://unsloth.ai/docs/models/inkling) · [Inkling (HF blog)](https://huggingface.co/blog/thinkingmachines-inkling) · [DeepSeek-V4 doc](https://unsloth.ai/docs/models/deepseek-v4) · [DeepSeek-V4-Pro (HF)](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro) · [V4 modes writeup (SitePoint)](https://www.sitepoint.com/deepseek-v4-preview-what-the-fast-expert-and-vision-modes-suggest/).

**Architecture / GraphRAG**: [Qwen3.6-27B-GGUF (sizes + arch)](https://huggingface.co/unsloth/Qwen3.6-27B-GGUF) · [NeoConverse GraphRAG (Neo4j)](https://neo4j.com/blog/developer/graphrag-and-agentic-architecture-with-neoconverse/) · [Graph-R1 (arXiv 2507.21892)](https://arxiv.org/html/2507.21892v2) · in-repo: [caption-context-enrichment-assessment-2026-07-05.md](./caption-context-enrichment-assessment-2026-07-05.md), [anti-hallucination-caption-generation-scope.md](../../scopes/anti-hallucination-caption-generation-scope.md), `scene/application/identity_merge/`, `scene/application/visual_facts_pass.py`.

**Hardware/infra**: `infra/oci/main.tf`, `infra/oci/GPU-BURST-PROVISIONING.md`, `docs/runbooks/oci-instance-state-and-cost.md`, `scene/config/profiles.py`, `scripts/eval_harness/bakeoff.py`, `infra/oci/incidents/a10-multimodel-bakeoff.sh`.

> **Caveats**: All three larger models and both Qwen3.x families are post-training-cutoff (Jan 2026) releases; specs cross-checked against Unsloth docs + HF cards + registries on 2026-07-18. The Unsloth "text-only" summary for Qwen3.6/3.5 is contradicted by the repos' `mmproj` files + `image-text-to-text` tags (they ARE VLMs). DeepSeek-V4 vision availability is genuinely unsettled (official card text-only). Vector-store ms figures are indicative third-party blog numbers, not peer-reviewed.
</content>
</invoke>
