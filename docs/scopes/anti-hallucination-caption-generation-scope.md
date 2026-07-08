# Anti-Hallucination Caption Generation (Ensemble Decoding + Region Proposals) — Scope Note

> **Status:** Scope one-pager (decision input). Not an epic or task plan.
> **Date:** 2026-07-07
> **Proposed Task ID:** `VLM-4` (anti-hallucination generation) · **Feeds:** E19/E20 caption-quality track, sequenced **after VLM-3** (needs the GPU tier to afford N× passes).
> **Source of truth:** research-papers survey (`~/Documents/research papers`, 2026-07-07) + [caption-context-enrichment-assessment-2026-07-05.md](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) §6 (gated-rubric eval). Recommendations picked against [engineering-heuristics.md](../workbay/rules/engineering-heuristics.md).
> **Key papers:** Attention-Guided Ensemble Decoding (arXiv 2505.17529); Sub-Semantic Image Segmentation / **DETECTURE** (arXiv 2606.14754); Hierarchical Multi-Modal Retrieval (arXiv 2606.18553); RE-VLM (arXiv 2605.19329); Whitened CLIP (arXiv 2505.06934).

---

## 0. Definitions (as used here)

- **Ensemble-decoding synthesis** — run the *same* VLM multiple times over different **views** of one image (the full image plus several sub-regions), and at **each decode step combine the token-probability distributions across the passes**, weighting each pass by where the model's **attention** actually falls. Tokens not visually grounded in any view get voted down → one **synthesized** caption with fewer hallucinations. It is **training-free and inference-time** (Attention-Guided Ensemble Decoding, arXiv 2505.17529, ICLR 2025; SOTA on POPE/CHAIR object-hallucination benchmarks). A logit-only variant (majority/confidence vote without attention) is the fallback when a serving stack does not expose attention.
- **DETECTURE** — the framework name coined by the *Sub-Semantic Image Segmentation* paper (arXiv 2606.14754). It couples a general VLM (they use Qwen3-VL-8B) to **SAM-3 promptable segmentation** through a learned "Bridge": the VLM proposes candidate regions, SAM-3 grounds each into a **mask**, a Winner-Takes-All step builds a non-overlapping partition, and the VLM emits a description **per region**. (The name is the paper's own; its expansion is not stated in the text — treat it as a proper noun, not an acronym to rely on.)
- **DETECTURE-style region proposals** — the reusable *idea* from that paper, independent of their trained model: instead of captioning the whole image at once (which invites "global" hallucination), first **partition the image into semantically-meaningful regions** with a promptable segmenter (SAM-class), then have the VLM describe each region in focus, then reconcile the parts. Region proposals give ensemble decoding *better* views than a naive grid.

## 1. Problem

The current and planned tiers (Florence CPU; Qwen3-VL CPU; the VLM-3 GPU tier) all do **single-pass, whole-image** captioning, whose classic failure is **hallucination** — plausible-but-ungrounded detail (Florence's "dining table" on a flower; a guessed name; an invented brand). The VLM-2A/2B **gated rubric catches hallucinations at *eval* time** (`Easy-Wrong` traps) but nothing reduces them at **generation** time. The papers survey identifies a **training-free, inference-time** technique — ensemble decoding — with measured hallucination reduction on off-the-shelf VLMs, plus a region-proposal front-end that could sharpen it. Neither exists in the service.

## 2. MVP Scope

> **Heuristic cut (YAGNI / speculative-generality gate):** ship the technique with the **strongest evidence and lowest cost first** — inference-time ensemble decoding on **one** off-the-shelf VLM — and gate everything on the eval harness. Region proposals (SAM) are a **stretch**, not MVP; the full trained DETECTURE stack is **out**.

**Tier A (MVP): inference-time ensemble decoding on the GPU detailed tier.**
- Wrap the VLM-3 GPU adapter with an **ensemble-decoding decode loop**: build **N views** (full image + a small fixed set of sub-regions, e.g. a 2×2 or attention-seeded crop set), run the VLM per view, and at each step **combine logits weighted by attention** (attention-guided) — or a **logit-only majority/confidence vote** fallback when attention isn't exposed by the serving stack.
- **Bounded N** (start N≈4; a hard cap) and an **adaptive-plausibility** calibration step (per the paper) to avoid degenerate votes.
- **Measure-gated adoption (falsifiable hypothesis):** it ships only if, on the VLM-2B corpus via `report.build_reports`, it **cuts `Easy-Wrong` hallucination hits without lowering insertion rate / `Must-Right`** and stays inside the tier's latency budget. If it fails the gate, it is not adopted — the scope's deliverable is the *measured decision*, like VLM-2B.

**Tier B (stretch): DETECTURE-style region proposals.**
- Replace the naive sub-region views with **SAM-class promptable-segmenter masks** as the per-region views (better-grounded regions → better ensemble). Reuses the OpenCV-5/segmentation surface only if that spike lands; otherwise a lightweight segmenter behind an adapter.

**Companion candidate — visual-analysis-first prior (EVENTA Stage 1).**
- From the Hierarchical Multi-Modal Retrieval / EVENTA solution (arXiv 2606.18553; ref impl [github.com/mf0212/EVENTA-Challange](https://github.com/mf0212/EVENTA-Challange)): **analyze the image *in isolation* first** — one structured VLM pass extracting visual facts across fixed dimensions (objects / attributes / spatial / text) **before** any supplied `ContextPack` text is applied — "to mitigate the risk of textual context overpowering the visual content." The final caption is then synthesized **anchored to that visual prior**, so injected names/facts can only attach to what was actually seen. Cheap (one extra structured pass, not N), inference-time, off-the-shelf → a second bake-off candidate alongside ensemble decoding; the two are composable (visual-prior + ensemble vote). **Only the Stage-1 faithfulness step is in scope — not EVENTA's external-article RAG (see Not-Doing).**

**Companion (cheap, optional): a hallucination *filter*.**
- **Whitened-CLIP** (arXiv 2505.06934) as a **training-free candidate re-ranker** — score each caption's CLIP-distribution likelihood; over-specific/ungrounded phrasing scores low → flag or down-rank. A near-free guardrail independent of the generator.

**Deliverables:**
1. An ensemble-decoding decode path behind the existing `DescriptionAdapter` seam (ports & adapters — no bespoke describe route).
2. A bake-off-style REPORT (acx-eval/v1) comparing, on the VLM-2B corpus: **single-pass baseline vs ensemble-decoding vs visual-prior-first (EVENTA Stage 1) vs the two composed** — on hallucination (`Easy-Wrong`), `Must-Right`, insertion rate, FKRE, **and the latency/cost multiplier** (visual-prior is +1 pass; ensemble is +N).
3. A decision memo: which technique(s) to adopt (or reject), with measured deltas and the cost each buys.

## 3. Stated Assumptions

1. **Runs only on the GPU detailed tier (VLM-3).** Ensemble decoding is **N× passes → N× latency + N× GPU cost** (heuristic: *tail-latency amplification* + *capacity multiplier*). That is affordable only on the async, minutes-tolerant GPU tier — **never** the fast interactive Florence tier. So VLM-4 is **sequenced after VLM-3 lands**.
2. **Attention-guided variant needs attention maps**, which not every serving stack exposes (heuristic: *functional coupling* — the technique couples to the VLM's logit/attention API). vLLM exposes logprobs but attention is easiest via a raw `transformers` path; llama.cpp exposes neither cleanly. So the MVP must offer the **logit-only vote fallback**, and the spike confirms which serving stack the winning model supports.
3. **The N region passes are independent** → parallelizable on the GPU (heuristic: *concurrency only helps independent I/O / Amdahl*), but bounded by VRAM batch on the 24 GB A10 → N is capped and batched, not unbounded.
4. **The eval harness is the arbiter** — no technique is adopted on vibes; the VLM-2A/2B gated rubric + the latency multiplier decide (heuristic: *measure, don't guess*).
5. **Off-the-shelf VLMs only** — training-based methods (DETECTURE's trained Bridge, RE-VLM's graph generator, CIAN's LoRA) are **idea sources, not adopted**; we serve pretrained models.

## 4. Not-Doing (explicit out-of-scope)

- **No model training / fine-tuning** — no trained Bridge, no LoRA, no graph-constrained generator (RE-VLM/CIAN/DETECTURE training paths are references only).
- **No ensemble of *different* models** in MVP — same-VLM multi-view first (cheaper, isolates the technique); cross-model ensembling is a later question.
- **No external-document / news RAG (EVENTA's retrieval half)** — knowledge/context *enrichment* is a different axis from *don't-invent*, and our facts already arrive via the WP `ContextPack`. Only EVENTA's Stage-1 visual-faithfulness step is in scope; its hierarchical retrieval + LLM synthesis over external articles belongs to the **separate context-fusion / enrichment track** (see §9).
- **No event-camera / depth input** — the survey found **no paper recommends depth-first captioning**; explicitly excluded.
- **No new async/serving infra** — reuses VLM-3's GPU tier, adapter seam, job store, and eval harness.
- **No fast-tier (Florence) ensemble** — cost-prohibitive on CPU.
- **Not before VLM-3** — hard sequencing dependency.

## 5. Success Criteria

1. A single committed acx-eval/v1 REPORT shows **single-pass vs ensemble-decoding** on the VLM-2B corpus with the same context packs, re-score bit-identical.
2. The decision memo states a **measured verdict**: ensemble decoding is adopted iff it reduces `Easy-Wrong` hallucination hits **without** reducing `Must-Right`/insertion rate, at an accepted latency multiplier (target: ≤ N× the single-pass GPU time, N bounded).
3. The ensemble path sits behind the `DescriptionAdapter` protocol (no bespoke route); togg: a profile/flag opts a request into it.
4. A logit-only fallback works when attention is unavailable, proven by a test with a stubbed logits-only endpoint.
5. If Tier B is attempted: region-proposal views measurably beat grid views on the same rubric, or the memo records that they don't.

## 6. Slice Outline (detail in the task plan)

1. **Ensemble-decode core** — the N-view decode loop (attention-weighted + logit-only fallback), bounded N, adaptive plausibility, behind the GPU adapter.
2. **Visual-prior-first path (EVENTA Stage 1)** — a structured visual-facts pass in isolation, then context-anchored synthesis; +1 pass, composable with slice 1.
3. **Bake-off** — baseline vs ensemble vs visual-prior vs composed, over the VLM-2B corpus via `report.build_reports`; REPORT + latency multiplier.
4. **Decision memo** — which technique(s) to adopt, measured.
5. **(Stretch) Region proposals** — SAM-class masks as views; re-run the bake-off.
6. **(Optional) Whitened-CLIP re-ranker** — cheap hallucination filter as a guardrail.

## 9. Related deferred track (NOT this scope)

**Context / knowledge enrichment** — adding *true external facts* (vs suppressing invented ones) is a separate axis and a separate scope-to-be:

- The **3-stage context-fusion caption architecture** (arXiv 2606.18553 / EVENTA control flow: visual-analysis → reconcile-with-context → synthesize) and **CIAN**-style multi-stage RAG.
- For our product the "retrieval" half is largely **already solved** by the WP `ContextPack` (tenant supplies names/events/places) + the identity-prose merge; the adoptable part is the **control flow**, not news-article RAG.
- This maps to the **E20 context-pack enrichment** track (E20-9) — flag a future `context-fusion` scope there, not here. VLM-4 borrows only EVENTA's Stage-1 faithfulness step.

## 7. Heuristic-Driven Decisions (picked, not asked — veto any)

- **YAGNI gate** → MVP = ensemble decoding on **one** model; DETECTURE's *trained* stack and cross-model ensembles are excluded; region proposals are stretch.
- **Measure, don't guess / falsifiable hypothesis** → adoption gated on harness deltas + latency; the deliverable is the *decision*, not a forced ship.
- **Tail-latency amplification + capacity multiplier** → GPU-tier only, N bounded, sequenced after VLM-3.
- **Ports & adapters + two hats** → the decode technique wraps the existing adapter; no new describe path; separate from VLM-3 serving.
- **Functional-coupling triage** → the attention-guided variant is coupled to the serving stack's attention exposure → a logit-only fallback is mandatory, not optional.

## 8. Open Risks

- **Attention exposure** (assumption 2) may force the logit-only variant, which the paper shows is weaker than attention-guided — the bake-off quantifies the gap.
- **Latency/cost multiplier** may exceed the tier's budget even at N=4 → the memo may reject or cap N=2–3.
- **Region proposals add a second model** (segmenter) to the burst pool → VRAM contention on the 24 GB A10 (coupling to VLM-3's hardware constraint); Tier B may require the A100 headroom shape.
- **Diminishing returns**: the gated Must-Right rubric already blocks the worst hallucinations at eval time; ensemble decoding must prove *additional* generation-time reduction to be worth N× cost.
