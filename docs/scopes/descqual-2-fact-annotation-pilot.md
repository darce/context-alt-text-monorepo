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
A=4, B=10, C=4, D=11, E=53. That is useless for B — the one stratum populated enough to
carry a comparative occlusion claim. B therefore gets a **precision floor** and is sized
from its own margin: **B_eyewear needs 44 of its 80 images for ±10 pp** unclustered
(35 for ±12.5 pp, 28 for ±15 pp), rising to **48** once its own clustering is priced in
(Kish a=2.1 on the PSU partition below, ICC=0.2). Allocation is disproportional by design, and the inclusion
probability of every drawn unit is recorded so a design-based interval remains computable (AUDIT-08).

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
correction (the Kish/Lohr order).

```
sizes = tuple(partition_counts.values())          # 241 PSUs, sum 640
a = kish_effective_cluster_size(sizes)            # 10.846875
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
| 0.0 | 1.00 | 84 |
| 0.05 | 1.49 | 118 |
| 0.1 | 1.98 | 148 |
| 0.2 | 2.97 | **198** (planning) |
| 0.3 | 3.95 | **239** (sensitivity) |
| 0.5 | 5.92 | 302 |

**Planning n is not measured from the ~30-image draw.** ICC information lives only in
within-subject pairs. An image-SRS of 30 on this frame yields E[within-subject pairs]
= C(30,2) × 6476 / (640 × 639) = 6.89, spread over ~3.5 replicated subjects (20k-draw
Monte Carlo on `fir12-selection-v1.json`: mean k with nᵢ ≥ 2 = 3.53, p5=1, p95=6,
P(k ≤ 2)=0.22). The sample Kish a is then ~1.5, not 10.85. Fisher-Z 95% CI at true
ρ=0.2 with k=4 clusters of size 2 is [−0.83, 0.92] — effectively [0, 1] — and the
implied n over that CI is 84..397, which is the entire table above plus the ICC=1
cap (`size_for_margin(..., cluster_size=10.846875, icc=1.0).n` → 397). Plugging a
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
4. **Two annotators per image on an overlap subset**, with a written disagreement rule.
   Both pre-adjudication labels are retained on the fact; the adjudicated value goes in the
   top-level fields (MLDATA-03). SME adjudication is recorded with `adjudicated_by` and
   `adjudication_rule` (HITL-07).
5. **QC**: gold-embedded items seeded into each annotation batch (HITL-03). Agreement is
   read as a diagnostic on the instrument, not as a score for the annotators (HITL-05,
   α ≈ 0.8 as the working target).
6. **Measure** from the pilot: minutes-per-image (hence cost per image and total
   annotation cost); rubric Krippendorff α on the overlap subset (instrument diagnostic,
   HITL-05); gold-item QC (HITL-03). Do **not** estimate the intra-subject ICC or derive
   full-sample n from this draw.

## Success criteria

- The pilot reports minutes per image, rubric α, and gold-item QC. It does not output
  a measured ICC or a design effect used to size the full sample.
- Full-sample n is the pre-registered planning value **n = 198** at ICC=0.20
  (sensitivity **n = 239** at ICC=0.30), not a number derived from the 30-image draw.
- Every drawn unit carries its inclusion probability; no convenience or first-n draw exists
  anywhere in the code path.
- Disagreements survive adjudication in the stored record — an implementation that
  overwrites them fails a test.
- The judgment pool has ≥2 independent contributors and ships an incompleteness disclosure.
- Cost per image and total projected annotation cost are reported alongside the design.

## Conditional follow-on — subject-stage ICC (not the baseline)

If a measured ICC is required before the remaining spend, the smallest honest design
on this frame is a **subject-stage draw over the 64 partition PSUs with m ≥ 3
(192 images: 3 images × 64 subjects)**. Named, conditional follow-on — not the
baseline. (Overlapping identity membership has 65 subjects with m ≥ 3; one of
those never reaches m = 3 as a first-listed PSU.)

Fisher-Z transform of the ICC (equal cluster size m, k groups):

```
z = (1/2) ln((1+(m-1)ρ)/(1-ρ))
SE(z) = sqrt(m / (2(k-2)(m-1)))
ρ = (e^{2z} - 1) / (e^{2z} + (m-1))
```

At the planning ρ=0.20, k=64, m=3, the Fisher-Z 95% CI is **[0.044, 0.361]**. The
study reports the **upper CI bound**, not the point estimate. Implied n on the
partition Kish a=10.846875:

```
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.044).n  # 114
size_for_margin(margin=0.10, population=640, cluster_size=10.846875, icc=0.361).n  # 261
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
- Planning ICC = 0.20 is a declared assumption, not a measurement. The sensitivity
  row at 0.30 is printed; neither is sourced from this corpus.
- Kish `a` and N share one PSU partition: unlabeled images are singleton
  clusters; a multi-identity image is assigned to its first-listed
  `present_identities` name. Overlapping membership counts are not a design
  effect.
- `/Volumes/Butter` stays mounted for the annotation passes.
- Annotator time is the binding constraint, not compute.
