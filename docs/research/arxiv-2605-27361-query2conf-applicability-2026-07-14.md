# Query2Conf/BRANE (arXiv 2605.27361) — Applicability Assessment

**Date:** 2026-07-14 · **Task:** ARXEVAL-1 · **Verdict:** Concept applicable, full framework premature. Adopt the routing *seam* + trace logging now; defer learned predictors until post-launch traffic exists.

## Paper summary

"Natural Language Query to Configuration for Retrieval Agents" (Pan, Arabzadeh, Jacob, Kazhamiaka, Choukse, Zaharia — UC Berkeley / UW / Azure Research). Framework: **Query2Conf** / **BRANE**.

- Per-query routing across retrieval-pipeline configurations instead of one static config.
- Mechanism: LLM extracts workload-specific binary characteristics per query → lightweight per-config tabular predictors estimate P(correct) → Lagrangian cost-accuracy selector picks the config; fuzzy Pareto pruning keeps the config space tractable.
- Results: matches best-static-config accuracy at 59.7% avg cost savings (up to 89.4% on MuSiQue); classical tabular predictors beat fine-tuned BERT/Qwen3-4B routers; characterization overhead 0.5–11.9% of generation cost.
- Needs: offline profiling of a labeled query set against every candidate config (600 queries × 60–335 configs in the paper). Authors commit to open-sourcing BRANE + 526 profiling traces.

## Fit to this project

The paper is RAG-centric, but its core move — *decompose input understanding from config selection, route per input on cost/quality* — maps directly onto the description service, which today runs **one static config for every image**:

| Static today | Where | Routing upside |
|---|---|---|
| VLM profile (7 profiles, one per process via `ACX_DESCRIPTION_ADAPTER`) | `scene/config/profiles.py:30-137`, `scene/interface_adapters/http/deps.py:155-221` | Highest leverage: cheap Florence for simple images, Qwen3-VL-30B/GPU for complex/text-heavy ones |
| Async two-phase CPU-provisional → GPU-final, unconditional | `scene/application/describe_async_worker.py:126-306` | Skip the GPU final pass when the provisional is adequate — BRANE's cost-aware selection in miniature; direct GPU-cost saving |
| Ensemble width N + view strategy (GRID, n_views=4, fixed) | `scene/infrastructure/vlm/ensemble_decode.py:50-139` | Per-image N (1 for simple, more views for cluttered scenes) |
| Prompt version pinned per backend | `scene/config/settings.py:39-40` | Per-image prompt variant (OCR-heavy / scene / product) is a cheap config axis |
| WP context pack: always maximum available context | `apps/prototype-wp-alt-context/src/api/services/class-describe-media-service.php:422-470` | Enrichment tiering per image trades token cost vs caption quality |
| Bulk describe runs: one adapter for the whole batch | `scene/interface_adapters/http/routers/describe_run.py:99-145` | Heterogeneous batches are the textbook per-item routing case |

**Dormant seam already exists:** the sync describe route accepts a per-request `tier: "cpu"|"gpu"` hint and swaps adapters (`describe.py:542-547`, schema `requests.py:122`) — but WP never sets it (`class-describe-media-service.php:164-187`), so per-request routing plumbing is live yet unused.

**Existing adaptive analogues (rule-based, not learned routers):** recognition confidence gating with curriculum EMA (`recognition/application/assignment/checks/confidence.py:51-189`) — the most BRANE-like mechanism in the repo, but it routes accept/suggest/reject outcomes, not pipeline configs; latency-feedback chunk sizing (`chunked_processor.py`); decorative-image zero-compute skip (`describe.py:421-427`).

## Why full BRANE is premature

1. **Profiling data scale:** per-config predictors train on labeled profiling runs (600+ queries/benchmark in the paper). Our labeled set is `scene/tests/seed/golden.json` — 37 entries. ~16× short of the smallest benchmark, and it labels recognition ground truth, not caption-quality-per-config.
2. **No traffic:** greenfield, no production users (per project policy) — no real query distribution to learn characteristics from; a learned router would be fit to synthetic data.
3. **Config space is small:** with effectively 2–3 live configs (seeded / florence_small / gpu_qwen30b[_ensemble]), Pareto pruning and Lagrangian selection are overkill; a heuristic gate captures most of the win.
4. **Per-config cost/outcome accounting doesn't exist yet** — nothing records which config produced which caption at what cost, so there is nothing to train or even evaluate a router against.

## Recommended adoption path (cheap → learned)

1. **Now (cheap, no ML):** wire WP to set the existing `tier` hint from per-image heuristics it already computes (decorative flag, face count, image dimensions, parent-post type, context-pack richness). Zero new backend surface.
2. **Now (instrumentation):** log per-request `(image characteristics, config used, cost proxy, outcome)` in the describe path — accumulating exactly the profiling traces BRANE trains on. Piggybacks on the existing cache-key fields (`visual_facts_service.py:195-214`, which already hash adapter kind + model_version + prompt_version + context).
3. **Next:** make the async GPU-final pass conditional on provisional confidence (cost-aware escalation).
4. **Post-launch, if ≥3 configs + real traffic:** revisit learned per-config predictors; watch for the promised BRANE open-source release + 526 profiling traces as a starter harness. Their finding that classical tabular predictors beat fine-tuned LLM routers keeps this cheap when the time comes.

## Sources

- Paper: https://arxiv.org/html/2605.27361v1
- Decision-point inventory: Explore-agent sweep 2026-07-14 (both apps, file:line anchors above; grok offload was admission_refused by host memory governor — see ARXEVAL-1 blocker).
