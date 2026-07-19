# FIR-5. Bake-off Harness Extension

> **Metadata**
>
> - **Date**: 2026-07-18
> - **Author**: Claude Opus 4.8 (claude-opus-4-8)
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `FIR-5`
> - **Target Branch**: `feature/fir-5`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-2 (neutral seam) · FIR-3 (candidate legs) — both `done`
> - **Review Coverage Target**: 2

## Objective

Extend the existing eval bake-off harness (`apps/prototype-description-service/scripts/eval_harness/`) so it can score the FIR-3 YuNet+SFace candidate pipeline against a buffalo_l reference over the Golden-150 corpus and **produce the numbers FIR-6's operator gate decision will rest on** — identification P/R, false-merge/false-split, cluster purity, unknown-rejection, and a throughput/cost perf leg — with the occlusion family (`masked`, `sunglasses`, `occlusion_other`) as first-class synthetic-paired gating slices plus real-tag validity checks. The harness **proposes** gate criteria; it never decides the gate (FIR-6, [RLSE-02/03]).

## Intake

- **Scope**: [commercial-face-identity-replacement.md](../../scopes/commercial-face-identity-replacement.md) — FIR-5 row (§Task decomposition), Success criterion 3, [FIR-5 slice sizing table](../../scopes/commercial-face-identity-replacement.md#fir-5-slice-sizing-ci-target-driven), §Coordination with VLM-6.
- **Reuse mandate** (NAME-02/REF-10): consume VLM-6 S1 outputs (curated manifest v2 + roster + `face_boxes` + retained full-res originals). No parallel corpus, no forked walker — reuse the per-item run walker `cli.py:fetch_run_record` (driven UNCHANGED by `bakeoff.py:283`, per-item isolation + rg-007 bounded stall), and extend `report.py`, `strata.py`, `face_metrics.py`. Candidate-leg registration is *new* code modeled on `bakeoff.py`'s driver — not an existing `fusion_runner` registry (none exists).
- **Not-Doing here**: no threshold calibration or quality rework (FIR-6 — this task measures at FIR-3 defaults); no operator gate decision (FIR-6); no switch-over / dimension-default flip / buffalo eviction from prod images (FIR-6); no production GPU path (FIR-7); no escalation-ladder candidates — SeetaFace/commercial SDK (FIR-8); no runtime/scan-path changes (FIR-4 shipped those).

## Problem Statement

FIR-4 wired YuNet+SFace in dark. Nothing yet tells the operator whether it is good enough to switch on. The gate cannot be a copied threshold ([DRIFT-03], [PERF-06]); it must come from ACX-domain measurement with **falsifiable unknown-first behavior** and statistically honest slice floors. The occlusion family is the known product-frequency failure mode (masks and sunglasses are distinct in user uploads) and must be measurable with real statistical power — which the corpus alone cannot supply at n=150, so the harness must generate synthetic-paired occlusion twins (free at any n) and cross-check them against small real-tagged slices for ecological validity.

## Constraints

- **Duplicating preprocessing invalidates the bake-off**: candidate legs run FIR-3's adapters in-process (same aligner/normalization the runtime uses), not a re-implementation. This is why FIR-3 is a hard dependency.
- **License isolation** ([SC-1]): the buffalo_l reference leg is eval-env-only; its embeddings live in **run artifacts**, never a prod DB, never a shared column. `insightface` reachable only via the `[bench]` extra (FIR-4 landing). Bake-off reports/galleries obey `is_publishable()` fail-closed (celebs01-only), identical to VLM-6.
- **Floor-gated honesty** (mirrors VLM-6 locked stance): a slice below its n-floor reports **DIRECTIONAL ONLY** and is structurally barred from the gate proposal. Floors, resolutions, and gate roles are copied verbatim from the sizing table — not re-derived by feel.
- **Deterministic re-scorable** ([verification]): every run supports `score --check-determinism` (re-score identical inputs → identical metrics); synthetic occlusion is seeded/deterministic per tag.
- **Unknown-first is a first-class metric, not a byproduct**: unknown-rejection (strangers absent from roster) is a gating slice; a candidate that identifies everyone confidently fails it.
- **No self-judged gate**: outputs are a report proposing criteria + per-slice rollups. The gate decision is an operator MCP decision in FIR-6.

## Current State Analysis

The harness already has: `manifest.py` (v2 corpus contract — `GoldenEntry`, `FaceBox`/`face_boxes` **landed** @5017c6d9, single-valued `Domain` StrEnum; `enrich_entry` persistence lives in `export_identities.py:131`), `cli.py:fetch_run_record` (per-item-isolated run walker, rg-007 bounded stall) with `bakeoff.py` driving it UNCHANGED, `fusion_runner.py` (`run_fusion_eval`, `score_misattachments`, `manifest_entries_as_dicts`, `_FusionStubAdapter` — no candidate registry), `report.py` (rollup rendering), `strata.py` (stratum selection + thin-slice reporting), `face_metrics.py` (`detection_pr`, `identification_pr`, `PrResult`), `face_pass.py` (tenant-scoped face pass over a live service). **Gaps**: (1) `Domain` is single-valued and carries none of the gating tags (`masked`/`sunglasses`/`occlusion_other`/`profile`/`low_res`/`blur`/`similar_people`/`unknown`) — an image is legitimately both `masked` and `low_res`; (2) no false-merge/false-split, cluster-purity, or unknown-rejection metrics; (3) no synthetic-occlusion generator; (4) no throughput/cost perf leg or recorded budget; (5) no floor-gated slice rollup that demotes below-floor slices to directional.

## Target Outcome

`make bakeoff-face` (or `eval-harness face-bakeoff`) runs candidate YuNet+SFace and the eval-only buffalo_l reference over Golden-150, emitting a deterministic, re-scorable bake-off report: headline identification P/R, false-merge/false-split, cluster purity, unknown-rejection, per-slice occlusion rollups (synthetic-paired gating + real validity checks with synthetic↔real degradation correlation), and a throughput/cost leg (embeddings/sec + sec/image on ARM A1 and A10, cost per 1k images, p95 scan latency vs a recorded budget). The report **proposes** gate criteria and flags every below-floor slice as directional. Buffalo embeddings confined to eval-env run artifacts.

## Contract and Boundary Impact

Manifest schema change (owned here per scope §Coordination item 1 if VLM-6 does not take it): extend `Domain` with the eight gating tags and make per-entry tagging multi-valued — either `domains: list[Domain]` or an additive `tags: list[Domain]` field on `GoldenEntry` + `enrich_entry` persistence. Additive/optional (v2 loader stays back-compatible; existing 37-entry + Golden-150 manifests load unchanged). No runtime/service contract change — the harness is offline eval tooling. `face_pipeline` purity unchanged (harness imports adapters, not vice versa).

## Slice Delivery

| Slice | Content | Verification |
| --- | --- | --- |
| S1 Tag schema | Extend `Domain` enum (`masked`, `sunglasses`, `occlusion_other`, `profile`, `low_res`, `blur`, `similar_people`, `unknown`); multi-valued per-entry tags on `GoldenEntry` (`manifest.py`) + tag persistence in `export_identities.py:enrich_entry`; `low-light`→`blur`/`low_res` mapping documented | Loader tests: multi-tag entry round-trips; legacy single-`domain` + tagless manifests still load; extra-forbid still rejects unknown tags |
| S2 Candidate leg | New in-process detector+embedder candidate driver modeled on `bakeoff.py`, reusing the `cli.py:fetch_run_record` walker (per-item isolation, bounded stall); buffalo_l reference leg gated to eval env, embeddings to run artifacts only | Offline leg produces per-face embeddings over golden manifest; determinism: two runs → identical embeddings; buffalo leg refuses outside eval env |
| S3 Identity metrics | `face_metrics` extension: false-merge / false-split, cluster purity, unknown-rejection (strangers absent from roster); headline identification P/R on celebs01 | Unit tests on synthetic cluster fixtures with known ground truth (each metric has a can-fail discrimination test per [TEST-15]); unknown-rejection distinguishes reject-stranger from label-stranger |
| S4 Synthetic occlusion | Deterministic seeded synthetic-occlusion generator (masked / sunglasses / patch) producing paired twins of every roster face; paired scoring (Δ paired-accuracy per tag) | Determinism: same seed → identical occluders; paired McNemar-style delta computed; ≥90-pair floor check wired |
| S5 Perf + report | Throughput/cost leg (embeddings/sec, sec/image on A1 + A10, cost per 1k, p95 vs recorded budget); floor-gated slice rollup (below-floor → DIRECTIONAL, barred from gate proposal); synthetic↔real degradation correlation (divergence >⅓ demotes synthetic to directional); `score --check-determinism`; report proposes gate criteria | Report renders all gating + directional slices with floors + roles; determinism re-score is byte-identical; below-floor slice never enters gate proposal (assertion test); perf leg stamps cost per [reports-include-cost-per-image] |

## Files and Surfaces to Change

All paths under `apps/prototype-description-service/`: `scripts/eval_harness/manifest.py` (Domain enum + multi-tag field on `GoldenEntry`) · `scripts/eval_harness/export_identities.py` (`enrich_entry` tag persistence) · `scripts/eval_harness/face_metrics.py` (false-merge/split, purity, unknown-rejection) · new candidate-leg driver modeled on `scripts/eval_harness/bakeoff.py`, reusing `scripts/eval_harness/cli.py:fetch_run_record` · `scripts/eval_harness/report.py` (floor-gated slice rollup + perf leg + gate-criteria proposal) · `scripts/eval_harness/strata.py` (occlusion-family slice selection guidance) · new `scripts/eval_harness/synthetic_occlusion.py` (seeded generator) · new `scripts/eval_harness/perf_leg.py` (throughput/cost + budget) · `scripts/eval_harness/cli.py` (`face-bakeoff` + `--check-determinism`) · Makefile target `bakeoff-face` · tests under `scene/tests/test_eval_harness_*.py` · buffalo reference leg confined to a `[bench]`-guarded module.

## Verification Strategy

Metrics have adversarial can-fail tests ([TEST-15]): prove each metric goes red on a wrong-clustering / mislabeled-stranger fixture before trusting green. Synthetic occlusion is seeded and determinism-checked. Real-corpus smoke before close: run the candidate leg over the actual Golden-150 (LIVE curation tenant `4ddf8f36`, do not dispose) and eyeball the detection/occlusion distribution (VLM-6 lesson: synthetic-green misses real-corpus pathologies). Scoped TDD locally; full suite via `make check-remote` per slice (never local full-suite). Cost stamped at run start/end; every report carries total cost + cost-per-image (A10 ~$2/GPU-hr, A1.Flex ~$0.152/hr).

## Coordination / Sequencing

- **VLM-6 (Golden-150, in flight)**: harness work starts against the 37-entry golden manifest v2 immediately; slice-level occlusion conclusions wait for Golden-150. Cheapest window for tag asks is the S1 curation pass — if the schema/tag asks (this task's S1) miss that window, fallback is a bounded operator post-pass tagging session (~1 h). Face boxes already landed. If VLM-6 declines the S2 registry generalization, ship a thin driver over the same corpus + manifest and record the walker-duplication cost as a decision (ARCH-06).
- **Do not dispose curation tenant `4ddf8f36`** — the bake-off rides the VLM-6 Golden-150 harness (LIVE @localhost:10018).
- **Blocks FIR-6**: FIR-6's operator gate decision + switch-over slice are blocked until this harness produces the bake-off report.

## Consolidated Checklist

- [ ] S1 tag schema: multi-valued occlusion/quality tags, additive/back-compatible loader
- [ ] S2 candidate + eval-only buffalo reference legs reuse the fusion registry/walker; buffalo confined to eval env + run artifacts
- [ ] S3 false-merge/false-split, cluster purity, unknown-rejection metrics, each with a can-fail discrimination test
- [ ] S4 seeded synthetic-occlusion generator (masked/sunglasses/patch) + paired scoring, determinism-checked
- [ ] S5 throughput/cost perf leg + recorded budget; floor-gated slice rollup demotes below-floor slices to directional; `--check-determinism` byte-identical; report proposes (never decides) gate criteria
- [ ] Real-corpus smoke over Golden-150 before close; cost + cost-per-image stamped on the report
- [ ] Per-slice adversarial review (≥1 remote grok HIGH reviewer + local adversarial subagent), findings cite heuristic IDs, batch-recorded in MCP
