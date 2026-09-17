# GPUFLOW-2 C1 — cluster-recovery calibration review

Date: 2026-09-16
Status: `NEEDS_OPERATOR` (numeric review artifact; no runtime setting is promoted)

This document is the C1 handoff artifact. It records the labelled demo case,
the numeric observations that are actually available in this worktree, the
pairwise recovery decision, and a provisional policy block for operator review.
The policy is not accepted merely because a row clears a configured threshold:
the frozen plan requires per-stratum floors, an explicit sparse-stratum
abstention rule, and a false-name gate before C2 or quality consumers may copy
the block [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:340-344,192-193].

## Evidence boundary and decision

The saved demo evidence is a real recognition run from 2026-09-06, but it is a
saved result rather than a live C1 calibration run [docs/assessments/current/guided-prototype-face-recognition-2026-09-05.md:277-281]. It gives two usable
same-identity gallery scores for the press photo (`0.742` for Katy Perry and
`0.686` for Justin Trudeau) [docs/assessments/current/guided-prototype-face-recognition-2026-09-05.md:283-288]. It does not provide the Watson triple's
embedding vectors, quality scores, runner-up scores, or source-media IDs, and
the earlier wrong-person Trudeau → Watson row explicitly preserves those
fields as `NOT CAPTURED` [docs/assessments/GPUFLOW-1-rebaseline-20260914.md:84-99].

Therefore:

* the two saved scores are descriptive genuine-pair observations, not a
  promoted threshold fit;
* the Watson pairwise cosine cells and all missing runner-up/impostor cells are
  `null`, never back-filled from a label or a visual resemblance;
* every quality stratum is abstained until at least the declared labelled-pair
  floor is met; and
* the numeric policy below is `needs_operator`. C2 stays feature-flagged off
  until an operator accepts a completed, disjoint calibration run, as required
  by the task plan [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:148-153,51-64].

## Labelled demo ground truth

The labels below are stable aliases for this report, not database identity IDs.
The press image contains two distinct faces: Trudeau on the left and Perry on
the right [docs/assessments/current/guided-prototype-face-recognition-2026-09-05.md:285-288]. The Watson aliases represent the three same-person residues
reported for `emma_watson_14-scaled.jpeg`; the defect is that one person is
rendered as three unnamed cards after singleton refinement [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:39-39].

| Alias | Canonical label | Role in the demo | Expected relation |
| --- | --- | --- | --- |
| `W1` | Emma Watson | Watson residue 1 | Same identity as `W2`, `W3` |
| `W2` | Emma Watson | Watson residue 2 | Same identity as `W1`, `W3` |
| `W3` | Emma Watson | Watson residue 3 | Same identity as `W1`, `W2` |
| `P_G` | Katy Perry | Clear gallery/reference face | Same identity as `P_P`; distinct from all `T_*` |
| `T_G` | Justin Trudeau | Clear gallery/reference face | Same identity as `T_P`; distinct from all `P_*` |
| `P_P` | Katy Perry | Press-Tribeca face on the right | Same identity as `P_G`; distinct from `T_P` |
| `T_P` | Justin Trudeau | Press-Tribeca face on the left | Same identity as `T_G`; distinct from `P_P` |

`P_P` and `T_P` are the mixed press residual when the two faces are treated as
one unlabelled group. It must not be attached to either named destination:
the plan's target outcome is a recovery merge for the Watson residue, but no
automatic merge across two named people [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:121-122,562-570].

## Captured score ledger

These are the numeric values available for review. A score in this table is a
saved query-to-gallery similarity, not a substitute for a complete symmetric
face-to-face matrix or for the missing quality/runner-up fields.

| Probe | Gallery identity | Similarity | Source condition | Calibration use |
| --- | --- | ---: | --- | --- |
| `P_P` | Katy Perry | `0.742` | Press-Tribeca, right face, turned slightly | Genuine-pair example; base pair floor passes |
| `T_P` | Justin Trudeau | `0.686` | Press-Tribeca, left face | Genuine-pair example; base pair floor passes |
| Coachella Perry | Katy Perry | `0.965` | Hand over mouth; evidence-only image | Context only; not in the bundled calibration set |
| Coachella Trudeau | Justin Trudeau | `0.972` | Backwards cap; evidence-only image | Context only; not in the bundled calibration set |
| Small-face Perry | Katy Perry | `0.662` | Coachella noodles; evidence-only image | Context only; not a C1 pair floor |
| Small-face Trudeau | Justin Trudeau | `0.692` | Coachella noodles; evidence-only image | Context only; not a C1 pair floor |
| Profile Perry | Katy Perry | `null` | Tribeca foreheads-touching example | No-match/score not captured |
| Profile Trudeau | Justin Trudeau | `0.554` | Tribeca foreheads-touching example | Context only; below current accept boundary |

The ledger values and their evidence-only status are recorded in the saved
demo report [docs/assessments/current/guided-prototype-face-recognition-2026-09-05.md:287-294]. The `0.742` Katy row is the representative acceptance
example below, but its policy-level runner-up margin and quality stratum are
still missing.

## Pairwise cosine matrix

The diagonal `1.000*` values are the mathematical self-similarity convention,
not model output. `null` means that no pairwise cosine was captured in the
available evidence. The two off-diagonal numeric cells are the saved
gallery-score edges above; no unrecorded cross-person score is inferred.

|  | `W1` | `W2` | `W3` | `P_G` | `T_G` | `P_P` | `T_P` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `W1` | `1.000*` | `null` | `null` | `null` | `null` | `null` | `null` |
| `W2` | `null` | `1.000*` | `null` | `null` | `null` | `null` | `null` |
| `W3` | `null` | `null` | `1.000*` | `null` | `null` | `null` | `null` |
| `P_G` | `null` | `null` | `null` | `1.000*` | `null` | `0.742` | `null` |
| `T_G` | `null` | `null` | `null` | `null` | `1.000*` | `null` | `0.686` |
| `P_P` | `null` | `null` | `null` | `0.742` | `null` | `1.000*` | `null` |
| `T_P` | `null` | `null` | `null` | `null` | `0.686` | `null` | `1.000*` |

This matrix is deliberately incomplete. The required operator capture must
replace each `null` that belongs to the labelled run with a cosine and must
include embedding model/version, source media ID, quality score, and the
runner-up destination. A same-image edge cannot count as two independent
exemplars; the recovery rule requires each moved member to clear its floor
against at least `k` distinct-media destination exemplars [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:346-349].

## Refinement and verification decisions

The decisions below are pair-level. `ABSTAIN` means keep the residual out of
an automatic merge and emit a review suggestion once C2 is available; it does
not mean that a missing score is a negative similarity.

| Pair | Label relation | Cosine | Refinement decision | Verification decision | C1 action |
| --- | --- | ---: | --- | --- | --- |
| `W1–W2` | Genuine | `null` | Same-person residue; no numeric refinement evidence | Pair not evaluable; do not merge on label alone | `ABSTAIN`, capture pair |
| `W1–W3` | Genuine | `null` | Same-person residue; no numeric refinement evidence | Pair not evaluable; do not merge on label alone | `ABSTAIN`, capture pair |
| `W2–W3` | Genuine | `null` | Same-person residue; no numeric refinement evidence | Pair not evaluable; do not merge on label alone | `ABSTAIN`, capture pair |
| `W1–P_G` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W1–T_G` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W1–P_P` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W1–T_P` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W2–P_G` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W2–T_G` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W2–P_P` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W2–T_P` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W3–P_G` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W3–T_G` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W3–P_P` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `W3–T_P` | Impostor | `null` | Keep separate | No cross-identity evidence | `NO MERGE` |
| `P_G–T_G` | Impostor | `null` | Keep named galleries partitioned | No cross-person merge is admissible | `NO MERGE` |
| `P_G–P_P` | Genuine | `0.742` | Pair clears the provisional base floor | `k`/margin/quality not captured; no auto-merge | `PAIR PASS; ABSTAIN POLICY` |
| `P_G–T_P` | Impostor | `null` | Keep named galleries partitioned | No cross-person merge is admissible | `NO MERGE` |
| `T_G–P_P` | Impostor | `null` | Keep named galleries partitioned | No cross-person merge is admissible | `NO MERGE` |
| `T_G–T_P` | Genuine | `0.686` | Pair clears the provisional base floor | `k`/margin/quality not captured; no auto-merge | `PAIR PASS; ABSTAIN POLICY` |
| `P_P–T_P` | Impostor, same press image | `null` | Mixed residual remains partitioned | Conflicting named identities require abstention | `NO MERGE; SUGGEST` |

The Watson rows are expected recovery candidates once the missing numeric
capture exists; the press pair is an explicit negative control. This honors the
partition-plus-verification requirement: a best edge or a transitive connected
component is never enough, and a conflicting confirmed identity blocks the
whole residual [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:57-64,346-349].

## Numeric defect baseline

### Watson fragmentation

For the reported three Watson observations, the canonical partition has three
same-label pairs: `C(3,2) = 3`. The observed residue has three singleton
clusters, so it has zero predicted same-cluster pairs and zero true positives.
Using the repository regression-harness convention (`precision=0` when there
are no predicted pairs, `recall=TP/ground_truth_pairs`) gives:

| Measure | Value | Calculation |
| --- | ---: | --- |
| Canonical labels | `1` | Emma Watson |
| Evaluated observations | `3` | `W1`, `W2`, `W3` |
| Ground-truth same-label pairs | `3` | `C(3,2)` |
| Predicted same-cluster pairs | `0` | Three singletons |
| True-positive pairs | `0` | No co-clustered Watson pair |
| False-positive pairs | `0` | No predicted pair |
| False-negative pairs | `3` | `3 - 0` |
| Pairwise precision | `0.000` | Harness empty-prediction convention |
| Pairwise recall | `0.000` | `0 / 3` |
| Pairwise F1 | `0.000` | `2PR/(P+R)` with `P=R=0` |
| B-cubed precision | `1.000` | Every singleton contains only Watson |
| B-cubed recall | `0.333` | Each item retrieves `1/3` of its label |
| B-cubed F1 | `0.500` | Harmonic mean of `1.000` and `0.333` |
| Fragmentation count | `3` | Three predicted clusters for one label |
| Estimated recovery merges | `2` | `fragmentation - 1` |

The pairwise formulas and the `fragmentation - 1` curation measure match the
existing harness implementation [apps/prototype-description-service/recognition/application/regression_harness/metrics.py:51-71,101-110]. This is a
defect baseline, not evidence that `tau_pair` should be lowered; the missing
cosines still make the recovery admission test unevaluable.

### Perry/Trudeau mixed residual

The minimal mixed residual contains one Perry face and one Trudeau face in one
predicted cluster. Its canonical same-label pair count is zero, while the
predicted cluster creates one cross-label pair:

| Measure | Value |
| --- | ---: |
| Canonical identities | `2` |
| Observations | `2` (`P_P`, `T_P`) |
| Ground-truth same-label pairs | `0` |
| Predicted same-cluster pairs | `1` |
| True-positive pairs | `0` |
| False-positive pairs / false merge | `1` |
| Pairwise precision | `0.000` |
| Pairwise recall | `not estimable` (`0/0`) |
| Action | `NO MERGE`; retain as a review suggestion |

The stored demo also has two positive named rows (`0.742` and `0.686`), but
there is no impostor denominator, quality stratum, or runner-up margin in that
saved result. It cannot certify the false-name gate. The earlier recorded
Trudeau → Watson wrong-person row is likewise not counted as a numeric FAR row
because its score and threshold were explicitly not captured
[docs/assessments/GPUFLOW-1-rebaseline-20260914.md:84-99].

## Quality strata and admission floors

The service's canonical `quality_score` is confidence multiplied by the
minimum face dimension divided by `min_face_size`, clamped and rounded to three
decimals [apps/prototype-description-service/recognition/application/assignment/quality.py:30-65]. Occlusion does not enter that score; it is a separate
threshold-adjustment input [apps/prototype-description-service/recognition/application/assignment/quality.py:39-44]. The four score strata below therefore
use the existing quality thresholds, not an invented occlusion score
[apps/prototype-description-service/recognition/application/settings/clustering.py:31-61].

### Quality-score strata

The provisional floor is the current discovery threshold plus the existing
quality-band adjustment, with a lower bound at the current discovery threshold:
`max(0.55, 0.55 + adjustment)`. This keeps the high-quality `-0.05` setting
from silently relaxing a recovery merge while retaining the current stricter
`+0.02`/`+0.05` values for mediocre/poor observations
[apps/prototype-description-service/recognition/application/settings/clustering.py:45-61,226-280]. Every row has zero captured labelled pairs, so every row is
abstained even though a provisional floor is present.

| Quality stratum | Score range | Labelled pairs | Pair precision | Pair recall | FAR | FRR | Provisional admission floor | False-accept interval | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `high` | `[0.900, 1.000]` | `0` | `null` | `null` | `null` | `null` | `0.550` | `null` (`0/0`) | `ABSTAIN` |
| `neutral` | `[0.800, 0.900)` | `0` | `null` | `null` | `null` | `null` | `0.550` | `null` (`0/0`) | `ABSTAIN` |
| `mediocre` | `[0.600, 0.800)` | `0` | `null` | `null` | `null` | `null` | `0.570` | `null` (`0/0`) | `ABSTAIN` |
| `poor` | `[0.000, 0.600)` | `0` | `null` | `null` | `null` | `null` | `0.600` | `null` (`0/0`) | `ABSTAIN` |

The unstratified saved-run pair rows are `2/2` accepted genuine rows, giving
descriptive pair precision `1.000`, pair recall `1.000`, and FRR `0.000`; FAR
and its interval are `null` because there is no impostor denominator. This
directional summary is not eligible to un-abstain any quality stratum.

### Stress/operating strata

The operator must additionally report these product-relevant strata. They are
listed separately because an eye-patch occlusion proxy is bounded in `[0,1]`
but only measures relative eye-patch activity, not an occluder type or a
landmark-visibility truth label [apps/prototype-description-service/recognition/infrastructure/embeddings/face_quality_factors.py:82-105]. No row below has a
captured labelled pair in this lane; the explicit `ABSTAIN` disposition avoids
pooled metrics hiding a sparse-stratum failure.

| Operating stratum | Labelled pairs | Pair precision | Pair recall | FAR | FRR | Floor | False-accept interval | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `clear` | `0` | `null` | `null` | `null` | `null` | `0.550` | `null` (`0/0`) | `ABSTAIN` |
| `profile` | `0` | `null` | `null` | `null` | `null` | `0.550` | `null` (`0/0`) | `ABSTAIN` |
| `sunglasses` | `0` | `null` | `null` | `null` | `null` | `0.550` | `null` (`0/0`) | `ABSTAIN` |
| `masked` | `0` | `null` | `null` | `null` | `null` | `0.600` | `null` (`0/0`) | `ABSTAIN` |
| `occlusion_other` | `0` | `null` | `null` | `null` | `null` | `0.600` | `null` (`0/0`) | `ABSTAIN` |
| `low_res` | `0` | `null` | `null` | `null` | `null` | `0.600` | `null` (`0/0`) | `ABSTAIN` |
| `blur` | `0` | `null` | `null` | `null` | `null` | `0.600` | `null` (`0/0`) | `ABSTAIN` |
| `similar_people` | `0` | `null` | `null` | `null` | `null` | `0.600` | `null` (`0/0`) | `ABSTAIN` |
| `unknown` | `0` | `null` | `null` | `null` | `null` | `0.600` | `null` (`0/0`) | `ABSTAIN` |

The `0.550` stress floors retain the base discovery floor where the current
quality path supplies no measured factor adjustment. The `0.600` floors are
the base `0.550` plus the current poor-quality tightening `+0.050`; they are a
conservative provisional proxy for strata that commonly reduce usable face
evidence, not measured stratum optima [apps/prototype-description-service/recognition/application/settings/clustering.py:45-61,226-280].

`null` is intentional and means the denominator is zero, not zero error. A
non-abstained row is invalid unless it has a floor, at least `min_pairs`
labelled pairs, a measured FAR/FRR, and a false-accept interval. Acceptance
fails on one missing or over-gate stratum even if an aggregate looks good, as
required by CAL-01/CAL-11 [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:185-193].

## Katy Perry acceptance example

`P_G–P_P` is the representative positive example:

* observed cosine: `0.742`;
* provisional base floor: `tau_pair = 0.550`; pair-level result: `0.742 >= 0.550`, so **pair pass**;
* saved gallery context: five Perry photos existed before the press photo and
  three were displayed [docs/assessments/current/guided-prototype-face-recognition-2026-09-05.md:296-300];
* policy-level result: **not admitted**, because the saved evidence does not
  identify `k` distinct source media, the runner-up score, the calibrated
  margin, or the quality stratum;
* if the operator's completed capture proves two distinct-media exemplars,
  `margin >= 0.050`, a non-abstained stratum floor, and zero false-name
  acceptance, this row is the example that may pass the full recovery rule;
* if `P_P` is bundled with `T_P`, the identity conflict wins and the entire
  residual is `NO MERGE`/`SUGGEST`, irrespective of `0.742`.

This keeps the useful positive row while preventing a high best edge from
turning into a persistent name. The plan specifically requires every moved
member to pass against multiple independent exemplars and requires a competing
identity margin [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:63-64,73-79].

## Promotion protocol

An operator must replace the missing cells with a sealed, reproducible run
before changing `Verdict` to `accepted`:

1. Freeze the embedding model/version and use one embedding space for gallery,
   calibration, and evaluation. Do not use a projection, clothing, semantic,
   or whole-image similarity as identity evidence; the target is a pairwise
   face-cosine decision.
2. Capture `W1`, `W2`, `W3`, `P_G`, `T_G`, `P_P`, and `T_P` with stable identity
   labels, source media IDs, quality components, and the complete pairwise
   cosine matrix. Add unknown/impostor probes and the mixed press residual.
3. Split calibration identities from evaluation identities before scoring. Keep
   same-image pairs from satisfying the independent-exemplar count. Record
   insertion-order permutations and rerun the exact candidate-selection
   procedure.
4. For each quality and operating stratum, report pairwise precision/recall,
   FAR/FRR, labelled-pair count, admission floor, false-accept interval,
   false merges, fragmentation, unknown absorption, rejected/singleton
   fraction, and insertion-order stability. Report B-cubed precision/recall
   alongside pairwise results; do not replace pairwise admission with an
   aggregate.
5. Keep a stratum abstained when `labelled_pairs < min_pairs`, when a floor or
   interval is missing, or when its false-name gate fails. Noise is unassigned;
   it is not a true negative manufactured to improve FAR.
6. Accept the policy only if every non-abstained stratum has a floor and no
   automatic false-name acceptance. On acceptance, C2 may copy the policy
   block verbatim and issue a revertible receipt; until then, consumers must
   leave recovery merge disabled [docs/tasks/v0.5.0/GPUFLOW-2-durable-describe-roster-identity-and-cluster-recovery-task-plan.md:346-349,455-466].

## Machine-readable calibration policy

The following YAML is intentionally provisional. Its numeric values are
derived from the current settings: discovery `0.55`, complete-link `0.45`,
low-confidence width `0.05`, suggestion floor `0.35`, suggestion ceiling
`0.55`, quality cuts `0.90/0.80/0.60`, quality adjustments
`-0.05/0.00/0.02/0.05`, `oact_coefficient=0.0`, and quality weights
`0.6/0.4` [apps/prototype-description-service/recognition/application/settings/clustering.py:31-70,91-99,226-280]. `min_pairs=2` is a
deliberate minimum-evidence sentinel aligned with the current two-member
cluster minimum, not a claim of statistical power [apps/prototype-description-service/recognition/application/settings/clustering.py:294-300]. All
values are named provisional because no disjoint C1 measurements were supplied.
The Wilson `0.95` level below is reporting metadata for the operator's
interval, not a runtime threshold copied into settings; the operator must keep
that level pre-registered when replacing the sparse rows.

```policy
schema_version: 1
rule_version: "GPUFLOW-2-C1-provisional-20260916"
status: "needs_operator"
apply_mode: "disabled_until_accepted"

# Recovery admission: similarity is cosine in the single pinned face space.
tau_pair: 0.55
tau_intra: 0.45
recovery_margin: 0.05
margin_delta: 0.05
delta: 0.05
k: 2
min_agreeing_exemplars: 2

# Quality-score cuts use the existing quality_score scale.
band_cuts:
  quality_score:
    high: {min_inclusive: 0.90, max_inclusive: 1.00}
    neutral: {min_inclusive: 0.80, max_exclusive: 0.90}
    mediocre: {min_inclusive: 0.60, max_exclusive: 0.80}
    poor: {min_inclusive: 0.00, max_exclusive: 0.60}
  similarity:
    reject_below: 0.30
    low_confidence_suggestion: {min_inclusive: 0.30, max_exclusive: 0.35}
    suggestion: {min_inclusive: 0.35, max_exclusive: 0.55}
    accept_at_or_above: 0.55

suggestion_band_cuts:
  low_confidence_floor: 0.30
  suggestion_floor: 0.35
  suggestion_ceiling: 0.55

per_stratum_floors:
  high: 0.55
  neutral: 0.55
  mediocre: 0.57
  poor: 0.60
  clear: 0.55
  profile: 0.55
  sunglasses: 0.55
  masked: 0.60
  occlusion_other: 0.60
  low_res: 0.60
  blur: 0.60
  similar_people: 0.60
  unknown: 0.60

min_pairs: 2
abstain:
  rule: "abstain the whole residual when any member is in an abstained stratum, has fewer than min_pairs labelled pairs, fails its per-stratum floor, lacks k distinct-media exemplars, fails tau_intra, misses recovery_margin against the runner-up, or conflicts with a confirmed named identity"
  strata:
    - high
    - neutral
    - mediocre
    - poor
    - clear
    - profile
    - sunglasses
    - masked
    - occlusion_other
    - low_res
    - blur
    - similar_people
    - unknown

abstained_strata:
  - high
  - neutral
  - mediocre
  - poor
  - clear
  - profile
  - sunglasses
  - masked
  - occlusion_other
  - low_res
  - blur
  - similar_people
  - unknown

false_name_acceptance_gate:
  max_automatic_false_name_accepts: 0
  max_observed_rate: 0.0
  interval: {method: "Wilson", confidence: 0.95}
  fail_if: "any non-abstained stratum has an observed automatic false-name acceptance or lacks its interval"

# OACT remains dark until an impostor/unknown-probe experiment proves its sign.
k_occ: 0.0
representative:
  weights:
    occlusion: 0.0
    detector_confidence: 0.6
    face_size: 0.4
  weights_sum: 1.0

evaluation:
  calibration_identities_disjoint_from_evaluation: true
  required_metrics:
    - pairwise_precision
    - pairwise_recall
    - bcubed_precision
    - bcubed_recall
    - false_merges
    - fragmentation
    - unknown_absorption
    - rejected_singleton_fraction
    - insertion_order_stability
    - far
    - frr
    - false_accept_interval
  no_same_image_exemplar_credit: true
  noise_is_unassigned: true
```

Verdict: needs_operator
