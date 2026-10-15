# FIRBENCH-1 Scope and Operator Decisions

> **Metadata**
>
> - **Date**: 2026-10-14
> - **Task ID**: `FIRBENCH-1` · branch `feature/firbench-1`
> - **Companion**: [task plan](FIRBENCH-1-fir-benchmark-tool-task-plan.md) · [lane briefs](firbench-1/README.md)
> - **Status**: operator-delegated answers (2026-10-14), binding after plan review. Canon citations are Canon v0.26.2 row IDs.

## In scope (this wave)

Benchmark tooling only: decision contract, frames, three in-process legs, scoring, cluster diagnostics, private static report, CLI, occlusion label-queue tooling, ux-map, and the acceptance evals that say when the tool is done.

## Out of scope (this wave)

Training, detector replacement, deployments, stack mode, the description-utility rubric, labelling execution, acquisition of the confirmatory frame, confirmatory claims, any local inference.

## Operator questions of 2026-10-14

### Golden-150 after human confirmation

Human confirmation changes the wording of the audit, not its conclusion for detector or end-to-end comparisons.

- **What it upgrades.** "Circular" becomes "verification-biased, positive-dominant" (AUDIT-04). Confirmed labels are valid for precision, and for identity labels of the faces that are in GT. Stage-isolated recognition on confirmed faces is admissible as diagnostic evidence.
- **What it cannot fix.**
  - The operator confirmed buffalo's proposals: 369 of 375 GT boxes are buffalo's. A face buffalo missed entered GT only if the operator added it (6 boxes). Recall and face prevalence stay non-identified (AUDIT-04, AUDIT-06).
  - Accept/reject review of model pre-labels anchors labels to the model's priors (HAI-11).
  - Candidate detectors are penalized twice. A true face that buffalo missed counts as a candidate false positive, which biases FPPI toward buffalo as well as recall.
  - Selection of the 150 was itself buffalo-influenced.
- **Re-run the same 150?** Not as confirmatory evidence. Sealing is not retroactive, and these images already informed decisions (EXP-22, EVAL-07).
  - A cheap, useful step is the **union-delta adjudication** helper (T-14 shape). The operator, blind to source and after the T-09 written label rule, verifies only the union of non-buffalo detector proposals that are unmatched to GT. The output is a bound (TPb−TPc)/U on this frame, not population recall.
- **Different or more images?**
  - Development uses the **already designed** fir-occ pilot (2026-09-19 population allocation): 120 probability draws (p = 120/588), 106 challenge candidates, 60 keyword negatives (p = 60/489), 6 caption failures and 23 zero-detection additions, for 286 unique images. These must be labelled pixel-first, without detector overlays (AUDIT-07, HITL-03).
  - Confirmatory needs **new, previously unexamined identities and sessions** with exhaustive pixel-first labels, sized by power on independent units (identities/PSUs, not images).

**Power, for sizing the confirmatory frame.** Paired FNIR difference, McNemar-type: n = [z·√p_d + z_β·√(p_d − Δ²)]² / Δ², with discordance p_d = 0.15, power 0.80 (z_β = 0.8416), and z the two-sided z of the step: 1.96 for H1 (one-sided 0.025) and 1.645 for H2 (one-sided 0.05). The estimand is the paired ΔFNIR at the primary point. The unit is effective mated searches, n_eff, with deff already applied. Compare effective with effective only. Raw rows equal n_eff × the measured deff, computed by S1 at run time.

| Margin Δ | H1 step (z 1.96) | H2 step (z 1.645) |
| --- | --- | --- |
| 0.10 | ≈ 115 effective mated searches | ≈ 91 |
| 0.05 | ≈ 469 | ≈ 369 |

- **What the current corpus can resolve.** The tracked corpus manifest v3r (646 images) gives 231 image–identity components (largest 79 images), image-count size-weighted mean M̃ ≈ 18.2, and deff ≈ 2.72 at ICC 0.10, so n_eff ≈ 238. This is an image-level proxy. The report's M̃ = 12.925 does not reproduce from the tracked manifest, and the PSU recount on the pinned frame (S1) replaces this figure. At n_eff ≈ 238 the frame resolves Δ = 0.10 at both steps (115 and 91 required) and cannot resolve Δ = 0.05 (469 and 369 required). The H2 MDE at this n_eff is about 0.06, above δ = 0.05.
- **FPIR resolvability.** A zero-error claim needs about 3/n independent non-mated source units (the README definition). FPIR 0.01 needs ≥ 300 and 0.001 needs ≥ 3,000. The exact zero-event floor at 0.01 is about 298, so the 3/n rule is kept as the conservative floor. The current 207-probe non-mated set resolves only ≳ 0.0145 (CARD-27, EXP-12).

### Does the full report change the tool's design? Yes.

| Change | Source | Canon |
| --- | --- | --- |
| **Frame registry with admissibility tags**: diagnostic, development or confirmatory. Golden-150 is diagnostic and verification-biased, the 646 corpus is development, and only new data is confirmatory. Every number carries its frame's tag. | v8 binding sequence; 2026-09-19 allocation | AUDIT-07, EXP-22 |
| **End-to-end primary metric, with stage attribution.** Raw detections are kept. Each GT face ends as one of: missed, unaligned, embedded-wrong, rejected, or correct. Two joint-intervention arms report the gap to native: `gt_crop_redetect` (re-detection on the GT box crop) and `cached_yunet_landmark_replay` (YuNet landmarks from `landmark_cache`, because human landmarks do not exist). They apportion no localization, alignment or embedder share, and they do not finish T-01 or D-02. The estimand is the model-compatible native pipeline, not an embedder-only contrast. | T-01, D-02, FIR-15 | EVAL-16, EVAL-17 |
| **Fixed non-mated source-unit denominator.** Detector false alarms add no denominator units. A false accept they cause counts against its source unit, and a unit counts once. FPI is an integer count of false-accept units, alongside FPIR and 1:1 FMR. Additional spurious names are reported separately. | D3 | EVAL-18, EVAL-19 |
| **PSU = image–identity connected component** (plus exact-duplicate groups). deff and n_eff are shown next to every interval. | §0f, D1 | AUDIT-11, EXP-23 |
| **Query × enrolled pair cells.** Real and synthetic occlusion are reported separately, and empty cells say "collect". | corpus contract | EVAL-20, EVAL-28, CARD-32 |
| **Thresholds on identity-disjoint calibration folds**, frozen before any test read, and on matched non-mates where possible. | FIR-13 | CAL-07, CAL-04, EVAL-07 |
| **A sealed decision manifest with dated disconfirmers.** A post-data change downgrades the result to exploratory. | §0a, EXP-22 | CARD-27, CARD-08, FORE-02 |
| **Two scorer semantics fixed.** The legacy scorer uses `> τ` for non-mated and `>= τ` for mated; this is versioned before new comparisons. `CentroidDiscovery._find_best_centroid_match` initializes best similarity to 0, conflating negative-only and empty galleries; this is fixed upstream, and the bench tests distinguish the two. | FIRDV-2 S3 | CAL-02, CARD-11 |
| **Two known metric defects carried over.** `report.build_real_occlusion_pairs` copies image tags to every named box; replaced by face-instance occluder labels. `face_unknown_rejection` (0.986 = 204/207) has no mated arm; the bench always pairs it with mated FNIR. | report evidence | MLDATA-03, EVAL-18 |
| Curation atlas UMAP and FiftyOne stay diagnostic-only. | v8 | VIZ-18 |

### Jupyter notebooks?

Not as the system of record.

- **Why not.** Decisions come from a CLI that writes immutable, hashed run artifacts and a static HTML report (FLOW-01, PROV-01, EVAL-07). Notebooks carry hidden execution state. Committed outputs would embed face crops of real people, and ad-hoc cells invite test-set peeking.
- **What is allowed.** An optional v1.1 `jupytext` `.py` exploration template that reads frozen run artifacts only. It lives under `benchmarks/private/notebooks/`, its outputs are never committed, and it is never cited for a decision. The canon research journal (RSCH-19) is a lab notebook, not Jupyter; handoff decisions play that role here.

### Clustering: ML tactics and visualizations

Yes, as diagnostics computed in each model's own space, never across spaces.

- **Metrics:** pairwise and B-cubed precision/recall, false merges, fragmentation, unknown absorption, singleton/noise fraction with an explicit noise policy, insertion-order stability, and a chaining check on held-out pairs (GRPH-18, GRPH-22).
- **Graph:** mutual-kNN graph as the conservative neighbourhood (GRPH-17).
- **Dendrogram.** Linkage is explicit, average or complete on cosine distance. Ward, median and centroid assume Euclidean geometry and are refused on cosine. The cut height equals the frozen τ, and the cophenetic correlation is printed.
- **PCA explained-variance spectra per space.** This is the metric-preserving companion: effective dimensionality and anisotropy of 128-D vs 512-D. Dimensionality alone selects nothing.
- **UMAP is diagnostic only.** n_neighbors (15–30) and min_dist (0.05–0.1) are stated on the figure, with pinned seed and versions and stored coordinates. One projection is fitted per embedding set and reused across clustering configs. It is never scored or gated, and there are no distance, density or axis claims (VIZ-18, VIZ-19).
- **Quantitative companions:** intra/inter cosine histograms, norm histograms, kNN-Jaccard drift between runs, and linear CKA between runs of the same leg.

### Resolutions of the four open decisions (operator-delegated, best answer from Canon v0.26.2)

1. **D3 operating point.**
   - Primary: FNIR at **FPIR = 0.01**, end to end, so detector misses count (EVAL-16, EVAL-18, EVAL-19). The gallery is the enrolled identities from `gallery_split`, with gallery size named.
   - Non-mated population: verified zero-identity faces plus held-out identities on identity-disjoint rotating folds. "Unlabeled" alone is not non-mated. The denominator is the non-mated source units: non-mated GT faces plus one background unit per frame image.
   - τ is fit on identity-disjoint calibration folds, frozen, and tested once (CAL-07, CAL-04, EVAL-07). The selection rule is the smallest τ whose pooled calibration FPI is within ⌊fpir_target × N⌋ over the pooled calibration non-mated source units (S3 Build 3). With an empty pool, the run refuses.
   - Secondary points are FPIR 0.05 and 0.001, each flagged "unresolvable" until n_nonmated_eff ≥ 3/FPIR. An unresolvable point shows the measured FPIR with its upper confidence limit as a designed unknown (CARD-03).
   - The primary point has the same resolvability rule. If n_nonmated_eff < 3/0.01 (300) on the frame in use, the verdict is `inconclusive` with reason `primary_fpir_unresolvable`, whatever the FNIR interval says. No winner is named, and the frame is not admissible for a verdict at that point.
   - `fir-gate-contract-v1.json` `max_fpi` and `n_nonmated_declared` are written once S1 counts the frozen non-mated frame (max_fpi = ⌊0.01·n⌋), through the `firplan_d3_operating_point_<date>` decision named by FIR-13.
   - The point is revisable only before the first sealed run.
2. **Margin and alpha (CARD-27, EXP-10, EXP-19, EXP-24).**
   - **Estimand.** Primary is the paired ΔFNIR@FPIR0.01, computed as SFace − AuraFace. The unit of resampling is the PSU (image–identity component), and the reported n is n_eff. Intervals come from a paired cluster percentile bootstrap.
   - **Hypotheses and step order.** The sealed manifest fixes the order H1, then H2. The family α = 0.05 is one-sided. Holm step-down over two hypotheses gives one-sided levels 0.025 for step 1 and 0.05 for step 2, which are two-sided 95% and 90% intervals.
     - H1 (step 1): AuraFace is superior to SFace iff the 95% two-sided lower bound is > 0 and the veto guardrails hold.
     - H2 (step 2, tested only if H1 is rejected): the in-house leg named in the manifest is non-inferior to the InsightFace reference iff the 90% two-sided upper bound of (FNIR_inhouse − FNIR_IF) is < δ = 0.05 and the veto guardrails hold.
     - The H2 leg is named in the sealed manifest before the first run on the frame (default AuraFace, the H1 candidate). `decide()` refuses any other leg. The other in-house leg is reported as exploratory, with no verdict word. A leg chosen after results are inspected is exploratory only.
     - `decide()` computes no p-values and stops at the first non-rejection.
   - **Strata** are estimation-only, except where a guardrail applies.
   - **Dominant harm** is a false name, so per-cohort FPIR is a veto guardrail (FAIR-04, FAIR-01). Other veto guardrails: false names per 1k mentions, worst pair-cell FNIR, and p95 ms per face. Cost per accepted description (COST-04) is report-only until its source is wired.
   - **Before unseal**, the tool displays MDE, power and n_eff. MDE is defined in S3 Build 6 (step-level z, power 0.80, effective n_eff). When H2's MDE is above δ, H2 cannot be decided on that frame. It reports `margin_unreachable_mde_gt_delta`, never a bare inconclusive.
   - **Inconclusive.** A CI that spans the boundary yields "inconclusive", never a win. A null or unscored veto guardrail also yields "inconclusive" (`required_guardrail_unscored`).
   - **Non-confirmatory frames.** On a frame whose registry entry is not confirmatory, H2 never emits `non_inferior`. Its numbers are shown as development evidence.
3. **Real-occlusion ground truth.** Yes, glean descriptions, then have the operator label from pixels.
   - **Queue source.** Use the 2026-09-19 mined queues and the widened-lexicon rescan (handoff decision 2924):
     - mask-tagged 162, 271, 276, 512, 536, plus 7 untriaged mask captions
     - 13 sunglasses-tagged plus 25 untriaged sunglasses captions
     - 15 other-occlusion tags missed by mining
     - the 60 keyword-negative draws, keeping their inclusion probability
     - the 6 caption failures
     - exact-duplicate groups 93↔468, 196↔471 and 486↔488, labelled once
   - **Known traps** are resolved from pixels: #162 lace eye mask, #271 sleep mask on forehead, #276 gold mask on another person, #93 conflicting caption, and #593/#623 in both mask and sunglasses channels.
   - **Labels** are face-instance labels: occluder multi-label, per-region visibility, and "cannot determine". Captions are queue sources, never labels.
   - **Arms.** The probability arm (IPW) and the enriched challenge arm are reported separately. The written label rule (T-09) comes first (MLDATA-03).
   - **Quality control.** About 10% blind repeats test intra-rater consistency, with gold items (HITL-03). An edit path lets the operator add faces that no detector proposed (HAI-11).
   - **Effort, two tiers.**
     - Tier (a): occluder labels plus missed-face additions on the ~150-image occlusion queue, about 2–3 min per image, ≈ 5–8 person-h.
     - Tier (b): full pixel-exhaustive labelling per the corpus contract, at the report's T-04 rate of ≈ 8–14 min per image, ≈ 40–65 person-h for the 286 pilot.
     - Tier (a) is the first operator task.
4. **UX-map location:** `benchmarks/ux-maps/` (approved). Needs a `.gitignore` allowlist line, because `/benchmarks/*` is ignored.

### Definitions (out of scope this wave)

- **Detector replacement:** swapping or retraining the face detector (YuNet vs SCRFD vs buffalo's RetinaFace). The bench *measures* detector misses end to end. The `gt_crop_redetect` arm reports their joint gap and does not isolate localization. It does not change the detector.
- **Stack mode:** driving the deployed recognition services over their public APIs (FIR-8 `cross_stack_bench` style) instead of in-process legs. It waits on AuraFace serving stacks, which do not exist yet. v1 is in-process only, with identical bytes and identical preprocessing receipts.
- **Description-utility rubric:** a human-rated rubric for whether the alt text is useful beyond correct names (§0a guardrail, DESCQUAL-2 packets). It cannot be automated. A reserved, nullable report column only.
