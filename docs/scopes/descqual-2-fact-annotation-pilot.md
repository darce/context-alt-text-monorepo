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
from its own margin: **B_eyewear needs 44 of its 80 images for ±10 pp** (35 for ±12.5 pp,
28 for ±15 pp). Allocation is disproportional by design, and the inclusion probability of
every drawn unit is recorded so a design-based interval remains computable (AUDIT-08).

**AUDIT-11**: images cluster within subject. With M = 640/130 ≈ 4.9 images per subject,
`deff ≈ 1 + (M−1)·ICC`:

| ICC | deff | inflated n for ±10 pp |
| --- | --- | --- |
| 0.1 | 1.39 | 117 |
| 0.2 | 1.78 | 150 |
| 0.3 | 2.18 | 183 |

The spread between 117 and 183 is the whole reason for a pilot. **ICC is measured, not
assumed.**

---

## MVP scope — the ~30-image pilot

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
6. **Measure** from the pilot: inter-annotator agreement, the intra-subject ICC on
   fact-level correctness, hence deff, hence the real n; and minutes-per-image, hence cost
   per image and total annotation cost.

## Success criteria

- The pilot outputs a measured ICC and a design effect, and the full-sample n is derived
  from them rather than chosen.
- Every drawn unit carries its inclusion probability; no convenience or first-n draw exists
  anywhere in the code path.
- Disagreements survive adjudication in the stored record — an implementation that
  overwrites them fails a test.
- The judgment pool has ≥2 independent contributors and ships an incompleteness disclosure.
- Cost per image and total projected annotation cost are reported alongside the design.

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

## Assumptions

- The 640-entry selection manifest stays frozen for the life of this task.
- `/Volumes/Butter` stays mounted for the annotation passes.
- Annotator time is the binding constraint, not compute.
