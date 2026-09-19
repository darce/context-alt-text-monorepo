# GPUFLOW-3 N4 — position-accuracy evaluation and enablement gate

Date: 2026-09-19
Status: `NEEDS_OPERATOR` — this is the locked protocol and review checklist;
no completed labelled run or operator sign-off is present in this worktree.

## Decision and scope

N4 is an analysis-only gate. It must be completed before enabling either the
GPU person-grounding flag or an `n >= 2` naming rule. The frozen plan names this
lane as the evaluation protocol for position accuracy and requires the metric,
labelled sample, group-size and occlusion intervals, abstention rule, and
enablement bar [docs/tasks/v0.5.0/GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md:299-307].
The existing `n == 1` substitution remains the only naming rule covered by the
wave; any other count must remain on the fallback path until this gate is
accepted [docs/tasks/v0.5.0/GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md:279-287].

This document changes no production setting, prompt, adapter, realizer, wire
enum, or report implementation. The operator may run an analysis copy of a
candidate with grounding enabled, but the production setting remains off until
the acceptance checks below are complete. The adapter already makes grounding
explicitly flag-controlled and returns an empty phrase-box set on follow-up
failure [apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:350-395,468-530].

The N3 contract is also a safety boundary for this evaluation: the grounding
request uses exact caption substrings and normalized boxes, and a missing,
malformed, or unlocatable box is represented by no box rather than a fabricated
one [apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:55-64,803-839].
That outcome is an abstention, not permission to attach the nearest name.

## What is being measured

### Position accuracy

The unit of evaluation is one labelled person position in one image. Every
visible person is annotated either as a roster target or as an unknown/non-roster
distractor. A positive target is eligible only when an operator has supplied:

* a canonical roster identity (unknown/non-roster labels are safety distractors,
  not positive accuracy targets);
* a positive, normalized face/person box in the original image coordinate
  system; and
* enough visible evidence for two independent annotators to agree that the
  identity is judgeable.

The labelled target order is viewer-left to viewer-right by normalized box
centre, with centre-y and then the canonical name as deterministic tie-breakers.
This is the repository's shared spatial ordering rule
[apps/prototype-description-service/scripts/eval_harness/face_metrics.py:232-244].
Missing or malformed labelled order is not an empty, all-wrong sequence: the
image is excluded from positional scoring and recorded as `order_unknown`, as
the harness requires [apps/prototype-description-service/scripts/eval_harness/face_metrics.py:476-506].

For each eligible target `t`, the scorer makes at most one prediction:

| Outcome | `hit` | `abstain` | Wrong-name event |
| --- | ---: | ---: | ---: |
| The emitted name and grounded region identify the labelled person | 1 | 0 | 0 |
| No usable association, no phrase box, an ambiguous association, or an explicit neutral/unknown result | 0 | 1 | 0 |
| A name is attached to a different labelled person, a stranger, or an identity-void region | 0 | 0 | 1 |

`position_accuracy` is the position-wise name attachment rate:

```text
position_accuracy = position_hits / position_total
position_total    = eligible labelled person positions
position_hits     = positions whose attached name is the correct canonical name
```

An abstention therefore remains visible as a miss in the accuracy denominator;
it must never be converted into a guessed label. A wrong name is both an
accuracy miss and a separately fatal safety event. If `position_total == 0`,
the result is `null` with `status=not_evaluable`, never a clean zero or pass.
This is compatible with `PositionalIdResult.position_accuracy`, whose value is
`position_hits / position_total`, and with its explicit non-evaluable status
[apps/prototype-description-service/scripts/eval_harness/face_metrics.py:754-785].

The evaluator must preserve the full association ledger in addition to the
ordered sequence:

```text
image_id, target_id, target_name, target_box, group_size, occlusion,
predicted_name, predicted_box, outcome, reason, model_id, prompt_version
```

The ordered metric must be computed from centre-ordered predictions, not from
alphabetical or storage order. A set-based identity score is insufficient: the
harness test demonstrates that a left/right swap can retain perfect set-based
precision/recall while falling to `1/3` positional accuracy
[apps/prototype-description-service/scene/tests/test_eval_harness_report.py:2306-2368].
Report `exact_order_rate`, `swap_images`, `position_hits`, `position_total`,
`abstain_count`, and `coverage` alongside `position_accuracy`; exact order is a
diagnostic and does not replace the position-wise score
[apps/prototype-description-service/scripts/eval_harness/face_metrics.py:792-850].

### Robust gate estimate

The pooled `position_accuracy` is required for compatibility and auditability,
but it is not sufficient by itself. To follow EMB-02, the adoption decision uses
an image-clustered, quality-weighted estimate so a crowded, blurred, or repeated
identity cannot dominate a raw target-level mean:

1. Remove only identity-void target rows from the accuracy denominator and
   compute `a_i = hits_i / targets_i` for each image with at least one remaining
   eligible target; an abstention is a zero in `hits_i` and a target in
   `targets_i`. For a mixed image, `q_i` below is the mean pre-run quality of
   its remaining eligible targets. An image with no eligible target is
   safety-only.
2. Assign the pre-run annotation weight `q_i = 1.0` when two annotators agree
   without adjudication and `q_i = 0.5` when an adjudicator resolves a genuine
   disagreement while retaining a judgeable identity. The model output may not
   change `q_i`; wrong-name events are always counted at full severity.
3. Compute `gate_accuracy = sum(q_i * a_i) / sum(q_i)` (one image, one bounded
   contribution), and also publish the unweighted pooled `position_accuracy`.
4. Resample complete image clusters, not individual targets, for a deterministic
   95% bootstrap interval. The seed is
   `sha256(manifest_sha256 + model_id + model_revision + prompt_version)` and
   the run records the bootstrap count and seed. A target-level Wilson interval
   may be shown as a cross-check, but it is not the adoption interval.

The gate requires both estimates and the lower interval; a high weighted value
cannot hide a low pooled value or a failing stratum. Identity-void target
observations have `q = 0` and are not eligible for either accuracy denominator.
They remain
in the abstention and false-name safety ledger below. This is the explicit
CAL-02/EMB-02 treatment of unknown: remove identity-void evidence from the
claim denominator, not from audit visibility, and abstain rather than force a
classification.

## Labelled sample and frozen splits

The current seed cannot certify this gate. Its 37-image golden corpus has
`face_boxes` on `0/37`, so positional scoring never runs
[apps/prototype-description-service/scripts/eval_harness/README.md:232-264].
The existing held-out file is only a preserved 20-image reporting half and is
not a substitute for a newly labelled position corpus
[apps/prototype-description-service/scene/tests/seed/README.md:89-100].

The operator must create a locked, model-blind position manifest with these
fields for every image and target:

| Field | Requirement |
| --- | --- |
| `media_id`, relative path, image SHA-256 | Stable, immutable image identity; no duplicate bytes across splits. |
| `target_id`, canonical name, `face_box` | One row per visible roster person; normalized top-left coordinates and a positive box. Include non-roster faces as `unknown` distractors. |
| `group_size`, `stranger_count` | `group_size` is the number of visible human persons; `stranger_count` is retained separately. The `n >= 2` subset requires at least two eligible named targets. |
| `occlusion` | Per-target `clean`, `partial`, `heavy_identifiable`, or `identity_void`; the last category is never silently relabelled as a scored target. |
| `label_quality`, reviewer IDs, adjudication note | `high`/`q=1.0` consensus or `adjudicated`/`q=0.5`; identity disagreement that cannot be resolved is `identity_void`. |
| `manifest_sha256`, label revision, split | Frozen digest, annotation revision, and `calibration` or `locked_test`. |

Use independent annotators before any candidate output is shown. A third
adjudicator resolves only label disagreements; it may not remove a model error.
The locked test is not used for prompt, threshold, phrase-box, or naming-rule
tuning. Keep identity and source-image overlap out of the calibration/test
boundary where the available corpus permits. Record the candidate's model
revision, quantization, adapter revision, prompt/task version, grounding
timeout, and production flag state in the run provenance; these are existing
adapter identity/configuration fields [apps/prototype-description-service/scene/infrastructure/vlm/gpu_remote_adapter.py:350-395].

### Required strata and denominators

Report both the nine joint cells and the six marginal strata below. A cell is
formed from the target's eligible group-size and occlusion labels; a mixed
image may contribute different target rows to different occlusion marginals,
but image-cluster bootstrap keeps those rows together.

| Dimension | Required strata | Minimum locked evidence per joint cell |
| --- | --- | ---: |
| Eligible named group size | `G1=1`, `G2=2`, `G3+=3 or more` | 50 distinct image clusters and 75 eligible target positions |
| Occlusion | `O0=clean`, `O1=partial`, `O2=heavy_identifiable` | 50 distinct image clusters and 75 eligible target positions |

The minimum applies to each of the nine `Gx × Ox` cells. The `G1` cells need
75 images because each contains only one eligible target; larger groups can
reach 75 positions with fewer images but still need 50 image clusters. Add at
least 50 `identity_void` safety images, distributed across visible group sizes,
and retain at least 25 with a non-roster stranger. If a cell or required
marginal cannot meet these floors, its estimate and interval are `null` and
the gate is `needs_operator`; do not pool it into a superficially large
aggregate.

Synthetic occlusion may be an explicitly labelled stress supplement, not a
replacement for real labelled frames. The repository's synthetic protocol
already distinguishes `masked`, `sunglasses`, and `occlusion_other`, excludes
structurally deficient galleries from the denominator, counts re-detect misses
inside eligible frames, and requires a named eligible-pair floor
[apps/prototype-description-service/scripts/eval_harness/synthetic_occlusion.py:1-20,570-618].
If synthetic frames are used, retain their generator seed, source media ID,
clean-detection eligibility, and `synthetic=true`; report real and synthetic
results separately before any combined diagnostic.

## Abstention and fail-closed rules

The following are required scoring rules, not optional operator judgement:

* A missing, malformed, out-of-image, non-positive, duplicate/ambiguous, or
  non-caption span is `abstain` for the affected target. It cannot be repaired
  by selecting the nearest face or by using alphabetical name order.
* An image with no judgeable identity is `identity_void`. No position accuracy
  denominator is created, and a neutral/empty result is safe. Any emitted
  roster name on an identity-void person or stranger is a wrong-name event.
* A candidate may abstain on all ambiguous targets. This is safe but not free:
  every eligible abstention lowers `position_accuracy` and `coverage`.
* A wrong name, a swapped attachment, or a name attached to a stranger is not
  an abstention. It is counted in `wrong_name_total` and fails the safety gate.
* An output that cannot be traced to one exact caption substring and one
  normalized phrase box is not an evaluated hit. Do not fabricate a span or
  infer a missing box.
* `recognition_enabled=false`, missing `face_boxes`, or
  `labeled_order_known=false` is an excluded/order-unknown row, not an accuracy
  zero. Exclusions are reported and reduce the required sample rather than
  disappearing from the denominator [apps/prototype-description-service/scripts/eval_harness/face_metrics.py:792-850].

For every run publish:

```text
coverage            = (hits + eligible_wrong_name_targets) / eligible_targets
abstain_rate        = abstain_count / eligible_targets
wrong_name_total    = wrong_names_live + ignored_wrong_names
wrong_name_image_rate = unique images with any wrong name / scored images
identity_void_named = names emitted on identity-void targets
```

`coverage` is diagnostic only when `wrong_name_total > 0`; a model must not
trade a wrong name for a higher coverage number. `position_accuracy` is
`null` when no eligible targets remain after the pre-run label rules. Any
`null` interval, vacuous category, or under-powered cell forces abstention from
enablement, consistent with the harness's explicit `not_evaluable` and
category-vacuity handling [apps/prototype-description-service/scripts/eval_harness/face_metrics.py:763-767; apps/prototype-description-service/scripts/eval_harness/report.py:1661-1754].

## Wrong-name ledger and ignore-list binding

The gate counts every wrong-name assertion, including rows moved to an operator
ignore list. The repository deliberately keeps `wrong_names` and
`ignored_wrong_names` separate for presentation but defines the hard count as
their sum [apps/prototype-description-service/scripts/eval_harness/report.py:1599-1630].
The presentation split also explicitly says that a side file must not zero a
hard gate [apps/prototype-description-service/scripts/eval_harness/report.py:2457-2470].

For N4:

```text
wrong_name_total = len(wrong_names_live) + len(ignored_wrong_names)
```

The pass bar is `wrong_name_total == 0`, including identity-void and stranger
rows. An ignore list therefore cannot turn a failed run into an accepted run.
If an operator supplies one for triage, the evidence must include its exact
sorted contents, SHA-256, author, timestamp, and the commit ID that produced
it; a missing or unbound digest is independently `needs_operator`. This keeps
the audit trail useful without treating triage as deletion.

## Confidence intervals and acceptance bars

For every joint cell, every group-size marginal, every occlusion marginal, and
the global result, publish:

```text
n_images, n_targets, hits, abstains, wrong_name_total,
position_accuracy, gate_accuracy, 95% cluster-bootstrap CI,
coverage, exact_order_rate, status
```

The status is `scored` only when all structural and sample floors hold;
otherwise it is `not_evaluable` or `needs_operator`. Intervals are two-sided
95% percentile intervals over complete image clusters, with the lower endpoint
used for the gate. A target-level Wilson interval may be included for
comparison, but it cannot override a cluster-bootstrap lower bound or a sparse
cell. This prevents repeated faces from pretending to be independent evidence.

### Shared pass bar for the grounding flag

The analysis candidate may be proposed for the grounding flag only when every
condition below is true:

1. All nine joint cells and six marginals meet the sample floors; no required
   interval or status is `null`, `not_evaluable`, or `needs_operator`.
2. Global unweighted `position_accuracy >= 0.95` and robust `gate_accuracy >=
   0.95`; both 95% cluster-bootstrap lower bounds are `>= 0.90`.
3. Each group-size and occlusion marginal has unweighted and robust point
   estimate `>= 0.90`, with robust 95% lower bound `>= 0.90`. The `O2`
   marginal is not waived as a stress case.
4. `coverage >= 0.90` globally and in every `G2`, `G3+`, and `O2` marginal.
   Abstention is safe but the candidate is not useful enough to enable if it
   cannot reach this floor.
5. `wrong_name_total == 0`, `identity_void_named == 0`, no fabricated or
   out-of-image association survives parsing, and the full wrong-name ledger is
   present and reproducible.
6. The candidate does not regress the existing `n == 1` baseline on `G1` or
   any occlusion marginal; compare both candidates on the same locked images.

If one item fails, keep the production grounding flag off. A measured value at
or below the repository's binary-chance quality floor is a hard failure, not a
soft sparse result [apps/prototype-description-service/scripts/eval_harness/report.py:276-305,1795-1813].

### Additional bar for an `n >= 2` naming rule

The `n >= 2` rule has a stricter scope gate in addition to the shared bar:

* `G2` and `G3+` each independently meet the point, lower-bound, coverage, and
  zero-wrong-name requirements; an aggregate that passes while either cell is
  sparse or red is insufficient.
* The candidate's ordered output is evaluated against the labelled boxes, not
  just against the set of names. Swaps, duplicate-name collapse, and a correct
  name on the wrong face remain failures.
* The `G1` path remains the already accepted `n == 1` behavior; a multi-person
  rule may not alter it. If a candidate cannot preserve that baseline, keep the
  `n >= 2` rule off even if its multi-person score passes.
* Grounding remains fail-closed for all malformed or ambiguous rows. No
  positional fallback may be promoted into a multi-person naming rule merely
  because the candidate abstained.

Passing the grounding bar does not automatically pass the `n >= 2` bar. The
operator records two explicit decisions, and both remain off until the relevant
decision is signed.

## Operator evidence checklist

Attach one immutable report for the locked run containing:

- the manifest digest, label revision, split membership, annotator/adjudicator
  record, and counts for all nine cells plus safety images;
- model ID/revision, quantization, adapter commit, prompt/task version,
  grounding timeout, candidate flag state, and deterministic bootstrap seed;
- the complete per-target ledger, including abstentions, invalid-box reasons,
  strangers, identity-void rows, swaps, and duplicate/ambiguous associations;
- pooled `position_accuracy`, robust `gate_accuracy`, exact-order diagnostics,
  coverage, abstain rate, all confidence intervals, and all sparse/vacuity
  reasons;
- live and ignored wrong-name arrays, their combined count, and—if an ignore
  list exists—the sorted file digest and commit binding; and
- separate verdict fields: `grounding_flag_gate` and `n_ge_2_rule_gate`, each
  one of `accepted`, `fail`, or `needs_operator`, with operator, UTC timestamp,
  and sign-off.

Do not report a single global mean as sufficient evidence. Do not replace a
missing interval with zero error, and do not treat the current 37-image golden
or 20-image held-out fixtures as this gate's completed sample. The existing
harness's own distinction between a measured quality-floor failure and an
unmeasured category-vacuity result is the required reporting model
[apps/prototype-description-service/scripts/eval_harness/report.py:1933-1951].

## Residual risk and handoff

This artifact defines the acceptance contract but contains no measured locked
run. The residual risk is therefore model- and corpus-dependent: the current
fixtures lack the positional labels needed to estimate the intervals, and
operator annotation quality, identity overlap, real occlusion coverage, and
candidate provenance remain to be supplied. Until that evidence is attached,
downstream lanes may consume the metric and ledger shape for review only; they
must not enable the grounding flag or introduce an `n >= 2` rule.

The frozen cross-lane contract remains unchanged. In particular, unknown or
ambiguous naming outcomes must retain the closed naming-status values and be
rendered neutrally by consumers; this assessment does not add a wire value
[docs/tasks/v0.5.0/GPUFLOW-3-demo-triage-identity-gpu-lifecycle-and-unified-queue-task-plan.md:69-89].

Verdict: needs_operator
