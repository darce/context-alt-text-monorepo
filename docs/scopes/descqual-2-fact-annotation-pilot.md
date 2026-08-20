# Scope: DESCQUAL-2 Fact-Level Description-Quality Ground Truth

> **Metadata**
>
> - **Date**: 2026-08-19
> - **Task ID**: `DESCQUAL-2`
> - **Target Branch**: `feature/descqual-2`
> - **Project**: `apps/prototype-description-service`
> - **Predecessor**: `DESCQUAL-1` (archived, superseded)
> - **Sibling, not parent**: `FIR-12` (occlusion-scoped bake-offs). This task is *not* FIR-12 Phase 3.
> - **Intake mode**: answered from heuristics canon + `distilled/` corpus, not asked of the operator.

---

## Problem

The description bake-off can score identity-grounded metrics (`must_right` on 530/646,
hallucinated names, missing identities, wrong-name hits, tag coverage) but **cannot score
fact-level hallucination**. `reference_facts` is non-empty on **0 of 646** manifest entries
and absent from the v3 entry schema; the `golden150-draft` carries the field on 1 of 150.

The scorers are not the gap. `caption_metrics.py` already ships `FabricatedFact`,
`HallucinationScores`, `score_hallucination`, `fabricated_fact_rate` and
`fabrication_by_kind`, all tested. **The gap is ground truth.**

---

## Why this is its own task ref, not FIR-12 Phase 3

The work DAG has **no edge** from the annotation chain into either FIR-12 phase. Both
bake-offs produce their numbers without a single annotated fact. The only edge is
`selection manifest → annotation`, and the selection is already frozen and committed
(`benchmarks/manifests/fir12-selection-v1.json`, 640 entries).

- **GRPH-31** — makespan is the longest chain. Two disjoint chains run in parallel at a
  makespan of `max(len)`. Folding annotation in as Phase 3 serialises them, and since the
  annotation chain is human-throughput-bound it immediately becomes the critical path.
- **TEAM-06** — a permanent critical-path hand-off silo is the named anti-pattern. Under
  this repo's Pre-Merge Gate Rule the coupling is concrete: FIR-12 could not reach a
  passing `handoff_close_check` until annotation finished.
- **TEAM-05** — the independence test passes: this task ships alone, with its own tests,
  its own artifact, and no FIR-12 code in its diff.
- **EVAL-25** — a separate ref can cleanly absorb the Phase 2 captions as a *second* pool
  contributor. A Phase 3 living inside the task that produced those captions would be
  pooling its own output against itself.

**Counter-case, recorded rather than waved away.** The frozen selection manifest is a
**bridge** in the dependency graph (GRPH-05) — a single shared artifact both chains rely on.
Mitigation: it is a versioned, published artifact (`bakeoff-selection/1`), never a live file
either task edits. The interaction between the two tasks is named with an owner and an exit
criterion (TEAM-09): *FIR-12 owns the selection manifest; DESCQUAL-2 consumes it read-only;
the exit criterion is that DESCQUAL-2 never writes to `benchmarks/manifests/fir12-*`.*

---

## Sizing, from margin of error rather than percent of N

**AUDIT-09**: the sample size comes from the target margin of error with a finite population
correction, never from a percentage of the population. Over N=640 unique-sha256 entries,
with z=1.96 and the conservative p=0.5:

| target margin | n |
| --- | --- |
| ±15 pp | 41 |
| ±10 pp | 84 |
| ±7.5 pp | 135 |
| ±5 pp | 241 |

**AUDIT-10**: proportional allocation of n=84 across the five strata gives
A=4, B=11, C=5, D=11, E=53 (Hamilton remainders applied; the floors alone are
B=10, C=4 and sum to 82). That is still thin for B — the one stratum populated
enough to carry a comparative occlusion claim. B therefore gets a **precision
floor** and is sized from its own margin: **B_eyewear needs 44 of its 80 images
for ±10 pp** unclustered (36 for ±12.5 pp, 29 for ±15 pp), rising to **48** once
its own clustering is priced in (Kish a=2.1 on the PSU partition below, ICC=0.2).
Allocation is disproportional by design, and the inclusion probability of every
drawn unit is recorded so a design-based interval remains computable (AUDIT-08).

```
import json
from pathlib import Path
from scripts.eval_harness.audit_sampling import (
    allocate,
    project_strata_image_counts,
    size_for_margin,
)

strata_counts = json.loads(Path("benchmarks/manifests/fir12-selection-v1.json").read_text())["strata_counts"]
allocate(strata_sizes=project_strata_image_counts(strata_counts), n=84)
# {'A_true_occluder': 4, 'B_eyewear': 11, 'C_pose': 5, 'D_capture': 11, 'E_clean': 53}
size_for_margin(margin=0.10,  population=80).n  # 44
size_for_margin(margin=0.125, population=80).n  # 36   (ceil of 35.007; not 35)
size_for_margin(margin=0.15,  population=80).n  # 29   (ceil of 28.062; not 28)
```

**AUDIT-11**: images cluster within subject, and Kish `deff = 1 + (a−1)·ICC` assumes
a **partition** of the frame — one PSU per image. The published `a = 12.90` was
`Σm²/Σm` over **130 labeled subjects (Σm=544)** and then applied to **N=640**,
which includes 115 images with empty `present_identities` that contribute no
cluster by design. Dropping that unclustered mass from M while applying `deff` to
the full N inflates the design effect (FIR-11 already forbade using overlapping
identity concentration `C_identity = 12.925` as a design effect for the same
reason). Compounding it: **16 images carry ≥2 `present_identities` (19 extra
memberships)**, so the 130 subject-counts overlap.

**PSU partition (declared once, used for both `a` and `N`).** The CI is claimed
on the frozen selection, so unlabeled images stay in N as singleton clusters.
Each image is assigned to exactly one PSU:

- non-empty `present_identities` → PSU = the **first-listed** identity on the
  entry (document order; extra memberships are not a second cluster);
- empty `present_identities` → singleton PSU `unlabeled:{media_id}`.

On `fir12-selection-v1.json` that yields **241 PSUs** (126 labeled + 115
unlabeled singletons), Σm = N = 640, Σm² = 6942. Cluster sizes run 1 to 49
(labeled cv=1.46). Kish `a = Σmᵢ²/Σmᵢ = 6942/640 = 10.846875`. `deff` is
applied to the infinite-population n₀ **before** the finite-population
correction (the Kish/Lohr order). Regenerated from
`benchmarks/manifests/fir12-selection-v1.json` through
`project_frame_psu_image_counts` (AUDIT-09). Repo-root REPL with
`PYTHONPATH=apps/prototype-description-service`:

```
import json
from pathlib import Path
from scripts.eval_harness.audit_sampling import (
    kish_effective_cluster_size,
    project_frame_psu_image_counts,
    size_for_margin,
)

entries = json.loads(Path("benchmarks/manifests/fir12-selection-v1.json").read_text())["entries"]
frame = project_frame_psu_image_counts(entries)   # 241 PSUs, Σm=640, Σm²=6942
a = kish_effective_cluster_size(frame.sizes)      # 10.846875
size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.2).n  # 198
size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.3).n  # 239
size_for_margin(margin=0.10, population=80,  cluster_size=2.1, icc=0.2).n  # 48  (B_eyewear)
```

The overlapping-membership construction (130 subjects, Σm=544, plus 115
singletons, overlap kept) gives a=10.827 and the same n=198 at ICC=0.2; it is
**not** the partition. The first-listed rule drops four identities that never
appear first (`Auburn Hollow`, `Tidal Quarry`, `Vellum Warren`, `Verdant Beacon`).

| ICC | deff | n for ±10 pp over N=640, a=10.846875 |
| --- | --- | --- |
| 0.0 | 1.000 | 84 |
| 0.05 | 1.492 | 118 |
| 0.1 | 1.985 | 148 |
| 0.2 | 2.969 | **198** (planning) |
| 0.3 | 3.954 | **239** (sensitivity) |
| 0.5 | 5.923 | 302 |

`n` is `size_for_margin(..., cluster_size=a, icc=...).n` —
unrounded `a` from `project_frame_psu_image_counts` (`a = 10.846875`), then
`math.ceil`. `deff` is display-rounded to three decimals; recomputing n
from the printed deff reproduces every cell. Two-decimal deff does not (ICC=0.1
printed 1.98 → n=147, not 148). The older pin `a=12.90` produced n=327 at
ICC=0.5; exact labeled-only `a=12.904412` produces 328. This table does not
use that pin.

**Estimand grain is the image, not the fact.** The headline estimand
`fabricated_fact_rate` is already image-level: the fraction of *images* that
trip any trap (an image counts once however many traps it trips). The
margin-of-error n is an image count. Kish `a` is images per subject PSU.
The planning ICC of 0.20 is therefore the **image-within-subject** correlation
of that image-level Y. An image is the coded unit: Y_i = 1 if the image is
caught fabricating, 0 otherwise (the `over='all'` rate). Facts nest in
images which nest in subjects, but `deff = 1 + (a−1)ρ` prices only
image-within-subject correlation of an image-level outcome. A fact-level ρ
plugged into this `a` is the wrong design effect. Fact-within-image
dependence is absorbed into the image-level aggregate and is not a second
term in this n. A later fact-level analysis would have to state a
facts-per-image cluster size and compose the two design effects explicitly;
that is not the sizing used here.

**Planning n is not measured from the ~30-image draw.** ICC information lives only in
within-subject pairs. An image-SRS of 30 on this frame yields E[within-subject pairs]
= C(30,2) × 6476 / (640 × 639) = 6.89, spread over ~3.5 replicated subjects (20k-draw
Monte Carlo on `fir12-selection-v1.json`: mean k with nᵢ ≥ 2 = 3.53, p5=1, p95=6,
P(k ≤ 2)=0.22). The sample Kish a is then ~1.5, not 10.85. Fisher-Z 95% CI at true
ρ=0.2 with k=4 clusters of size 2 is [−0.83, 0.92] — effectively [0, 1] — and the
implied n over that CI is 84..397, which is the entire table above plus the ICC=1
cap (`size_for_margin(..., cluster_size=a, icc=1.0).n` → 397). Plugging a
30-image ICC point estimate into `size_for_margin` is cargo-cult precision (AUDIT-11).

There is no sourced ICC for this estimand in the repo or the canon. `design_effect`
and `size_for_margin` both require the caller to pass one and ship no default. The
full study is sized from a **pre-registered planning ICC of 0.20 → n = 198**,
declared as an assumption, with the **0.30 → n = 239** sensitivity row printed
beside it. Both n values use the partition `a` above, not the labeled-only 12.90.

The ~30-image draw stays ICC-blind (`allocate(cluster_params=None)`,
`DeffOrder.FPC_ONLY`). Every quoted figure that is not ICC-blind names the ICC and
deff it used (AUDIT-11).

**Frame cap.** Identity membership (overlapping, 130 named subjects, Σm=544):
**76** have m ≥ 2 and **65** have m ≥ 3. Under the PSU partition (one image, one
cluster): **76** labeled PSUs have m ≥ 2 and **64** have m ≥ 3. The follow-on
ICC draw uses the partition.

---

## MVP scope — the ~30-image cost and instrument pilot

The ~30-image draw is a **cost and instrument pilot**. Its outputs are minutes per
image, rubric α, and gold-item QC. It is not the source of `deff` and does not
produce the ICC the full-study n is divided by.

1. **Draw** a stratified probability sample of ~30 images across A/B/C/D/E with recorded
   inclusion probabilities (`audit_sampling.draw`, seeded and reproducible).
2. **Pool** the candidate facts from at least two independent caption sources plus a human
   free-write pass, so the annotation set is not one model graded against itself
   (`judgment_pool.build_pool`, which refuses a single-contributor pool). Report the pool's
   incompleteness explicitly; unjudged candidates are **not** negatives (EVAL-25).
3. **Annotate** each pooled candidate as a v4 `ReferenceFact` carrying per-label lineage —
   annotator id, batch, timestamp, source pool (MLDATA-04).
4. **Two annotators per image.** The pilot is 100% dual-annotated so α is
   measurable (full-study overlap may drop to 20% only after the pilot α clears
   0.8). Both pre-adjudication labels are retained on the fact; the adjudicated
   value goes in the top-level fields (MLDATA-03). SME adjudication is recorded
   with `adjudicated_by` and `adjudication_rule` (HITL-07).
5. **Gold-embedded QC (HITL-03)** — rate, provenance, and a per-annotator
   threshold, specified below. Agreement is a diagnostic on the instrument, not
   a score for the annotators (HITL-05, α ≈ 0.8 as the working target). Without
   gold, α certifies shared rater bias, not truth.
6. **Measure** from the pilot: minutes-per-image (hence cost per image and total
   annotation cost); rubric Krippendorff α on the dual-annotated set (instrument
   diagnostic, HITL-05); per-annotator gold accuracy (HITL-03). Do **not**
   estimate the intra-subject ICC or derive full-sample n from this draw.

### Written disagreement rule (MLDATA-03)

When two annotators label the same pooled candidate:

1. **Agree** (same `polarity` and `kind` on the same candidate text): that
   shared label is stored in the top-level fields. Both labels still go in
   `pre_adjudication`.
2. **Disagree**: no coin-flip, no silent merge. Escalate to an SME who produced
   neither label. The SME label is written to the top-level fields; both
   original labels stay in `pre_adjudication`; `adjudicated_by` names the SME;
   `adjudication_rule` is stored as the token **`disagreement-escalate-to-sme`**.
3. Gold items never have their known answer overwritten by this rule. A
   disagreement on gold is a QC event (counts against gold accuracy) and still
   records both live labels; the reference stays the pre-authored gold.

A sibling lane is converting `adjudication_rule` from free text to a
constrained enum. The enum member **must match** `disagreement-escalate-to-sme`.
This scope doc does not edit the model.

### Gold items (HITL-03)

- **Rate.** Gold items are **10% of the annotation queue**, injected unannounced,
  *in addition to* the probability sample so they do not consume design-based n
  and are excluded from `fabricated_fact_rate`. On the ~30-image pilot that is
  **3 gold images**. Mix, as HITL-03 requires: **random + batch-matched + hard**
  (pilot: one of each — random from the frozen frame outside the drawn n; one
  matched to the batch's plurality stratum; one hard cell: `B_eyewear`,
  `A_true_occluder`, or multi-identity).
- **Provenance.** Known answers exist before the batch is drawn. They are not
  authored by the annotators under test and not taken from the caption pool
  being judged. Eligible sources: independently operator-confirmed
  `reference_facts`, or items arbitrated for gold by an SME who will not
  annotate the live queue.
- **Per-annotator threshold.** Gold accuracy is the fraction of gold *facts*
  (not images) on which the annotator matches the known answer on polarity and
  kind. The pre-registered bar is **≥ 0.80**. Below it, that annotator's live
  labels in the batch are held for SME review and the annotator is retrained or
  replaced. Annotators are not dropped in order to chase α (HITL-05). At pilot
  gold volume (3 images) report the raw k/n; the 0.80 bar is the full-study
  gate and a diagnostic here.

## Success criteria

- The pilot reports minutes per image, rubric α, and per-annotator gold
  accuracy (10% gold, bar 0.80, provenance as specified). It does not output
  a measured ICC or a design effect used to size the full sample.
- Disagreements follow the written rule `disagreement-escalate-to-sme`; both
  pre-adjudication labels survive in the stored record. An implementation that
  overwrites them, coin-flips, or omits `adjudication_rule` fails a test.
- Full-sample n is the pre-registered planning value **n = 198** at ICC=0.20
  (sensitivity **n = 239** at ICC=0.30), not a number derived from the 30-image draw.
- Every drawn unit carries its inclusion probability; no convenience or first-n draw exists
  anywhere in the code path.
- The judgment pool has ≥2 independent contributors and ships an incompleteness disclosure.
- Cost per image and total projected annotation cost are reported alongside the design.

## Conditional follow-on — subject-stage ICC (not the baseline)

If a measured ICC is required before the remaining spend, the smallest honest design
on this frame is a **subject-stage draw over the 64 partition PSUs with m ≥ 3
(192 images: 3 images × 64 subjects)**. The ICC estimated there is the same
image-within-subject correlation of the image-level Y defined above, not a
fact-level ICC. Named, conditional follow-on — not the baseline. (Overlapping
identity membership has 65 subjects with m ≥ 3; one of those never reaches
m = 3 as a first-listed PSU.)

Fisher-Z transform of the ICC (equal cluster size m, k groups):

```
z = (1/2) ln((1+(m-1)ρ)/(1-ρ))
SE(z) = sqrt(m / (2(k-2)(m-1)))
ρ = (e^{2z} - 1) / (e^{2z} + (m-1))
```

At the planning ρ=0.20, k=64, m=3, the Fisher-Z 95% CI is **[0.044, 0.361]**. The
study reports the **upper CI bound**, not the point estimate. Implied n on the
partition Kish a, regenerated from `benchmarks/manifests/fir12-selection-v1.json`
through shipped `project_frame_psu_image_counts` (a=10.846875). Same REPL as
the planning-n block above:

```
import json
from pathlib import Path
from scripts.eval_harness.audit_sampling import (
    kish_effective_cluster_size,
    project_frame_psu_image_counts,
    size_for_margin,
)

entries = json.loads(Path("benchmarks/manifests/fir12-selection-v1.json").read_text())["entries"]
frame = project_frame_psu_image_counts(entries)
a = kish_effective_cluster_size(frame.sizes)  # 10.846875
size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.044).n  # 114
size_for_margin(margin=0.10, population=640, cluster_size=a, icc=0.361).n  # 261
```

so 114..261. The 30-image image-SRS is not a cheaper substitute for this design.

## Not doing

- No full-corpus annotation. The 640-image census is not the plan and never was.
- No annotation of images outside the frozen selection manifest.
- No writes to `benchmarks/manifests/fir12-*` — FIR-12 owns those.
- No spatial-placement claim. The mechanically-derived `left_of` facts cover 17 images /
  23 pairs and remain a diagnostic (MLDATA-07).
- No LLM-judge substitution for the human pass at pilot stage. A judge may only be adopted
  after it is validated against blinded human labels (EVAL-12) with model, prompt, rubric,
  seed and ordering pinned (EVAL-13).
- No nonresponse patching by drawing more units. Unannotatable images are bias to be
  reported, not a reason for a bigger n (AUDIT-13).
- No ICC / deff estimated from the ~30-image cost-and-instrument draw, and no
  full-sample n derived from that draw's point estimate.

## Assumptions

- The 640-entry selection manifest stays frozen for the life of this task.
- Planning ICC = 0.20 is a declared assumption, not a measurement: it is the
  image-within-subject correlation of the image-level fabricated-fact
  indicator, not a fact-level ICC. The sensitivity row at 0.30 is printed;
  neither is sourced from this corpus.
- Kish `a` and N share one PSU partition: unlabeled images are singleton
  clusters; a multi-identity image is assigned to its first-listed
  `present_identities` name. Overlapping membership counts are not a design
  effect.
- `/Volumes/Butter` stays mounted for the annotation passes.
- Annotator time is the binding constraint, not compute.
