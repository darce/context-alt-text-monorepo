# Description Model GTM Selection — Assessment

> **Metadata**
>
> - **Date**: 2026-10-28
> - **Author**: Claude Opus 5.5 (claude-opus-5-5)
> - **Scope**: go-to-market description model for `apps/prototype-description-service` (`gpu_qwen30b`) on the OCI A10 burst tier (`infra/oci`), and beta expectation-setting in `apps/prototype-wp-alt-context`
> - **Status**: Draft
> - **Task**: DESCPICK-2; promotes advisory decision 20400 (`claude_descpick_gtm_keep_incumbent_q4_assessment`, MAINT-desc-model-pick-20261026)
> - **Evidence classes**: `[code]` read at `file:line` on `c9674a2aa0` · `[artifact]` gitignored local report in the root checkout; bare file names are relative to `benchmarks/reports/qwen-high-precision-20261025/review-decision-v3/` · `[handoff]` decision id · `[est]` author's estimate, not measured

> Keep the served Qwen3-VL-30B-A3B-Instruct Q4_K_M (`gpu_qwen30b`) on the A10 24 GB for go-to-market as a reversible keep, not a declared winner. On the A10 the higher-precision F16/BF16 arms are an order of magnitude slower because their weights spill to host RAM, and none has quality evidence that would justify the wait: the sealed decision rule (handoff 20175) has no decision-cell reviews, compares builds that are not the served one, and uses 29 selected images. Human-certified ground truth removes the need for preference A/B, not for model-blind per-description review. Beta users should hear the stage, that output is a draft, and that the wait has two parts: minutes for a cold start, seconds per image.

**Related docs:**

- [E15 public-demo launch readiness epic](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
- [Caption quality and occlusion model-combination assessment](caption-quality-occlusion-model-combination-assessment-2026-10-07.md) — names the Q4 incumbent as comparator
- [FIR embeddings, dims and detectors QA report](../../../benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html) — v13 adoption bar, v15 capacity, OEC
- [GPU-LAUNCH-1 research and UX](../GPU-LAUNCH-1-research-and-ux-20260909.md)
- [Public demo WP plugin launch assessment](public-demo-wp-plugin-launch-assessment-2026-04-30.md)
- Review report (gitignored): `benchmarks/reports/qwen-high-precision-20261025/review-decision-v3/index.html`, built by DESCPICK-1 (`claude_slice_complete_DESCPICK-1_decision_report_l1_l4`)

## Executive Summary

**Model.** Ship `gpu_qwen30b` on `VM.GPU.A10.1`. It is the only description model with a serving profile, an immutable pin and required wiring on every GTM target (F1). In the operator's historical reviews it accepts 28/45 descriptions (OCR ignored) with 5/45 major-or-worse, the highest point estimate of the four reviewed models (`incumbent`, `qwen-gsq`, `mimo`, `joy`); those reviews were not blind, not independent and not sampled (F3, F4). Treat the keep as reversible, with named revisit triggers (Recommendation 1).

**Enough evidence?** Enough to keep; not enough to switch or to buy a larger GPU. The sealed rule has 0 of 86 decision cells reviewed, its candidates are F16/BF16 builds that its own deploy gate says need a Q4 rerun before serving, and 29 selected images resolve differences of roughly ±20 pp, wider than the rule's 10 pp delta (F3). The speed side is settled: on the A10 the high-precision arms are memory-bound (F2). Cost per accepted description has never been computed (F7).

**A/B.** Ground truth replaces preference A/B for the model pick: rule 20175 decides on per-cell accepted and major-error rates (`index.html:40-41`), not on preferences. It does not replace per-description review: ground truth certifies what is in the image, not whether a given description states it correctly. Keep model-blind per-cell review and set OCR on every decision cell; an unset OCR blocks the panel from unsealing and drops the incumbent's strict accepted rate from 28/45 to 2/45 (F4).

**Beta.** No speed/quality toggle: the slow arms have no measured quality gain to offer. Name the stage, disclose AI, frame output as a draft, show the cold-start and per-image waits separately with a Cancel, quote no accuracy rate from the selected set, and log accept/edit/flag so the beta produces its own accuracy and cost numbers (F6, F7). Two operator decisions gate the next panel build (Next Step).

## Findings

### F1. Only the served incumbent can ship without a release `[code]`

The `gpu_qwen30b` profile pins one immutable Q4_K_M artifact, every GTM env target selects it, and the burst tier is a 24 GB A10. The 8B and 27B exist only as bake-off entries, so switching is a release (new profile, env change, then the rule's own Q4-rerun quality gate, F3), not a config flip.

Current examples:

- `apps/prototype-description-service/scene/config/profiles.py:30` — `DescriptionProfile` has no 8B or 27B member.
- `apps/prototype-description-service/scene/config/profiles.py:105-117` — `GPU_QWEN30B` pins `unsloth/Qwen3-VL-30B-A3B-Instruct-GGUF` @ `0af19e7479857aa7f3246466a4ad16c7e7299639`, `Q4_K_M`.
- `apps/prototype-description-service/scene/config/profiles.py:118-130` — the ensemble profile reuses that artifact; only the async resolver wraps it.
- `config/env/manifest.d/10-service-shared.toml:350-358` — dev, staging, prod and demo all set `gpu_qwen30b`.
- `config/env/manifest.d/21-service-vm.toml:122-126`, `config/env/manifest.d/40-demo.toml:144-148` — `required = true`; the demo flip contract allows only `florence_small | gpu_qwen30b | gpu_qwen30b_ensemble`.
- `infra/oci/variables.tf:50-54` — `gpu_shape` defaults to `VM.GPU.A10.1`.
- `infra/oci/gpu_lifecycle/tests/test_gpu_failover.py:374` — every service env routes the burst GPU to AD2.
- `apps/prototype-description-service/scripts/eval_harness/bakeoff_candidates.yaml:52`, `:71` — `qwen3-vl-8b` and `qwen38-27b` are bake-off candidates only.

**Impact:** Keeping costs nothing and changes nothing; any switch carries its own gate and deploy.

### F2. On the A10 the high-precision arms are memory-bound, not compute-bound `[artifact]` · high

Unquantized weights do not fit in 24 GB, so the runtime offloads experts or layers to host RAM. The served Q4 timing has only a writing stage, so the writing column is the like-for-like comparison.

| Arm on A10 24 GB | Placement | Summed stages p50 / p95 (n) | Writing stage p50 |
|---|---|---|---|
| 30B-A3B Q4_K_M (served) | — | not recorded | 5.39 s (p95 9.26 s, n=12) |
| 27B Q4 (historical `qwen-gsq`) | — | 17.91 / 31.97 s (29) | 8.55 s (p95 10.38 s, n=29) |
| 30B-A3B F16 | `--cpu-moe`, experts in RAM | 112.0 / 201.5 s (28) | 57.8 s |
| 27B BF16 | 18 CUDA layers, rest in RAM | 280.0 / 395.8 s (26) | 122.1 s |
| 8B F16 | fully resident, 2 slots | 14.8 / 24.7 s (29) | 7.5 s (p95 9.0 s) |

The rule's own latency statistic uses the profile with the most joined rows, unpooled (`index.html:42`): 145.0 s p50 for the 30B F16 (profile `144645d2`, n=17) and 295.5 s for the 27B BF16 (`cc8a6365`, n=21). Decision 2574's 2.02 s p50 (p95 7.88 s, 646 images) measures a single-pass route and is not comparable with these two-stage figures.

Current examples:

- `runtime-evidence/FP16-GPU-checkpoint-identity.json:44`, `:100`, `:188` — the 30B F16 runs `--cpu-moe` with `RAM_expert_offload: true`; the A10 shows 5351 of 23028 MiB in use.
- `runtime-evidence/BF16-GPU-checkpoint-identity-C5.json:6` — the 27B BF16 places 18 layers on CUDA.
- `runtime-evidence/Qwen8-F16-GPU-checkpoint-identity-C6.json:12-13` — the 8B F16 has no RAM offload and two parallel slots.
- `gpu-performance.json:3` — stage sums exclude model load and include queueing and contention.
- `gpu-performance.json:8849` — two active slots during the 8B run; "no speedup factor inferred".
- `historical-timings.json` — `shared_extraction_seconds` is null in all 12 served-Q4 rows, hence writing stage only.
- `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html:123` — `#v15-capacity`: never infer memory fit from file size alone (SERVE-05).

**Impact:** A faster card with the same 24 GB would not remove the offload; only more VRAM or quantization does. Per image, the F16/BF16 arms move the wait from seconds to minutes (11× and 23× the served Q4's writing-stage p50).

### F3. Sealed rule 20175 cannot yield a GTM decision as built `[artifact]` · high

The rule was registered before any cross-model review, as EXP-09 requires, but it decides between three builds none of which is served, and it unseals only when every decision cell is reviewed.

Current examples:

- `index.html:11` — registered as handoff decision 20175 on DESCPICK-1, 2026-10-26, `before_any_cross_model_review: true`.
- `index.html:16` — candidates `incumbent-f16`, `qwen3-vl-8b-f16`, `qwen38-bf16`; the served Q4 is not one of them (amendment 20420 adds it; Recommendation 4).
- `index.html:43` — panel sealed until every decision cell is decision-reviewed.
- `index.html:44` — deploy gate: the 30B-A3B and 27B candidates need a Q4 rerun plus a quality gate before serving on the A10.
- `decision-build-receipt.json:11` — 86 decision cells; the build's initial review state holds 192 imported historical reviews and none for the three candidates; the operator export `benchmarks/reports/operator-reviews2.json` (2026-10-28) confirms 0 of 86 scored.
- `index.html:37-39` — 29 images, delta 0.10, paired bootstrap (2000 resamples, seed `0x51f15e`).
- `review-coverage-audit.json` — the 29 images are the earlier 12 plus a 17-image extension, selected rather than sampled.
- `model-coverage.json:53-56`, `:64` — the fourth registered model (`qwen36-bf16`) was never run; `full_four_model_report_complete: false`.

**Impact:** [est] At n=29 paired images with about 30% discordant pairs, the CI95 half-width on an accepted-rate delta is about ±20 pp, wider than the 10 pp delta and the proposed +5 pp adoption bar (FIR `#v13-caption`). The panel can at best nominate a candidate for a Q4 rerun; it cannot license a switch (AUDIT-08, EXP-12).

### F4. An unset OCR field silently removes cells from the decision `[artifact]` · high

Current examples:

- `operator-metrics.7697815fe671.js:7` — OCR values include `not_applicable`.
- `operator-metrics.7697815fe671.js:42` — OCR is optional for "Reviewed"; `not_assessed` is unknown, not an error.
- `index.html:27`, `operator-metrics.7697815fe671.js:51` — a decision-reviewed cell needs both severity and OCR set.
- `index.html:30` — "accepted" excludes OCR `not_assessed`, `wrong` and `uncertain`.
- `operator-review.603fbaeb072a.js:256` — cross-model blind mode marks a decision cell without OCR as incomplete.
- `historical-review-import.json` — 37 of the incumbent's 45 reviews leave OCR `not_assessed`; accepted falls from 28/45 (OCR ignored) to 2/45 under the rule's definition.

**Impact:** Reviewing the panel the way the history was reviewed leaves it sealed, and anything unsealed would measure OCR completion, not description quality. `not_applicable` is the right value for text-free images.

### F5. An unset adapter falls back to Florence; the settings comment is stale `[code]` · low

Current examples:

- `apps/prototype-description-service/scene/config/settings.py:78-81` — comment lists `seeded | florence_small | florence_large | gpu_phi4`; default `florence_small`.
- `apps/prototype-description-service/api/main.py:286-293` — `_resolve_description_profile()` also defaults to `florence_small`.
- `config/env/manifest.d/22-service-fir.toml:166-169`, `config/env/manifest.d/23-service-aura.toml:138-141` — svc-fir and svc-auraface override only the example (`seeded`) and inherit `required = false`.

**Impact:** GTM targets require the variable (F1), so only dev services can drift to Florence. The comment still misdirects; FIR `#v13-caption` treats Florence as configuration drift, not the baseline.

### F6. Users face two waits; the public demo cannot cancel `[code]` · medium

The cold start dominates the first request; the model sets only the per-image wait. A START path exists on `main`, but its finding has not been reconciled.

Current examples:

- `infra/oci/gpu_lifecycle/controller.py:71-81` — `start_needed_instances` emits START for STOPPED burst instances. Finding 10035 (DEMO-UX-1-GPU-01, high, "no START path") is `resolved_on_branch` at `016789be8d` on `feature/defwave-2`, which is not an ancestor of `main`.
- `apps/prototype-wp-alt-context/js/admin/hooks/jobMachine.ts:105`, `:211-216` — 510 s startup budget; warming follows it so a cold start is not shown as a stall.
- `apps/prototype-wp-alt-context/js/admin/guidedPrototype/liveDescription.ts:79-86` — 510 s warm-up plus 180 s generation: a 690 s cold-start ceiling.
- `apps/prototype-wp-alt-context/src/api/class-public-demo-describe-controller.php:81` — demo proxy warm-up timeout 510 s.
- `apps/prototype-wp-alt-context/js/public/demo-describe.js:282-285` — demo copy: "A cold start can take several minutes…".
- `apps/prototype-wp-alt-context/js/public/demo-describe.js:141-157` — the wait ends only on deadline or navigation. No Cancel control in `demo-describe.js` or `src/public/class-public-demo-shortcode.php` (only these two files searched).
- `apps/prototype-wp-alt-context/js/admin/pages/settings/GpuControlCard.tsx:502` — admin copy: "Warming up, this can take a few minutes".

**Impact:** A beta tester's first impression is set by GPU warm policy, not model choice; a high-precision arm would add minutes per image on top.

### F7. Cost per accepted description has never been computed `[artifact]` · medium

Current examples:

- `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html:483` — `#oec`: cost per accepted description "has never been computed" (COST-04).
- `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html:554` — metric M-09, "never computed".
- `[handoff]` 2265 (A10 about $2/h) and 2459 (always-on about $1,400/month).

**Impact:** [est] Using the historical 28/45 accepted rate, $1,400 ÷ (1,000 images × 0.622) ≈ $2.25 per accepted description, or ≈ $0.22 at 10,000 images a month. At beta volume utilization drives cost, not model choice; no cost case for a larger GPU exists yet.

## Recommendations

### 1. Ship `gpu_qwen30b` on the A10 as a reversible keep

**Traces:** F1, F2, F3
**Priority:** P0

No profile, env or shape change. Record the keep as reversible (NDM-25) with three revisit triggers: a decided panel whose Q4 rerun passes a quality gate on the A10, gated on the major-error delta rather than aggregate retention (SERVE-07, CARD-28); a beta accept rate below a floor registered before launch; a priced, available ≥80 GB shape (2455). Say "kept", not "won".

### 2. Set beta expectations; no speed/quality toggle

**Traces:** F6, F2
**Priority:** P0

Content for the beta copy:

1. Stage (PROD-39): the product is in beta.
2. Disclosure and role (HAI-05, HAI-12): descriptions are AI-generated drafts to review before publishing.
3. How well it works (Amershi G2), qualitatively: expect to correct some drafts, especially unsupported details, who-does-what, counts and attributes, text in the image and identities — the rule's factual-issue classes (`index.html:31`). Quote no rate from the selected set (AUDIT-08).
4. Two waits (INT-08): the first request after a quiet period starts the GPU and can take several minutes; after that each image takes seconds. Offer Cancel. Quote p95, not the mean (PERF-01), after an end-to-end re-measure; 12 writing-stage rows are too thin.
5. The tradeoff, stated plainly: larger models were tested; on current hardware they took minutes per image with no measured accuracy gain, so the beta uses the faster model. Flagging a wrong draft informs the next choice.

A toggle would offer a minutes-long wait for an unproven gain on a build that cannot be served (F1, F3).

### 3. Make the beta produce its own accuracy and cost numbers

**Traces:** F7, F3
**Priority:** P1

Log accept / edit / flag per description with profile and revision (AIPX-03). Compare the ground-truth accepted rate with the online accept rate on overlapping images as descriptive evidence only; the offline proxy stays unvalidated until a controlled experiment shows that offline deltas predict online accept deltas (EVAL-22). Compute cost per accepted description from GPU-hours (COST-04) and replace the estimate in F7.

### 4. Amend the rule, then finish the model-blind panel

**Traces:** F3, F4
**Priority:** P1

Operator decision first (EXP-09): add the served Q4 incumbent as a fourth candidate before any decision cell is scored, so a result is deployable without the Q4-rerun loop (`index.html:44`) and the served build is the baseline (EVAL-01). Amending after scoring starts would be peeking. Approved 2026-10-28 as amendment 20420 (`incumbent-q4km`), before any decision cell was scored. Hold decision scoring until the four-candidate panel is built, so all four are reviewed in one counterbalanced pass (EVAL-14). Then review in "Cross-model blind review" mode (`operator-review.603fbaeb072a.js:5`; EVAL-14): set OCR on every decision cell (`not_applicable` when there is no text), pixel-check any claim absent from ground truth (19285), and export JSON regularly (`OPERATOR_REVIEW.md:15`). Size the decision on design-effect n_eff (CARD-27) and check that accepted rate does not rise with word count (CARD-30). An automated judge scoring descriptions against ground truth could later cut review time, but only after its agreement with these human cells is measured (EVAL-14).

### 5. Prove the cold start end to end; add Cancel to the public demo

**Traces:** F6
**Priority:** P2

Reconcile finding 10035 with `controller.py:71`, then run one cold start from STOPPED on the demo path and record the measured wait. Add a Cancel control to the public demo wait (INT-08) and align the admin and demo warm-up copy.

### 6. Sync the adapter comment

**Traces:** F5
**Priority:** P3

Update `settings.py:78` to list the current profiles and note that GTM targets require the variable.

## Code-Verified Critique

### What the assessment gets right

- F1 is code-backed end to end: profile, env manifests, failover test and shape agree.
- F2 rests on runtime identity files (offload flags, CUDA layer count), not file size (SERVE-05).
- F4 is reproducible from the incumbent's own history: 28/45 accepted becomes 2/45 under the sealed definition.

### Where the assessment overstates the problem

- The ≥80 GB option is an estimate. [est] The 30B-A3B reads about 6 GB per token at F16 (about 3B active parameters) versus about 1.7 GB at Q4, so it would approach today's Q4 speed only on a card with roughly 3× the A10's memory bandwidth. Unmeasured, unpriced, and subject to capacity risk (2455).
- The 8B F16 is not ruled out on speed. Its writing-stage p50 (7.5 s, under two-slot contention) is close to the served Q4's 5.39 s; it is ruled out on evidence (no reviewed cells, no profile). [est] At about 16 GB per token it cannot decode faster than the Q4 MoE on the same card.
- The served Q4 latency is thin: 12 writing-stage rows; decision 2574 measures a different route.
- The historical 27B Q4 (9/42 major-or-worse) versus the incumbent (5/45) is neither significant nor blind, and the incumbent's 45 reviews cover about 23 images across two lexicon arms (CARD-27).
- Finding 10035 may be bookkeeping only: the START path is on `main`.

### Recommendations the assessment is missing

**R-MISS-1. Page context is untested.** The decision filter selects lexicon-off arms (`index.html:15`), and no arm in the report supplies page context, the product's differentiator. A ranking on image-only prompts may not hold once context is in the prompt; add a context arm before any switch decision.

**R-MISS-2. Degraded mode is undecided.** When the GPU is unavailable the product can wait or degrade (COST-10). The demo flip contract permits `florence_small` (`40-demo.toml:144-148`; about 14 s/image on the A1 CPU per `21-service-vm.toml:122-126`), and `florence-reference-120.json` exists in the report, but Florence has never been scored against ground truth. Decide the policy, and disclose a degraded result if one is shown (HAI-05).

## Canon Validation

Heuristics canon v0.26.2; mechanisms checked against the distilled corpus.

| Canon row | Rule | Verdict here |
|---|---|---|
| COST-06 | Eliminate work before buying hardware | Defer the ≥80 GB shape; Q4 already removes the offload. |
| COST-10 | Graceful degradation under budget | Open (R-MISS-2). |
| COST-04 | Cost per accepted output | Never computed (F7); Recommendation 3. |
| NDM-25 | Reversible trial | Keep with named triggers (Recommendation 1). |
| EXP-09 | No peeking | Amend before any decision cell is scored (Recommendation 4). |
| EXP-12 | Power and practical significance | n=29 cannot resolve 10 pp (F3). |
| EVAL-01 | Require offline baselines | The served Q4 belongs in the panel (Recommendation 4). |
| SERVE-07 | Quality-gate behaviour-changing serving optimizations | Any F16-to-Q4 path needs a quality gate (`index.html:44`). |
| SERVE-05 | KV-cache capacity budget | Fit read from runtime identity, not file size (F2). |
| EVAL-14 | Counterbalance and measure judge bias | Counterbalanced model-blind per-cell review; no preference A/B. |
| PROD-39 | Communicate product stage | Name the beta (Recommendation 2). |
| HAI-05 | Imperceptible AI is not ethical | Disclose AI and any degraded result. |
| HAI-12 | Output is a proposal, not the answer | Frame descriptions as drafts. |
| AUDIT-08 | Probability sample before a design-based interval | Quote no accuracy rate from the selected 29. |
| INT-08 | Wait state and cancel | Two waits; the demo lacks Cancel (F6). |
| PERF-01 | Percentiles, not averages | Quote p95 after re-measure. |
| AIPX-03 | Instrument the flywheel | Accept/edit/flag telemetry. |
| EVAL-22 | Validate the offline proxy against online impact | Unvalidated; the beta overlap comparison is descriptive (Recommendation 3). |

Reasoning cards: CARD-27 (seal the margin; size the floor from design-effect n_eff), CARD-28 (gate a quantization on the failure-metric delta, not aggregate retention), CARD-30 (signal density, not length).

Distilled-corpus mechanisms (`heuristics-canon-research/distilled/`):

- `ml-systems/systems-performance-gregg.md:41` — search eliminate, cache, less, later, off-peak, concurrent before buying hardware (COST-06 at `:62`).
- `ml-systems/guidelines-human-ai-interaction.md:21` — G2: "Make clear how well the system can do what it can do."
- `business/perri-escaping-the-build-trap.md:311-316`, `:435` — Alpha, Beta and GA stage labels; promises match the stage.
- `ml-systems/lohr-sampling-design-analysis.md:29` — judgment samples yield leads, not population estimates.

## Priority Ordering

| Priority | Change | Impact | Effort | Trace |
|----------|--------|--------|--------|-------|
| **P0** | Keep `gpu_qwen30b` on the A10; record revisit triggers | No regression; reversible | Decision only | F1, F2, F3 |
| **P0** | Beta copy: stage, AI disclosure, drafts, two waits | Honest expectations without an accuracy claim | S | F6, F2 |
| **P1** | Accept/edit/flag telemetry, descriptive overlap comparison, cost per accepted | The beta measures its own accuracy and cost | M | F7, F3 |
| **P1** | Amend rule 20175, then model-blind review with OCR set | A decidable, deployable panel | Operator time, 86+ cells | F3, F4 |
| **P2** | Verified cold start; Cancel on the public demo | Removes the worst wait failure | S–M | F6 |
| **P3** | Sync the adapter comment | Removes a misleading comment | XS | F5 |

## Deferred or Rejected Directions

- **Deferred: ≥80 GB GPU shape.** Eliminate work first (COST-06), measure the quantization delta on major errors before paying for precision (CARD-28), and price the capacity risk (2455).
- **Deferred: 8B F16.** No reviewed cells, no profile, and [est] no decode-speed advantage over the Q4 MoE.
- **Rejected: preference A/B for the model pick.** Ground truth plus counterbalanced per-cell review is the stronger instrument, and the rule does not consume preferences (EVAL-14).
- **Rejected: a user-facing speed/quality toggle for beta.** There is no measured gain to offer (F3).
- **Rejected for interactive use: F16/BF16 with RAM offload on the A10.** Minutes per image (F2).

## Suggested Spec Direction

One spec under E15 covering Recommendations 2, 3 and 5: stage label, AI disclosure, draft framing, two-wait presentation with Cancel on the public demo, aligned warm-up copy, accept/edit/flag events and the cost-per-accepted query. All copy goes through gettext (`__()`, `wp.i18n`, text domain `alt-context`; sr-012). The rule amendment and panel rebuild are an operator decision plus a DESCPICK-1 rebuild, not spec work. No ADR: the model decision is a keep.

## Next Step

- [x] Operator export: `benchmarks/reports/operator-reviews2.json` (2026-10-28); 0 of 86 decision cells scored.
- [x] Operator approved the served Q4 incumbent as a fourth candidate: amendment 20420 (2026-10-28), before any decision cell was scored.
- [ ] Collect the Q4 cells on the A10 with the decision profile, then build the four-candidate panel (rule 20175 plus amendment 20420) before decision scoring starts.
- [ ] Review page: give exported JSON a local-timestamp default file name (operator request, 2026-10-28).
- [ ] Align the production serve command with the measured profile or quality-gate the difference (SERVE-07): `infra/oci/gpu-cloud-init.yaml:330-341` runs the floating `server-cuda` tag with only `--ctx-size 8192`, while the decision profile pins an image digest and sets offload, parallelism and token limits.
- [ ] Write a spec (path: `docs/specs/e15-beta-expectations-and-telemetry-spec.md`) for Recommendations 2, 3 and 5.
- [ ] No spec needed for Recommendation 1 (a recorded decision) or Recommendation 6 (a comment sync).

## References

- Heuristics canon v0.26.2: rows under Canon Validation; reasoning cards CARD-27, CARD-28, CARD-30.
- Handoff decisions: 20175 (sealed rule), 20400 (advisory keep), 19285 (pixel-check), 2574 (VLM-6 latency), 2265 (A10 rate), 2459 (always-on cost), 2455 (≥80 GB capacity risk); DESCPICK-1 slice `claude_slice_complete_DESCPICK-1_decision_report_l1_l4`.
- Report artifacts (gitignored, root checkout) in `benchmarks/reports/qwen-high-precision-20261025/review-decision-v3/`: `index.html`, `OPERATOR_REVIEW.md`, `operator-metrics.7697815fe671.js`, `operator-review.603fbaeb072a.js`, `decision-build-receipt.json`, `review-coverage-audit.json`, `model-coverage.json`, `gpu-performance.json`, `historical-timings.json`, `historical-review-import.json`, `runtime-evidence/`.
- `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`: `#v13-caption`, `#v14-experiment`, `#v14-freeze`, `#v15-capacity`, `#oec`, `#metrics`.
