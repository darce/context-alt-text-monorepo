# VLM-2B — Detailed-Tier Caption Model Bake-Off — Scope Note

> **Status:** Scope one-pager (decision input). Not an epic or task plan.
> **Date:** 2026-07-06
> **Task ID:** `VLM-2B` · **Target Branch:** `feature/vlm-2b`
> **Feeds:** E19 (detailed-description tier). Downstream of VLM-2A (eval harness) and the parent assessment.
> **Source of truth:** [caption-context-enrichment-assessment-2026-07-05.md](../assessments/current/caption-context-enrichment-assessment-2026-07-05.md) §10 (model landscape / "slow but detailed" tier), §12 item 4 (bake-off before adapter build), §6c (metric tiers), §11 (implementable-now CPU-only A1), §13 (open risks). Derived from an approved assessment — **no user Q&A required**; assumptions are documented below.

---

## 1. Problem

The assessment picks a two-tier serving design: a fast interactive tier (Florence-2 today) and a slow **detailed-description tier** (opt-in, async, minutes-per-image) that "paints the image" for BLV users. Three GGUF-servable candidates are in contention for the detailed tier, but **no public benchmark measures the one property that matters for our product — whether the model weaves injected, roster-confirmed names from a supplied context block into the caption** (assessment §10: "No public benchmark measures injected-name weaving — we must test it ourselves"). Picking a detailed-tier model without measuring injected-name obedience and hallucination on our own imagery is a blind bet (assessment §13: CapRL's instruction-obedience is explicitly unknown and "disqualifying regardless of caption quality").

VLM-2A shipped the scoring harness (`apps/prototype-description-service/scripts/eval_harness/`) but scored only the deployed `seeded`/`florence_small` describe path. Nothing has scored the detailed-tier candidates.

## 2. MVP Scope

Run a **three-model bake-off** over ~10 golden images with **real context packs** (roster names injected), score every candidate with the VLM-2A deterministic metric tier, and produce **one decision memo picking a single model with evidence**. The winner later becomes one `DescriptionAdapter` behind the existing protocol — **that adapter build is a follow-on task, not this one**.

**Candidates (settled from assessment §10 table + §12 item 4):**

| Candidate | Params / license | CPU path | Why in the run |
| --- | --- | --- | --- |
| **CapRL-Qwen3VL-4B** | 4B, Apache-2.0 | official GGUF (llama.cpp) | Caption-specialized RL tune of the E19-1 quality winner; **injection-obedience is the open question this bake-off answers** (§13) |
| **Qwen3-VL-4B-Instruct** | 4B, Apache-2.0 | official GGUF (llama.cpp) | E19-1 measured quality winner; strongest instruction-following → best a-priori bet for weaving injected names |
| **MiniCPM-V 4.5** | 8B, Apache-2.0\* | official GGUF / Ollama | Best hallucination story (RLAIF-V, tops ObjectHalBench); slowest — the deep-detail opt-in candidate |

\* MiniCPM: Apache-2.0 weights gated behind a free-commercial registration questionnaire — license terms must be confirmed before a shipping decision (assessment §13). MiniCPM-V 4.6 (1.3B) is the assessment's **fast-tier** successor candidate, **not** a detailed-tier entrant — explicitly excluded here.

**Scoring (VLM-2A harness reuse, assessment §6c):** insertion rate, Must-Right gates (any miss zeroes the image), hallucinated-unit / wrong-fact signal, FKRE, plus the deterministic caption-tier signals (repetition ratio, first-sentence gist, tag coverage). Deterministic tier only — the LLM-judge tier stays a stub (VLM-2A already gates it off with `--llm-judge` rejection).

**Decoding:** greedy; `/no_think` appended if a candidate is reasoning-tuned; per-request timeout, fail-per-item + continue, bounded consecutive-failure exit (rg-007) — same Nygard posture VLM-2A's `remote_client.py`/`cli.py` already encode.

**Deliverables:**
1. Per-candidate benchmark artifacts in the E19-1 / VLM-2A eval-harness JSON schema (`schema="acx-eval/v1"`, `DocKind.REPORT`) — reproducible, deterministic re-score.
2. One decision memo (`docs/tasks/vlm/VLM-2B-detailed-tier-decision-memo.md`) picking **one** model, citing the artifacts, incl. measured latency/RSS on A1 and the license verdict.

## 3. Stated Assumptions

1. **All three candidates are GGUF-servable on the A1 CPU via llama.cpp** (Q4_K_M or nearest official quant). Assessment §10 states official GGUF exists for all three; the 1–3 min/img A1 estimate is **unverified** (§13) — a first slice re-benchmarks it and a candidate that cannot load or exceeds a per-request wall-clock ceiling is scored as a **fail-per-item**, not a run-aborter.
2. **Same infra posture as VLM-2A:** the laptop performs **no** inference; each candidate runs as a llama.cpp server (OpenAI-compatible `/v1/chat/completions` or native `/completion`) on the OCI A1, driven remotely. **Concurrency 1**, run **one model at a time, off the live-demo path** — the shared box must not degrade.
3. **Real context packs are required and must be authored.** The current `scene/tests/seed/golden.json` has 37 entries with **empty** `context_pack` objects and all `recognition_enabled=true` (verified). The bake-off needs a ~10-image subset whose context packs carry the injected roster names (and non-visible event/place facts) so insertion rate and Must-Right name gates are meaningful. Authoring that subset's context packs is in scope; it reuses the existing `ContextPack`/`GoldenEntry` manifest schema (`manifest.py`), adding no schema fields.
4. **Candidate caption ≠ full describe envelope.** These are raw caption generators; they emit a caption, not the service's `VisualFactsResponse`. The bake-off runner shapes each candidate's output into a run-record item (`describe.alt_text_draft`, `describe.adapter/model_id/model_version`, optional `describe.visual_facts.objects`) so the existing `report.score_run_record()` scores it unchanged. This runner is a **throwaway bake-off harness, not a productionized `DescriptionAdapter`.**
5. **Face-recognition metrics are candidate-independent and out of band.** The caption model does not do recognition; the harness's `face_metrics.py` detection/identification P/R is driven by the separate recognition service, unchanged across candidates. The bake-off reports only the **caption** section; face metrics are N/A for model selection here.
6. **Ground truth already exists.** The VLM-2A roster (10 names) and golden corpus are reused; no new labeling beyond authoring the bake-off subset's context packs and per-image Must-Right/Easy-Wrong rubric entries.

## 4. Not-Doing (explicit out-of-scope)

- **No adapter productionization** — the winner becomes a `DescriptionAdapter` + async worker in a follow-on; this task stops at the pick.
- **No `DescriptionProfile`/`PROFILE_SPECS` registry entry** for any candidate (that is the follow-on adapter build).
- **No ROC / threshold / confidence sweeps** and no TAR@FAR — same non-goal as VLM-2A.
- **No LLM-judge implementation** — deterministic tier only; judge stays a stub.
- **No fusion / instructed-fusion Tier-1 work**, no E19-4a identity-prose merge, no phase-split caching (separate sequenced items).
- **No new auth surfaces, endpoints, or server code paths** — reuse the dedicated eval tenant + existing dev key posture from VLM-2A.
- **No OpenCV 5 spike, no brand detection, no PG18/19 work.**
- **No CI gating / dashboards / UI** for the bake-off numbers.
- **No fast-tier model** (MiniCPM-V 4.6 / Florence successor) evaluation.
- **No vendoring** of GGUF weights or the image corpus in git.

## 5. Success Criteria

1. Each of the three candidates produces a scored **acx-eval/v1 REPORT** artifact over the same ~10-image bake-off subset with real context packs, provenance-stamped with the candidate model id/version (`report._model_provenance`).
2. Scores are **deterministic and reproducible** — re-scoring a captured run record is bit-identical (`cli._cmd_score --check-determinism` passes), and captures are re-scorable offline.
3. Results are comparable on the assessment §6c metrics: **insertion rate**, Must-Right gate pass count, wrong-fact/hallucination signal, FKRE, plus latency/RSS per candidate on the A1.
4. A decision memo names **exactly one** winner, cites the artifacts, states the license verdict (esp. MiniCPM registration terms), and records disqualifiers (e.g. CapRL ignoring injected context per §13).
5. The bake-off never degrades the live demo box (concurrency 1, off-path) and never aborts the whole run on a single candidate/item failure (rg-007 bounded-stall exit only).

## 6. Slice Outline (detail in the task plan)

1. **Bake-off subset + context packs** — curate ~10 golden images (identity, scene, text/brand, context-interplay classes per assessment §6b) into a bake-off manifest with real context packs (injected roster names) + Must-Right/Easy-Wrong rubrics. Reuses `manifest.load_manifest` validation; adds no schema fields.
2. **Candidate serving + A1 re-benchmark** — stand up each GGUF candidate on the A1 via llama.cpp; measure load + per-image latency/RSS; confirm/deny the 1–3 min/img estimate; establish per-request timeout ceiling.
3. **Bake-off runner** — throwaway remote client (Nygard discipline mirroring `remote_client.RemoteSceneClient`) that prompts each candidate (greedy, `/no_think` if reasoning-tuned, anchor-visual/inject-factual context contract) and shapes output into acx-eval run-record items; per-item isolation + bounded-stall exit.
4. **Score + compare** — run every candidate through `report.build_reports`; emit per-candidate REPORT artifacts; assemble a comparison table.
5. **Decision memo** — pick one model with evidence; record disqualifiers and license verdict; commit artifacts under `docs/tasks/vlm/`.

## 7. Open Risks (from assessment §13)

- GGUF quantization quality loss and the 1–3 min/img A1 estimate are both unmeasured on ARM/A1 — Slice 2 answers this before any pick.
- CapRL's instruction obedience is unknown; a caption-RL model that ignores injected context is disqualified regardless of caption quality — the bake-off's injected-name weaving metric is the test.
- Wrong-name/wrong-fact insertion is the top product risk; the §6c gated Must-Right rubric is the regression net. LLM judges are trustworthy only on visually-grounded traits — deterministic tier is the decision basis here.
- MiniCPM commercial-registration terms need a license review before it can win a shipping decision.
