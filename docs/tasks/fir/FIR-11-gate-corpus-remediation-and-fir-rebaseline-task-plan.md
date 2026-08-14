# FIR-11. Gate-Corpus Remediation and FIR Re-Baseline

> **Metadata**
>
> - **Date**: 2026-07-27 (rev 2, 2026-07-28 · rev 3, 2026-08-13 · rev 4, 2026-08-13)
> - **Author**: Claude Opus 5 (high) — rev 2 after `plan-analyze` (12 findings) + 5-lane remote grok-4.5 adversarial flock (21 findings); rev 3 judgment pass against the 35 open FIR-11 findings in handoff; rev 4 remediation of the R1P adversarial panel (25 consolidated findings, bodies in the DB, referenced here by ID only)
> - **Project**: `apps/prototype-description-service`
> - **Task ID**: `FIR-11`
> - **Target Branch**: `feature/fir-11`
> - **Epic**: [E22 Commercial Face Identity Replacement](../../epics/v0.5.0/commercial-face-identity-replacement-epic.md)
> - **Depends on**: FIR-9 (curation atlas — owns the labeling UI this task specifies a blind mode for)
> - **Review Coverage Target**: 2 (≥1 remote HIGH + ≥1 local adversarial; findings in MCP, never pasted here)

---

## Rev 3 Changelog

Finding bodies live in the handoff DB under task_ref `FIR-11`; this table maps each rev 3 change to the finding IDs it addresses. Findings whose substance rev 2 already resolved are re-verified here and marked *confirmed*.

| Change | Addresses |
| --- | --- |
| Measurement Contract: explicit H0 row, statistic–interval pairing row, IU-gate ownership moved explicitly to Product B, per-test-power caveat for shared subjects, DEFF/aggregation dependence clarification. Contract marked **DRAFT-PENDING-REVIEW** | GF-07, PA-05, GF-06, GF-09, GF-08 |
| Slice 4: provisional occasion-key derivation from existing pixels with named fallback proxy and stated bias direction; exact IU inflation re-derived under McNemar sizing | PA-04, GF-09 |
| Slice 5: `A2 − A1′` rescoped from "circularity estimate" to bundled labeling-regime effect with residual-contamination caveat; determinism contract for the new statistics; template-fusion weighting bound to EMB-02/EMB-07/EMB-10; subject-key derivation stated; non-mated threshold pre-declared | GF-03, PA-12, GF-15, PA-07, GF-16 |
| Slice 3: blind-queue record schema stated; headless CLI fallback for the FIR-9 dependency; walkthrough verifier must not be the original adjudicator; single-labeler pass renamed "independent re-pass, not blind" with the bias implication stated | PA-02, PA-11, GF-02 |
| Slice 1 + Slice 0 + Cost Model + checklists: scrape-signature census widened from the two-regex 36/150 to the full signature family (census recorded in the PR-35 finding: 113/150 entries · 130/167 probes · 44/53 identities); worst-case pool restated 37 entries / 37 probes / 22 identities; ceiling shortfall re-derived; loader warning implements the full family; counts re-derived at Slice 1 against the frozen manifest hash (manifest data is not present in this checkout) | PR-35, PROV-01 |
| Slice 2: coverage-validator error taxonomy (invariant name, entry index, path); count-then-box `face_count` procedure so the coverage invariant can fail; `LabelLineage` gains `batch_id`; consumer inventory gains `bakeoff10-manifest-20260716.json`, `refetch6-manifest-20260716.json`, `scripts/eval_harness/tests/fixtures/` | GF-21, GF-11, GF-12, GF-13, PA-06, GF-10 |
| Context Loading: canon citations pruned to rules with triggering work in this plan (every retained ID verified present in current canon); `filter_headline_probes` re-cited from MLDATA-20 to MLDATA-09 (trigger fit) | GF-01 |
| Cost Model: FIR-9 blind-mode wait recorded as a schedule-risk line | GF-20 |
| Verified as already resolved by rev 2, no further edit: Product A/B split and under-powered banner (GF-05, GF-06 core), gold-QC/second-pass/arbitration/inconclusive (GF-04), sizing-before-labeling ordering (GF-17), VoI subsample (GF-18), roster_only refusal inventory (GF-19), conditional-on-pool intervals per AUDIT-08 (GF-14 — rule text re-verified against current canon), epic metadata (PA-01), draft_labels/corpus_inventory new-symbol naming (PA-02/PA-03 core — verified against the modules on disk), golden-v2 path (PA-08), consumer inventory (PA-09), named new test modules (PA-10 — `scripts/eval_harness/tests/` holds one module today, matching the plan's "(new)" markers), FIR-9 dependency line (PA-11 core), EVAL-18 endpoint (GF-16 core — rule text re-verified). *Rev 4 correction: PA-09 (consumer inventory) was over-claimed here — the description-eval consumer enumeration is still deferred to the pre-Slice-2 grep and the inventory had verified holes; see the rev 4 changelog.* | — |

---

## Rev 4 Changelog

Remediation of the consolidated R1P panel (finding bodies in the handoff DB under task_ref `FIR-11`; IDs only here). Two structural rules this rev adds: **claims about repo state or cross-plan edits that are not true on disk are converted into named blocking preconditions with owners, never stated as done**; and **the Slice 1 pool re-derive is a blocking gate on Slices 2+**.

| Change | Addresses |
| --- | --- |
| Pool arithmetic re-derived in one frame from the Slice 1 table (150 − 7 celeb − 3 scraped-unprovenanced = 140, with the 3 kept `IMG_*` rows retained as `operator/mock_entity`; all-drop of the 110 remaining adjudicable signature-family entries → **30 entries / 30 named probes / 17 identities**). Every 37 / 137 / ~170× figure replaced by the 30–140 interval and ~210×; Slice 1 re-derive made a blocking gate: Slices 2+ do not start until re-derived numbers are committed and any divergence from the planning interval is dispositioned in a plan changelog entry | FIR-11-R1P-02, FIR-11-R1P-05, FIR-11-R1P-16 |
| Circularity claim rescoped end to end: Ship rule second clause, FIR-7 evidence-tier language, Objective, and Success Criteria restated in terms of the **bundled labeling-regime effect** `A2 − A1′`; no upper bound on ground-truth circularity is claimed anywhere; the golden150→Product-B transport gap is named and the Product-B bias clause is deferred to contract lock | FIR-11-R1P-01 |
| Primary-endpoint honesty: no candidate leg runs in Slices 0–5; the "Product A can execute every row" claim corrected; Slice 5 arm deltas barred from being reported as the contract's Δ̂ | FIR-11-R1P-03 |
| k resolved by an explicit lock rule: k=7 governs Product A descriptive tables only; Product B's gate is k=8-with-populated-`similar_people` unless an explicit exclusion decision is recorded at contract lock | FIR-11-R1P-04 |
| NI test named as a real procedure: Nam/Tango score test for paired non-inferiority at resolved one-sided α = 0.025; null discordant split `π₀ = (p_d − δ)/(2·p_d)` stated next to the alternative split; `mcnemar_exact` respecified accordingly | FIR-11-R1P-06 |
| Slice 0 ceiling restated in Connor's actual unit (independent paired subjects); the 1.86×/3.1×/~6,300 chain marked provisional wrong-family illustration pending Slice 4's exact re-derivation; the hard gate rescoped to the order-of-magnitude conclusion, which survives every reading | FIR-11-R1P-07 |
| Identity-as-PSU fallback: false "bracket" replaced by a single-reading DEFF plus sensitivity sweep plus an empirical sign check on EXIF-recoverable rows; the m-direction contradiction with the Contract's m row fixed; the fallback's role bounded to provisional sizing, reconciled with the identity-resampling ban | FIR-11-R1P-08 |
| `capture_session_id` given writable surfaces (`LabelLineage` field, commit-record field); provisional occasion key given named **(new)** functions, a persistence artifact, and an owning slice | FIR-11-R1P-09 |
| Repo-state honesty: `/benchmarks/` is gitignored with zero tracked paths — a **Slice 0 blocking precondition (not yet done)** now gates every freeze/hash/commit claim; FIR-7 and VLM-6 reciprocal-edit claims converted from past-tense assertions to blocking preconditions with owners; VLM-6 added to the Consumer Inventory | FIR-11-R1P-10, FIR-11-R1P-11 |
| FIR-9 dependency given an acceptance precondition and a versioned queue schema; headless fallback de-identified (opaque item ids, no `image_path` in the export); GF-02 conditional blind/independent-re-pass wording carried through; gold-item source independence from buffalo's partition made an explicit requirement; operator `face_count` write target named | FIR-11-R1P-12 |
| Statistic–interval pairing disambiguated at the implementing symbol: `deff_adjust` is sizing-time only; analysis intervals come from the subject-level multilevel/sandwich analysis with no probe-level DEFF multiplier | FIR-11-R1P-13 |
| 8-image disposition: drop-only branch acknowledged as the sole Slice-1-legal path | FIR-11-R1P-14 |
| Problem-statement Wilson widths: implicit p̂ ≈ 0.70 stated, p̂ = 0.5 worst case shown, discordant-pair restatement added at the top | FIR-11-R1P-15 |
| Residual number hygiene: retired-104 pricing removed; merged-pool shortfall restated in probe units (~11×); gold-item budget re-derived from the corrected pool | FIR-11-R1P-16 |
| Canon hygiene: decorative AUDIT-11 co-citations pruned; Slice 5 sampling-frame disclosure re-cited AUDIT-07 → AUDIT-08; canon path corrected to the canonical `heuristics-canon` repo; MLDATA-20 moved to an explicit out-of-scope line | FIR-11-R1P-17, FIR-11-R1P-23 |
| Ownership closure: every Files-table symbol has an owning slice Changes bullet or is deleted (`merge_manifest_pools` deleted — no slice merges pools); golden-v2 assembly assigned; legacy-loader "Slice 3 only" corrected to the Slice 5 arms; tracked harness copy of the corpus646 manifest added to the inventory; the rev-3 "PA-09 already resolved" claim corrected | FIR-11-R1P-18 |
| A1″/A1′ reproducibility: "original scoring" pinned by a recorded full scoring-code SHA and invoked from that SHA; the pre-CVUP-1 mixed-store branch's effect on A1″ resolved explicitly | FIR-11-R1P-19 |
| vMF σ estimator corrected to the R̄-only form (no store-size N in a population dispersion) | FIR-11-R1P-20 |
| Contract draft-vs-reviewed contradiction removed: the 2026-07-28 PSU amendment is part of the draft and locks only at contract lock | FIR-11-R1P-21 |
| `wilson_half_width` reuses the existing `report.py:912` helper; the conflicting **(new)** marker dropped | FIR-11-R1P-22 |
| Terminology gains a three-sense "sealed" disambiguation; `LabelLineage` gains `label_source` enum and a graded `confidence` channel | FIR-11-R1P-24 |
| Documented command fixed: `make bakeoff-face-score FACE_RUN=<run-record>` | FIR-11-R1P-25 |

---

## Objective

Make the FIR gate corpus honest about what it can and cannot measure, then buy the measurement it actually needs.

Two products, deliberately separated because one is achievable on existing pixels and the other is not:

- **Product A — bias-bounded re-baseline (this task).** Schema invariants that make the measured defects unrepresentable, a Value-of-Information-sized double-labeled audit that measures the **bundled labeling-regime effect** (procedure + coverage + box geometry together — see Slice 5), and a re-run baseline published with that measurement and an explicit **under-powered** declaration. Ground-truth circularity proper is **bounded from below, not identified and not upper-bounded**, by this design; the honest claim is stated at the Ship rule and Slice 5.
- **Product B — occasion-structured successor corpus (specified here, executed after).** The only design in this document that can reach the δ=10pp intersection-union gate. Product A does not replace it and must not be reported as if it did.

**Product A is not a ship gate.** Nothing in Slices 0–5 licenses retiring InsightFace. Slice 6 specifies what would.

## Problem Statement

`benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` reports a buffalo_l baseline whose ground truth cannot support the conclusions drawn from it. Three defects, all measured at source, plus one ceiling.

1. **Outcome-dependent ground truth.** Identity labels were produced by operator *merge-only* adjudication of buffalo's own cluster proposals. Merge-only adjudication cannot split a false join, so buffalo's false joins freeze into the reference partition. The measured `false_split 0.065` vs `0.351` (5.40×) advantage for the incumbent is therefore preferentially optimistic.
   Canon: **[EXP-22]** (subset/cluster chosen using the outcome, then the same outcome tested on those observations — circular analysis); **[AUDIT-04]** (gold review applied only to detector-positive items, so miss rate is not estimable from the verified slice); **[MLDATA-08]** (set built by running a detector over images, needing a post-hoc stratum audit); **[OBS-09]** (success metric produced or editable by the same subsystem under optimization).
   *Not* **[EVAL-19]** — that rule governs an error rate normalized by a system-produced volume. `false_split` is normalized by reference-partition pairs, not by buffalo's own candidate count. Rev 1 cited it; 5/5 flock lanes rejected the citation. Corrected here.
   The circularity is **partial, not total**: HARD rank-1 `0.558` against chance `1/53 = 0.0189` (≈29.6×) proves real residual class structure survives. Per **[MEAS-02]**, the deliverable is a narrowed range on the contamination, not a refusal to state one.
2. **Roster-conditioned annotation coverage (π = 0).** `benchmarks/manifests/corpus-manifest-v3.json` records **584 named** boxes against **1,763 detected** across the 646 images, with a per-image positive excess of **1,182** on **368 of 646** images — the annotation records only roster names, so every non-roster face the detector proposes sits outside the label set. *(First evidence came from the superseded `corpus646-interleave-manifest-20260716.json`, whose 584 boxes were all named with zero unnamed: on the 64 images it shares with `golden150-draft-20260723.json`, golden150 recorded 189 boxes where it recorded 74. v3 now measures the full 646 directly, so that 115-face overlap figure is superseded, not generalised.)* A detector that correctly finds a bystander scores as a false positive against this manifest. Canon: **[AUDIT-07]** (rate claims a population but the draw list is an unnamed subset with no coverage inventory) — a partial fit, since AUDIT-07's trigger is a population rate from an unnamed draw list and here the draw list is *named by construction*.
3. **Provenance holes.** 6 golden150 entries carry no `provenance` key at all; `GoldenEntry.provenance` is `Provenance | None = None` (`manifest.py:365`) so nothing rejects them. Canon: **[PROV-05]**.
4. **Hard power ceiling on existing pixels.** No stratum resolves a 10pp difference. Largest (clean, n=56) has a Wilson 95% half-width of ±11.9pp at the observed stratum accuracy **p̂ ≈ 0.70** (the p̂ these widths were computed at — previously unstated); `masked` (n=5) is ±31.4pp at the same p̂. At the p̂ = 0.5 worst case the widths are ±12.7pp and ±33.0pp — the conclusion is unchanged either way. In the Contract's own decision units: 56 subjects yield ≈11 expected discordant pairs at p_d = 0.20, against the ≈157 independent paired subjects Slice 0's sizing requires per stratum — the Wilson figures here are the descriptive illustration only, per the statistic–interval pairing row. `strata.py:78` sets `MIN_STRATUM_POOL = 5`, roughly two orders of magnitude below a δ=10pp gate, so a stratum passes the harness's own floor while being statistically empty. **Re-labeling does not fix this** — see Slice 0.

### Superseding input: `corpus-manifest-v3.json` (2026-07-28)

`benchmarks/manifests/corpus646-interleave-manifest-20260716.json` is superseded by **`benchmarks/manifests/corpus-manifest-v3.json`**, rebuilt 2026-07-28 over the same 646 pixels. Defects 1, 3 and 4 are unaffected. Defect 2 is **confirmed and now quantified**; one supporting claim elsewhere in this plan is **falsified**.

*Re-derivation duty, closed form.* Search this plan for `20260716`, `corpus646-interleave`, and any headcount not listed in the Population paragraph below; replace each from v3 and cite `benchmarks/manifests/corpus-manifest-v3.json` at the point of use. **Done when that search returns only the freeze/retag instructions that intentionally name the old file.**

**Population (v3, re-derived).** 646 images · **137** distinct identities · **558** identity appearances · **538** images carrying ≥1 identity · **108** carrying none. Multi-identity images: **14 carry two, 3 carry three** (17 total, 20 surplus memberships — `558 − 538 = 20`, not 17; rev 2 and QA v7/v8 both said "17 carrying two", which double-counts the triples into the pair bucket). Images per identity: mean 4.073, median 2, max 50. Size-weighted mean cluster **M̃ = 12.925** (`Σ s_i² / Σ s_i` over identity clusters, = 7,212 / 558).

> **Two units, one paragraph — do not cross them.** `538 / 108` counts **images by identity roster** (`named_identities` non-empty); the `584` in the next block counts **named boxes** (`Σ named_face_count`). Neither is a headcount of the other. Measured on v3: **530** images carry ≥1 named *box*, so **8 images list a named identity and carry zero named boxes**. That 8 is not a rounding artifact and not merely a legibility defect — those roster members are inside the identification estimand while contributing no localisable probe, so they are unscoreable under an `exhaustive` manifest and would fail the Slice 2 coverage invariant on the spot. **Disposition them in Slice 1 alongside the provenance cases.** The only Slice-1-legal disposition is to **drop the identity claim as unsubstantiated**: the boxing alternative cannot execute, because Slice 3 runs after Slice 2 and never touches corpus646 by scope, and these 8 are a v3/corpus646 fact — deferring them "to the Slice 3 pass" parks them in a slice that excludes them and runs too late. Record each drop; re-adding any of the 8 via boxing is future corpus646 work outside this plan. Do not let them ride into Slice 2 unresolved.

> **Naming, because these two nearly collided.** Call `M̃ = 12.925` and the expression `1 + 11.925·ICC` **`C_identity`** — an *identity-membership concentration index*, **descriptive only**. It is **not a design effect and must never be used as this plan's `DEFF`**, for the reason the block itself establishes below: identity clusters overlap (17 images sit in two or three) and exclude 108 images, so a Kish correction over them is not a valid corpus-wide deff — it is a statement about how concentrated identity membership is, nothing more. The **bare token `DEFF` everywhere else in this plan means exactly one thing**: the Measurement Contract's occasion-level `1 + (m − 1)·ρ` at m ≈ 3.3, over named probes, on non-overlapping occasion PSUs. Different corpus, different observation unit, different cluster definition, different correlation parameter. Slice 4 recomputes `DEFF`; it does not touch `C_identity`.

**Defect 2 is confirmed and larger than stated.** v3 records `named_face_count` and `detected_face_count` separately for the first time: **584 named**, **1,763 detected**. The gap is not a single subtraction — it runs in both directions:

- `sum(max(0, detected − named)) = 1,182` — the **per-image positive excess of detector proposals over named boxes**, on **368 of 646** images. Note the formula: it is a per-image *count* difference, clipped at zero and summed. The manifest carries `detected_boxes` and `named_boxes` but **does not associate them**, so this is not a face-level unmatched count.
- `sum(detected) − sum(named) = 1,179`. The 3-unit difference is real and points the other way: **3 images carry a named face the detector did not find at all** (media_id 221, 271, 556 — `named 1, detected 0`). Those are detector misses on curated ground truth.

**How 1,182 may and may not be restated.** It is an **unmatched machine-proposal inventory** — the size of the adjudication queue — and nothing else. It is **not** a count of omitted real faces, and it is **not even an upper bound** on them in either direction, for two independent reasons: (a) without box matching, an image can simultaneously hold a detector miss on a named face and a spurious proposal elsewhere, so the excess and the omissions are not nested sets; (b) false positives inflate it while detector misses — which never enter the excess at all, and the three images above prove such misses exist — deflate any omission reading of it. So the only defensible sentence is the queue-size one. **Never restate 1,182 as a verified population size, as a face count, or as a bound.** Describing any individual detection as "a real face carrying no name" requires spatial adjudication first. Adjudicating it is exactly the work Slice 2 buys. What is established without adjudication is the structural claim: π = 0 was never a schema quirk. (The 64-image golden150 overlap — 115 omitted faces — was the early evidence of this defect; v3 now measures the full 646 directly, so that figure is superseded, not generalised.)

**Falsified: "corpus646 carries no `tags` field at all."** v3 carries operator hand strata: **150 entries were hand-reviewed** (`slice_tags_source: operator_hand`), of which **96 produced at least one tag** and **54 were reviewed and produced none**. Tag counts across the 96: profile 50 · blur 28 · low_res 26 · occlusion_other 19 · sunglasses 13 · masked 5 · **similar_people 0**. No entry carries a tag from any other source. So the merged pool does contribute stratum members without new tagging — and the 54 reviewed-clean entries are *evidence of absence*, unlike the 496 never reviewed.

> **Closed action.** Two units, kept apart. **Image inventory:** the image-level union is **732** (`150 + 646 − 64` shared sha256), not "~700"; corpus646 contributes **96 hand-tagged / 550 untagged** images with stratum maxima profile 50 · sunglasses 13 · masked 5 · similar_people 0. **Probe units, which is what the pool-sizing table is denominated in:** the 96 tagged images carry **99 identity appearances / 111 named boxes**; the 550 untagged carry **459 / 473**. Do not let 96 and 550 stand as pool contributions inside a table sized in raw named probes — that is an image count in a probe column, and it makes the contribution look ~5× smaller than it is.
> **Verdict to preserve, unchanged:** every hard stratum remains under the plan's derived stratum floor, and `similar_people` is empty in *both* pools, so no amount of re-tagging invents lookalike pairs. Do not reword either into a soft pass.

**Missing deliverable: the sealed eval split (QA v8 T-08).** QA v8 assigns this plan the split artifact and requires it be **drawn and frozen before curation selection runs** [EVAL-07] [MLDATA-09] [EVAL-10]. Rev 2 did not name it; it is now named — **"sealed eval split"**, a Slice-2 deliverable committed by hash, drawn on the post-remediation corpus and before any stratum curation decision. The term is deliberately distinct: see the Terminology entry disambiguating the three senses of "sealed" in this plan's orbit (proposal-reveal seal, sealed eval split, FIR-7's sealed K-budget). VLM-6 is the live consumer and is currently curating with no split frozen. **Blocking precondition, not yet done:** `docs/tasks/vlm/VLM-6-gpu-vlm-bakeoff-task-plan.md` contains no reference to FIR-11, the re-gate, or this split (verified on disk at rev 4); adding that blocking pointer is owned by the VLM-6 plan owner and must land before the split is treated as protecting VLM-6 — this plan cannot claim it done and does not.

**Two consumer-surface gaps this block opens and must therefore close.**

1. **`corpus-manifest-v3.json` is now load-bearing and appears in no Files-to-Change, Consumer Inventory, or Related Files row.** It supplies the strata this plan's pool sizing depends on and it carries two fields the plan's own Terminology does not define — `named_face_count` and `detected_face_count`, where the existing `face_count` is explicitly *not* "faces the detector found". Before Slice 2, state which is true: v3 loads through `load_legacy_manifest` and is **not** a v3-schema artifact, or it must validate under `SUPPORTED_MANIFEST_VERSION` 3 and `manifest.py` gains the two count fields. The retag instruction and the frozen-artifact row both currently point at the **superseded** 20260716 file; the retag target is correct there (it is the legacy file being retired) but v3 needs its own row.
2. **FIR-7 is a consumer of `golden150-draft-20260723.json` through the gate CLI, and is not in the inventory.** This plan freezes that manifest read-only, makes the v3 gate loader reject it by design, and asserts no `cli.py` gate command path reaches `load_legacy_manifest`. FIR-7's frozen baseline, identity split, every per-floor base value written into `fir-7-regate.json`, all three sealed K-budget touches and its descope thresholds read that corpus through `score-face --manifest` and `regate.py` — gate CLI paths. This plan's own rule ("any consumer not on this list that breaks is a plan defect") convicts the omission. **Add FIR-7's `regate.py`, `config_levers.py`, `benchmarks/gates/fir-7-regate.json` and `golden150-fir7-identity-split.json` to the Consumer Inventory, and state which plan's slice lands first.** Neither plan currently references the other, and both were authored the same day under `MAINT-fir-qa-decomposition-reflow-20260728`.

**Sampling-design constraint, now absorbed into the Contract above (see the amended PSU / m / DEFF rows).** Images here are drawn via containers (identity, shoot, occasion) while the power math treats each image as an independent SRS unit — so Slice 4's ρ estimation must name its PSU, its deff or ICC, and its *n*<sub>eff</sub> **[AUDIT-11]**. Two corpus facts constrain how: identity clusters **do not partition** the 646 images (14 belong to two clusters, 3 to three, 108 to none), so a subject-level bootstrap over identity is not a valid resampling scheme as it stands — construct non-overlapping PSUs (the occasion key already specified in this plan is the right instrument) or use a multilevel / sandwich estimator. Do not apply a cluster correction to the 108 unclustered images; that is a plan-local consequence of the non-partition, not an AUDIT-11 requirement.

Handoff: findings `FIRQA8-PR-02`, `FIRQA8-PR-06` under `MAINT-fir-qa-decomposition-reflow-20260728`.

## Measurement Contract

**Status: DRAFT-PENDING-REVIEW (rev 3).** Declared before any labeling or scoring work begins; a planning-review pass must lock it, and changes after lock require a new review pass. The gate in Context and Ownership ("reviewed and locked before any labeling or scoring work") is satisfied only by that lock, not by this draft.

**Scope split, stated once (GF-06):** the δ=10pp intersection-union gate and the Ship rule below belong to **Product B** — they are executable only on the occasion-structured successor corpus (Slice 6). **Product A does not instantiate the primary endpoint either:** no candidate leg runs anywhere in Slices 0–5 — every Slice 5 arm is a buffalo_l leg varying labels, pool, scoring, or toolchain, so the buffalo-vs-candidate paired comparison is wholly deferred to Product B. What Product A executes is the contract's *machinery* — subject-level rollup, the paired-test wiring, DEFF-handled intervals, the under-powered banner — exercised on within-buffalo_l arm pairs, plus the power ceiling and the labeling-regime measurement. **No Slice 5 arm delta may be reported as the contract's Δ̂**, and no Product A artifact may be presented as an IU-gate result.

| Field | Value |
| --- | --- |
| **Estimand** | Finite-pool **descriptive** comparison over the named gate corpus. Not a design-based inference to any image population. Per **[AUDIT-08]**, no design-based margin of error may be reported on this operator-picked convenience sample; intervals are labeled *conditional on this pool*. |
| **Analysis unit** | Subject (identity), not face. Per **[EVAL-17]**. |
| **PSU (primary sampling unit)** | **Occasion** — one independent capture event for one identity. Two frames of the same person from the same shoot are one PSU. **Amended 2026-07-28 (QA v8 re-gate); the amendment is part of this draft and, like every other row, locks only at the contract lock named in the Status line.** Occasion is *not* a partition of images either: on the 17 corpus-v3 images carrying two or three identities an image belongs to two or three occasions, and the 108 identity-free images belong to none. So (a) the analysis is over **occasions**, never over images — an image is a container, not a unit; (b) the 108 identity-free images are **outside** the identification estimand entirely and receive no cluster correction; (c) multi-identity images contribute one probe to each of their occasions, which is correct at the occasion level and only breaks if anyone re-aggregates to images. A subject-level bootstrap over *identity* remains invalid and is not the fallback. |
| **m (cluster size)** | Mean named probes per PSU. Measured, not assumed. In golden150 today: 160 named probes / 48 identities ≈ **3.3** (identity is an *upper-bound* proxy for occasion-m: an identity pools all of its occasions, so probes-per-identity ≥ probes-per-occasion, with equality exactly when an identity was shot on a single occasion; true occasion m is smaller or equal — this direction statement is the single canonical one, and Slice 4's fallback note must match it). **Amended 2026-07-28:** 3.3 is a golden150 figure — the corpus this plan exists to replace — and is **provisional only**. `m` is **re-measured on the post-Slice-2 corpus** once the occasion key exists, and the Slice-0 ceiling table is re-derived from the measured value. Do not inherit 3.3 past Slice 2, and do not substitute corpus-v3's 4.073 images-per-identity for it: that is images per *identity*, not named probes per *occasion*. |
| **DEFF** | `1 + (m − 1)·ρ`, ρ measured in Slice 4, PSU = occasion, unit = named probe. **This is the only quantity in this plan named `DEFF`** — corpus-v3's identity-membership concentration `C_identity` (M̃ = 12.925) is descriptive and must never be substituted here (see the superseding-input block). **Slice 4 must also report `n_eff` and name the estimator [AUDIT-11]**; a deff without a printed `n_eff` does not satisfy the contract. At m=3.3: ρ=0.7 → 2.6; ρ=0.9 → 3.1. *(Rev 1 quoted "n_eff 1.11 at n=100, ρ=0.9" as if it justified DEFF 1.2–3×. Those are inconsistent — n_eff 1.11 implies DEFF ≈ 90 by treating all 100 probes as one cluster. The n=100 line is deleted; DEFF derives from m, not from total n.)* |
| **Primary endpoint** | Paired per-subject identification correctness, buffalo_l vs candidate leg, on identical detected inputs. The primary scalar is the per-stratum difference in subject-level identification accuracy, `Δ = acc(candidate) − acc(buffalo_l)`, estimated from discordant subject pairs. |
| **H0 (per stratum)** | Non-inferiority null: `H0: Δ ≤ −δ` (the candidate is worse than buffalo_l by at least 10pp on paired subjects). **Named procedure:** the **Nam/Tango score test for paired non-inferiority** (shifted null on the discordant split — under H0 at the margin, the "candidate-loses" fraction of discordant pairs is `π₀ = (p_d − δ)/(2·p_d)`, e.g. 0.25 at p_d = 0.20, δ = 0.10 — with the nuisance p_d handled by the score/constrained-MLE construction, not plugged in), at **one-sided α = 0.025** (see the α row). Classical McNemar at `Bin(n_d, ½)` tests `Δ = 0` and is **not** this gate's test; it remains available for descriptive equality checks only. Rejecting H0 in **all k** gate strata (see the k row) is the IU pass condition (Product B only). Product A reports per-stratum arm deltas descriptively with no H0 decision, under the under-powered banner — and never as the contract's Δ̂ (no candidate leg exists in Product A). |
| **Statistic–interval pairing** | One frame governs each number (GF-07/PA-05): the *decision* statistic is the Nam/Tango NI score test above; its accompanying interval is **the CI on `Δ` from the subject-level paired analysis (multilevel or sandwich estimator per the DEFF-vs-aggregation row) — no probe-level DEFF multiplier is applied to it.** `deff_adjust` is a **sizing-time helper only** and must never touch an analysis interval; applying probe-level `1+(m−1)ρ` on top of the subject-level analysis would double-count clustering that aggregation already collapsed. Wilson half-width on a single arm's accuracy is **descriptive precision only** — it appears in stratum tables labeled *conditional on this pool* and never grounds a power or gate claim. The Slice 0 ceiling is stated in paired-subject/discordant-pair units (Connor/NI sizing), with Wilson shown alongside as the single-proportion illustration, not the argument. |
| **Secondary endpoints** | `false_split`, `false_merge`, non-mated reject rate at a **fixed score threshold pre-declared in the sizing note before scoring** **[EVAL-18]** (rank metrics cannot express "no one here"; the threshold is declared, not tuned on results), per-stratum FMR/FNMR **[CAL-01]**. |
| **δ (minimum effect worth detecting)** | 10pp absolute on the primary endpoint. Declared now, per **[EXP-12]** — not chosen after seeing the data. |
| **α** | **Resolved: the NI decision runs at one-sided α = 0.025**, the one-sided size implied by the declared two-sided 0.05 frame — "0.05 two-sided per test" and "one-sided within the frame" previously coexisted without resolution; 0.025 one-sided is the resolution and 0.05 one-sided is explicitly rejected. Per test, **not split**: the gate is intersection-union, every stratum must pass, so per-test α stays fixed and per-stratum *power* is raised instead. Bonferroni is the wrong correction here. Holm/BH applies only to the exploratory "which strata differ" question. |
| **k (strata in the IU gate)** | **Resolved by corpus, decided at lock.** For **Product A's descriptive tables**, k=7 — clean, profile, blur, low_res, occlusion_other, sunglasses, masked — because `similar_people` has **zero** members in every existing pool and the exclusion rule ("excluded until populated") applies. For **Product B**, whose Slice 6 corpus *deliberately populates* `similar_people`, the same rule makes the gate **k=8** — unless an explicit Product-B `similar_people` exclusion decision is recorded at contract lock, which would also delete Slice 6's lookalike-recruitment line so the corpus does not build a stratum the gate ignores. One of those two (k=8-with-populated-stratum, or k=7-with-recorded-exclusion) **must be chosen at lock; this draft defaults to k=8 for Product B** and every Product-B sizing constant is re-derived at the locked k (at k=8: per-test power `0.80^(1/8) ≈ 0.973`). *(Rev 1 used k=9; rev 3 locked k=7 while Slice 6 populated the 8th stratum — that contradiction is what this row now resolves.)* |
| **Per-test power** | `0.80^(1/k)` at the locked k — `0.969` at k=7 (Product A illustration), `≈0.973` at k=8 (Product B default). Normal-theory N inflation vs 80%: **1.86×**, carried **as a provisional wrong-family illustration only**: it is a continuous-endpoint normal-theory ratio, the exact factor under the discordant-pair sizing is ≈1.77–1.97 depending on formulation, and **no exact sizing row at the IU-inflated power exists in this document yet** — Slice 4 derives the exact rows at the locked k and power, records them in the sizing note, and `test_power_sizing.py` validates them. Declared caveat (GF-09): `0.80^(1/k)` assumes independent strata, but the strata share subjects, so this allocation is a conservative lower bound on joint power — it can oversize, never undersize. |
| **DEFF vs subject aggregation** | Stated so the same correlation is neither double- nor zero-counted (GF-08): DEFF applies at the **named-probe level for sizing**. The analysis then aggregates probes to occasions (template fusion) and occasions to subjects; the dependence remaining *after* occasion aggregation is between occasions of one identity, and Slice 4's estimator (multilevel or sandwich, named in the sizing note) carries it. No additional DEFF multiplier is applied on top of the subject-level analysis. |
| **Ship rule** | Candidate ships only if **every** one of the k gate strata (k row) clears δ=10pp non-inferiority at the locked per-test power **and** the bias-evidence clause below is satisfied. Locked at contract lock (see Status line — this draft does not lock it); not renegotiable after seeing results. This rule is Product B's gate; Product A cannot invoke it. **Second clause, rescoped honestly (rev 4): this task produces no upper bound on ground-truth circularity, under any labeler configuration.** What two independent labelers produce is the **bundled labeling-regime effect** `A2 − A1′` (procedure + coverage + box geometry, inseparable by the Slice 5 arm design) — a more honest identification of the bundle, not an upper bound on the circularity component, and no CI endpoint defined in this plan isolates that component. The single-labeler fallback yields only a **lower** bound, and "a lower bound is smaller than the margin" is vacuous. Two further gaps, named so lock cannot paper over them: the measurement is taken on golden150 under the legacy merge-only mechanism, while Product B is a fresh de-novo-labeled capture that **excludes that mechanism by construction** — no transport argument from the golden150 bundle to Product B's bias exists in this plan. Therefore the second clause is rescoped to: **the two-labeler bundled labeling-regime effect is measured, published with its CI and its bundle caveat, and an explicit bias-evidence decision — what quantity, measured where, gates Product B — is adjudicated and recorded at contract lock.** Under the single-labeler fallback even that input is a lower bound and the candidate does **not** ship on this evidence, regardless of the observed margin; recruiting the second labeler remains a ship precondition. |
| **Human-labeling error rate** | A measured input, not an assumption. Per **[HITL-09]**, a stage credited with catching model error carries its own measured rate or the gate does not credit it. Measured in Slice 3 via gold items **[HITL-03]**. |

## Constraints

- **Re-inference cannot remediate.** buffalo_l is deterministic on fixed pixels; re-running regenerates the same boxes and clusters. The contamination is in the labeling *procedure*, not the inference run. Any step proposing "re-process the corpus" as the fix is rejected by construction.
- **Re-labeling cannot buy power.** It changes procedure, not sample design. It mints no new occasions, no new hard-condition captures, no new multi-shot identities, and no lookalike pairs. See Slice 0.
- **Both corpora are private and unpublishable.** `PRIVATE_SOURCES` (`manifest.py:154`) covers `localwp` and `operator`; `Provenance.is_publishable` (`manifest.py:261`) fails closed on private source regardless of licence or explicit flag. golden150 is 137 `operator/mock_entity` + 7 `celeb/fixture` + 6 unprovenanced; corpus646 is 646 × `localwp/consented`. Remediation restores *auditability*, not publishability.
- **The two pools are not independent.** 64 shared sha256; 49 of golden150's 53 roster names present in corpus646; only 15 identities exclusive to the golden150-only half. Treating corpus646 as a fresh sample would double-count. corpus646 carries hand strata on **96 of 646 entries** under `corpus-manifest-v3.json` (profile 50 · blur 28 · low_res 26 · occlusion_other 19 · sunglasses 13 · masked 5 · similar_people 0) — the remaining 550 contribute to no stratum without new tagging, and the tagged 96 are still far under floor in every hard stratum. *(Rev 2 said "no `tags` field at all"; that was read from the superseded 20260716 manifest.)*
- **Greenfield policy applies.** No migration shims in the gate path. The one deliberate exception is a read-only legacy loader used *only* by the bias-audit arms A1′/A1″/A3 (which are **Slice 5's** arms; rev 3 said "Slice 3", but Slice 3 consumes legacy labels only through the audit-queue draw) — never by the gate CLI. See GF-10 resolution in Slice 2.
- **Buffalo licence wall.** buffalo_l stays a *judge under audit*, never a teacher for the gate labels (QA §14).

## Workflow Principles

- Ground truth for the gate is produced by a procedure with no access to the system under test's proposals at labeling time, and no reveal of those proposals until the corpus is sealed.
- A manifest declares what kind of ground truth it holds; a roster-only manifest is structurally barred from scoring detection.
- Sizing is declared before collection: pick δ, derive n, then decide how many images to label.
- Effective sample size, not raw face count, is the sizing unit.
- A confounded delta is decomposed or not reported.

## Terminology

- **Blind de-novo labeling**: an operator draws and names boxes without seeing machine detections, cluster assignments, prior names, or any derived hint for that image. Machine proposals are **not** revealed per-image at commit time — reveal is deferred until the whole corpus is sealed, because per-image reveal trains the labeler on buffalo's behaviour within the session.
- **Annotation mode**: a manifest-level declaration — `exhaustive` (every human face in the frame is boxed, named or `null`) vs `roster_only` (only roster members are boxed).
- **`face_count`**: the number of **human faces visible in the frame**, including non-roster strangers, background faces, and faces too small or occluded to identify. Not "faces the detector found", not "roster members present". Under `exhaustive`, `len(face_boxes) == face_count` by definition.
- **Occasion**: an independent capture event for one identity. Two frames from one burst are one occasion. The occasion key is `(identity_id, capture_session_id)`, where `capture_session_id` is assigned at labeling time by the operator and is required on every box in an `exhaustive` manifest.
- **Gold item**: an image with a pre-established, independently arbitrated label, injected into the labeling queue unannounced, used to measure per-labeler accuracy **[HITL-03]**.
- **Inconclusive**: a labeler decision distinct from both "named" and "stranger" — the face is present but the labeler cannot determine identity. Recorded as `decision: "inconclusive"`, excluded from the identification denominator, reported as a rate.
- **n_eff**: `N / DEFF` — the number of independent observations a correlated sample is worth.
- **Sealed (three senses — every use in this plan names its sense).** (1) **Proposal-reveal seal**: machine proposals are revealed only after the whole audit subsample is committed (Slice 3's blinding discipline). (2) **Sealed eval split**: the frozen, identity-disjoint, hash-committed held-out artifact `golden-v2-eval-split-<YYYYMMDD>.json` (QA v8 T-08; Slice 2 deliverable). (3) **Sealed K-budget** (FIR-7): a burn-after-use query budget external to this plan, mentioned only in the FIR-7 consumer rows. Conflating these is a defect; grep hits on "sealed" must be read against this entry.

## Current State Analysis

**Works today.** `make bakeoff-face` → `scripts.eval_harness.cli face-bakeoff` (`cli.py:855`) runs an offline detect→align→embed walk with no tenant writes; `--leg buffalo` selects the InsightFace fused baseline behind `ACX_EVAL_BENCH=1` + the `[bench]` extra. `make bakeoff-face-score` → `score-face` (`cli.py:875`) scores a run record offline and supports `--check-determinism`. Neither needs a GPU; `benchmarks/reports/cpu-full-corpus-baseline-*.html` is the CPU evidence. `load_manifest` (`manifest.py:423`) already enforces sha256 hex form, media_id/path uniqueness, roster membership, and on-disk digest match.

**Broken or drifting.**

| Defect | Anchor | Measured |
| --- | --- | --- |
| `provenance` optional | `manifest.py:365` | 6 golden150 entries have no provenance key |
| No annotation-coverage invariant | `manifest.py:386 _face_count_covers_labeled` checks only `face_count >= len(present_identities)` | v3 measures the full 646: **584 named** vs **1,763 detected**, positive excess **1,182** on 368 images *(the 115-face figure on the 64-image golden150 overlap is the superseded early evidence)* |
| No annotation-mode declaration | `GoldenManifest` (`manifest.py:396`) | roster-only manifest is indistinguishable from exhaustive |
| No label lineage | `GoldenEntry` (`manifest.py:365`) | cannot tell who labeled what, in which pass, with or without machine hints |
| Stratum floor far below power | `strata.py:78 MIN_STRATUM_POOL = 5` | no stratum resolves 10pp |
| Declared stratum with zero members | `SliceTag.SIMILAR_PEOPLE` (`manifest.py:149`) | 0 entries tagged in golden150 |
| Every probe has a mate | `face_metrics.py:256 face_identification_pr` | no non-mated / reject-non-enrolled measurement **[EVAL-18]** |
| Best-single-observation matching | `face_metrics.py:571 single_linkage_labels` | no template fusion across an occasion **[EMB-07]** |
| Occlusion measured only on synthetic twins | `synthetic_occlusion.py:724 filter_headline_probes` strips occluded faces from the headline set — **[MLDATA-09]**, the QC filter removes the regime under test *(rev 2 cited MLDATA-20 for this mechanism; wrong trigger)* | occlusion readiness argued from synthetic twins only — live exposure (no slice here instruments live occlusion scoring; MLDATA-20 is explicitly out of scope, see Context Loading) |
| Cluster centroid unweighted | `db/migrations/versions/001_identity_schema.py:1720 mv_identity_cluster_centroids` | `l2_normalize(AVG(l2_normalize(e)))` — **[EMB-02]** violation, out of scope here, tracked separately |

**Misleading assumptions to retire.** That corpus646 is a licence-clean alternative to golden150 (both private/unpublishable; `mock_entity` and `consented` are both fail-closed). That corpus646 is a larger, fresher pool (it is a superset-overlap of the same operator material, and only **partially** tagged — 96 of 646 entries carry non-empty hand strata; "untagged" in rev 2 was read from the superseded manifest and is false). That the QA report's false-split advantage is a clean measurement. **That re-labeling the existing pool yields a powered gate.**

## Target Outcome

**Product A (this task, Slices 0–5).**
A `benchmarks/manifests/golden-v2-<YYYYMMDD>.json` over the **audited** golden150 pixels — `annotation_mode: exhaustive`, provenance-required, label lineage on every box, produced under blinding (two-labeler configuration) or as an independent re-pass (single-labeler fallback — the artifact is renamed accordingly per Slice 3). A measured **bundled labeling-regime effect**, from a VoI-sized double-labeled stratified subsample — which lower-bounds ground-truth circularity but does not upper-bound or identify it (see the Ship rule row).

> **Scope of golden-v2, stated because the slices could not otherwise deliver it.** Blind labels are produced by Slice 3, and Slice 3 labels the **audit subsample** — not the pool. Meanwhile Slice 2 makes `LabelLineage` mandatory ("a box without `LabelLineage` fails validation"), so a hybrid manifest of blind-labeled boxes plus un-relabeled legacy boxes is **unloadable by construction**: it is neither `exhaustive`-under-blinding nor a valid v3 artifact. Rev 2 promised a whole-pool blind exhaustive golden-v2 and scheduled no slice that could produce one. Resolution, stated as a branch rather than a foregone conclusion (the convergence claim can only be *checked* once Slice 1 lands the pool and Slice 4 lands n — asserting it now would be a conclusion dressed as an assumption): after Slice 1's dispositions the surviving pool is **at most 140, down to 30 in the all-drop worst case** (re-derivation shown in Slice 1; the Slice 1 re-derive is a blocking gate). **If** Slice 4's derived n meets or exceeds the realized pool — guaranteed at the low end of the interval, false at the top (an n near 120 is below 140) — the audit is a census, the subsample and the pool converge, and one blind pass produces a genuinely pool-wide golden-v2 whose `entry_count` is asserted equal to the post-Slice-1 pool. **If instead Slice 4 derives an n strictly below the surviving pool, golden-v2 ships as `golden-v2-audit-<YYYYMMDD>.json` scoped to the labeled subset** and the un-audited remainder stays in the frozen legacy manifest, reachable only through `load_legacy_manifest`. Both branches are specified now; which one runs is decided by the recorded numbers, not by this paragraph. What never ships is a manifest that claims `exhaustive` over boxes no blind pass touched. Assembly of the shipping manifest is owned by Slice 3 (`assemble_golden_v2`, see the Files table and Slice 3 Changes).

A re-run buffalo_l baseline scored subject-level, published with the **6-arm decomposition** that separates *toolchain*, *pool composition*, *labeling-procedure* and *scoring-code* change, and carrying an explicit "**under-powered for δ=10pp; not a ship gate**" banner on every stratum table.

**Product B (Slice 6 spec, executed after).**
An occasion-structured successor corpus sized from measured ρ: the only path to the δ=10pp IU gate. Slice 6 delivers the spec and the capture budget, not the corpus.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`
- Canon (**unpinned — canon versions are mutable, rule IDs are idempotent; consult current canon at implementation time**), `~/Development/heuristics-canon/lexicons/` — the **canonical repo, not the `heuristics-canon-research` mirror** (rev 3 pointed at the mirror; a plan that mandates consulting current canon must point at the source) — each rule verified present before citation:
  - *Circularity / design*: EXP-12, EXP-22, OBS-09, MEAS-02
  - *Audit / sampling*: AUDIT-04, AUDIT-07, AUDIT-08, AUDIT-11
  - *Data*: MLDATA-08, MLDATA-09; PROV-05
  - **MLDATA-20 is explicitly out of scope** — no slice in this plan instruments live occlusion scoring (Slice 6's occluded capture is Product B spec, not an instrumented control); per the pruning rule below it is not cited as live work here, and re-enters only together with the slice that instruments it
  - *Eval / embeddings*: EVAL-07, EVAL-10, EVAL-16, EVAL-17, EVAL-18; EMB-02, EMB-07, EMB-10; CAL-01
  - *Human loop*: HITL-03, HITL-09
  - *Engineering / cost*: TEST-15; COST-04
  - **[EVAL-19] is explicitly retired from this plan's citation set** — see Problem Statement §1.
  - **Rev 3 pruning (GF-01):** every ID above has triggering work at a named point in this plan and was re-verified present in current canon. IDs cited in rev 2 with no instrumented trigger anywhere in the plan (EXP-03, EXP-19, EXP-20, AUDIT-05, MLDATA-18, MLDATA-21, MLDATA-22, CAL-09, FAIR-05, TEST-08, DIAG-03) are removed rather than left as ID-existence decoration; re-add any of them only together with the work that triggers it. Stale `file:line` pins are dropped — canon is mutable, rule IDs are the stable handle.
- Report: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` §14 (buffalo as judge, not teacher), §17 (curation), §18 (economics). **Intended to be the committed sole source of the old baseline numbers — but it is currently untracked**: `.gitignore:175` ignores `/benchmarks/` wholesale and git tracks zero `benchmarks/` paths, so the file exists only in the root checkout and is absent from this worktree. Until the Slice 0 tracked-path gate lands, "committed artifact" is a target state, not a fact; the old manifest is never re-loaded by the gate path either way.
- Code: `apps/prototype-description-service/scripts/eval_harness/{manifest,strata,face_metrics,face_bakeoff,synthetic_occlusion,corpus_inventory,draft_labels,cli}.py`
- Handoff: `MAINT-fir-training-feasibility-20260727` decision `claude_decision_golden150_successor_corpus_plan_20260727`; adjacent plan `docs/tasks/fir/FIR-9-workbench-curation-atlas-task-plan.md`

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Golden manifest schema | backend (eval harness) | `manifest.py` `GoldenManifest` / `GoldenEntry` | `manifest_version` 2 → 3; `provenance` required; add `annotation_mode`; add manifest-level coverage invariant; add label-lineage fields | no for the gate path; a read-only `load_legacy_manifest` is retained for bias-audit arms only | `pytest scripts/eval_harness/tests` + load of regenerated manifests |
| Face run-record / report | backend (eval harness) | `face_run_record.py`, `report.py` | subject-level rollup, DEFF-corrected conditional intervals, exact McNemar, non-mated rates, under-powered banner | no | `score-face --check-determinism` asserted in CI, not by hand |
| Detection scoring | backend (eval harness) | `face_metrics.py:151 detection_pr` | refuses `roster_only` manifests | no | negative test |
| Labeling surface | frontend (Workbench) | FIR-9 curation atlas | consume a blind queue; suppress every cluster/name/detection hint in gate mode; gold-item injection; inconclusive channel | **yes — FIR-9 owns the UI and this is a hard dependency for Slice 3** | operator walkthrough + schema assertion on the queue payload |

### Consumer inventory (blast radius of the version bump)

Enumerated before the bump lands; any consumer not on this list that breaks is a plan defect.

- [ ] `scripts/eval_harness/cli.py` — `face-bakeoff` (`:855`), `score-face` (`:875`)
- [ ] `scripts/eval_harness/face_bakeoff.py` — manifest walk
- [ ] `scripts/eval_harness/face_metrics.py` — `detection_pr`, `identification_pr`, `face_identification_pr`, `demographic_rollup`
- [ ] `scripts/eval_harness/strata.py` — stratum assembly
- [ ] `scripts/eval_harness/synthetic_occlusion.py` — `filter_headline_probes` (`:724`)
- [ ] `scripts/eval_harness/draft_labels.py` — `generate_draft_manifest` (`:30`) emits v2 today
- [ ] Description-eval consumers of `corpus646-interleave-manifest-20260716.json` — **must be enumerated by grep before Slice 2 lands**; the retag to `roster_only` must not break description scoring
- [ ] `Makefile:611 bakeoff-face`, `Makefile:614 bakeoff-face-score`
- [ ] `scene/tests/seed/golden.json` (the `--manifest` default) — regenerated or pinned to the legacy loader
- [ ] `scripts/eval_harness/bakeoff10-manifest-20260716.json` and `scripts/eval_harness/refetch6-manifest-20260716.json` — v2 manifests shipped inside the harness itself (PA-06); regenerated as v3 or pinned to `load_legacy_manifest` before the bump lands
- [ ] `scripts/eval_harness/tests/fixtures/` — every fixture manifest regenerated to v3 or explicitly exercised through the legacy loader in its test
- [ ] `scripts/eval_harness/corpus646-interleave-manifest-20260716.json` — the **tracked harness copy** of the corpus646 manifest (verified on disk; distinct from the untracked `benchmarks/manifests/` copy). Retagged/dispositioned in lockstep with its `benchmarks/` twin, or the two silently diverge
- [ ] **VLM-6** (`docs/tasks/vlm/VLM-6-gpu-vlm-bakeoff-task-plan.md`) — live consumer of the corpus this plan re-cuts, curating with no split frozen; consumes the sealed eval split once drawn and may see it re-drawn once (Slice 2). Its reciprocal blocking pointer back to FIR-11 is **not yet landed** — see the precondition in the Problem Statement and the Slice 2 checklist
- [ ] `benchmarks/manifests/corpus-manifest-v3.json` — **load-bearing for this plan's pool sizing.** Before Slice 2, record which is true: it loads through `load_legacy_manifest` and is *not* a v3-schema artifact, or it must validate under `SUPPORTED_MANIFEST_VERSION` 3 and `manifest.py` gains `named_face_count` / `detected_face_count`. Both fields are absent from Terminology today and neither is `face_count`.
- [ ] **FIR-7 gate surfaces** — `regate.py`, `config_levers.py`, `benchmarks/gates/fir-7-regate.json`, `golden150-fir7-identity-split.json`. *(Rev 3 cited `docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md`; verified at rev 4: **no such file exists anywhere in this checkout** — the FIR-7 consumer facts below are carried on their own evidence, and every "in its plan" claim is a precondition, not a fact.)* FIR-7 reads `golden150-draft-20260723.json` through `score-face --manifest` and `regate.py`, i.e. **gate CLI paths**, for its frozen baseline, its identity split, every per-floor base value, all three sealed K-budget touches, and its descope thresholds. This plan freezes that manifest read-only and makes the v3 loader reject it by design, so the bump breaks FIR-7 unless the ordering below holds.

**Which plan's slice lands first (required by the rule above).** **FIR-11 Slices 1–2 land before FIR-7 Slice 0a seals anything.** The reverse order would have FIR-7 freeze a baseline, an identity split and seven per-floor base values on labels this plan has already established are outcome-dependent — and FIR-7's sealed K-budget (sense 3 of "sealed", Terminology) is burn-after-use, so a baseline sealed on contaminated labels cannot be re-sealed. Two consequences bind FIR-7. **Blocking precondition, not yet done:** they are *not* mirrored anywhere — the FIR-7 plan file does not exist in this checkout — so this ordering is currently a one-sided constraint only this plan asserts. Owner: the FIR-7 plan author must carry both consequences verbatim when that plan is (re)created, and FIR-7 Slice 0a must not seal anything before that reciprocal edit exists; this plan cannot land the edit itself (one writer per plan) and does not claim it landed:

1. **No golden150-derived figure may carry a CONFIRMATORY evidence tier** while Problem Statement §1 stands. DIRECTIONAL is the ceiling, and **nothing in FIR-11 lifts it**: this task produces no upper bound on circularity under any labeler configuration (the two-labeler output is the bundled labeling-regime effect; the single-labeler output is a lower bound — see the Ship rule row). Lifting the ceiling would require an estimator that yields a real upper bound plus a transport argument, neither of which this plan delivers; within FIR-11's horizon DIRECTIONAL is a terminus, not a stage.
2. **FIR-7's Slice 0a baseline is re-drawn on the post-Slice-2 manifest**, not on `golden150-draft-20260723.json`. FIR-7 is already blocked on CVUP-1 for an unrelated reason (OpenCV 4.x/5.x embedding incomparability), so this ordering costs it no additional wall-clock.

If FIR-7 needs any pre-remediation number for internal comparison, it reads it from the committed QA report, exactly as arm A1 does — never by re-loading the manifest through a gate command.

## Proposed Solution

Sequence, with the ordering constraint made explicit:

1. **Slice 0** publishes the power ceiling. It is a **hard gate**: no bulk labeling starts until the ceiling arithmetic is written down and acknowledged, because the rev-1 plan's 6–12 h labeling pass would have bought a corpus that still cannot gate.
2. **Slices 1–2** are **contract hygiene**. They make the measured defects unrepresentable. They buy **zero** statistical power and must not be described as if they do.
3. **Slice 4 runs before Slice 3's bulk work**, inverting rev 1. ρ and σ come from the *existing* embedding store, need no new labels, and determine whether any labeling is worth doing at what size.
4. **Slice 3** is a VoI-sized double-labeled **bias audit**, not a full-pool re-label. Its product is a bound on circularity, which is what Product A actually needs.
5. **Slice 5** re-baselines and publishes the 6-arm decomposition with the under-powered banner.
6. **Slice 6** specifies Product B.

## Files and Surfaces to Change

Functions named. **(new)** marks a symbol that does not exist yet — verified against the current files, so no invented API is implied.

| Surface | File | Symbols |
| --- | --- | --- |
| backend | `scripts/eval_harness/manifest.py` | `GoldenEntry.provenance` (drop `\| None = None`, `:365`); `AnnotationMode` **(new)** StrEnum; `GoldenManifest.annotation_mode` **(new)**; `GoldenManifest._boxes_cover_face_count` **(new, manifest-level)**; `LabelLineage` **(new)** model — fields incl. `capture_session_id`, `label_source`, `confidence`, per Slice 2; `warn_scrape_signature` **(new)** loader warning implementing the full signature family (owner: Slice 1); `SUPPORTED_MANIFEST_VERSION` 2→3 (`:34`); retire `_face_count_covers_labeled` (`:386`); `load_legacy_manifest` **(new)** read-only v2 reader for the Slice 5 audit arms |
| backend | `scripts/eval_harness/strata.py` | delete `MIN_STRATUM_POOL = 5` (`:78`); `derive_stratum_floor(delta, p_d, deff, k)` **(new)** (owner: Slice 4); `draw_eval_split` **(new)** sealed-eval-split drawer (owner: Slice 2). Wilson half-widths **reuse the existing `report.py:912 wilson_half_width(p, n, *, z)`** — rev 3 marked a `strata.py` `wilson_half_width(k, n)` **(new)**, but that helper already exists with a proportion-first signature; shipping a same-named count-first twin invites silent misuse, so no new symbol is added |
| backend | `scripts/eval_harness/face_metrics.py` | `subject_level_rollup` **(new)**; `mcnemar_exact` **(new)** — implements **both** the descriptive classical McNemar and the Nam/Tango shifted-null NI score test (the Contract's H0 row is the NI mode; classical mode never grounds a gate decision); `deff_adjust` **(new)** — **sizing-time only**, must refuse to be applied to analysis intervals (Contract pairing row); `nonmated_reject_rate` **(new, [EVAL-18])**; `fuse_occasion_template` **(new)** — fusion contract bound here (GF-15): quality-gate then aggregate **all retained** observations of an occasion [EMB-07], robust aggregation so one identity-void frame cannot move the template [EMB-02], and **equal weight per occasion** when pooling occasions into a subject template so capture rate cannot stand in for evidence [EMB-10]; `subject_level_rollup` derives its subject key as the manifest roster `identity_id` on each face row (PA-07); guard `detection_pr` (`:151`) against `roster_only`. Owner for all of the above: **Slice 5 Changes**, except `nonmated_reject_rate` threshold pre-declaration (Slice 4 sizing note) |
| backend | `scripts/eval_harness/occasion_key.py` **(new module)** | `derive_provisional_occasion_key` **(new)** — EXIF capture-timestamp bucketing + source-directory clustering over existing images, emitting the provisional-key artifact; `occasion_rho_report` **(new)** — within-occasion ρ / m / n_eff report over a given key. Owner: Slice 4 (provisional pass) and Slice 4's post-Slice-3 re-measurement (final `capture_session_id` key) |
| backend | `scripts/eval_harness/draft_labels.py` | `export_blind_queue` **(new)**; `join_agreement_report` **(new)**; `inject_gold_items` **(new, [HITL-03])**; `assemble_golden_v2` **(new)** — builds `golden-v2-<YYYYMMDD>.json` from arbitrated audit labels (owner: Slice 3). Existing file has only `normalize_rel_path` (`:21`) and `generate_draft_manifest` (`:30`) — neither can do this today |
| tooling | `scripts/eval_harness/cli.py` | `export-blind-queue` **(new subcommand)** (owner: Slice 3); `bias-audit` **(new subcommand)** (owner: Slice 5 — runs the arm table and delta assertions); `draw-eval-split` **(new subcommand)** (owner: Slice 2) |
| tests | `scripts/eval_harness/tests/test_manifest_invariants.py` **(new)** | provenance-required, annotation-mode, coverage, lineage — each with a paired failing case **[TEST-15]** |
| tests | `scripts/eval_harness/tests/test_blind_queue.py` **(new)** | queue payload carries no detection/cluster/name field; gold items indistinguishable from real items |
| tests | `scripts/eval_harness/tests/test_power_sizing.py` **(new)** | `derive_stratum_floor` and `wilson_half_width` against hand-computed values |
| tests | `scripts/eval_harness/tests/test_bias_audit.py` **(new)** | 6-arm decomposition arithmetic; the five deltas cannot be silently merged, and each is asserted to differ from its comparator in exactly one factor |
| docs | `benchmarks/plans/fir-11-sizing-note.md` **(new)** | measured ρ, σ, m, declared δ, derived per-stratum n, ceiling arithmetic |
| manifests | `benchmarks/manifests/golden-v2-<YYYYMMDD>.json` **(new)** | the re-labeled gate manifest |
| manifests | `benchmarks/manifests/corpus-manifest-v3.json` | schema disposition recorded before Slice 2: legacy-loader input, or v3-schema with `GoldenEntry.named_face_count` / `detected_face_count` **(new)** added to `manifest.py` and defined in Terminology |
| manifests | `benchmarks/manifests/golden-v2-eval-split-<YYYYMMDD>.json` **(new)** | the **sealed eval split** (QA v8 T-08), committed by hash |

> **Every `benchmarks/…` deliverable above is gated on the Slice 0 tracked-path precondition.** `.gitignore:175` ignores `/benchmarks/` wholesale and git tracks zero `benchmarks/` paths today, so as written none of these files can be committed, frozen by hash, or read from this worktree. No "committed"/"frozen" claim in this plan is executable until that gate lands (see Slice 0).

## Related Files

| File | Note |
| --- | --- |
| `benchmarks/manifests/golden150-draft-20260723.json` | **frozen read-only** at Slice 2. Never loaded by the gate CLI again. Old numbers come from the committed QA report; audit arms use `load_legacy_manifest`. |
| `benchmarks/manifests/corpus646-interleave-manifest-20260716.json` | description-eval fields stay valid; FR fields superseded; retagged `roster_only` |
| `docs/tasks/fir/FIR-9-workbench-curation-atlas-task-plan.md` | owns the curation UI; blind mode is a hard dependency for Slice 3 |
| `benchmarks/manifests/corpus-manifest-v3.json` | **superseding input**, 2026-07-28. Sole source of this plan's population, strata and probe counts. Carries `named_face_count` / `detected_face_count`, which `manifest.py` does not model. Schema disposition decided before Slice 2 — see Consumer Inventory. **Freeze it by hash as a Slice 1 precondition.** It is "sole source" for every figure in Problem Statement §3, the Measurement Contract's `m`, and the Slice 0 ceiling — yet it is produced by an unsequenced manifest-rebuild umbrella outside this plan's slices and is not pinned anywhere. An unpinned sole source means a rebuild silently re-derives the population under a plan already reviewed against the old one. Record the sha256 in the sizing note next to each figure it supplies; a hash change forces a re-derivation pass, not a merge. |
| FIR-7 task plan (**file does not exist in this checkout** — rev 3's `docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md` path is dangling) | downstream gate consumer of `golden150-draft-20260723.json`. Ordering and evidence-tier ceiling stated in the Consumer Inventory; the reciprocal mirror edit is a blocking precondition owned by the FIR-7 plan author, not a done fact. |
| `docs/tasks/vlm/VLM-6-gpu-vlm-bakeoff-task-plan.md` | live consumer, curating with no split frozen; carries **no** FIR-11/re-gate pointer yet — reciprocal edit is a blocking precondition (Slice 2). |

## Verification Strategy

- Deterministic tests: `cd apps/prototype-description-service && uv run --extra dev pytest scripts/eval_harness/tests -q`. Every new invariant gets a paired positive/negative test — **[TEST-15]** discrimination guard: prove the green can go red.
- Contract/fixture verification:
  - `uv run python -m scripts.eval_harness.cli score-face --manifest <golden-v2> --run-record <rec> --check-determinism`, **asserted in CI as a non-zero-exit gate**, not read by eye.
  - Loading `golden150-draft-20260723.json` under the v3 gate loader must fail with a named error listing all 6 paths; loading it under `load_legacy_manifest` must succeed. Both asserted.
- Runtime-parity: `make bakeoff-face EVAL_ARGS="--manifest <golden-v2> --leg buffalo"` on CPU with `ACX_EVAL_BENCH=1`; full gate via `make check-remote` at the merge SHA.
- Manual: 10 queue items are labeled to confirm no cluster, name, box, or count hint is visible, gold items are indistinguishable, and the inconclusive channel is reachable. **The walkthrough is performed by the second labeler (or, single-labeler case, its items are excluded from the audit sample)** — running the original adjudicator through a rehearsal on live audit items would institutionalise the contamination the blind protocol exists to avoid (GF-02).

---

## Slice Delivery

### Slice 0: Publish the power ceiling (hard gate — blocks all bulk labeling)

**Goal**: Nobody spends labeling hours on a corpus that provably cannot gate.

**Unit discipline first (rev 4).** Connor's 157 is a count of **independent paired subjects per stratum** — at p_d = 0.20 that is ≈31 expected discordant pairs, the same quantity the Slice 4 sizing table's McNemar row lists as 30 at p₁ = 0.75. Rev 3 relabeled it "discordant-informative probes" and multiplied through probe-level factors, sizing a probe-level test the Contract forbids. The chain below keeps the units explicit, and its multiplier constants are **provisional wrong-family illustrations** (the 1.86× is normal-theory continuous-endpoint glue; the exact factor under the discordant-pair sizing is ≈1.77–1.97 and is derived in Slice 4). **What this slice's hard gate rests on is the order-of-magnitude conclusion — the existing pool is one to two orders of magnitude short under every reading of the chain — not on any exact constant.** Slice 4 replaces the constants; no reading of them rescues the pool.

The provisional arithmetic, using the Contract's declared values and DEFF at ρ=0.9 (recomputed in Slice 4 once ρ is measured):

| Step | Value |
| --- | --- |
| Connor requirement, δ=10pp at p_d=0.20 | **157 independent paired subjects per stratum** (≈31 expected discordant pairs) |
| IU inflation, joint 80% → per-test `0.80^(1/k)` | × 1.86 (provisional, wrong-family — exact factor from Slice 4; at Product B's default k=8 it is marginally larger) → **~292 paired subjects per stratum** |
| Probe conversion for sizing only: DEFF at m=3.3, ρ=0.9 <span>(occasion-level, the Contract's `DEFF` — **not** `C_identity`)</span> | × 3.1 → **~905 raw named probes per stratum** as a supply-side illustration. This conversion is where subject demand meets probe supply; it is sizing-only and moves when `m` is re-measured after Slice 2 |
| × 7 strata (Product A illustration; Product B re-derives at locked k) | **~6,300 raw named probes** |
| Cross-check against Product B's own spec | Slice 6 targets 60–80 identities — **tens of subjects per stratum**, not ~292. Either the capture spec grows or the sizing constants shrink at Slice 4's re-derivation; the two currently cannot be reconciled and the sizing note must reconcile them before capture spend |
| golden150 has today (post fail-closed drop of unprovenanced + celeb/fixture) | **160** raw named probes |
| …after adjudicating the signature family (worst case, all 110 adjudicable entries dropped; census re-derived at Slice 1) | **30** — see Slice 1's re-derivation. *(Rev 3's 37 mixed frames that do not compose; rev 2's 123 came from the undercounted 36-entry scope.)* |
| golden150 ∪ corpus646, optimistic, before dedup of shared identities | **732** *images* (`150 + 646 − 64` shared sha256; rev 2 said "~700"). In this table's own unit — **raw named probes** — corpus646 contributes **111** from its 96 hand-tagged images (max hard stratum: profile 50; sunglasses 13, masked 5) and **473** from the 550 untagged, which land in no stratum without new tagging. **584 named probes total, not 646** |

Shortfall, all in probe units per this table's own rule: **~11× on the merged pool (6,300 / 584 named probes; rev 3's "~9×" divided by the forbidden image count 732), ~39× on golden150 as-is (6,300 / 160), up to ~210× after signature-family adjudication in the all-drop worst case (6,300 / 30).** Re-labeling changes none of these numbers — it mints no new occasions, no new hard-condition captures, no new multi-shot identities, and no `similar_people` pairs (that stratum has zero members and no amount of re-boxing invents lookalikes).

Changes:

- **BLOCKING precondition, not yet done: carve a tracked path for `benchmarks/` deliverables.** `.gitignore:175` ignores `/benchmarks/` wholesale; git tracks zero `benchmarks/` paths; the QA report, `corpus-manifest-v3.json`, and `golden150-draft-20260723.json` exist only untracked in the root checkout and are **absent from this worktree**. Either add negated `.gitignore` rules for the deliverable subtrees (`benchmarks/plans/`, `benchmarks/manifests/`, `benchmarks/reports/` deliverables) or relocate the deliverables to a tracked root (e.g. `docs/benchmarks/`), then commit the three existing source artifacts so their hashes exist in git. Owner: FIR-11 Slice 0 implementer. **Until this lands, every freeze/hash/"committed artifact" claim in this plan is unexecutable, and no later slice may start.** This is a `.gitignore` change executed in Slice 0 — deliberately *not* claimed done in this planning revision.
- Write `benchmarks/plans/fir-11-sizing-note.md` (under the carved path) with the table above, marked provisional pending Slice 4's measured ρ and exact inflation factor.
- Record a handoff decision stating that Slices 1–5 deliver a **bias-bounded, under-powered** measurement and **do not** constitute a ship gate.

Proof:

- `git ls-files` shows the carved `benchmarks/` deliverable paths (or the relocated root) tracked, with the QA report, v3 manifest, and golden150 draft committed.
- The sizing note exists and is referenced from the Slice 5 report's banner.
- The handoff decision is recorded before any Slice 3 labeling work is dispatched.

### Slice 1: Provenance becomes required and fail-closed *(contract hygiene — buys no power)*

**Goal**: An entry without auditable provenance cannot enter a manifest.

Changes:

- `GoldenEntry.provenance: Provenance` — drop `| None = None` at `manifest.py:365`.
- `load_manifest` raises `ManifestError` naming every offending path.
- Remediate the 6 unprovenanced golden150 entries. All 6 carry `present_identities: []` and **0 named probes** (5 have no boxes at all; `IMG_0249-rotated.jpg` has 9 unnamed detector boxes and `recognition_enabled: false`), so the fail-closed drop costs nothing in identification power. Disposition splits on filename evidence, not one blanket rule:

  | media_id | path (`2026/07/…`) | Disposition | Basis |
  | --- | --- | --- | --- |
  | 375 | `alixiaxo__3747817309907040649.jpg` | **drop** | Instagram handle + CDN filename; consent not attestable |
  | 438 | `barbara___elena_233787312_1809183585932731_2698952567892095846_n.jpg` | **drop** | same |
  | 484 | `slutcoree_269675263_586898972411337_4485327336255690007_n.jpg` | **drop** | same |
  | 603 | `IMG_0249-rotated.jpg` | `operator/mock_entity` | camera-roll capture; tags `profile`, `low_res` |
  | 633 | `IMG_0005-scaled.jpg` | `operator/mock_entity` | camera-roll capture; tag `blur` |
  | 648 | `IMG_1089.png` | `operator/mock_entity` | camera-roll capture; carries operator-confirmed `reference_facts` |

  Assigning `operator/mock_entity` to the three scraped entries would be a **false attestation**; `localwp/consented` would be worse. Drop is the only honest fail-closed action for them.
- **The drop is FR-gate-scoped, not global.** All 6 carry `context_pack` + `base_caption`, and 648 carries an operator-verified caption trap. They retain description-eval value and must not be deleted from the description corpus.
- **Mis-attested provenance is the larger defect (measured), and the two-regex figure understates it ~3× (PR-35).** The narrow Instagram-CDN signature (`handle_<9+digits>_<9+digits>_<9+digits>_n.jpg`, `handle__<15+digits>.jpg`) returns 33 hits among the 144 provenanced entries, all tagged `operator/mock_entity` — 36 of 150 entries with the 3 scraped unprovenanced ones. But the **full social-CDN signature family** (census recorded in finding FIR-11-PR-35; stem-matched, camera-roll prefixes `IMG|DSC|PXL|Screen[- ]?Shot` excluded first: (A) `\d{6,}_\d{5,}[^/]*_(n|o)(-\d+)?$`, (B) `(^|[_-])\d{15,}$`, (C) `^highlights[_-]\d{10,}`, (D) `^vsco[0-9a-f]{10,}`, (E) `^[A-Za-z0-9_-]{15}$` bare IG shortcodes) matches **113 of 150 entries (75%), 130 of 167 named probes (78%), 44 of 53 identities — 31 of which exist *only* on CDN-shaped entries**; 110 of the 113 are tagged `operator/mock_entity`, 3 are unprovenanced. The manifest is not present in this checkout, so these census figures are adopted from the PR-35 finding and **re-derived at Slice 1 against the frozen manifest hash before adjudication begins** — the census method above is the specification. The sampling-frame disclosure in the Slice 5 report is stated against 113/150, not 36/150. Two defects compound: `source=operator` is a false attestation for material the operator did not capture, and `license=mock_entity` is a **category error** — `mock_entity` denotes a fabricated identity, while these are real people's posts, so the tag asserts the opposite of the truth. A missing key fails closed; a wrong key passes. Per **[PROV-05]**, mis-attestation is more dangerous than absence. *(Rev 3 co-cited AUDIT-11 here; that rule governs cluster design effects / PSU / n_eff and carries no attestation duty — decorative co-citation pruned per this plan's own GF-01 standard.)*
- **Adjudicate all 113 signature-family entries before dropping anything.** Operator reviews each individually (own repost vs third-party), re-tags survivors with a truthful `source`/`license` pair, drops the rest. `mock_entity` is never a valid tag for a real third-party subject. *(Rev 2 scoped this adjudication to 36 entries — the two-regex subset; that scope was ~3× too small.)*
- **Consequence: the drop is no longer free, and the worst case is severe. One coherent frame, arithmetic shown (rev 4 — the prior 37/137 figures mixed frames that do not compose):**

  | Step | Entries | Named probes | Identities |
  | --- | --- | --- | --- |
  | golden150 full | 150 | 167 | 53 |
  | − 7 `celeb/fixture` (dropped per the celeb bullet; not in the signature family) | 143 | 160 | 48 |
  | − 3 scraped unprovenanced (the 3 `IMG_*` rows are **kept** as `operator/mock_entity` per the disposition table; the scraped 3 carry 0 named probes) | **140** | 160 | 48 |
  | − 0…110 adjudicated signature-family drops (113 census entries minus the 3 scraped already dropped above; their probes are the census's 130, all on CDN-shaped entries; 31 identities exist only there) | **30–140** | **30–160** | **17–48** |

  All-drop worst case: **30 entries / 30 named probes / 17 identities** (census strata at the worst case re-derived alongside). The rev-2 worst case (104/123/44) and rev-3's 37/37/22 and "137 post-celeb-drop" are all retired — 137 double-dropped the kept unprovenanced rows or retained celebs the same frame had removed, and no path from any of them reproduces on the table above. The Slice 0 ceiling shortfall on golden150 alone worsens from ~39× to **~210×** in the all-drop case (~6,300 required vs 30 surviving probes). Adjudication will likely keep genuine own-repost entries, so the realized pool lands in **30–140** — Slice 0's table is re-derived from post-adjudication counts, never assumed.
- **BLOCKING gate (rev 4): Slices 2, 4, 3, 5, 6 may not start until the Slice 1 re-derive is committed.** The re-derived census and pool counts (against the frozen manifest hash) are committed to the sizing note, and **any divergence from the 30–140 planning interval above is dispositioned in a plan changelog entry** (what number, why the interval missed it, which downstream figures move) before any later slice begins. A re-derive that silently disagrees with the planning interval and proceeds anyway is the exact failure the panel flagged.
- Add a loader-level filename-heuristic warning — `manifest.py` `warn_scrape_signature` **(new)**, owner this slice — so the pattern cannot silently re-enter; it **implements the full signature family above, not the two-regex subset**, or the pattern re-enters through the bare-shortcode form (PR-35). Carry the sampling-frame disclosure in the Slice 5 report per **[AUDIT-08]** (conditional-on-pool frame — the pool here is named by construction, which is AUDIT-08's case; rev 3 hung this on AUDIT-07 against that rule's own "unnamed draw list" trigger and its partial-fit disclaimer in Problem Statement §2).
- Disposition the 7 `celeb/fixture` entries explicitly. They carry 7 named probes across 5 identities (Anne Hathaway, Ariana Grande, Arnold Schwarzenegger, Audrey Hepburn, Bob Dylan) appearing **nowhere else** in the corpus, each noted `identity from filename, confirmed present; upstream license unverified`. Recommendation: **drop** — filename-derived identity is not attested labeling, and 5 singleton identities add ~0 power. Post-celeb-drop (before the unprovenanced and signature-family dispositions compose — see the coherent-frame table above): 143 entries / 160 named probes / 48 identities; strata become profile 49, low_res 25, blur 25, occlusion_other 17, sunglasses 13, masked 5.

Proof:

- Negative test: a fixture entry with no `provenance` key raises `ManifestError`.
- Loading `golden150-draft-20260723.json` unmodified under the v3 loader fails, naming all 6 paths.

### Slice 2: Annotation mode, coverage invariant, label lineage *(contract hygiene — buys no power)*

**Goal**: A roster-only manifest can never score detection; every label states its own provenance.

Changes:

- Add `AnnotationMode` StrEnum (`exhaustive` | `roster_only`) as a **required** `GoldenManifest` field; bump `SUPPORTED_MANIFEST_VERSION` to 3.
- Move the coverage check **to `GoldenManifest`** (not `GoldenEntry`) since the mode is manifest-level: `len(face_boxes) == face_count` under `exhaustive`, `len(face_boxes) <= face_count` under `roster_only`. Retire `_face_count_covers_labeled` (`manifest.py:386`) — the new manifest-level check **replaces** it outright, it does not compose with it. Every coverage/mode/lineage failure raises `ManifestError` carrying a named invariant, the entry index, and the entry path (GF-21), so a junior implementer has an error taxonomy rather than a boolean.
- Adopt the `face_count` definition from Terminology and assert it in the loader docstring; the old ambiguity is what let corpus646 pass with 74 boxes on frames holding 189 faces. **`face_count` is recorded by the operator as a separate count-first step before any box is drawn, and is never derived from `len(face_boxes)`** — a derived count makes the coverage invariant unfalsifiable (GF-11). The invariant then compares two independently produced numbers. Declared limitation (GF-12): equality proves the operator's count matches the operator's own boxes, i.e. internal consistency; exhaustiveness *in the world* is checked only by Slice 3's independent exhaustiveness audit [AUDIT-04], never by this invariant.
- Add `LabelLineage` per box: `labeler_id`, `batch_id` (labeling-session identifier, so a contaminated or rushed session can be filtered and disagreement partitioned by batch — GF-13), `capture_session_id` (**the writable surface for the occasion key** — operator-assigned at labeling time, required on every box of an `exhaustive` manifest per Terminology; this is the field Slice 4's final ρ/m re-measurement GROUPs BY, and without it the Terminology requirement had no schema home), `pass_index`, `labeled_at`, `tool_version`, `saw_machine_proposals: bool`, `label_source: operator_blind|operator_repass|arbitration|gold_reference|legacy_import` (GF-13's source channel — `saw_machine_proposals` is a flag, not a source), `decision: named|stranger|inconclusive`, `confidence: high|medium|low` (GF-13's graded-confidence channel — `inconclusive` is a decision, not a confidence), `arbitration_of: list[label_id] | None`. Per **[PROV-05]**, a label without lineage cannot be audited. *(Rev 3 co-cited AUDIT-11 here; pruned — PROV-05 alone carries the auditability duty.)*
- `detection_pr` (`face_metrics.py:151`) raises against a `roster_only` manifest rather than silently reporting inflated false positives.
- Retag `corpus646-interleave-manifest-20260716.json` as `roster_only`, **after** grepping and fixing the description-eval consumers listed in the Consumer Inventory.
- **Draw and freeze the sealed eval split (QA v8 T-08).** `strata.py` `draw_eval_split` **(new)** behind the `draw-eval-split` CLI subcommand **(new)** — owner this slice — emits `benchmarks/manifests/golden-v2-eval-split-<YYYYMMDD>.json` (under the Slice 0 tracked-path carve-out): an identity-disjoint held-out split over the post-remediation corpus, committed by hash, drawn **before any stratum curation or selection decision runs** [EVAL-07] [MLDATA-09] [EVAL-10].
- **The split's identity-disjointness is provisional, and the artifact says so.** Drawing it here means drawing it on the *pre-audit* identity partition — the buffalo-derived merge-only partition this plan exists because it distrusts. If Slice 3's blind pass splits a merged identity or merges two, the disjointness guarantee is void: the same person can land on both sides under two ids. Timing is nonetheless forced — VLM-6 is curating live at `:10018` with no split frozen, and drawing after Slice 3 leaves it unprotected for the whole audit. So: draw now, and (a) stamp the artifact `partition_provenance: "pre-audit, buffalo-derived merge-only"` with `disjointness: provisional`; (b) make **re-validation against the Slice 3 arbitration output a Slice 5 precondition** — any identity whose membership changed forces a re-draw and voids every selection made against the old split; (c) VLM-6 consumes it knowing it may be re-drawn once. A provisional split that is labeled provisional is usable; one that is silently trusted is the circularity defect again, one level up. **"Sealed eval split" is sense 2 of the three-sense Terminology entry** — distinct from the proposal-reveal seal (sense 1) and FIR-7's sealed K-budget (sense 3); the senses must not be conflated. VLM-6 is the live downstream consumer and is currently curating with no split frozen. **Its plan carries no pointer back here (verified absent at rev 4)** — landing that reciprocal blocking pointer in `docs/tasks/vlm/VLM-6-gpu-vlm-bakeoff-task-plan.md` is a precondition owned by the VLM-6 plan owner, tracked in this slice's checklist, and until it lands the split protects VLM-6 only by convention, not by contract.
- **Resolve the version-bump contradiction (GF-10):** golden150 is frozen read-only. The v3 gate loader rejects it by design. A separate `load_legacy_manifest` reads v2 for the **Slice 5 bias-audit arms (A1′/A1″/A3)** and Slice 3's audit-queue draw only *(rev 3 said "Slice 3 … arms"; the arms are Slice 5's)*; it is not reachable from `cli.py` gate commands, and a test asserts that.

Proof:

- Negative test: `exhaustive` manifest with `face_count=3, len(face_boxes)=1` fails validation.
- Negative test: detection scoring against a `roster_only` manifest raises.
- Negative test: a box without `LabelLineage` fails validation.
- Test: no `cli.py` gate command path reaches `load_legacy_manifest`.
- The sealed eval split exists, is committed by hash, and its draw timestamp precedes every curation-selection artifact; identity-disjointness from the train/validation side is asserted, not eyeballed.
- Regression: retagged corpus646 loads clean; every enumerated description-eval consumer still passes.

### Slice 4 *(runs before Slice 3's bulk work)*: Derive power from measured correlation

**Goal**: Per-stratum sizes follow from a declared δ and a measured ρ — and Slice 3's audit size follows from Value of Information, not from "label everything".

Changes:

- **Define the occasion key over existing pixels first (PA-04)** — the store has no capture or session column, so "within-occasion ρ" is not queryable until a grouping exists. Step order: (1) build a **provisional occasion key** with `occasion_key.py` `derive_provisional_occasion_key` **(new — see Files table; owner this slice)**: EXIF capture-timestamp bucketing plus source-directory clustering over the existing images, persisted as `benchmarks/plans/fir-11-occasion-key-provisional-<YYYYMMDD>.json` (under the Slice 0 tracked-path carve-out) so the grouping is a joinable artifact, not a query someone re-improvises. (2) Where neither recovers a grouping, fall back to **identity-as-PSU** — and this is the **central path, not an edge case**: 113/150 entries are CDN-shaped, so EXIF recovery fails on most rows. Honesty about what the fallback yields (rev 4 — the prior "bracket" claim was false): under the fallback the store yields exactly **one** `(m_id, ρ_id)` pair, and in `DEFF = 1 + (m−1)·ρ` the two proxy errors enter with opposite signs — identity-level ICC *understates* within-occasion ρ while identity-level m *overstates* occasion m (the Contract's m row now carries this same direction) — so the single computable reading is **not known to bound the estimand DEFF in either direction**, and no second reading exists to sandwich it. The sizing note therefore carries: the fallback DEFF as a **single labeled reading**, plus a **sensitivity sweep** over ρ ∈ [ρ_id, ρ_max] and m ∈ [m_recovered, m_id] (bounds taken from the EXIF-recoverable subset and a stated ρ ceiling), plus an **empirical sign check**: on the rows where the EXIF key *does* recover a grouping, compute both keys' (m, ρ) and verify the claimed proxy directions actually hold there — if they don't, the sweep bounds are re-set from the data, not the argument. Reconciliation with the identity ban (the Contract and Problem Statement forbid identity as a resampling/cluster unit because identity clusters do not partition): the fallback uses identity **only as a provisional sizing scalar's grouping proxy**, never as a bootstrap/resampling unit and never as an analysis cluster correction — the ban stands untouched, and no cluster correction is applied to unclustered images. (3) The provisional ρ is superseded by a re-measurement (`occasion_rho_report` re-run) on the operator-assigned `capture_session_id` from `LabelLineage` once Slice 3's lineage exists; the Terminology definition (`(identity_id, capture_session_id)`, assigned at labeling time) describes that *final* key, not this provisional one.
- Query the existing embedding store for (a) within-occasion correlation ρ (per the provisional key above, via `occasion_rho_report` **(new)**) and (b) HARD genuine/impostor score σ. For unit vectors use the **vMF concentration from the resultant length alone**: `R̄ = ‖Σvᵢ‖/N`, `κ̂ ≈ R̄(d − R̄²)/(1 − R̄²)`, and the population angular/score dispersion derived from `(κ̂, d)` — a function of R̄ and d, **never of store size N**. *(Rev 3 prescribed `σ̂ = √(d/(N·R̄²))`, which is SEM-shaped — it shrinks with N and makes any large store look arbitrarily concentrated; retired.)* Not bare Euclidean `σ/√n` either.
- **Read `d` from the store; never write it into the plan.** `PGVECTOR_DIM` is the sole dimension root (`db/settings.py:213 _resolve_pgvector_dimension`, default **512**; `recognition/config/settings.py:80` binds the recognition setting to it and deliberately ignores `RECOGNITION_EMBEDDING_DIMENSION` so no second root exists). At the current default the null reference is uniform cosine SD on S⁵¹¹ = `1/√512 ≈ 0.0442`. *(Rev 2 wrote `1/√128 ≈ 0.0884` — an SFace-era 128-D figure. It is **2× too large** against a buffalo_l/512-D store, and since this null scale sets what counts as a detectable ρ it propagates straight into Slice 3's sample size. Corrected here.)* A 128-D store is legal — the knob is configurable — so the deliverable records the value it read rather than either literal.
- **Stamp the store before trusting it [PROV-05].** The sizing note records, for the queried store: `PGVECTOR_DIM`, embedder model + weights id, OpenCV major, and the align/preprocess path that produced the vectors. Vectors written **before CVUP-1** (OpenCV 4.x) are not interchangeable with 5.x vectors — that incomparability is exactly why FIR-7 is blocked (Consumer Inventory §2) — so a mixed-toolchain store is re-embedded or the arms it feeds are declared pre-CVUP-1. An unstamped ρ is not a measured ρ.
- Measure **m** (mean named probes per occasion) directly under the provisional occasion key, since DEFF depends on it; re-measure both m and ρ on the operator-assigned `capture_session_id` once Slice 3's lineage exists. *(Rev 2 said the key "now exists from Slice 2's lineage" — wrong: lineage fields are schema added in Slice 2, but values land only when Slice 3 labels, which this slice precedes. PA-04.)*
- Recompute DEFF = `1 + (m − 1)·ρ` and re-derive the Slice 0 ceiling table with measured values.
- Sizing references, all cross-checked, with the two discordant splits kept apart (rev 4 — feeding one where the other belongs is the exact implementer error the Contract's H0 row now forecloses): the **alternative** split `p₁ = (p_d + δ)/(2·p_d)` (0.75 at p_d=0.20, δ=0.10) is the cross-walk used **for power/sizing**; the **null-at-margin** split `π₀ = (p_d − δ)/(2·p_d)` (0.25 at the same values) is what the Nam/Tango NI test tests against. Superiority-style rows at 80% power, exact-binomial on discordant pairs, α=.05 two-sided — p₁=0.60 → 199; 0.65 → 90; 0.67 → 67; 0.70 → 49; 0.75 → 30; 0.80 → 20. Connor normal approximation `N = 7.849·p_d/δ²` (unit: **independent paired subjects**) — δ=5pp at p_d=.15 → 471; δ=10pp at .20 → 157; δ=15pp at .25 → 88. **This slice adds the missing exact NI rows at the locked k's per-test power (none exist in this document — every row above is 80%-power), records them in the sizing note, and `test_power_sizing.py` validates them alongside the 80% rows.**
- Keep per-test α = one-sided 0.025 per the Contract's α row; raise per-stratum power to `0.80^(1/k)` at the locked k (0.969 at k=7; ≈0.973 at Product B's default k=8). Do **not** Bonferroni-split α for an IU gate. The 1.86× inflation quoted in the Contract is normal-theory for continuous endpoints; **this slice re-derives the exact inflation under the Nam/Tango/Connor discordant-pair sizing actually used** and records it in the sizing note (GF-09), noting also that `0.80^(1/k)` is a conservative lower-bound allocation because the strata share subjects.
- Replace `MIN_STRATUM_POOL = 5` with `derive_stratum_floor(...)` and surface each stratum's Wilson half-width in the report — computed via the **existing** `report.py:912 wilson_half_width(p, n, *, z)` helper, no new twin (Files table) — labeled *conditional on this pool* per **[AUDIT-08]**.
- **Gate:** Slice 3 bulk labeling does not start until this slice's numbers are recorded. Slice 4's output sets Slice 3's sample size.

Proof:

- `benchmarks/plans/fir-11-sizing-note.md` updated with measured ρ, σ, m, chosen δ, derived per-stratum n, and the corrected ceiling.
- `test_power_sizing.py` reproduces the McNemar/NI and Connor rows — including the new exact rows at the locked per-test power — against hand-computed values, and exercises `derive_stratum_floor` plus the reused `report.py` Wilson helper.
- Test: a stratum below the derived floor is reported as under-powered, never silently rolled up.

### Slice 3: VoI-sized double-labeled bias audit *(replaces the full-pool re-label)*

**Goal**: A defensible **bound** on how much of buffalo's reported advantage is ground-truth circularity — at a fraction of the cost of relabeling 732 images that still would not gate.

Design:

- **Sample, don't sweep — but check that there is anything left to sample.** Stratified subsample of the golden150 pool sized to estimate the per-image label-disagreement rate to ±10pp at p≈0.2 — roughly 70 images unstratified, ~120–150 stratified across the 7 strata. Slice 4 fixes the exact n.
- **The pool this draws from is not 150.** Slice 1's dispositions run first: the coherent frame (Slice 1's table) is 150 − 7 celeb − 3 scraped-unprovenanced = **140**, taken anywhere down to **30** by signature-family adjudication in the all-drop worst case. Two different quantities meet here and must not be conflated (rev 4): the sizing above targets a **per-image label-disagreement rate** (an audit-precision estimand); the Contract's Δ is **subject-level** — so "Slice 4's output sets Slice 3's sample size" governs the audit-rate estimand only, while **Slice 1's realized pool, not Slice 4, sets the labeling workload** whenever `n ≥ N`. Whether the audit is a census is a **branch decided by recorded numbers, never asserted in advance**: at the low end of 30–140 any derived n is a census; at the top it is not (n ≈ 120 < 140). Census branch: the sampling design collapses, the ±10pp *sampling*-precision claim is replaced by a finite-population statement with the FPC applied — **and the FPC kills sampling error only**: labeler error, arbitration disagreement, and the exhaustiveness sub-pass residual all survive at n = N, so the reported uncertainty on the labeling-regime effect carries those components explicitly and is never stated as ~zero-width just because the audit was a census. Subsample branch: golden-v2 ships scoped to the labeled subset (Target Outcome). If Slice 4's derived n exceeds the surviving pool, that is the answer — label the pool, and record that the audit is pool-limited, not precision-limited.
- **The effort comparison was against the wrong denominator.** Rev 2 billed this as "≈ 1–2 h, versus 6–12 h for the full pool". The 6–12 h figure is the Cost Model's *rejected* full-**732** blind re-label (golden150 ∪ corpus646) — a pool Slice 3 never touches under any sizing. The honest comparison is against the surviving golden150 pool: at 30–60 s/image × 2 passes + ~15% arbitration, **30 images ≈ 0.6–1.2 h**, **140 ≈ 2.6–5.4 h**, which is what the Cost Model books. *(Rev 3 also priced a "104"-image case — a retired rev-2 worst-case figure; removed.)* The saving over rev 1 is real but it comes from *dropping corpus646 from scope*, not from sampling — do not sell a scope reduction as a sampling efficiency.
- **Blind means blind (GF-02).** The operator who performed the original merge-only adjudication has already seen buffalo's partition; UI suppression does not undo that. Mitigations, in preference order: (1) a **second labeler** who never saw the original adjudication does the de-novo pass; (2) if only one labeler is available, the pass is **renamed in every artifact from "blind de-novo" to "independent re-pass, not blind"** — the labeler has seen buffalo's partition and UI suppression does not erase memory, so residual anchoring toward buffalo's joins biases the measured disagreement *downward* — and the bias bound is reported as a **lower** bound with that mechanism stated in the report. Machine proposals are revealed **only after the whole audit subsample is sealed**, never per-image.
- **Gold QC [HITL-03].** `inject_gold_items` seeds independently arbitrated known-answer items, unannounced, at ~10% of the queue. **Gold-source independence requirement (rev 4):** a gold item's reference label must not derive from buffalo's partition — merge-only-adjudicated golden150 labels are ineligible as gold references. Eligible sources: operator camera-roll entries with operator-confirmed `reference_facts` (the media-648 pattern), or items arbitrated fresh for gold purposes by the second labeler plus an adjudicator who did not perform the original adjudication, before queue injection. Gold records carry `label_source: gold_reference`. Per-labeler accuracy on gold is the **measured human error rate** the Measurement Contract requires **[HITL-09]**. Agreement between labelers alone does not certify correctness.
- **Second pass + arbitration.** Every audit image is labeled twice, independently. Disagreements go to an arbitration pass recorded with `arbitration_of`. Inter-labeler agreement is reported, not assumed.
- **Inconclusive channel.** Labelers can decline. `decision: "inconclusive"` is excluded from the identification denominator and reported as a rate. Forcing a binary choice manufactures label noise.
- **Independent exhaustiveness audit [AUDIT-04].** A third pass on a small sub-subsample checks for faces *both* labelers missed. Without it, the exhaustive claim is verified only on labeler-positive items — the same defect as the original corpus, one level up.
- Queue record schema (PA-02), stated so Slice 3 is implementable from the text, versioned `blind_queue_schema_version: 1`: each exported item carries an opaque `queue_item_id`, `sha256`, and `queue_position` only — **never `image_path`** (rev 4: the pool's filenames are Instagram-handle/celebrity-name shaped and this very plan treats them as identity evidence in Slice 1; a path in the export is an identity hint). Pixels are delivered by the exporter itself: `export_blind_queue` **materializes sanitized copies** into a staging directory named by `queue_item_id` (filename stripped, EXIF identity-bearing fields stripped), and the labeler — FIR-9 UI or headless — renders only those. Each committed label record carries `queue_item_id`, the box geometry, `decision`, the operator-recorded `face_count` and `capture_session_id`, and the full `LabelLineage` block; at manifest assembly the operator `face_count` is written into `GoldenEntry.face_count` and `capture_session_id` into each box's `LabelLineage` (the count-then-box independence of Slice 2 is preserved because the count is committed before boxes are drawn). No detection, cluster, name, count-hint, prior-tag, or **path/filename** field may appear in the export — that absence, including the path absence, is what `test_blind_queue.py` schema-asserts.
- Existing-code reality: `export_blind_queue`, `join_agreement_report`, `inject_gold_items`, `assemble_golden_v2` are all **new** (owners: this slice — Changes bullets are the Files-table assignments). `draft_labels.py` holds only `normalize_rel_path` and `generate_draft_manifest`; `corpus_inventory.py` is filesystem-only. *(Rev 3 also listed `merge_manifest_pools` — deleted from the plan: no slice merges manifest pools; Slice 3 never touches corpus646 and the full-732 merge is the Cost Model's rejected alternative.)*
- **Assemble the shipping manifest.** `assemble_golden_v2` **(new)** builds `golden-v2-<YYYYMMDD>.json` (or `golden-v2-audit-<YYYYMMDD>.json` on the subsample branch — Target Outcome) from the arbitrated audit labels, with `annotation_mode: exhaustive`, full lineage, and provenance on every entry. This is the owning bullet golden-v2 previously lacked.
- **Dependency:** FIR-9 blind mode in the curation atlas is the primary labeling surface. **Acceptance precondition (rev 4, not yet done):** FIR-9 has no named slice, shared schema version, or acceptance test for this consumption today — before Slice 3 schedules any UI-based labeling, FIR-9 must accept `blind_queue_schema_version: 1` and demonstrate its gate-mode render suppresses every hint field against the `test_blind_queue.py` fixture; owner: FIR-9. Until that lands, **the headless fallback is the path of record, not a contingency**. **Headless fallback (PA-11):** `export-blind-queue` emits the queue as JSON; the labeler works from the sanitized staging-directory renders (never original paths) plus a file-based commit of one queue-record per image; `join_agreement_report` consumes the same records. Degraded ergonomics; blindness and lineage guarantees hold **because the export is de-identified as specified above** — rev 3's "identical blindness" claim was false while the export carried `image_path`, and the fallback queue payload passes the same `test_blind_queue.py` schema assertions, including the no-path assertion. Under the single-labeler configuration every artifact this slice emits is renamed "independent re-pass, not blind" (GF-02), and the fallback does not change that.

Proof:

- Blind-queue export contains no detection, cluster, name, count, or path/filename field (schema-asserted in `test_blind_queue.py`; the path assertion is the filename-leak guard).
- Gold items are indistinguishable from real items in the exported payload (asserted).
- Measured per-labeler gold accuracy and inter-labeler agreement are recorded in the sizing note.
- The labeling-regime measurement is stated with its bundle caveat and its interval; in the single-labeler case it is labeled a lower bound with the anchoring mechanism stated.

### Slice 5: Re-baseline with 6-arm decomposition and an under-powered banner

**Goal**: A buffalo_l baseline on non-circular labels, with the confound decomposed rather than papered over.

The rev-1 plan proposed publishing a single old-vs-new `Δfalse_split` as "the measurement of prior circularity". That delta simultaneously absorbs a labeling-procedure change, a manifest-schema change, a scoring-code change (subject-level + DEFF), a corpus-size change from the fail-closed drop, and a metric-definition change. It measures none of them. Replaced by:

| Arm | Pixels | Labels | Scoring code | Toolchain | Isolates |
| --- | --- | --- | --- | --- | --- |
| **A1** | golden150 (full) | original (merge-only) | original | **OpenCV 4.x (pre-CVUP-1)** | published baseline — read from the committed QA report, **not** recomputed |
| **A1″** | golden150 (full) | original | original | 5.x | **toolchain change** (everything else held against A1) |
| **A1′** | golden150 audit subsample | original | original | 5.x | **pool composition** (everything else held against A1″) |
| **A2** | golden150 audit subsample | new audit labels (blind, or independent re-pass per the Slice 3 labeler configuration — artifacts named accordingly, GF-02) | original | 5.x | **labeling regime** (procedure + coverage + box geometry, bundled — see below) |
| **A3** | golden150 audit subsample | original | new (subject-level, DEFF-aware sizing, paired-test statistics) | 5.x | **scoring change** |
| **A4** | golden150 audit subsample | new audit labels (as A2) | new | 5.x | the new baseline |

**No arm here carries a candidate leg** — every arm is buffalo_l (`--leg buffalo`); the pairings this table can form (toolchain, pool, labeling regime, scoring) are *not* the Contract's primary endpoint, and the paired-test machinery applied to them must never be reported as the Contract's Δ̂ (Scope split row).

Deltas, each taken against the arm that differs in exactly one factor:

- `A1″ − A1` = **toolchain**. *(Rev 2 had no such arm. A1 is a pre-CVUP-1 measurement and every other arm runs post-CVUP-1, so without A1″ the OpenCV 4→5 embedding shift is silently absorbed into whichever delta is taken against A1. That is precisely the incomparability this plan invokes to block FIR-7's baseline — Consumer Inventory §2 — and it cannot be an argument there and an oversight here.)*
- `A1′ − A1″` = **pool composition**. *(Rev 2 read `A2 − A1` as the circularity estimate, but A1's pixels are the full pool and A2's are the audit subsample, so that difference confounds the label-procedure change with the change of frame — and after Slice 1's dispositions the two frames differ by construction, not by rounding.)*
- **`A2 − A1′` is the labeling-regime effect, and that is the only claim published for it (GF-03).** "Labels" is itself a bundle: the blind pass changes labeling procedure, annotation mode/coverage, and box geometry+source together, and the arm design cannot separate those three. Two consequences, stated in the report verbatim: (a) `A2 − A1′` is published as the **combined labeling-regime effect**, never as "the circularity measurement"; (b) because the single-labeler case leaves residual operator anchoring toward buffalo's partition inside A2's labels, the labeling-regime effect is itself a **lower bound** on what fully independent labels would show. Circularity proper is bounded, not identified, and the bound's direction follows the Slice 3 labeler configuration.
- `A3 − A1′` is the accounting change.
- `A4` is the number to carry forward.

Arms A1′, A1″ and A3 read old labels through `load_legacy_manifest`. **"Original scoring" is pinned, not remembered (rev 4):** the sizing note records `original_scoring_sha` — the full 40-char commit SHA at which the QA report's scoring code (`face_metrics.py` and its callees) last ran — and every "original scoring" arm (A1″, A1′, A2) invokes the scorer **checked out at that SHA** (temporary `git worktree` at the pinned commit), because once this slice lands the new statistics, "original" otherwise stops existing. **Mixed-store branch resolved:** if Slice 4's store stamp declares the embedding store pre-CVUP-1 (OpenCV 4.x), A1″ cannot measure the toolchain delta — it would collapse into A1's frame — so in that branch the report **drops A1″, states why, and reports the remaining deltas without a toolchain decomposition** rather than silently merging frames. "Adding two arms costs essentially nothing" holds **only while** both the 5.x bakeoff path and the pinned-SHA scorer remain invocable — that invocability is asserted in this slice's proof, not assumed. `test_bias_audit.py` asserts the five deltas cannot be collapsed, not just that A2−A1 is reported separately.

Changes:

- Implement the Files-table statistics surface (owning bullet, rev 4): `subject_level_rollup`, `mcnemar_exact` (classical + Nam/Tango NI modes), `deff_adjust` (sizing-only guard included), `nonmated_reject_rate`, `fuse_occasion_template` in `face_metrics.py`, and the `bias-audit` CLI subcommand that runs the arm table and delta assertions.
- `make bakeoff-face EVAL_ARGS="--manifest <golden-v2> --leg buffalo"` on CPU, then `make bakeoff-face-score FACE_RUN=<run-record>` (the target exits 2 without `FACE_RUN` — `Makefile:614`).
- Report carries: per-stratum n, Wilson half-width labeled *conditional on this pool* (via the existing `report.py` helper), subject-level analysis intervals per the Contract's pairing row (no probe-level DEFF multiplier on them), paired arm-delta tests (labeled as arm deltas, never as the Contract's Δ̂), subject-level rollups, non-mated reject rate **[EVAL-18]**, per-stratum FMR/FNMR **[CAL-01]**, and the measured human-labeling error rate.
- Every stratum table carries a banner: **"under-powered for δ=10pp — descriptive only, not a ship gate"**, with a link to the sizing note.
- End-to-end metrics are computed on detector-supplied inputs, not ground-truth crops **[EVAL-16]**.
- Cost recorded per standing reporting rule **[COST-04]** — see Cost Model below.

Proof:

- New report supersedes `fir-embeddings-dims-detectors-qa-20260723.html`, carrying the 6-arm table and all five deltas.
- `test_bias_audit.py` asserts the arms cannot be silently collapsed into one delta, and that no delta is taken between two arms differing in more than one factor.
- `score-face --check-determinism` passes as a CI gate. Determinism contract for the new statistics (PA-12): grouping iterates over **sorted** subject/stratum keys, reductions run in fixed key order, and `single_linkage_labels` tie-breaks are explicit (lowest media_id wins), so DEFF, variance, and rollup outputs are bit-stable across runs.
- `make check-remote` green at the merge SHA.
- The pinned `original_scoring_sha` scorer and the 5.x bakeoff path are both demonstrated invocable (a smoke run of each is recorded) before any arm delta is published.

### Slice 6: Occasion-structured successor corpus — specification (Product B)

**Goal**: Specify the corpus that *can* clear the gate. Promoted from rev 1's Stretch Goals, where it was the only adequate design in the document.

Changes:

- Capture spec sized from Slice 4's measured ρ **at the k locked in the Contract's k row**: target ~60–80 identities × 8–12 **independent occasions** each, ~2 frames per occasion, distributed so every one of the **k gate strata** reaches the derived floor. The Slice 0 cross-check row applies: 60–80 identities is tens of subjects per stratum against a ~292-paired-subject illustration — the spec and the re-derived sizing must be reconciled in the sizing note before any capture spend, and the identity/occasion targets here move with that reconciliation.
- Populate `SliceTag.SIMILAR_PEOPLE` deliberately — recruit or select lookalike pairs; it cannot be harvested from existing pixels. **This line exists iff the lock chose k=8** (the draft default): under a recorded k=7 Product-B exclusion this bullet is deleted rather than building a stratum the locked gate ignores (k row).
- Consent and provenance designed in from the start so the successor corpus is **publishable**, unlike both current pools.
- Split the FR gate corpus from the description corpus so the two axes stop competing for the same images.
- Capture budget, operator hours, and per-identity cost written down before any capture begins.

Proof:

- A reviewable capture spec exists with per-stratum targets traceable to Slice 4's numbers.
- The spec states its total cost and what it buys, in units of the Measurement Contract's δ.

---

## Cost Model

Recorded before execution, per **[COST-04]** and the standing reporting rule.

| Item | Basis | Estimate |
| --- | --- | --- |
| Slice 3 labeling (double-labeled + arbitration) | post-Slice-1 surviving pool — **30–140** images (coherent-frame interval, Slice 1; blocking re-derive gate) × 2 passes × 30–60 s + ~15% arbitration. At the low end of the interval any derived n is a census; at the top it may not be — the census-vs-subsample branch is decided by recorded numbers (Slice 3) | **0.6–5.4 operator-hours** |
| Slice 3 gold-item preparation | ~10% of the realized queue — **≈3–14 items** on the 30–140 pool *(rev 3's flat "~15" over-books the worst case ~2×)* — independently arbitrated from buffalo-independent sources (Slice 3 gold rule) | **0.5–1 h** |
| Schedule risk: FIR-9 blind-mode wait (GF-20) | Slice 3's primary surface is frontend-owned; idle wait is a real cost line even at $0 compute. Mitigated by the headless CLI fallback (Slice 3), which caps the wait at the fallback's ergonomic penalty | tracked in handoff; not $0 |
| Slice 5 compute (buffalo_l, CPU only) | A1.Flex ~$0.152/hr, prior full-corpus CPU runs | **< $1 total** |
| Slice 5 per-image compute cost | total ÷ images scored | reported in the artifact |
| *Rejected alternative*: full-732 blind re-label | 732 images × 30–60 s, single pass. **This is the only thing the 6–12 h figure ever costed** — it is not the comparator for Slice 3's sizing, which never touches corpus646 | **6–12 operator-hours for a corpus that still cannot gate** |
| Slice 6 capture (Product B, not executed here) | ~70 identities × ~10 occasions | scoped in Slice 6 |

---

## Consolidated Checklist

### Context and Ownership

- [ ] Every cited canon rule ID verified present in current `~/Development/heuristics-canon/lexicons/` (the canonical repo, not the research mirror) at citation time (**no canon version pinned — versions are mutable, rule IDs are idempotent**); **[EVAL-19]** confirmed retired and **[MLDATA-20]** confirmed out-of-scope for this plan.
- [ ] FIR-9 confirmed as owner of the curation UI; blind mode registered as a hard dependency for Slice 3.
- [ ] Manifest-schema ownership and the `manifest_version` bump recorded in handoff.
- [ ] Measurement Contract reviewed and locked before any labeling or scoring work. *(Rev 3 ships the contract DRAFT-PENDING-REVIEW; the planning-review pass performs the lock.)*

### Checklist for Slice 0: Power ceiling

- [ ] Tracked path for `benchmarks/` deliverables carved (`.gitignore` negation or relocation) and the three existing source artifacts committed; `git ls-files` proves it.
- [ ] Ceiling arithmetic written to `benchmarks/plans/fir-11-sizing-note.md`, in paired-subject units with the provisional constants flagged.
- [ ] Handoff decision recorded that Slices 1–5 are not a ship gate.
- [ ] No bulk labeling dispatched before all three land.

### Checklist for Slice 1: Provenance required

- [ ] `GoldenEntry.provenance` non-optional; loader raises a named `ManifestError` listing every offending path.
- [ ] 6 unprovenanced entries dispositioned per the Slice 1 table (3 dropped as scraped, 3 assigned `operator/mock_entity`), each with a recorded rationale.
- [ ] Drop confirmed FR-gate-scoped; the 6 remain available to description eval.
- [ ] Signature-family census re-derived against the frozen manifest hash (method in Slice 1; PR-35 recorded 113/150 entries), then **all census hits adjudicated individually**; survivors re-tagged with a truthful source/license; `mock_entity` removed from every real third-party subject; `warn_scrape_signature` landed.
- [ ] Loader emits a filename-heuristic warning implementing the **full signature family** (not the two-regex subset) so the scrape pattern cannot silently re-enter.
- [ ] Slice 0 ceiling table re-derived from post-adjudication counts.
- [ ] Re-derived pool counts committed to the sizing note and any divergence from the 30–140 planning interval dispositioned in a plan changelog entry; no later slice starts before this lands (blocking gate).
- [ ] 7 celeb/fixture entries dispositioned explicitly.
- [ ] The **8 v3 images carrying a named identity with zero named boxes** dispositioned by **dropping the identity claim** (the only Slice-1-legal branch — see the Population block). None ride into Slice 2 unresolved.
- [ ] `corpus-manifest-v3.json` frozen by sha256, and the hash recorded in the sizing note beside every figure it supplies.
- [ ] Negative test proves an unprovenanced entry fails to load.

### Checklist for Slice 2: Mode, coverage, lineage

- [ ] `AnnotationMode` added; `SUPPORTED_MANIFEST_VERSION` bumped to 3.
- [ ] Coverage validator lives on `GoldenManifest`; `_face_count_covers_labeled` retired.
- [ ] `face_count` semantics documented in the loader and asserted.
- [ ] `LabelLineage` added and required on every box.
- [ ] Detection scoring refuses `roster_only`.
- [ ] Description-eval consumers of corpus646 enumerated and verified before the retag.
- [ ] golden150 frozen read-only; `load_legacy_manifest` unreachable from gate commands (asserted).
- [ ] **Sealed eval split (QA v8 T-08) drawn via `draw_eval_split`, identity-disjoint, committed by hash, timestamped before any curation-selection artifact.**
- [ ] Split artifact stamped `partition_provenance: "pre-audit, buffalo-derived merge-only"` / `disjointness: provisional`; re-validation against Slice 3 arbitration registered as a Slice 5 precondition; VLM-6 notified it may be re-drawn once.
- [ ] Reciprocal blocking pointer to FIR-11 confirmed present in the VLM-6 plan (owner: VLM-6 plan owner) before the split is relied on as protecting VLM-6.
- [ ] `corpus-manifest-v3.json` schema disposition recorded (legacy loader vs v3-schema + two new count fields).
- [ ] FIR-7 gate surfaces confirmed on the Consumer Inventory; the FIR-7-side mirror of the ordering + evidence-tier consequences confirmed landed (owner: FIR-7 plan author — a blocking precondition, currently not done and not claimable from here) before FIR-7 Slice 0a seals anything.

### Checklist for Slice 4: Power derivation *(precedes Slice 3 bulk work)*

- [ ] Provisional occasion key built via `derive_provisional_occasion_key` and persisted, or the identity-as-PSU fallback used with its single-reading DEFF, sensitivity sweep, and EXIF-subset sign check recorded (PA-04).
- [ ] ρ, σ, and m measured from the existing embedding store under that key and recorded, marked provisional pending the Slice 3 `capture_session_id` re-measurement.
- [ ] Embedding dimension **read from `PGVECTOR_DIM`** (not written into the plan) and the null cosine SD `1/√d` derived from it — 512-D ⇒ ≈ 0.0442, never the retired 128-D ≈ 0.0884.
- [ ] Store stamped: `PGVECTOR_DIM`, embedder model + weights id, OpenCV major, align/preprocess path. Pre-CVUP-1 vectors re-embedded or the arms they feed declared pre-CVUP-1.
- [ ] DEFF recomputed; Slice 0 ceiling table re-derived with measured values.
- [ ] δ=10pp, one-sided α=0.025 per test, the locked k (per the Contract's k row), and the per-test power `0.80^(1/k)` confirmed in the sizing note, with the exact NI rows at that power added.
- [ ] `MIN_STRATUM_POOL` replaced by `derive_stratum_floor`; Wilson half-widths surfaced and labeled conditional.
- [ ] Slice 3 audit sample size set from this slice's output.

### Checklist for Slice 3: Bias audit

- [ ] Blind-queue export carries no detection, cluster, name, or count field (schema-asserted).
- [ ] Second independent labeler used, or the single-labeler limitation printed and the measurement declared a lower bound — **and, in that case, the Ship rule's bias-evidence clause recorded as unsatisfied on this evidence (see the rescoped Ship rule row).**
- [ ] Sample size reconciled against the post-Slice-1 surviving pool (30–140, coherent frame); where n ≥ N, the audit is recorded as a pool-limited census with the FPC applied — and the non-sampling error components (labeler, arbitration, exhaustiveness) still reported, never a ~zero-width claim.
- [ ] Gold items injected; per-labeler accuracy measured and recorded.
- [ ] Every audit image double-labeled; disagreements arbitrated with `arbitration_of` recorded.
- [ ] Inconclusive channel available and its rate reported.
- [ ] Independent exhaustiveness pass run on a sub-subsample.
- [ ] Machine proposals revealed only after the subsample is sealed.

### Checklist for Slice 5: Re-baseline

- [ ] All six arms computed (A1″ dropped with stated cause in the pre-CVUP-1 store branch); A1 read from the tracked QA report (post Slice 0 carve-out), never recomputed; A1″ and A1′ recomputed under 5.x through `load_legacy_manifest` at the pinned `original_scoring_sha`.
- [ ] Sealed eval split re-validated against Slice 3 arbitration before scoring; a changed identity membership forces a re-draw.
- [ ] Report carries subject-level rollups, DEFF-corrected conditional intervals, exact McNemar, non-mated rates, per-stratum FMR/FNMR, and the measured human error rate.
- [ ] Under-powered banner present on every stratum table with a link to the sizing note.
- [ ] End-to-end metrics computed on detector inputs, not GT crops.
- [ ] Cost and cost-per-image published.
- [ ] `score-face --check-determinism` asserted as a CI gate.

### Checklist for Slice 6: Successor corpus spec

- [ ] Per-stratum capture targets traceable to Slice 4's measured ρ.
- [ ] `similar_people` capture designed in.
- [ ] Consent/provenance designed for publishability.
- [ ] Capture budget written down.

## Review Readiness

- [ ] Every new invariant has a paired negative test proving the assertion can fail **[TEST-15]**.
- [ ] No manifest-schema change lands without every enumerated consumer verified.
- [ ] Handoff decision records the schema bump and its contract implications.
- [ ] No reported figure claims design-based inference to a population **[AUDIT-08]**.

## Success Criteria

- [ ] No manifest in `benchmarks/manifests/` can load with a missing provenance, an undeclared annotation mode, or a box without lineage.
- [ ] The power ceiling is published, and no artifact from Slices 1–5 is presented as a ship gate.
- [ ] The bundled labeling-regime effect is measured and published with its interval, its bundle caveat, and its direction statement (lower bound on circularity in the single-labeler case; never an upper bound in any case), derived from double-labeled data with a measured human error rate.
- [ ] The old-vs-new comparison is published as a 6-arm decomposition, not a single confounded delta; toolchain (A1″−A1) and composition (A1′−A1″) are reported separately from the labeling-regime effect (A2−A1′), which is published as the bundled labeling-regime effect — never as "the circularity measurement" and never as an upper bound on it.
- [ ] Every reported per-stratum figure carries its Wilson half-width, labeled conditional on this pool; no stratum is rolled up while under-powered.
- [ ] Slice 6 specifies, with costed per-stratum targets, the corpus that would actually clear δ=10pp.
