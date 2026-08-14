# FIR-11. Gate-Corpus Remediation and FIR Re-Baseline

> **Metadata**
>
> - **Date**: 2026-07-27 (rev 2, 2026-07-28 · rev 3, 2026-08-13)
> - **Author**: Claude Opus 5 (high) — rev 2 after `plan-analyze` (12 findings) + 5-lane remote grok-4.5 adversarial flock (21 findings); rev 3 judgment pass against the 35 open FIR-11 findings in handoff (bodies in the DB, referenced here by ID only)
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
| Verified as already resolved by rev 2, no further edit: Product A/B split and under-powered banner (GF-05, GF-06 core), gold-QC/second-pass/arbitration/inconclusive (GF-04), sizing-before-labeling ordering (GF-17), VoI subsample (GF-18), roster_only refusal inventory (GF-19), conditional-on-pool intervals per AUDIT-08 (GF-14 — rule text re-verified against current canon), epic metadata (PA-01), draft_labels/corpus_inventory new-symbol naming (PA-02/PA-03 core — verified against the modules on disk), golden-v2 path (PA-08), consumer inventory (PA-09), named new test modules (PA-10 — `scripts/eval_harness/tests/` holds one module today, matching the plan's "(new)" markers), FIR-9 dependency line (PA-11 core), EVAL-18 endpoint (GF-16 core — rule text re-verified) | — |

---

## Objective

Make the FIR gate corpus honest about what it can and cannot measure, then buy the measurement it actually needs.

Two products, deliberately separated because one is achievable on existing pixels and the other is not:

- **Product A — bias-bounded re-baseline (this task).** Schema invariants that make the measured defects unrepresentable, a Value-of-Information-sized double-labeled audit that puts a *bound* on how much of buffalo's reported advantage is ground-truth circularity, and a re-run baseline published with that bound and an explicit **under-powered** declaration.
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
4. **Hard power ceiling on existing pixels.** No stratum resolves a 10pp difference. Largest (clean, n=56) has a Wilson 95% half-width of ±11.9pp; `masked` (n=5) is ±31.4pp. `strata.py:78` sets `MIN_STRATUM_POOL = 5`, roughly two orders of magnitude below a δ=10pp gate, so a stratum passes the harness's own floor while being statistically empty. **Re-labeling does not fix this** — see Slice 0.

### Superseding input: `corpus-manifest-v3.json` (2026-07-28)

`benchmarks/manifests/corpus646-interleave-manifest-20260716.json` is superseded by **`benchmarks/manifests/corpus-manifest-v3.json`**, rebuilt 2026-07-28 over the same 646 pixels. Defects 1, 3 and 4 are unaffected. Defect 2 is **confirmed and now quantified**; one supporting claim elsewhere in this plan is **falsified**.

*Re-derivation duty, closed form.* Search this plan for `20260716`, `corpus646-interleave`, and any headcount not listed in the Population paragraph below; replace each from v3 and cite `benchmarks/manifests/corpus-manifest-v3.json` at the point of use. **Done when that search returns only the freeze/retag instructions that intentionally name the old file.**

**Population (v3, re-derived).** 646 images · **137** distinct identities · **558** identity appearances · **538** images carrying ≥1 identity · **108** carrying none. Multi-identity images: **14 carry two, 3 carry three** (17 total, 20 surplus memberships — `558 − 538 = 20`, not 17; rev 2 and QA v7/v8 both said "17 carrying two", which double-counts the triples into the pair bucket). Images per identity: mean 4.073, median 2, max 50. Size-weighted mean cluster **M̃ = 12.925** (`Σ s_i² / Σ s_i` over identity clusters, = 7,212 / 558).

> **Two units, one paragraph — do not cross them.** `538 / 108` counts **images by identity roster** (`named_identities` non-empty); the `584` in the next block counts **named boxes** (`Σ named_face_count`). Neither is a headcount of the other. Measured on v3: **530** images carry ≥1 named *box*, so **8 images list a named identity and carry zero named boxes**. That 8 is not a rounding artifact and not merely a legibility defect — those roster members are inside the identification estimand while contributing no localisable probe, so they are unscoreable under an `exhaustive` manifest and would fail the Slice 2 coverage invariant on the spot. **Disposition them in Slice 1 alongside the provenance cases**: either box the faces during the Slice 3 pass, or drop the identity claim as unsubstantiated. Do not let them ride into Slice 2 unresolved.

> **Naming, because these two nearly collided.** Call `M̃ = 12.925` and the expression `1 + 11.925·ICC` **`C_identity`** — an *identity-membership concentration index*, **descriptive only**. It is **not a design effect and must never be used as this plan's `DEFF`**, for the reason the block itself establishes below: identity clusters overlap (17 images sit in two or three) and exclude 108 images, so a Kish correction over them is not a valid corpus-wide deff — it is a statement about how concentrated identity membership is, nothing more. The **bare token `DEFF` everywhere else in this plan means exactly one thing**: the Measurement Contract's occasion-level `1 + (m − 1)·ρ` at m ≈ 3.3, over named probes, on non-overlapping occasion PSUs. Different corpus, different observation unit, different cluster definition, different correlation parameter. Slice 4 recomputes `DEFF`; it does not touch `C_identity`.

**Defect 2 is confirmed and larger than stated.** v3 records `named_face_count` and `detected_face_count` separately for the first time: **584 named**, **1,763 detected**. The gap is not a single subtraction — it runs in both directions:

- `sum(max(0, detected − named)) = 1,182` — the **per-image positive excess of detector proposals over named boxes**, on **368 of 646** images. Note the formula: it is a per-image *count* difference, clipped at zero and summed. The manifest carries `detected_boxes` and `named_boxes` but **does not associate them**, so this is not a face-level unmatched count.
- `sum(detected) − sum(named) = 1,179`. The 3-unit difference is real and points the other way: **3 images carry a named face the detector did not find at all** (media_id 221, 271, 556 — `named 1, detected 0`). Those are detector misses on curated ground truth.

**How 1,182 may and may not be restated.** It is an **unmatched machine-proposal inventory** — the size of the adjudication queue — and nothing else. It is **not** a count of omitted real faces, and it is **not even an upper bound** on them in either direction, for two independent reasons: (a) without box matching, an image can simultaneously hold a detector miss on a named face and a spurious proposal elsewhere, so the excess and the omissions are not nested sets; (b) false positives inflate it while detector misses — which never enter the excess at all, and the three images above prove such misses exist — deflate any omission reading of it. So the only defensible sentence is the queue-size one. **Never restate 1,182 as a verified population size, as a face count, or as a bound.** Describing any individual detection as "a real face carrying no name" requires spatial adjudication first. Adjudicating it is exactly the work Slice 2 buys. What is established without adjudication is the structural claim: π = 0 was never a schema quirk. (The 64-image golden150 overlap — 115 omitted faces — was the early evidence of this defect; v3 now measures the full 646 directly, so that figure is superseded, not generalised.)

**Falsified: "corpus646 carries no `tags` field at all."** v3 carries operator hand strata: **150 entries were hand-reviewed** (`slice_tags_source: operator_hand`), of which **96 produced at least one tag** and **54 were reviewed and produced none**. Tag counts across the 96: profile 50 · blur 28 · low_res 26 · occlusion_other 19 · sunglasses 13 · masked 5 · **similar_people 0**. No entry carries a tag from any other source. So the merged pool does contribute stratum members without new tagging — and the 54 reviewed-clean entries are *evidence of absence*, unlike the 496 never reviewed.

> **Closed action.** Two units, kept apart. **Image inventory:** the image-level union is **732** (`150 + 646 − 64` shared sha256), not "~700"; corpus646 contributes **96 hand-tagged / 550 untagged** images with stratum maxima profile 50 · sunglasses 13 · masked 5 · similar_people 0. **Probe units, which is what the pool-sizing table is denominated in:** the 96 tagged images carry **99 identity appearances / 111 named boxes**; the 550 untagged carry **459 / 473**. Do not let 96 and 550 stand as pool contributions inside a table sized in raw named probes — that is an image count in a probe column, and it makes the contribution look ~5× smaller than it is.
> **Verdict to preserve, unchanged:** every hard stratum remains under the plan's derived stratum floor, and `similar_people` is empty in *both* pools, so no amount of re-tagging invents lookalike pairs. Do not reword either into a soft pass.

**Missing deliverable: the sealed eval split (QA v8 T-08).** QA v8 assigns this plan the split artifact and requires it be **drawn and frozen before curation selection runs** [EVAL-07] [MLDATA-09] [EVAL-10]. This plan does not name it. Its five existing uses of "sealed" are the unrelated proposal-reveal sense (reveal after the audit subsample is sealed), so the artifact needs a distinct term — **"sealed eval split"** — or the two senses will be conflated the first time someone greps. Add it as a **Slice-2 deliverable**, committed by hash, drawn on the post-remediation corpus and before any stratum curation decision. VLM-6 is the live consumer and is currently curating with no split frozen; a re-gate line has been added to its plan pointing back here.

**Two consumer-surface gaps this block opens and must therefore close.**

1. **`corpus-manifest-v3.json` is now load-bearing and appears in no Files-to-Change, Consumer Inventory, or Related Files row.** It supplies the strata this plan's pool sizing depends on and it carries two fields the plan's own Terminology does not define — `named_face_count` and `detected_face_count`, where the existing `face_count` is explicitly *not* "faces the detector found". Before Slice 2, state which is true: v3 loads through `load_legacy_manifest` and is **not** a v3-schema artifact, or it must validate under `SUPPORTED_MANIFEST_VERSION` 3 and `manifest.py` gains the two count fields. The retag instruction and the frozen-artifact row both currently point at the **superseded** 20260716 file; the retag target is correct there (it is the legacy file being retired) but v3 needs its own row.
2. **FIR-7 is a consumer of `golden150-draft-20260723.json` through the gate CLI, and is not in the inventory.** This plan freezes that manifest read-only, makes the v3 gate loader reject it by design, and asserts no `cli.py` gate command path reaches `load_legacy_manifest`. FIR-7's frozen baseline, identity split, every per-floor base value written into `fir-7-regate.json`, all three sealed K-budget touches and its descope thresholds read that corpus through `score-face --manifest` and `regate.py` — gate CLI paths. This plan's own rule ("any consumer not on this list that breaks is a plan defect") convicts the omission. **Add FIR-7's `regate.py`, `config_levers.py`, `benchmarks/gates/fir-7-regate.json` and `golden150-fir7-identity-split.json` to the Consumer Inventory, and state which plan's slice lands first.** Neither plan currently references the other, and both were authored the same day under `MAINT-fir-qa-decomposition-reflow-20260728`.

**Sampling-design constraint, now absorbed into the Contract above (see the amended PSU / m / DEFF rows).** Images here are drawn via containers (identity, shoot, occasion) while the power math treats each image as an independent SRS unit — so Slice 4's ρ estimation must name its PSU, its deff or ICC, and its *n*<sub>eff</sub> **[AUDIT-11]**. Two corpus facts constrain how: identity clusters **do not partition** the 646 images (14 belong to two clusters, 3 to three, 108 to none), so a subject-level bootstrap over identity is not a valid resampling scheme as it stands — construct non-overlapping PSUs (the occasion key already specified in this plan is the right instrument) or use a multilevel / sandwich estimator. Do not apply a cluster correction to the 108 unclustered images; that is a plan-local consequence of the non-partition, not an AUDIT-11 requirement.

Handoff: findings `FIRQA8-PR-02`, `FIRQA8-PR-06` under `MAINT-fir-qa-decomposition-reflow-20260728`.

## Measurement Contract

**Status: DRAFT-PENDING-REVIEW (rev 3).** Declared before any labeling or scoring work begins; a planning-review pass must lock it, and changes after lock require a new review pass. The gate in Context and Ownership ("reviewed and locked before any labeling or scoring work") is satisfied only by that lock, not by this draft.

**Scope split, stated once (GF-06):** the δ=10pp intersection-union gate and the Ship rule below belong to **Product B** — they are executable only on the occasion-structured successor corpus (Slice 6). Product A can execute every row of this contract *except* the IU gate: it publishes the descriptive paired comparison, the bias bound, and the power ceiling, and is banner-labeled under-powered. No Product A artifact may be presented as an IU-gate result.

| Field | Value |
| --- | --- |
| **Estimand** | Finite-pool **descriptive** comparison over the named gate corpus. Not a design-based inference to any image population. Per **[AUDIT-08]**, no design-based margin of error may be reported on this operator-picked convenience sample; intervals are labeled *conditional on this pool*. |
| **Analysis unit** | Subject (identity), not face. Per **[EVAL-17]**. |
| **PSU (primary sampling unit)** | **Occasion** — one independent capture event for one identity. Two frames of the same person from the same shoot are one PSU. **Amended 2026-07-28 (QA v8 re-gate), and this amendment is the required review pass.** Occasion is *not* a partition of images either: on the 17 corpus-v3 images carrying two or three identities an image belongs to two or three occasions, and the 108 identity-free images belong to none. So (a) the analysis is over **occasions**, never over images — an image is a container, not a unit; (b) the 108 identity-free images are **outside** the identification estimand entirely and receive no cluster correction; (c) multi-identity images contribute one probe to each of their occasions, which is correct at the occasion level and only breaks if anyone re-aggregates to images. A subject-level bootstrap over *identity* remains invalid and is not the fallback. |
| **m (cluster size)** | Mean named probes per PSU. Measured, not assumed. In golden150 today: 160 named probes / 48 identities ≈ **3.3** (identity is a *lower bound* proxy for occasion; true m is larger because most identities were shot on one occasion). **Amended 2026-07-28:** 3.3 is a golden150 figure — the corpus this plan exists to replace — and is **provisional only**. `m` is **re-measured on the post-Slice-2 corpus** once the occasion key exists, and the Slice-0 ceiling table is re-derived from the measured value. Do not inherit 3.3 past Slice 2, and do not substitute corpus-v3's 4.073 images-per-identity for it: that is images per *identity*, not named probes per *occasion*. |
| **DEFF** | `1 + (m − 1)·ρ`, ρ measured in Slice 4, PSU = occasion, unit = named probe. **This is the only quantity in this plan named `DEFF`** — corpus-v3's identity-membership concentration `C_identity` (M̃ = 12.925) is descriptive and must never be substituted here (see the superseding-input block). **Slice 4 must also report `n_eff` and name the estimator [AUDIT-11]**; a deff without a printed `n_eff` does not satisfy the contract. At m=3.3: ρ=0.7 → 2.6; ρ=0.9 → 3.1. *(Rev 1 quoted "n_eff 1.11 at n=100, ρ=0.9" as if it justified DEFF 1.2–3×. Those are inconsistent — n_eff 1.11 implies DEFF ≈ 90 by treating all 100 probes as one cluster. The n=100 line is deleted; DEFF derives from m, not from total n.)* |
| **Primary endpoint** | Paired per-subject identification correctness, buffalo_l vs candidate leg, on identical detected inputs. The primary scalar is the per-stratum difference in subject-level identification accuracy, `Δ = acc(candidate) − acc(buffalo_l)`, estimated from discordant subject pairs. |
| **H0 (per stratum)** | Non-inferiority null: `H0: Δ ≤ −δ` (the candidate is worse than buffalo_l by at least 10pp on paired subjects), tested per stratum by exact-binomial McNemar on discordant pairs at one-sided α within the two-sided 0.05 frame. Rejecting H0 in **all 7** strata is the IU pass condition (Product B only). Product A reports the same per-stratum `Δ̂` descriptively with no H0 decision, under the under-powered banner. |
| **Statistic–interval pairing** | One frame governs each number (GF-07/PA-05): the *decision* statistic is exact McNemar on discordant pairs; its accompanying interval is the DEFF-adjusted CI on `Δ` from paired data. Wilson half-width on a single arm's accuracy is **descriptive precision only** — it appears in stratum tables labeled *conditional on this pool* and never grounds a power or gate claim. The Slice 0 ceiling is stated in discordant-pair units (Connor/McNemar), with Wilson shown alongside as the single-proportion illustration, not the argument. |
| **Secondary endpoints** | `false_split`, `false_merge`, non-mated reject rate at a **fixed score threshold pre-declared in the sizing note before scoring** **[EVAL-18]** (rank metrics cannot express "no one here"; the threshold is declared, not tuned on results), per-stratum FMR/FNMR **[CAL-01]**. |
| **δ (minimum effect worth detecting)** | 10pp absolute on the primary endpoint. Declared now, per **[EXP-12]** — not chosen after seeing the data. |
| **α** | 0.05 two-sided, **per test, not split**. The gate is intersection-union: every stratum must pass, so per-test α stays 0.05 and per-stratum *power* is raised instead. Bonferroni is the wrong correction here. Holm/BH applies only to the exploratory "which strata differ" question. |
| **k (strata in the IU gate)** | **7** — clean, profile, blur, low_res, occlusion_other, sunglasses, masked. `similar_people` has **zero** members and is excluded from the gate until populated. *(Rev 1 used k=9; the measured corpus has 7 populated strata and one empty.)* |
| **Per-test power** | `0.80^(1/7) = 0.969`. Normal-theory N inflation vs 80%: **1.86×**. Two declared caveats (GF-09): `0.80^(1/7)` assumes independent strata, but the 7 strata share subjects, so this allocation is a conservative lower bound on joint power — it can oversize, never undersize. And 1.86× is a normal-theory ratio for continuous endpoints; Slice 4 re-derives the exact inflation under the McNemar/Connor sizing actually used and records it in the sizing note. |
| **DEFF vs subject aggregation** | Stated so the same correlation is neither double- nor zero-counted (GF-08): DEFF applies at the **named-probe level for sizing**. The analysis then aggregates probes to occasions (template fusion) and occasions to subjects; the dependence remaining *after* occasion aggregation is between occasions of one identity, and Slice 4's estimator (multilevel or sandwich, named in the sizing note) carries it. No additional DEFF multiplier is applied on top of the subject-level analysis. |
| **Ship rule** | Candidate ships only if **every** one of the 7 strata clears δ=10pp non-inferiority at 96.9% power **and** the bias bound from Slice 3 is smaller than the observed margin. Locked at contract lock (see Status line — this draft does not lock it); not renegotiable after seeing results. This rule is Product B's gate; Product A cannot invoke it. **The second clause requires an *upper* bound on circularity, and Slice 3 does not always produce one.** Under the single-labeler fallback (Slice 3, GF-02 mitigation 2) the bound is explicitly a **lower** bound, and "a lower bound is smaller than the margin" is vacuous — it is satisfiable by a bias of any size. So: with two independent labelers Slice 3 yields the upper bound this rule needs and the rule is live; with one labeler the rule is **not satisfiable on this evidence** and the candidate does **not** ship, regardless of the observed margin. Recruiting the second labeler is therefore a ship precondition, not a preference ordering. |
| **Human-labeling error rate** | A measured input, not an assumption. Per **[HITL-09]**, a stage credited with catching model error carries its own measured rate or the gate does not credit it. Measured in Slice 3 via gold items **[HITL-03]**. |

## Constraints

- **Re-inference cannot remediate.** buffalo_l is deterministic on fixed pixels; re-running regenerates the same boxes and clusters. The contamination is in the labeling *procedure*, not the inference run. Any step proposing "re-process the corpus" as the fix is rejected by construction.
- **Re-labeling cannot buy power.** It changes procedure, not sample design. It mints no new occasions, no new hard-condition captures, no new multi-shot identities, and no lookalike pairs. See Slice 0.
- **Both corpora are private and unpublishable.** `PRIVATE_SOURCES` (`manifest.py:154`) covers `localwp` and `operator`; `Provenance.is_publishable` (`manifest.py:261`) fails closed on private source regardless of licence or explicit flag. golden150 is 137 `operator/mock_entity` + 7 `celeb/fixture` + 6 unprovenanced; corpus646 is 646 × `localwp/consented`. Remediation restores *auditability*, not publishability.
- **The two pools are not independent.** 64 shared sha256; 49 of golden150's 53 roster names present in corpus646; only 15 identities exclusive to the golden150-only half. Treating corpus646 as a fresh sample would double-count. corpus646 carries hand strata on **96 of 646 entries** under `corpus-manifest-v3.json` (profile 50 · blur 28 · low_res 26 · occlusion_other 19 · sunglasses 13 · masked 5 · similar_people 0) — the remaining 550 contribute to no stratum without new tagging, and the tagged 96 are still far under floor in every hard stratum. *(Rev 2 said "no `tags` field at all"; that was read from the superseded 20260716 manifest.)*
- **Greenfield policy applies.** No migration shims in the gate path. The one deliberate exception is a read-only legacy loader used *only* by the bias-audit arms (Slice 3), never by the gate CLI — see GF-10 resolution in Slice 2.
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
| Occlusion measured only on synthetic twins | `synthetic_occlusion.py:724 filter_headline_probes` strips occluded faces from the headline set — **[MLDATA-09]**, the QC filter removes the regime under test *(rev 2 cited MLDATA-20 for this mechanism; wrong trigger)* | occlusion readiness argued from synthetic twins only — live **[MLDATA-20]** exposure |
| Cluster centroid unweighted | `db/migrations/versions/001_identity_schema.py:1720 mv_identity_cluster_centroids` | `l2_normalize(AVG(l2_normalize(e)))` — **[EMB-02]** violation, out of scope here, tracked separately |

**Misleading assumptions to retire.** That corpus646 is a licence-clean alternative to golden150 (both private/unpublishable; `mock_entity` and `consented` are both fail-closed). That corpus646 is a larger, fresher pool (it is a superset-overlap of the same operator material, and only **partially** tagged — 96 of 646 entries carry non-empty hand strata; "untagged" in rev 2 was read from the superseded manifest and is false). That the QA report's false-split advantage is a clean measurement. **That re-labeling the existing pool yields a powered gate.**

## Target Outcome

**Product A (this task, Slices 0–5).**
A `benchmarks/manifests/golden-v2-<YYYYMMDD>.json` over the **audited** golden150 pixels — `annotation_mode: exhaustive`, provenance-required, label lineage on every box, produced under blinding. A **bias bound** on ground-truth circularity, estimated from a VoI-sized double-labeled stratified subsample rather than assumed.

> **Scope of golden-v2, stated because the slices could not otherwise deliver it.** Blind labels are produced by Slice 3, and Slice 3 labels the **audit subsample** — not the pool. Meanwhile Slice 2 makes `LabelLineage` mandatory ("a box without `LabelLineage` fails validation"), so a hybrid manifest of blind-labeled boxes plus un-relabeled legacy boxes is **unloadable by construction**: it is neither `exhaustive`-under-blinding nor a valid v3 artifact. Rev 2 promised a whole-pool blind exhaustive golden-v2 and scheduled no slice that could produce one. Resolution, and it follows from this plan's own arithmetic rather than from preference: after Slice 1's dispositions the surviving pool is **at most 137, down to 37 in the all-drop worst case (PR-35)**, against which Slice 4's derived n is already a census (Slice 3), **so the audit subsample and the pool converge** and one blind pass produces a genuinely pool-wide golden-v2. Therefore: golden-v2 covers exactly the set Slice 3 blind-labels, its `entry_count` is asserted equal to the post-Slice-1 pool, and **if Slice 4 derives an n strictly below the surviving pool, golden-v2 ships as `golden-v2-audit-<YYYYMMDD>.json` scoped to the labeled subset** and the un-audited remainder stays in the frozen legacy manifest, reachable only through `load_legacy_manifest`. What never ships is a manifest that claims `exhaustive` over boxes no blind pass touched.

A re-run buffalo_l baseline scored subject-level, published with the **6-arm decomposition** that separates *toolchain*, *pool composition*, *labeling-procedure* and *scoring-code* change, and carrying an explicit "**under-powered for δ=10pp; not a ship gate**" banner on every stratum table.

**Product B (Slice 6 spec, executed after).**
An occasion-structured successor corpus sized from measured ρ: the only path to the δ=10pp IU gate. Slice 6 delivers the spec and the capture budget, not the corpus.

## Context Loading

- Rules: `docs/workbay/rules/testing-python.md`, `docs/workbay/rules/backend-python-guidelines.md`
- Canon (**unpinned — canon versions are mutable, rule IDs are idempotent; consult current canon at implementation time**), `~/Development/heuristics-canon-research/lexicons/`, each rule verified present before citation:
  - *Circularity / design*: EXP-12, EXP-22, OBS-09, MEAS-02
  - *Audit / sampling*: AUDIT-04, AUDIT-07, AUDIT-08, AUDIT-11
  - *Data*: MLDATA-08, MLDATA-09, MLDATA-20; PROV-05
  - *Eval / embeddings*: EVAL-07, EVAL-10, EVAL-16, EVAL-17, EVAL-18; EMB-02, EMB-07, EMB-10; CAL-01
  - *Human loop*: HITL-03, HITL-09
  - *Engineering / cost*: TEST-15; COST-04
  - **[EVAL-19] is explicitly retired from this plan's citation set** — see Problem Statement §1.
  - **Rev 3 pruning (GF-01):** every ID above has triggering work at a named point in this plan and was re-verified present in current canon. IDs cited in rev 2 with no instrumented trigger anywhere in the plan (EXP-03, EXP-19, EXP-20, AUDIT-05, MLDATA-18, MLDATA-21, MLDATA-22, CAL-09, FAIR-05, TEST-08, DIAG-03) are removed rather than left as ID-existence decoration; re-add any of them only together with the work that triggers it. Stale `file:line` pins are dropped — canon is mutable, rule IDs are the stable handle.
- Report: `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html` §14 (buffalo as judge, not teacher), §17 (curation), §18 (economics). **This committed artifact is the sole source of the old baseline numbers** — the old manifest is never re-loaded by the gate path.
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
- [ ] `benchmarks/manifests/corpus-manifest-v3.json` — **load-bearing for this plan's pool sizing.** Before Slice 2, record which is true: it loads through `load_legacy_manifest` and is *not* a v3-schema artifact, or it must validate under `SUPPORTED_MANIFEST_VERSION` 3 and `manifest.py` gains `named_face_count` / `detected_face_count`. Both fields are absent from Terminology today and neither is `face_count`.
- [ ] **FIR-7 gate surfaces** (`docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md`) — `regate.py`, `config_levers.py`, `benchmarks/gates/fir-7-regate.json`, `golden150-fir7-identity-split.json`. FIR-7 reads `golden150-draft-20260723.json` through `score-face --manifest` and `regate.py`, i.e. **gate CLI paths**, for its frozen baseline, its identity split, every per-floor base value, all three sealed K-budget touches, and its descope thresholds. This plan freezes that manifest read-only and makes the v3 loader reject it by design, so the bump breaks FIR-7 unless the ordering below holds.

**Which plan's slice lands first (required by the rule above).** **FIR-11 Slices 1–2 land before FIR-7 Slice 0a seals anything.** The reverse order would have FIR-7 freeze a baseline, an identity split and seven per-floor base values on labels this plan has already established are outcome-dependent — and FIR-7's sealed K-budget is burn-after-use, so a baseline sealed on contaminated labels cannot be re-sealed. Two consequences bind FIR-7 and are mirrored in its plan:

1. **No golden150-derived figure may carry a CONFIRMATORY evidence tier** while Problem Statement §1 stands. DIRECTIONAL is the ceiling until Slice 3 publishes an **upper** bound on circularity and that bound is smaller than the observed margin. Same direction constraint as the Ship rule: a single-labeler lower bound never lifts the ceiling, so under that fallback DIRECTIONAL is not a stage but a terminus.
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
| backend | `scripts/eval_harness/manifest.py` | `GoldenEntry.provenance` (drop `\| None = None`, `:365`); `AnnotationMode` **(new)** StrEnum; `GoldenManifest.annotation_mode` **(new)**; `GoldenManifest._boxes_cover_face_count` **(new, manifest-level)**; `LabelLineage` **(new)** model; `SUPPORTED_MANIFEST_VERSION` 2→3 (`:34`); retire `_face_count_covers_labeled` (`:386`); `load_legacy_manifest` **(new)** read-only v2 reader for audit arms |
| backend | `scripts/eval_harness/strata.py` | delete `MIN_STRATUM_POOL = 5` (`:78`); `derive_stratum_floor(delta, p_d, deff, k)` **(new)**; `wilson_half_width(k, n)` **(new)** |
| backend | `scripts/eval_harness/face_metrics.py` | `subject_level_rollup` **(new)**; `mcnemar_exact` **(new)**; `deff_adjust` **(new)**; `nonmated_reject_rate` **(new, [EVAL-18])**; `fuse_occasion_template` **(new)** — fusion contract bound here (GF-15): quality-gate then aggregate **all retained** observations of an occasion [EMB-07], robust aggregation so one identity-void frame cannot move the template [EMB-02], and **equal weight per occasion** when pooling occasions into a subject template so capture rate cannot stand in for evidence [EMB-10]; `subject_level_rollup` derives its subject key as the manifest roster `identity_id` on each face row (PA-07); guard `detection_pr` (`:151`) against `roster_only` |
| backend | `scripts/eval_harness/draft_labels.py` | `export_blind_queue` **(new)**; `join_agreement_report` **(new)**; `inject_gold_items` **(new, [HITL-03])**. Existing file has only `normalize_rel_path` (`:21`) and `generate_draft_manifest` (`:30`) — neither can do this today |
| tooling | `scripts/eval_harness/corpus_inventory.py` | `merge_manifest_pools` **(new)** — existing `inventory_dir` (`:213`) / `dedupe_by_sha256` (`:222`) are filesystem-only and cannot merge manifests |
| tooling | `scripts/eval_harness/cli.py` | `export-blind-queue` **(new subcommand)**; `bias-audit` **(new subcommand)** |
| tests | `scripts/eval_harness/tests/test_manifest_invariants.py` **(new)** | provenance-required, annotation-mode, coverage, lineage — each with a paired failing case **[TEST-15]** |
| tests | `scripts/eval_harness/tests/test_blind_queue.py` **(new)** | queue payload carries no detection/cluster/name field; gold items indistinguishable from real items |
| tests | `scripts/eval_harness/tests/test_power_sizing.py` **(new)** | `derive_stratum_floor` and `wilson_half_width` against hand-computed values |
| tests | `scripts/eval_harness/tests/test_bias_audit.py` **(new)** | 6-arm decomposition arithmetic; the five deltas cannot be silently merged, and each is asserted to differ from its comparator in exactly one factor |
| docs | `benchmarks/plans/fir-11-sizing-note.md` **(new)** | measured ρ, σ, m, declared δ, derived per-stratum n, ceiling arithmetic |
| manifests | `benchmarks/manifests/golden-v2-<YYYYMMDD>.json` **(new)** | the re-labeled gate manifest |
| manifests | `benchmarks/manifests/corpus-manifest-v3.json` | schema disposition recorded before Slice 2: legacy-loader input, or v3-schema with `GoldenEntry.named_face_count` / `detected_face_count` **(new)** added to `manifest.py` and defined in Terminology |
| manifests | `benchmarks/manifests/golden-v2-eval-split-<YYYYMMDD>.json` **(new)** | the **sealed eval split** (QA v8 T-08), committed by hash |

## Related Files

| File | Note |
| --- | --- |
| `benchmarks/manifests/golden150-draft-20260723.json` | **frozen read-only** at Slice 2. Never loaded by the gate CLI again. Old numbers come from the committed QA report; audit arms use `load_legacy_manifest`. |
| `benchmarks/manifests/corpus646-interleave-manifest-20260716.json` | description-eval fields stay valid; FR fields superseded; retagged `roster_only` |
| `docs/tasks/fir/FIR-9-workbench-curation-atlas-task-plan.md` | owns the curation UI; blind mode is a hard dependency for Slice 3 |
| `benchmarks/manifests/corpus-manifest-v3.json` | **superseding input**, 2026-07-28. Sole source of this plan's population, strata and probe counts. Carries `named_face_count` / `detected_face_count`, which `manifest.py` does not model. Schema disposition decided before Slice 2 — see Consumer Inventory. **Freeze it by hash as a Slice 1 precondition.** It is "sole source" for every figure in Problem Statement §3, the Measurement Contract's `m`, and the Slice 0 ceiling — yet it is produced by an unsequenced manifest-rebuild umbrella outside this plan's slices and is not pinned anywhere. An unpinned sole source means a rebuild silently re-derives the population under a plan already reviewed against the old one. Record the sha256 in the sizing note next to each figure it supplies; a hash change forces a re-derivation pass, not a merge. |
| `docs/tasks/fir/FIR-7-occlusion-adapters-task-plan.md` | downstream gate consumer of `golden150-draft-20260723.json`. Ordering and evidence-tier ceiling fixed in the Consumer Inventory. |

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

The arithmetic, using the Measurement Contract's declared values and DEFF at ρ=0.9 (recomputed in Slice 4 once ρ is measured):

| Step | Value |
| --- | --- |
| Connor requirement, δ=10pp at p_d=0.20 | 157 discordant-informative probes per stratum |
| IU inflation for k=7 at joint 80% power | × 1.86 → **292** |
| DEFF at m=3.3, ρ=0.9 <span>(occasion-level, the Contract's `DEFF` — **not** `C_identity`)</span> | × 3.1 → **~905 raw named probes per stratum**. This requirement is **unchanged** by the corpus-v3 re-derivation: v3 corrected the *supply* side of this table, not the demand side. It moves only when `m` is re-measured after Slice 2 |
| × 7 strata | **~6,300 raw named probes** |
| golden150 has today (post fail-closed drop of unprovenanced + celeb/fixture) | **160** |
| …after adjudicating the 113 signature-family entries (worst case, all dropped; PR-35 census, re-derived at Slice 1) | **37** — see Slice 1. *(Rev 2's 123 was derived from the undercounted 36-entry scope.)* |
| golden150 ∪ corpus646, optimistic, before dedup of shared identities | **732** *images* (`150 + 646 − 64` shared sha256; rev 2 said "~700"). In this table's own unit — **raw named probes** — corpus646 contributes **111** from its 96 hand-tagged images (max hard stratum: profile 50; sunglasses 13, masked 5) and **473** from the 550 untagged, which land in no stratum without new tagging. **584 named probes total, not 646** |

Shortfall: **~9× on the merged pool, ~39× on golden150 as-is, up to ~170× after signature-family adjudication in the all-drop worst case (~51× under the retired 36-entry scope).** Re-labeling changes none of these numbers — it mints no new occasions, no new hard-condition captures, no new multi-shot identities, and no `similar_people` pairs (that stratum has zero members and no amount of re-boxing invents lookalikes).

Changes:

- Write `benchmarks/plans/fir-11-sizing-note.md` with the table above, marked provisional pending Slice 4's measured ρ.
- Record a handoff decision stating that Slices 1–5 deliver a **bias-bounded, under-powered** measurement and **do not** constitute a ship gate.

Proof:

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
- **Mis-attested provenance is the larger defect (measured), and the two-regex figure understates it ~3× (PR-35).** The narrow Instagram-CDN signature (`handle_<9+digits>_<9+digits>_<9+digits>_n.jpg`, `handle__<15+digits>.jpg`) returns 33 hits among the 144 provenanced entries, all tagged `operator/mock_entity` — 36 of 150 entries with the 3 scraped unprovenanced ones. But the **full social-CDN signature family** (census recorded in finding FIR-11-PR-35; stem-matched, camera-roll prefixes `IMG|DSC|PXL|Screen[- ]?Shot` excluded first: (A) `\d{6,}_\d{5,}[^/]*_(n|o)(-\d+)?$`, (B) `(^|[_-])\d{15,}$`, (C) `^highlights[_-]\d{10,}`, (D) `^vsco[0-9a-f]{10,}`, (E) `^[A-Za-z0-9_-]{15}$` bare IG shortcodes) matches **113 of 150 entries (75%), 130 of 167 named probes (78%), 44 of 53 identities — 31 of which exist *only* on CDN-shaped entries**; 110 of the 113 are tagged `operator/mock_entity`, 3 are unprovenanced. The manifest is not present in this checkout, so these census figures are adopted from the PR-35 finding and **re-derived at Slice 1 against the frozen manifest hash before adjudication begins** — the census method above is the specification. The sampling-frame disclosure in the Slice 5 report is stated against 113/150, not 36/150. Two defects compound: `source=operator` is a false attestation for material the operator did not capture, and `license=mock_entity` is a **category error** — `mock_entity` denotes a fabricated identity, while these are real people's posts, so the tag asserts the opposite of the truth. A missing key fails closed; a wrong key passes. Per **[AUDIT-11]** / **[PROV-05]**, mis-attestation is more dangerous than absence.
- **Adjudicate all 113 signature-family entries before dropping anything.** Operator reviews each individually (own repost vs third-party), re-tags survivors with a truthful `source`/`license` pair, drops the rest. `mock_entity` is never a valid tag for a real third-party subject. *(Rev 2 scoped this adjudication to 36 entries — the two-regex subset; that scope was ~3× too small.)*
- **Consequence: the drop is no longer free, and the worst case is severe.** If every signature-family entry goes, the surviving corpus is **37 entries / 37 named probes / 22 identities**, with strata profile 10, blur 9, low_res 8, occlusion_other 7, sunglasses 1, masked 1 (PR-35 census; re-derived at Slice 1). The rev-2 worst case of 104 entries / 123 probes / 44 identities was derived from the undercounted 36 and is retired. The Slice 0 ceiling shortfall on golden150 alone worsens from ~39× to **~170×** in the all-drop case (~6,300 required vs 37 surviving probes). Adjudication will likely keep genuine own-repost entries, so the realized pool lands between 37 and 137 — Slice 0's table is re-derived from post-adjudication counts, never assumed.
- Add a loader-level filename-heuristic warning so the pattern cannot silently re-enter — the warning **implements the full signature family above, not the two-regex subset**, or the pattern re-enters through the bare-shortcode form (PR-35). Carry the sampling-frame disclosure in the Slice 5 report **[AUDIT-07]**.
- Disposition the 7 `celeb/fixture` entries explicitly. They carry 7 named probes across 5 identities (Anne Hathaway, Ariana Grande, Arnold Schwarzenegger, Audrey Hepburn, Bob Dylan) appearing **nowhere else** in the corpus, each noted `identity from filename, confirmed present; upstream license unverified`. Recommendation: **drop** — filename-derived identity is not attested labeling, and 5 singleton identities add ~0 power. Post-drop: 137 entries / 160 named probes / 48 identities; strata become profile 49, low_res 25, blur 25, occlusion_other 17, sunglasses 13, masked 5.

Proof:

- Negative test: a fixture entry with no `provenance` key raises `ManifestError`.
- Loading `golden150-draft-20260723.json` unmodified under the v3 loader fails, naming all 6 paths.

### Slice 2: Annotation mode, coverage invariant, label lineage *(contract hygiene — buys no power)*

**Goal**: A roster-only manifest can never score detection; every label states its own provenance.

Changes:

- Add `AnnotationMode` StrEnum (`exhaustive` | `roster_only`) as a **required** `GoldenManifest` field; bump `SUPPORTED_MANIFEST_VERSION` to 3.
- Move the coverage check **to `GoldenManifest`** (not `GoldenEntry`) since the mode is manifest-level: `len(face_boxes) == face_count` under `exhaustive`, `len(face_boxes) <= face_count` under `roster_only`. Retire `_face_count_covers_labeled` (`manifest.py:386`) — the new manifest-level check **replaces** it outright, it does not compose with it. Every coverage/mode/lineage failure raises `ManifestError` carrying a named invariant, the entry index, and the entry path (GF-21), so a junior implementer has an error taxonomy rather than a boolean.
- Adopt the `face_count` definition from Terminology and assert it in the loader docstring; the old ambiguity is what let corpus646 pass with 74 boxes on frames holding 189 faces. **`face_count` is recorded by the operator as a separate count-first step before any box is drawn, and is never derived from `len(face_boxes)`** — a derived count makes the coverage invariant unfalsifiable (GF-11). The invariant then compares two independently produced numbers. Declared limitation (GF-12): equality proves the operator's count matches the operator's own boxes, i.e. internal consistency; exhaustiveness *in the world* is checked only by Slice 3's independent exhaustiveness audit [AUDIT-04], never by this invariant.
- Add `LabelLineage` per box: `labeler_id`, `batch_id` (labeling-session identifier, so a contaminated or rushed session can be filtered and disagreement partitioned by batch — GF-13), `pass_index`, `labeled_at`, `tool_version`, `saw_machine_proposals: bool`, `decision: named|stranger|inconclusive`, `arbitration_of: list[label_id] | None`. Per **[AUDIT-11]** / **[PROV-05]**, a label without lineage cannot be audited.
- `detection_pr` (`face_metrics.py:151`) raises against a `roster_only` manifest rather than silently reporting inflated false positives.
- Retag `corpus646-interleave-manifest-20260716.json` as `roster_only`, **after** grepping and fixing the description-eval consumers listed in the Consumer Inventory.
- **Draw and freeze the sealed eval split (QA v8 T-08).** Emit `benchmarks/manifests/golden-v2-eval-split-<YYYYMMDD>.json` — an identity-disjoint held-out split over the post-remediation corpus, committed by hash, drawn **before any stratum curation or selection decision runs** [EVAL-07] [MLDATA-09] [EVAL-10].
- **The split's identity-disjointness is provisional, and the artifact says so.** Drawing it here means drawing it on the *pre-audit* identity partition — the buffalo-derived merge-only partition this plan exists because it distrusts. If Slice 3's blind pass splits a merged identity or merges two, the disjointness guarantee is void: the same person can land on both sides under two ids. Timing is nonetheless forced — VLM-6 is curating live at `:10018` with no split frozen, and drawing after Slice 3 leaves it unprotected for the whole audit. So: draw now, and (a) stamp the artifact `partition_provenance: "pre-audit, buffalo-derived merge-only"` with `disjointness: provisional`; (b) make **re-validation against the Slice 3 arbitration output a Slice 5 precondition** — any identity whose membership changed forces a re-draw and voids every selection made against the old split; (c) VLM-6 consumes it knowing it may be re-drawn once. A provisional split that is labeled provisional is usable; one that is silently trusted is the circularity defect again, one level up. **"Sealed eval split" is a distinct term** from this plan's five other uses of "sealed", which all mean the proposal-reveal sense (machine proposals revealed only after the audit subsample is sealed). The two must not be conflated. VLM-6 is the live downstream consumer and is currently curating with no split frozen; its plan now carries a blocking pointer back here.
- **Resolve the version-bump contradiction (GF-10):** golden150 is frozen read-only. The v3 gate loader rejects it by design. A separate `load_legacy_manifest` reads v2 for the Slice 3 bias-audit arms only; it is not reachable from `cli.py` gate commands, and a test asserts that.

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

- **Define the occasion key over existing pixels first (PA-04)** — the store has no capture or session column, so "within-occasion ρ" is not queryable until a grouping exists. Step order: (1) build a **provisional occasion key** by EXIF capture-timestamp bucketing plus source-directory clustering over the existing images; (2) where neither recovers a grouping, fall back to **identity-as-PSU**, with the bias direction stated in the sizing note: identity clusters pool multiple occasions, so identity-level ICC *understates* within-occasion ρ while identity-level m *overstates* occasion m — the two biases do not cancel, so the note carries the DEFF under both readings as a bracket, not a point. (3) The provisional ρ is superseded by a re-measurement on the operator-assigned `capture_session_id` once Slice 3's lineage exists; the Terminology definition (`(identity_id, capture_session_id)`, assigned at labeling time) describes that *final* key, not this provisional one.
- Query the existing embedding store for (a) within-occasion correlation ρ (per the provisional key above) and (b) HARD genuine/impostor score σ. Use the spherical/vMF estimator `σ̂ = √(d / (N·R̄²))` for unit vectors, not bare Euclidean `σ/√n`.
- **Read `d` from the store; never write it into the plan.** `PGVECTOR_DIM` is the sole dimension root (`db/settings.py:213 _resolve_pgvector_dimension`, default **512**; `recognition/config/settings.py:80` binds the recognition setting to it and deliberately ignores `RECOGNITION_EMBEDDING_DIMENSION` so no second root exists). At the current default the null reference is uniform cosine SD on S⁵¹¹ = `1/√512 ≈ 0.0442`. *(Rev 2 wrote `1/√128 ≈ 0.0884` — an SFace-era 128-D figure. It is **2× too large** against a buffalo_l/512-D store, and since this null scale sets what counts as a detectable ρ it propagates straight into Slice 3's sample size. Corrected here.)* A 128-D store is legal — the knob is configurable — so the deliverable records the value it read rather than either literal.
- **Stamp the store before trusting it [PROV-05].** The sizing note records, for the queried store: `PGVECTOR_DIM`, embedder model + weights id, OpenCV major, and the align/preprocess path that produced the vectors. Vectors written **before CVUP-1** (OpenCV 4.x) are not interchangeable with 5.x vectors — that incomparability is exactly why FIR-7 is blocked (Consumer Inventory §2) — so a mixed-toolchain store is re-embedded or the arms it feeds are declared pre-CVUP-1. An unstamped ρ is not a measured ρ.
- Measure **m** (mean named probes per occasion) directly under the provisional occasion key, since DEFF depends on it; re-measure both m and ρ on the operator-assigned `capture_session_id` once Slice 3's lineage exists. *(Rev 2 said the key "now exists from Slice 2's lineage" — wrong: lineage fields are schema added in Slice 2, but values land only when Slice 3 labels, which this slice precedes. PA-04.)*
- Recompute DEFF = `1 + (m − 1)·ρ` and re-derive the Slice 0 ceiling table with measured values.
- Sizing references, all cross-checked: exact-binomial McNemar discordant pairs at α=.05 two-sided, 80% power — p₁=0.60 → 199; 0.65 → 90; 0.67 → 67; 0.70 → 49; 0.75 → 30; 0.80 → 20. Connor normal approximation `N = 7.849·p_d/δ²` — δ=5pp at p_d=.15 → 471; δ=10pp at .20 → 157; δ=15pp at .25 → 88. The two tables cross-walk via `p₁ = (p_d + δ) / (2·p_d)`.
- Keep per-test α = 0.05; raise per-stratum power to `0.80^(1/7) = 0.969`. Do **not** Bonferroni-split α for an IU gate. The 1.86× inflation quoted in the Contract is normal-theory for continuous endpoints; **this slice re-derives the exact inflation under the McNemar/Connor discordant-pair sizing actually used** and records it in the sizing note (GF-09), noting also that `0.80^(1/7)` is a conservative lower-bound allocation because the strata share subjects.
- Replace `MIN_STRATUM_POOL = 5` with `derive_stratum_floor(...)` and surface each stratum's Wilson half-width in the report, labeled *conditional on this pool* per **[AUDIT-08]**.
- **Gate:** Slice 3 bulk labeling does not start until this slice's numbers are recorded. Slice 4's output sets Slice 3's sample size.

Proof:

- `benchmarks/plans/fir-11-sizing-note.md` updated with measured ρ, σ, m, chosen δ, derived per-stratum n, and the corrected ceiling.
- `test_power_sizing.py` reproduces the McNemar and Connor rows against hand-computed values.
- Test: a stratum below the derived floor is reported as under-powered, never silently rolled up.

### Slice 3: VoI-sized double-labeled bias audit *(replaces the full-pool re-label)*

**Goal**: A defensible **bound** on how much of buffalo's reported advantage is ground-truth circularity — at a fraction of the cost of relabeling 732 images that still would not gate.

Design:

- **Sample, don't sweep — but check that there is anything left to sample.** Stratified subsample of the golden150 pool sized to estimate the per-image label-disagreement rate to ±10pp at p≈0.2 — roughly 70 images unstratified, ~120–150 stratified across the 7 strata. Slice 4 fixes the exact n.
- **The pool this draws from is not 150.** Slice 1's dispositions run first: post-celeb-drop the pool is **137**; signature-family adjudication (PR-35 scope, 113 entries reviewed) takes it anywhere down to **37** in the all-drop worst case. Against any point in that range, the stratified figure above is `n ≥ N` — the "subsample" is a **census** of the surviving pool, or larger than it. Two consequences the plan must own rather than paper over: (a) the sampling design collapses, so the ±10pp precision claim is replaced by a finite-population statement over the whole pool and the FPC is applied, not omitted; (b) whichever point in 37–137 Slice 1 lands on becomes the labeling workload, and Slice 4 sizes *strata within it*, not a draw from it. If Slice 4's derived n still exceeds the surviving pool, that is the answer — label the pool, and record that the audit is pool-limited, not precision-limited.
- **The effort comparison was against the wrong denominator.** Rev 2 billed this as "≈ 1–2 h, versus 6–12 h for the full pool". The 6–12 h figure is the Cost Model's *rejected* full-**732** blind re-label (golden150 ∪ corpus646) — a pool Slice 3 never touches under any sizing. The honest comparison is against the surviving golden150 pool: at 30–60 s/image × 2 passes + ~15% arbitration, **37 images ≈ 0.7–1.5 h**, **104 ≈ 2–4 h**, **137 ≈ 2.5–5 h**, which is what the Cost Model books. The saving over rev 1 is real but it comes from *dropping corpus646 from scope*, not from sampling — do not sell a scope reduction as a sampling efficiency.
- **Blind means blind (GF-02).** The operator who performed the original merge-only adjudication has already seen buffalo's partition; UI suppression does not undo that. Mitigations, in preference order: (1) a **second labeler** who never saw the original adjudication does the de-novo pass; (2) if only one labeler is available, the pass is **renamed in every artifact from "blind de-novo" to "independent re-pass, not blind"** — the labeler has seen buffalo's partition and UI suppression does not erase memory, so residual anchoring toward buffalo's joins biases the measured disagreement *downward* — and the bias bound is reported as a **lower** bound with that mechanism stated in the report. Machine proposals are revealed **only after the whole audit subsample is sealed**, never per-image.
- **Gold QC [HITL-03].** `inject_gold_items` seeds independently arbitrated known-answer items, unannounced, at ~10% of the queue. Per-labeler accuracy on gold is the **measured human error rate** the Measurement Contract requires **[HITL-09]**. Agreement between labelers alone does not certify correctness.
- **Second pass + arbitration.** Every audit image is labeled twice, independently. Disagreements go to an arbitration pass recorded with `arbitration_of`. Inter-labeler agreement is reported, not assumed.
- **Inconclusive channel.** Labelers can decline. `decision: "inconclusive"` is excluded from the identification denominator and reported as a rate. Forcing a binary choice manufactures label noise.
- **Independent exhaustiveness audit [AUDIT-04].** A third pass on a small sub-subsample checks for faces *both* labelers missed. Without it, the exhaustive claim is verified only on labeler-positive items — the same defect as the original corpus, one level up.
- Queue record schema (PA-02), stated so Slice 3 is implementable from the text: each exported item carries `media_id`, `image_path`, `sha256`, and `queue_position` only; each committed label record carries the box geometry, `decision`, the operator-recorded `face_count`, and the full `LabelLineage` block. No detection, cluster, name, count-hint, or prior-tag field may appear in the export — that absence is what `test_blind_queue.py` schema-asserts.
- Existing-code reality: `merge_manifest_pools`, `export_blind_queue`, `join_agreement_report`, `inject_gold_items` are all **new**. `draft_labels.py` holds only `normalize_rel_path` and `generate_draft_manifest`; `corpus_inventory.py` is filesystem-only.
- **Dependency:** FIR-9 blind mode in the curation atlas is the primary labeling surface. **Headless fallback (PA-11), so this slice is not hard-blocked on frontend delivery:** `export-blind-queue` emits the queue as JSON; the labeler works from rendered images plus a file-based commit of one queue-record per image; `join_agreement_report` consumes the same records. Degraded ergonomics, identical blindness and lineage guarantees — the fallback queue payload passes the same `test_blind_queue.py` schema assertions.

Proof:

- Blind-queue export contains no detection, cluster, name, or count field (schema-asserted in `test_blind_queue.py`).
- Gold items are indistinguishable from real items in the exported payload (asserted).
- Measured per-labeler gold accuracy and inter-labeler agreement are recorded in the sizing note.
- The bias bound is stated with its direction (lower bound if single-labeler) and its interval.

### Slice 5: Re-baseline with 6-arm decomposition and an under-powered banner

**Goal**: A buffalo_l baseline on non-circular labels, with the confound decomposed rather than papered over.

The rev-1 plan proposed publishing a single old-vs-new `Δfalse_split` as "the measurement of prior circularity". That delta simultaneously absorbs a labeling-procedure change, a manifest-schema change, a scoring-code change (subject-level + DEFF), a corpus-size change from the fail-closed drop, and a metric-definition change. It measures none of them. Replaced by:

| Arm | Pixels | Labels | Scoring code | Toolchain | Isolates |
| --- | --- | --- | --- | --- | --- |
| **A1** | golden150 (full) | original (merge-only) | original | **OpenCV 4.x (pre-CVUP-1)** | published baseline — read from the committed QA report, **not** recomputed |
| **A1″** | golden150 (full) | original | original | 5.x | **toolchain change** (everything else held against A1) |
| **A1′** | golden150 audit subsample | original | original | 5.x | **pool composition** (everything else held against A1″) |
| **A2** | golden150 audit subsample | new blind labels | original | 5.x | **labeling regime** (procedure + coverage + box geometry, bundled — see below) |
| **A3** | golden150 audit subsample | original | new (subject-level, DEFF, exact McNemar) | 5.x | **scoring change** |
| **A4** | golden150 audit subsample | new blind labels | new | 5.x | the new baseline |

Deltas, each taken against the arm that differs in exactly one factor:

- `A1″ − A1` = **toolchain**. *(Rev 2 had no such arm. A1 is a pre-CVUP-1 measurement and every other arm runs post-CVUP-1, so without A1″ the OpenCV 4→5 embedding shift is silently absorbed into whichever delta is taken against A1. That is precisely the incomparability this plan invokes to block FIR-7's baseline — Consumer Inventory §2 — and it cannot be an argument there and an oversight here.)*
- `A1′ − A1″` = **pool composition**. *(Rev 2 read `A2 − A1` as the circularity estimate, but A1's pixels are the full pool and A2's are the audit subsample, so that difference confounds the label-procedure change with the change of frame — and after Slice 1's dispositions the two frames differ by construction, not by rounding.)*
- **`A2 − A1′` is the labeling-regime effect, and that is the only claim published for it (GF-03).** "Labels" is itself a bundle: the blind pass changes labeling procedure, annotation mode/coverage, and box geometry+source together, and the arm design cannot separate those three. Two consequences, stated in the report verbatim: (a) `A2 − A1′` is published as the **combined labeling-regime effect**, never as "the circularity measurement"; (b) because the single-labeler case leaves residual operator anchoring toward buffalo's partition inside A2's labels, the labeling-regime effect is itself a **lower bound** on what fully independent labels would show. Circularity proper is bounded, not identified, and the bound's direction follows the Slice 3 labeler configuration.
- `A3 − A1′` is the accounting change.
- `A4` is the number to carry forward.

Arms A1′, A1″ and A3 read old labels through `load_legacy_manifest`. Adding two arms costs essentially nothing: Slice 5 compute is buffalo_l on CPU at **< $1 total** (Cost Model), and A1″/A1′ add no labeling. `test_bias_audit.py` asserts the five deltas cannot be collapsed, not just that A2−A1 is reported separately.

Changes:

- `make bakeoff-face EVAL_ARGS="--manifest <golden-v2> --leg buffalo"` on CPU, then `make bakeoff-face-score`.
- Report carries: per-stratum n, Wilson half-width labeled *conditional on this pool*, DEFF-corrected intervals, exact McNemar for paired comparisons, subject-level rollups, non-mated reject rate **[EVAL-18]**, per-stratum FMR/FNMR **[CAL-01]**, and the measured human-labeling error rate.
- Every stratum table carries a banner: **"under-powered for δ=10pp — descriptive only, not a ship gate"**, with a link to the sizing note.
- End-to-end metrics are computed on detector-supplied inputs, not ground-truth crops **[EVAL-16]**.
- Cost recorded per standing reporting rule **[COST-04]** — see Cost Model below.

Proof:

- New report supersedes `fir-embeddings-dims-detectors-qa-20260723.html`, carrying the 6-arm table and all five deltas.
- `test_bias_audit.py` asserts the arms cannot be silently collapsed into one delta, and that no delta is taken between two arms differing in more than one factor.
- `score-face --check-determinism` passes as a CI gate. Determinism contract for the new statistics (PA-12): grouping iterates over **sorted** subject/stratum keys, reductions run in fixed key order, and `single_linkage_labels` tie-breaks are explicit (lowest media_id wins), so DEFF, variance, and rollup outputs are bit-stable across runs.
- `make check-remote` green at the merge SHA.

### Slice 6: Occasion-structured successor corpus — specification (Product B)

**Goal**: Specify the corpus that *can* clear the gate. Promoted from rev 1's Stretch Goals, where it was the only adequate design in the document.

Changes:

- Capture spec sized from Slice 4's measured ρ: target ~60–80 identities × 8–12 **independent occasions** each, ~2 frames per occasion, distributed across clean / profile / occluded / low-light / low-res so every one of the 7 strata reaches the derived floor.
- Populate `SliceTag.SIMILAR_PEOPLE` deliberately — recruit or select lookalike pairs. It cannot be harvested from existing pixels.
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
| Slice 3 labeling (double-labeled + arbitration) | post-Slice-1 surviving pool — **37–137** images (PR-35 adjudication range) × 2 passes × 30–60 s + ~15% arbitration. Not a draw from 150: Slice 4's derived n meets or exceeds the surviving pool, so this is a census | **0.7–5 operator-hours** |
| Slice 3 gold-item preparation | ~15 items, independently arbitrated | **0.5–1 h** |
| Schedule risk: FIR-9 blind-mode wait (GF-20) | Slice 3's primary surface is frontend-owned; idle wait is a real cost line even at $0 compute. Mitigated by the headless CLI fallback (Slice 3), which caps the wait at the fallback's ergonomic penalty | tracked in handoff; not $0 |
| Slice 5 compute (buffalo_l, CPU only) | A1.Flex ~$0.152/hr, prior full-corpus CPU runs | **< $1 total** |
| Slice 5 per-image compute cost | total ÷ images scored | reported in the artifact |
| *Rejected alternative*: full-732 blind re-label | 732 images × 30–60 s, single pass. **This is the only thing the 6–12 h figure ever costed** — it is not the comparator for Slice 3's sizing, which never touches corpus646 | **6–12 operator-hours for a corpus that still cannot gate** |
| Slice 6 capture (Product B, not executed here) | ~70 identities × ~10 occasions | scoped in Slice 6 |

---

## Consolidated Checklist

### Context and Ownership

- [ ] Every cited canon rule ID verified present in current `~/Development/heuristics-canon-research/lexicons/` at citation time (**no canon version pinned — versions are mutable, rule IDs are idempotent**); **[EVAL-19]** confirmed retired from this plan.
- [ ] FIR-9 confirmed as owner of the curation UI; blind mode registered as a hard dependency for Slice 3.
- [ ] Manifest-schema ownership and the `manifest_version` bump recorded in handoff.
- [ ] Measurement Contract reviewed and locked before any labeling or scoring work. *(Rev 3 ships the contract DRAFT-PENDING-REVIEW; the planning-review pass performs the lock.)*

### Checklist for Slice 0: Power ceiling

- [ ] Ceiling arithmetic written to `benchmarks/plans/fir-11-sizing-note.md`.
- [ ] Handoff decision recorded that Slices 1–5 are not a ship gate.
- [ ] No bulk labeling dispatched before both land.

### Checklist for Slice 1: Provenance required

- [ ] `GoldenEntry.provenance` non-optional; loader raises a named `ManifestError` listing every offending path.
- [ ] 6 unprovenanced entries dispositioned per the Slice 1 table (3 dropped as scraped, 3 assigned `operator/mock_entity`), each with a recorded rationale.
- [ ] Drop confirmed FR-gate-scoped; the 6 remain available to description eval.
- [ ] Signature-family census re-derived against the frozen manifest hash (method in Slice 1; PR-35 recorded 113/150 entries), then **all census hits adjudicated individually**; survivors re-tagged with a truthful source/license; `mock_entity` removed from every real third-party subject.
- [ ] Loader emits a filename-heuristic warning implementing the **full signature family** (not the two-regex subset) so the scrape pattern cannot silently re-enter.
- [ ] Slice 0 ceiling table re-derived from post-adjudication counts.
- [ ] 7 celeb/fixture entries dispositioned explicitly.
- [ ] The **8 v3 images carrying a named identity with zero named boxes** dispositioned — boxed in the Slice 3 pass, or the identity claim dropped. None ride into Slice 2 unresolved.
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
- [ ] **Sealed eval split (QA v8 T-08) drawn, identity-disjoint, committed by hash, timestamped before any curation-selection artifact.**
- [ ] Split artifact stamped `partition_provenance: "pre-audit, buffalo-derived merge-only"` / `disjointness: provisional`; re-validation against Slice 3 arbitration registered as a Slice 5 precondition; VLM-6 notified it may be re-drawn once.
- [ ] `corpus-manifest-v3.json` schema disposition recorded (legacy loader vs v3-schema + two new count fields).
- [ ] FIR-7 gate surfaces confirmed on the Consumer Inventory and the FIR-11-before-FIR-7-Slice-0a ordering acknowledged in both plans.

### Checklist for Slice 4: Power derivation *(precedes Slice 3 bulk work)*

- [ ] Provisional occasion key built from EXIF/source-dir evidence, or the identity-as-PSU fallback used with its bias bracket recorded (PA-04).
- [ ] ρ, σ, and m measured from the existing embedding store under that key and recorded, marked provisional pending the Slice 3 `capture_session_id` re-measurement.
- [ ] Embedding dimension **read from `PGVECTOR_DIM`** (not written into the plan) and the null cosine SD `1/√d` derived from it — 512-D ⇒ ≈ 0.0442, never the retired 128-D ≈ 0.0884.
- [ ] Store stamped: `PGVECTOR_DIM`, embedder model + weights id, OpenCV major, align/preprocess path. Pre-CVUP-1 vectors re-embedded or the arms they feed declared pre-CVUP-1.
- [ ] DEFF recomputed; Slice 0 ceiling table re-derived with measured values.
- [ ] δ=10pp, α=0.05 per test, k=7, per-test power 0.969 confirmed in the sizing note.
- [ ] `MIN_STRATUM_POOL` replaced by `derive_stratum_floor`; Wilson half-widths surfaced and labeled conditional.
- [ ] Slice 3 audit sample size set from this slice's output.

### Checklist for Slice 3: Bias audit

- [ ] Blind-queue export carries no detection, cluster, name, or count field (schema-asserted).
- [ ] Second independent labeler used, or the single-labeler limitation printed and the bound declared as a lower bound — **and, in that case, the Ship rule recorded as unsatisfiable, since it requires an upper bound.**
- [ ] Sample size reconciled against the post-Slice-1 surviving pool (37–137, PR-35 range); where n ≥ N, the audit is recorded as a pool-limited census with the FPC applied, not as a ±10pp precision claim.
- [ ] Gold items injected; per-labeler accuracy measured and recorded.
- [ ] Every audit image double-labeled; disagreements arbitrated with `arbitration_of` recorded.
- [ ] Inconclusive channel available and its rate reported.
- [ ] Independent exhaustiveness pass run on a sub-subsample.
- [ ] Machine proposals revealed only after the subsample is sealed.

### Checklist for Slice 5: Re-baseline

- [ ] All six arms computed; A1 read from the committed QA report, never recomputed; A1″ and A1′ recomputed under 5.x through `load_legacy_manifest`.
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
- [ ] A bias bound on ground-truth circularity exists, with its direction and interval stated, derived from double-labeled data with a measured human error rate.
- [ ] The old-vs-new comparison is published as a 6-arm decomposition, not a single confounded delta; toolchain (A1″−A1) and composition (A1′−A1″) are reported separately from the labeling-regime effect (A2−A1′), which is published as a bound on circularity, not as its measurement.
- [ ] Every reported per-stratum figure carries its Wilson half-width, labeled conditional on this pool; no stratum is rolled up while under-powered.
- [ ] Slice 6 specifies, with costed per-stratum targets, the corpus that would actually clear δ=10pp.
