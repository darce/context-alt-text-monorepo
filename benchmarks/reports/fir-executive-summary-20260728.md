# FIR Executive Summary — replacing InsightFace, and improving occlusion performance

**Date:** 2026-07-28 · **Status:** program re-based on QA v8 · **Audience:** operator
**Binding reference:** `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` (v8, gitignored, uncommitted by design)
**This document does not create new claims.** Every number below is traceable to a v8 register row (D-\*, T-\*, M-\*) or to a committed task plan. Where v8 withdrew a number, this document says so rather than repeating it.

---

## 1. Bottom line

**FIR can replace InsightFace. It cannot do so on the evidence we have today, and the gap is not a GPU-budget gap.**

Three things are simultaneously true:

1. **The measurement surface is broken.** Every FIR-vs-buffalo comparison in the tree was produced by scoring FIR against ground truth that buffalo generated. That is circular. The headline "FIR is detection-bound, the embedder is fine" reading rests on it, and v8 has withdrawn or ceilinged every external claim built on it (M-05 withdrawn outright; M-11 demoted to hypothesis generator; M-12 inadmissible for external claims).
2. **The data blocker is gone.** As of 2026-07-27 we hold Open Images V6 `Human face` (`/m/0dzct`) — 1,037,710 training boxes over 331,627 images, ~80× WIDER FACE, plus 22,602 **exhaustively annotated** val+test boxes. Annotations are CC BY 4.0. This falsified the standing "detector leg is data-blocked" finding.
3. **Training is procured but not funded, and should not be funded yet.** The binding constraint on the detector leg is *weeks of engineering* (an ignore-region / semi-supervised loop) plus *88–147 person-hours* of ground-truth adjudication. The GPU run itself is short and repeatable. Spending GPU dollars before the ground truth is adjudicated buys a number nobody can interpret.

**The single most valuable next action costs $0 and about one engineering day: merge CVUP-1 (OpenCV 4→5) and re-run the SFace baselines as recorded artifacts.** Nothing measured under 4.x survives the upgrade — an SFace embedding computed under 4.x is not comparable to one computed under 5.x. Until that lands, every downstream measurement is provisional.

---

## 2. What we are actually building

Exactly **two** components get retrained in-house. Everything else is off-the-shelf Apache-licensed.

| Component | Disposition | Notes |
|---|---|---|
| Face **detector** | Retrain — SCRFD-architecture, occlusion-hardened | The `yunet-occ` line in FIR-7 Slice 2 |
| Face **embedder** | Retrain — AdaFace-style, **512D hard ceiling** | 768/1024 buy distance concentration and 2× index cost for zero evidence |
| Person cascade | Off-the-shelf (RT-DETR / PicoDet) | Body prior narrows the face search region — see §5 |
| Content search | Off-the-shelf (SigLIP / DINOv2) | Not in the FR path |
| Segmentation | Off-the-shelf (SAM) | **Offline training-data factory only** — occluder compositing. Never an occlusion *stratum definition* |
| buffalo_l | **Judge only, never in the training loop** | Distillation rights are an open question for the InsightFace quote email |

**Adjacent-code doctrine:** take the code, never the weights. AdaFace loss + CVLface recipes (MIT) and torchvision power the retrain campaign. DCFace is operator-cleared. One vector space per (modality, model), stamped, never crossed.

---

## 3. Where the evidence stands

### Withdrawn or ceilinged (do not cite externally)

| Claim | Status | Why |
|---|---|---|
| M-05: FIR recall 0.504 vs buffalo 0.995 | **Withdrawn** | Measures agreement with buffalo, not recall |
| M-11: hard-face embedding margin +0.012 [−0.034, +0.057] | **Hypothesis generator only** | No artifact in tree; legs not separable (crops aligned by detector-emitted landmarks); the only discriminating arm is a rank metric, inadmissible for an open gallery; pre-CVUP-1 |
| M-12: all numerics | **Inadmissible for external claims** | Same circular-GT root cause |
| DCFace/DigiFace detection-campaign sizing, and the $20–100 band | **Withdrawn** | Category error — those packs ship aligned FR crops, not scene images with boxes. They are embedder-leg data only |
| Everything from `golden150-draft-20260723.json` | **Ceiled at DIRECTIONAL** | Until FIR-11 publishes its bias bound |

### Admissible

| Item | Value |
|---|---|
| M-06 non-mated reject rate | 0.986 (204/207) measured. FNIR@FPIR still unmeasured |
| M-08 Open Images occlusion attenuation | **×4.31 [3.80, 4.57]** (val) · **×4.33 [4.24, 4.46]** (test). Composition-controlled on single-face images. Seed 20260728, B=4,000 bootstrap |
| Open Images occlusion prevalence | val 32.61% [30.60, 34.63] · test 32.04% [30.88, 33.21] · train 53.91% [53.66, 54.17] |

**The train/val discrepancy is a mechanism, not noise.** Open Images *train* is machine-proposal-plus-human-verification, so hard faces are never proposed and never labelled; *val and test are exhaustively annotated*. Consequence: train's unlabelled regions are **not background**. Treating them as negatives injects false negatives in exactly the small/occluded regime the program targets [MLDATA-09].

> **Standing rule: positives-only with ignore-regions. Measure only on val+test.**

---

## 4. Next steps — the binding sequence

This supersedes every other scheduling instruction in the tree.

Every row's **Gate** cell states what makes that step complete and what makes it fail, so a step can be declared done or dead on evidence rather than on assertion. Two things the table deliberately does not carry: **calendar dates**, which are operator-reserved and would go stale on contact, and **ordering-only gates** — a cell reading "follow T-03" is a dependency, not a criterion, and any row still shaped that way is unfinished.

| # | Step | Cost | Gate |
|---|---|---|---|
| **0** | **Merge CVUP-1 (OpenCV 4→5), then re-run SFace baselines as recorded artifacts** | ~1 eng-day, $0 | Blocker for FIR-7 Slice 0a — **necessary, not sufficient**: Edge 3 also blocks Slice 0a on FIR-11 Slices 1–2 (§8 risk 1). Nothing measured before it survives. The regenerated baselines inherit the standing buffalo-labelled ground-truth ceiling — step 0 makes them *reproducible*, not *trustworthy*. **The merge is itself gated:** CVUP-1 carries open review findings, and zero-open is a Pre-Merge Gate precondition — the step does not start with findings outstanding. **Both halves are the step.** Merging without regenerating the baselines leaves every downstream measurement running against numbers the merge invalidated; a sequence that keeps only the merge has dropped the half that makes the rest valid |
| **0a** | **T-18** validate the effort anchors the rest of this table is priced from | ~2 eng-h, $0 | **Cheapest step on the board and it gates the credibility of every other cost cell.** Two anchors checked so far were wrong (T-01's, T-05c's), and `benchmarks/protocols/` — the declared anchor for both T-09 and T-02 — does not exist. Until T-18 runs, treat every estimate keyed to an anchor as unvalidated, including the load-bearing ones in this table. No dependencies; it can run today, in parallel with step 0 |
| 1 | **T-12a** adopt an OEC (overall evaluation criterion) — **decision half only** — + **T-13** adopt the embedder acceptance criterion D3 | ~1 eng-h each, $0 | Cheapest unblock on the board. **D2 stays SUSPENDED until T-12a lands.** v8 splits this row: the decision is free and unblocked today; the **instrumentation** half is step 9, because it is defined over the sealed split and an OEC instrumented before T-08 yields numbers that cannot be quoted |
| 2 | **T-09** write the face-label rule (what counts as a face) | ~1 eng-h, $0 | Prerequisite for any adjudication |
| **2a** | **FIR-11 Slices 0–2** — publish the power ceiling, make provenance required and fail-closed | In FIR-11 | **Hard gate on all bulk labeling and on the step-4 GPU spend, and it is currently scheduled after both.** FIR-11 plan:250 makes Slice 0 a hard gate on bulk labeling, yet T-14 (20–34 person-h) and T-04 (88–147 person-h) are exactly that. Slice 1 makes provenance fail-closed and is expected to drop mis-attested entries — captioning them first spends A10 money on images the gate removes, and finding FIR-11-PR-35 says the undercount is ~3×. Slices 1–2 buy **zero statistical power** and must not be described as if they do; what they buy is this ordering constraint. **Status caveat:** the FIR-11 plan is filed as Done while carrying open findings and with no baseline landed on `main`, so "in FIR-11" is not evidence the slice exists — this row is satisfied by merged code and a recorded baseline, never by the plan's own status field |
| **2b** | **T-05c** post-5.x identification baseline, reported as **FNIR@FPIR, not rank-1** | ~0.5–1 day, $0 | Depends only on step 0. The harness already exists (`face_metrics.py:510 face_unknown_rejection()`); only the mated arm is missing. **T-01 at step 3 cannot attribute a loss without a post-5.x baseline to attribute it against**, so this is a dependency of step 3, not an optional extra on the align+embed line |
| **2c** | **FIR-7 Slice 0a hold** — the release condition, stated as a row rather than as prose | ~0, $0 | **This is the enforcement surface FIR-7 currently lacks.** §9 item 7 records the constraint and then admits "FIR-7 appears nowhere in the binding sequence", which makes it a manual hold nobody owns. Slice 0a is released only when **step 0 has merged with regenerated baselines** and **step 2a (FIR-11 Slices 1–2) has landed** — both, not either. **It is one-shot:** Slice 0a burns a K=3 budget on use, so a premature start is not recoverable by re-running it. Until both preconditions are recorded, Slice 0a does not start |
| 3 | **T-01** alignment-vs-embedder attribution spike (runs in parallel) | ~1 eng-day, $0 | **No anchor for this exists in the tree yet — no worktree, no plan, no estimate beyond this cell — and it sits on the critical path.** Before it starts it needs a charter: the intervention, the apportionment, the interval, and a stated **hour cap** at which an inconclusive spike is declared inconclusive rather than extended. Closes D-02 |
| **3a** | **Operator signs the T-14 dead-zone rule** — state, in writing, what a bootstrap UCL landing in **0.05–0.10** means, *before* T-14 runs | ~0, $0 | **Hard precondition on step 3b**, not advice. The frame's resolvable floor is the bootstrap CI half-width on Δ (B=2000, `resampling_unit = image`), which is not computable before T-14 runs — see *Known ceiling*. The 0.05–0.10 band is the provisional scope of the signature, not a measured limit. Operator-reserved; unsigned ⇒ T-14 does not start |
| **3b** | **T-14** union adjudication — the cheap kill | **20–34 person-h**, $0 GPU | Kill D1 only if the **miss-inflated** bootstrap **95% UCL < 0.05** at matched-FPPI. **The raw bound is biased toward killing and must not be used as stated.** `U` is human-verified true faces drawn from the *union of detector proposals*, so a face no contributing detector proposed never enters `U` — the same verification bias FIR-11 names, pointing in exactly the kill direction. Correction, and it keeps the row cheap: annotate **30 images exhaustively** (≈80 faces, ≈2–4 person-h, a strict subset of the T-04 work, not additional) to estimate the union miss rate `m` with its own 95% UCL `m_ucl`; inflate the deficit bound by `m_ucl` before comparing to 0.05. **The kill fires only if the inflated UCL clears 0.05.** If `m_ucl ≥ 0.05` the probe has already shown the union frame cannot resolve the threshold: T-14 returns *inconclusive*, does not kill, and the line escalates to T-04 proper. Bound holds on the Golden-150 frame, not the 646-image deployment frame |
| 4 | **T-03** 646-image detection + description GPU pass over the consented corpus | 1 A10 session, **≤6 GPU-h / ≤$12**, hard stop | The one justified bursty-GPU spend today. Not detector training — not under the §19e embargo. **Owner:** operator (nobody else can start an A10 burst). **Output artifact:** one run directory under `benchmarks/results/t03-<date>/` containing `items.jsonl`, the per-image detection export, and a `provenance.json` stamping model ids, commit SHA, and total spend. **Acceptance:** the pass covers all 646 images with zero decode failures and zero missing export rows, and the run directory reproduces its own image count from `items.jsonl`; short of that it is a failed run, not a partial one. **Quarantine:** outputs are quarantined and MUST NOT feed the sealed split (step 8) until step 0 has merged, because a pass run on OpenCV 4 inherits the invalidated detector geometry. Re-run after step 0 rather than back-patching. **Not a precondition of T-14:** step 3b is bounded on the Golden-150 frame and does not read this pass, so a delayed A10 slot delays step 5 onward, never the cheap kill |
| 5 | **T-02** sampling design | 1.5–3 eng-days | Only if T-14 didn't kill. **Complete when** the design names the strata, the per-stratum target counts, the resampling unit, and the sample size that funds the T-05a effect at the declared precision — written down and reviewed. **Fails** if the size it returns is unaffordable at T-04's per-face rate: that is a real outcome, and it sends the line back to a narrower question rather than to a bigger annotation budget |
| 6 | **T-04** exhaustive annotation | **88–147 person-h** (full 646 ≈ 1,763 faces); ×2 if dual-annotated | Only if T-14 didn't kill. 150-image subset ≈ 410 faces ≈ 20–34 person-h. **Complete when** every image in T-02's sample is annotated to the T-09 face-label rule and inter-annotator agreement on the dual-annotated portion clears the threshold T-09 sets. **Fails** if agreement lands below it — the rule is underspecified and T-09 reopens; do not average disagreeing annotators into a ground truth |
| 7 | **T-05a** deficit test | ~1 eng-day, $0 | Terminal gate for the detector line. Closes D-01. **Kill D-01** if the 95% UCL on the deficit clears the threshold T-13/T-12a set. **Keep D-01** if the LCL sits above it. **Inconclusive** if the interval straddles it — and inconclusive is a terminal state here, not a licence to re-run: the frame was sized by T-02 to resolve this, so straddling means the effect is smaller than the programme decided was worth chasing |
| **8** | **T-08** Golden-150 rebuild — draw and **seal** the test split (`benchmarks/manifests/`) | **~2 days**, $0 | Depends on **T-02, T-03, T-04**. Sealed before any curation or selection runs; strata declared and populated; hard cells kept, never filtered. Size is T-02's output — "Golden-150" is a name, never a sizing claim. **Unresolved conflict — operator call:** T-08's stated dependencies include T-02/T-04, which the decision table closes on a T-14 kill, yet FIR-11 Slice 3 and the VLM-6 curation at `:10018` need the sealed split either way. Decide what T-08 draws from if D1 dies |
| **9** | **T-12b** instrument the OEC | ~2–3 days, $0 | Depends on **T-03** (descriptions) and **T-08** (the split the OEC is defined over). Emits enrolled roster, present-enrolled set per image, and name mentions per description, with the abstention selection rule fixed |
| **branch** | **Person cascade / body prior (§5a)** — the success deliverable on `D1 passes` | **Not sized.** §11 calls it "no new weights, cheap"; it carries no T-\* row, no effort figure and no anchor. **Size it before committing** | This is the branch the register expects most, and it is the only terminal deliverable currently unscheduled |

### Decision table while D2 is suspended

- **D1 killed by T-14** ⇒ close the detector line. All effort to the embedder. Requires the *miss-inflated* bound (step 3b); the raw union bound does not authorise a kill.
- **T-14 inconclusive** — inflated UCL does not clear 0.05, or the union miss probe returns `m_ucl ≥ 0.05` ⇒ **D1 is not killed and not passed.** The cheap frame has been shown insufficient; proceed to T-02 and T-04 as if T-14 had not run. This branch is the expected outcome if the union miss mass is material, and budgeting should assume it.
- **D1 fails T-05a** ⇒ same as killed.
- **D1 passes** ⇒ **take the cascade (no new weights) and stop there.** Detector GPU spend stays unauthorised **until D2 is evaluable (T-12a) and also fires.** The cascade is the branch row in the table above — unsized; size it before committing.
- **D1 and D2 both fire** ⇒ cascade, then T-15 (dual-label pilot), then an SCRFD A/B.

### The align+embed line

Not gated by D1, **but not independent and not authorised.** These are logical dependencies of the unlock, **not a schedule** — the step table above is the schedule, and it adopts D3 at step 1, ahead of T-01 at step 3, so adoption is never post-hoc. (a) step 0 recovers the measurement under 5.x, reported as **FNIR@FPIR, not rank-1** (T-05c); (b) T-13's already-adopted D3 supplies the acceptance criterion; (c) T-01 attributes the loss against it. **Only if (c) lands on *embedding* do T-16 (embedder corpus) and T-17 (retrain — the first GPU-hour on training) unlock.** If (c) lands on *alignment*, the whole line moves to the detector leg.

### Known ceiling — read before committing to T-14

The resolvable-effect floor of this frame is the **half-width of the percentile CI on Δ**, from the image-level cluster bootstrap at B=2000 with `resampling_unit = image` — the estimator the FIR-8 statistical contract has been on since v6.4. The frame resolves an effect only when that half-width is ≤ Δ/2.

**That half-width is not yet computed, and no number here should be read as if it were.** It is a property of the realised Golden-150 detection outcomes, so it cannot exist before T-14 produces them; the earliest it can be known is the T-14 run itself. The figures this section previously carried — a design effect `1 + 11.925·ICC` and a "realistic MDE of 0.10–0.12", attributed to a §0f that exists in no document in this repo — were computed under the DEFF/ICC/MDE machinery that v6.4 **retired**, and they are not convertible into a bootstrap half-width. They have been removed rather than restated, because sizing the same frame by two incompatible methods is how a bench reports a winner it did not measure.

Until the half-width is computed, treat the **0.05–0.10 dead zone as provisional**: it is the band the retired machinery projected, retained only as the *scope* of the operator signature, not as a measured property of the frame. A T-14 bound landing in that band is neither kill nor pass — it is an operator decision, stated in writing *before* the run. **That signature is step 3a of the sequence, not a note** — it is scheduled and it gates step 3b. Step 3a's written rule must be phrased against the bootstrap CI half-width, and must say what happens if the realised half-width turns out wider than the band it was written for.

---

## 5. Occlusion performance — the specific path

Occlusion is where InsightFace's replacement has to win, and it is the one place where a real, measured signal already exists (M-08: a ×4.3 attenuation in apparent face size under occlusion, on exhaustively annotated data).

Four levers, in increasing cost:

**(a) Body prior / person cascade — cheapest, no new weights.**
Detect a *person* with the off-the-shelf cascade, then search for a face in the expected region above the torso instead of across the whole image. This collapses the search space in exactly the hard cases. The motivating case is real and in our corpus: `pewter_hollow_271.jpg`, where only part of the left eye is visible and the rest of the face is behind a phone. **If D1 passes, this is the terminal deliverable — the plan explicitly says take the cascade and stop.**

**(b) COCO keypoints 2017 as a hard-occlusion mining complement.**
5 of 17 keypoints are facial (nose, eyes, ears). 26.1% clean licence = 30,836 images, 16,513 with a person, 33,193 head-bearing instances. Instances with labelled shoulders/hips but **all facial keypoints v=0** are candidate hard-occlusion positives — the `pewter_hollow_271` case as *data*. **Trap:** 51.4% of person instances carry no facial keypoint at all, so keypoint-derived faces are **not** exhaustive ground truth. Tracked as D-05 / D-10 / T-07 (~3 eng-h).

**(c) SAM-based occluder compositing — synthetic degradation.**
SAM segments occluders offline and composites controlled degradation onto clean faces. This supplies a *controlled* difficulty axis for training and ablation. It must **never** be used to define an occlusion stratum for evaluation — synthetic occlusion is not the thing we are measuring.

**(d) Ignore-region / semi-supervised detector training on Open Images.**
This is the real occlusion-hardening campaign, and the honest cost is *weeks of engineering*, not GPU dollars. Train is non-exhaustive, so the loop must carry positives-only supervision with ignore-regions and must be validated only on the exhaustive val+test split. **Gated behind D-04.**

### The hard licence gate on (d)

| Layer | Licence | Consequence |
|---|---|---|
| Open Images **annotations** | CC BY 4.0 | Clean. Attribution duty: credit Google LLC, link the licence, state changes |
| Open Images **images (pixels)** | Per-image **CC BY 2.0, warranty explicitly disclaimed** | **Conditionally clean only** |

Annotation-layer analysis (everything in M-08) is fine today. **Training on pixels is a hard gate: D-04 at prior 0.85, requiring per-image verification and an attribution manifest (T-06).** Do not start the training loop before that clears.

**Rejected corpora, and why it matters:** `faces4coco` and `coco-faces` are out — their boxes come from yoloface/YOLOv3 trained on WIDER FACE and cut at conf ≥ 0.7. Using them re-imports the exact Golden-150 circularity at 59k scale [MLDATA-08 audit failure, MLDATA-09 directional harvest bias]. WIDER FACE itself is excluded by policy (CC BY-NC-ND); the NC/ND reach-through argument is **our policy, not a legal finding**. Not yet licence-checked and therefore not usable: CrowdHuman, COCO-WholeBody, FDDB, AFLW, MAFA, UFDD (D-07 / T-11, ~4 eng-h).

**And do not spend the eval set.** val+test is 22,602 boxes / ~7,127 occluded / 12,416 images. It is the *only* exhaustively annotated measurement surface we have. Training on it destroys the ability to measure the thing we trained for.

---

## 6. Resources required

### Human effort — the actual bottleneck

| Item | Cost | When |
|---|---|---|
| T-09 face-label rule | ~1 eng-h | Now |
| T-12 OEC + T-13 D3 criterion | ~1 eng-h each | Now — cheapest unblock on the board |
| T-07 COCO replication | ~3 eng-h | With (b) |
| T-11 per-corpus licence read | ~4 eng-h | Before any new corpus enters |
| T-01 alignment/embed attribution spike | ~1 eng-day | Now, in parallel |
| CVUP-1 merge + baseline regeneration | ~1 eng-day | **Step 0** |
| T-02 sampling design | 1.5–3 eng-days | After T-14 survives |
| **T-14 union adjudication** | **20–34 person-h** | The cheap kill |
| **T-04 exhaustive annotation (full 646)** | **88–147 person-h**, ×2 if dual-annotated | Only if T-14 doesn't kill |
| T-05a deficit test | ~1 eng-day | After T-04 — terminal gate on D-01 |
| **T-08 Golden-150 rebuild (sealed split)** | **~2 days** | After T-02/T-03/T-04 — before any curation selection runs |
| T-12b OEC instrumentation | ~2–3 days | After T-03 **and** T-08 |
| T-15 dual-label pilot | **47–78 person-h** (~940 faces × 3–5 min) — v8 withdrew the earlier "2–3 days" as 2–3× under its own cost model | Only if D1 and D2 both fire |
| Ignore-region training loop (detector) | **weeks of engineering** | Only after D-04 clears |
| FIR-11 Slice 3 labeling | 2.5–5 operator-h (~140 images × 2 passes) + 0.5–1 h gold-item prep | In FIR-11 |

### Compute

| Item | Cost |
|---|---|
| T-03 646-image detection + description pass | 1 A10 session (~$2/GPU-hr) — **authorised, do it** |
| FIR-11 Slice 5 re-baseline compute | **< $1** (A1.Flex ~$0.152/hr) |
| FIR-7 Slice 1–2 adapter budget | 2–12 GPU-hr ≈ **$4–24** — **CONDITIONAL on D-01, do not price or spend.** Retired outright if T-14's bootstrap 95% UCL < 0.05 |
| T-17 embedder retrain | **The first GPU-hour on training.** Unauthorised until T-01 lands on *embedding* and D3 is adopted |
| Detector training campaign | **Not funded.** Any figure must be re-derived as `images × epochs ÷ throughput × $/hr` with a stated schedule and a **measured** A10 img/s |

> **Dollar discipline:** §19e's verdict is *"corpus procured, training not funded."* The withdrawn $20–100 band and the claim "GPU cost never was the constraint" are both retired. Do not quote a training dollar figure that has not been re-derived from a measured throughput.

### Infrastructure

- **Stay on OCI A10 burst** for adapter/embedder training. Data locality, privacy, and ops beat HuggingFace's ~$0.5/hr list saving; HF is not used for face data at all.
- **Rent a specialist A100** (RunPod / Lambda) only if wall-clock demands it.
- Curation atlas: UMAP face atlas + FiftyOne queue on the existing CPU box. Projections are **DIAGNOSTIC-display only, never a gate**.
- Descriptions and VLM inference run on the remote OCI VM. The laptop is orchestration-only.

### Legal / commercial

- **Counsel review is the one operator-reserved gate.** Nothing in the training campaign should start without it clearing D-04.
- Obligations to satisfy before public launch: consent architecture (GDPR explicit consent + DPIA; BIPA subject release; geo-gating), an Art. 6 AI-Act classification memo, wp.org readme disclosure, and a model card carrying intersectional performance at fixed thresholds.
- **No regime compels publishing training data.** Server-side weights remain a structural moat; wp.org freemium is supportable (full local code free, capability-priced SaaS tier). Local-only is an escape hatch shipping clean-tier models only.
- **Send the InsightFace commercial-quote email.** $0, and it is the only action that can make "parity" and "commercially clean" simultaneously true while the in-house line matures. Include the distillation-rights question.

---

## 7. Open decisions

| ID | Question | Prior | Closes on |
|---|---|---|---|
| D-01 | Is the collapse detection-bound? | 0.35 | T-14 / T-05a |
| D-02 | Alignment vs embedder | 0.50 | T-01 |
| D-03 | True occlusion prevalence in our domain | — | T-02 / T-04 |
| **D-04** | **May we train on Open Images pixels?** | **0.85 — hard gate** | T-06 + counsel |
| D-05 | COCO {4,5,7,8} pool + BY-SA | 0.70 | T-07 |
| D-06 | Train/val IsOccluded mechanism | re-opened | **T-15** (dual-label pilot) |
| D-07 | Which corpora are licence-admissible | — | T-11 |
| D-08 | Embedder acceptance criterion | **never declared** | T-13 |
| D-09 | What counts as a face | — | T-09 |
| D-10 | COCO v=0 semantics | deferred | — |

---

## 8. Risks that would sink the program

1. **Sealing the gate against contaminated GT.** FIR-7 Slice 0a burns a K=3 budget after use; if it freezes against buffalo-generated ground truth, all three re-gate attempts are permanently uninterpretable. Mitigated: FIR-7 Edge 3 now blocks Slice 0a on FIR-11 Slices 1–2, and CVUP-1 is step 0.
2. **Spending the exhaustive val+test split on training.** Irreversible loss of the only clean measurement surface.
3. **Fixing detection alone.** If T-01 lands on alignment or embedding, a better detector ships *more* faces to a component that misidentifies them — a worse product. This is why T-01 runs early and in parallel.
4. **A T-14 bound in the 0.05–0.10 dead zone.** Neither kill nor pass. Decide the rule in writing before running it.
5. **Starting the pixel-training loop before D-04 clears.** Weeks of engineering against a licence that may not permit the output to ship.

---

## 9. Do this week

1. Merge **CVUP-1** and regenerate the SFace baselines as recorded artifacts. *(step 0 — one of two blockers on FIR-7 Slice 0a; Edge 3 also blocks it on FIR-11 Slices 1–2, so item 7 is not optional)*
2. Write **T-09** (face-label rule), **T-12a** (OEC decision), **T-13** (D3 embedder criterion). ~3 engineering hours total. **That figure covers the decision half only.** T-12a's instrumentation half is step 9 (T-12b, ~2–3 days) and is not in it; **Do not describe this as unblocking D2.** T-12a lifts the stated suspension condition; it does not make D2 decidable, because no OEC number exists until T-12b runs over the sealed split at step 9.
3. Open the **T-01** alignment-vs-embedder spike. No anchor exists in the tree — create one.
4. Run the **T-03** 646-image GPU pass. Authorised; prerequisite for rebuilding the sealed eval split.
5. **Sign the T-14 dead-zone rule** *(step 3a)* — decide in writing what a 0.05–0.10 UCL means before T-14 is scheduled. Operator-reserved, ~0 cost, and it gates a 20–34 person-h task.
6. Send the **InsightFace commercial-quote email**, with the distillation-rights question.
7. Land **FIR-11 Slices 0–2** so the provenance gate and the sealed-split machinery exist. **Do not over-read this:** the plan states Slices 1–2 are *contract hygiene* and "buy zero statistical power and must not be described as if they do" — the rebaseline is Slice 5. What Slices 1–2 do buy is the ordering constraint FIR-7 depends on: they must land **before** FIR-7 Slice 0a seals anything, because Slice 0a burns a K=3 budget after use. That constraint is now carried as **step 2c** of the binding sequence, which states the two-part release condition and records that Slice 0a is one-shot.
8. **Do not** price or spend the detector training budget.
9. **Assign an owner and a date** to the 20 open FIRTRAIN/GT2 findings below, and decide the migration question. They are named as the program's genuine live work and currently have neither.

---

### Related open work (not in the critical path)

- **FIR-8** remains blocked: `acx-dev-fir` does not exist on the VM. Unblocks when **FIR23-STACK Slice 1** lands the per-model isolated stack (InsightFace 512d and SFace 128d cannot share a database).
- 20 findings remain open on `MAINT-fir-training-feasibility-20260727` (FIRTRAIN-01, 06–12; GT2-01..12). These are the program's genuine live work. Recommend migrating them into the v8 D-\*/T-\* register rather than tracking the same questions in two places. **This recommendation has no owner and no date and is not a sequenced step — it is item 9 of "Do this week" precisely so that the gap is visible.** Calling work "the program's genuine live work" and then filing it under *not in the critical path* is a contradiction the next planning pass has to resolve, not inherit.
