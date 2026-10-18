# Occlusion corpus, metric vocabulary and research reassessment

Date: 2026-09-19 · Status: proposed protocol; no new recognition result
Companion: [development assessment](fir-development-wave-assessment-2026-09-19.md) · [implementation epic](../../epics/v0.5.0/fir-development-and-measurement-epic.md)

Keep Golden-150 as a historical diagnostic set and build a **versioned face-instance successor**, rather than overwriting its labels or preserving 150 as a statistical target. Real occlusion, unknown-person rejection and correct name placement are the target behaviors. More dimensions, more image tags and cleaner-looking clusters do not establish improvement.

## Corpus evidence and reconciliation

The September 4 v11 section of the [requested research register](../../../benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html) supersedes older counts and mechanism claims. September 19 read-only JSON inspection confirmed:

| Artifact | Observed shape | Interpretation |
| --- | --- | --- |
| `corpus-manifest-v3r-20260814.json` | 646 entries; inventory fields `named_boxes` / `detected_boxes`; no `reference_facts` | Inventory is not the eval `GoldenEntry` schema. Do not mistake absent `face_boxes` for an absence of all boxes. |
| `golden150-draft-20260723.json` | 150 entries; `face_boxes` on 145; nonempty `reference_facts` on only 1 | Cannot support general factuality scoring across 150. Existing boxes are not an independent exhaustive face audit. |
| `fir12-selection-v1.json` | 640 entries; `face_boxes` on 525; no `reference_facts` | Reuse selection lineage, not an unqualified gold claim. |
| v11 saved-description mining | 640 successes / 6 failures in its 646-image run; 95-image candidate union | Previously measured retrieval candidates, not newly verified faces. Do not recaption the entire pool. |

v11 reports 130 identities in its revised inventory, versus older 133/137-derived analyses. Recompute roster, mate availability and sampling components from the exact chosen manifest hash. Do not combine counts from v3, v3r, the converted 640 selection and Golden-150. The [CORPUS-1 spec](../../specs/fr-corpus-acquisition-spec.md) targets capture diversity and real occlusion, but its 77 mate-capable identities and acquisition quotas derive from an older frame. Preserve the mechanism; recompute the counts. Likewise, [DESCQUAL-2](../../tasks/descqual/DESCQUAL-2-fact-annotation-pilot-implementation-report.md)'s n=239 and eyewear floor n=48 are frame-specific examples, not universal acceptance sizes.

Historical detection recall 0.504 and the M-12 buffalo/SFace recovery comparison were withdrawn. Positive-only adjudication of detector proposals cannot reveal both detectors' shared misses. The later T-14 contract adds an independently exhaustive subset; retain that protection. A bound within a selected legacy slice does not become a deployment-wide claim.

## Successor corpus contract

Proposed version name: `fir-occ-v1`; annotate into a new manifest and explicit conversion layer. Store private pixels, identity maps and image-bearing reports under ignored `benchmarks/private/`; commit only schema, synthetic fixtures, protocols and non-sensitive summaries. Current ignore rules allowlist other benchmark subdirectories, so check each output path. The [source register](../../research/firwave-source-register-2026-09-19.json) records paper provenance, not private media. [Concrete population queues](fir-corpus-population-allocation-2026-09-19.md) now map all 646 records without promoting existing tags to face-level truth.

1. **Recover and join pixels.** Verify image and original-file checksums, media ID mapping, EXIF orientation, coordinate spaces and exact resize transforms. A matching media ID is not a verified pixel join. Quarantine unrecoverable images as nonresponse with reasons; do not silently replace sampled units.
2. **Allocate before optimizing.** Freeze development, calibration and evaluation groups by identity, session/event and exact/near-duplicate ancestry. A gallery and its mated probes necessarily share identity within an evaluation split, but use distinct captures. Training/calibration identities stay disjoint from evaluation identities. All synthetic descendants remain with their source group.
3. **Create two populations.** A probability-sampled deployment arm estimates operational rates; an enriched challenge arm covers hard occlusion. Publish separately, or use an explicitly designed weighting estimator. Challenge prevalence must not masquerade as deployment precision.
4. **Annotate pixels independently.** Human reviewers search entire sampled images, outside detector proposals. Retain no-face media, unknown people, ambiguous/ignore regions and missed faces. Head-only observations are person/head targets, not invented visible-face boxes. Union adjudication is an efficient diagnostic supplement, not exhaustive truth.
5. **Reuse curation candidates carefully.** Review v11's caption hits, old tags, all six failed caption items and a probability sample of keyword negatives. Log sampling probability and marginal confirmed yield by retrieval channel. Caption semantic search is an optional mining ablation; agreement between model-generated captions is not independent verification.
6. **Adjudicate face-level support.** Double-annotate a bounded pilot and disputed/hard cases; keep original annotations, adjudication and rubric versions. Use DESCQUAL-2's packet/QC primitives. Human masks are needed on a bounded oracle subset, not every image initially.
7. **Collect only verified gaps.** Obtain independent captures for thin real-mask, eyewear, mixed and lookalike cells. Newly collected, previously unexamined identities/sessions are required for a strong confirmatory improvement claim. A new split of the already repeatedly inspected legacy pool remains exploratory.

### Annotation fields

| Group | Required contents |
| --- | --- |
| Stable unit | `image_id`, image/source sha256, `person_instance_id`, `face_id`, duplicate/near-duplicate group, coordinate-space ID and transform |
| Identity | verified pseudonymous identity or explicit `unknown` / `unresolved`; gallery membership; annotation confidence and evidence source. Unknown is not missing annotation. |
| Geometry | visible face box, head/person box where available, visible vs amodal convention, face↔person association, ambiguity/ignore reason |
| Occlusion | per-face multi-label type: lower-face mask/respirator, opaque/tinted/reflective sunglasses, clear glasses, hand, phone, hair, other object, mixed; self-occlusion and out-of-frame separate |
| Anatomy | left/right eye, brows, nose, mouth, cheeks, forehead, ears: visible / occluded / self-occluded / out-of-frame / uncertain; coverage estimate only where support is defined |
| Oracle subset | landmark coordinates and visibility; mask with support convention; annotator agreement and uncertain boundaries. Predicted masks in a separate field/artifact. |
| Capture | session/event with reliability, device/resolution/pose/lighting; rights/use scope; previous benchmark use; optional consented subgroup metadata, never model-inferred demographic labels |
| Description gold | visible objects/actions/relations, eligible names and person regions, salient required facts, allowed paraphrases and unsupported-claim adjudication. Facts are not model-generated truth. |

Mandatory diagnostic pair matrix: clear→clear, clear→mask, clear→sunglasses, mask→mask, sunglasses→sunglasses, mask→sunglasses, reverse cross-condition directions when asymmetric, and mixed occlusion. Include small faces, profile/rotated heads, crops without shoulders, overlapping people, mirrors/screens/posters, shared clothing/accessories, and independent unknown lookalikes. Report counts of faces, identities, sessions and independent groups per cell; empty or underpowered cells are explicit.

### Size and confidence

Preregister gallery size, false-identification budget, worthwhile recall gain, clean-cell non-inferiority margin, primary cells and resampling unit before scoring. Current `fir-gate-contract-v1.json` leaves ratification fields null: this plan supplies **no invented accepted numeric threshold**.

For independent Bernoulli negative trials with zero errors, the one-sided 95% upper bound is `1 - 0.05**(1/n)`, approximately `3/n`. Thus approximately 3,000 independent negative trials are needed even for a zero-error claim near 10^-3, and 30,000 near 10^-4. Thousands of pairs from a few people do not meet that independence assumption. For clustered sampling, use the declared grouped/multilevel design and effective sample size; multi-person image–identity components may leave very few independent units. A 150-image development set can find defects and compare mechanisms, but cannot automatically certify a rare false-name rate.

## Normalize metric names by task

Use **recall** as the canonical label; **sensitivity** and **true-positive rate** are synonyms only for the same positive class, unit and denominator. **Precision** is a different conditional probability. Avoid the bare word “accuracy” in report headers.

| Task | Canonical metric / definition | Mandatory companion |
| --- | --- | --- |
| Face detection | Recall = matched GT faces / all eligible GT faces; precision = correct proposals / all scored proposals, with fixed IoU and one-to-one matching | FPPI = false proposals / images; matched-FPPI comparison; AP/PR as diagnostic. No meaningful general TN count over arbitrary image regions. |
| 1:1 verification | FMR = accepted impostor pairs / impostor pairs; FNMR = rejected genuine pairs / genuine pairs; TAR = 1−FNMR | TAR@FMR at frozen calibration policy; counts and intervals. EER/overall pair accuracy are diagnostic, not open-set ship gates. |
| Open-set 1:N identification | FNIR = mated probes without correct accepted mate / all mated probes; TPIR = 1−FNIR for the same protocol | FPI = integer non-mated false identifications; FPIR over a **fixed preregistered non-mated probe population**. Gallery size, own threshold, unknown coverage, wrong-ID-on-mated count. |
| Operational unknown media | Media-level false-name rate = unknown/no-face media with ≥1 incorrect emitted name / fixed unknown/no-face media | Also total false name events, so many errors in one image are visible. Never divide by an algorithm-controlled number of detected false faces. |
| ANN retrieval | Recall@k = overlap with exact same-space top-k / k | Query set, filtered gallery, k, index knobs and latency. This is index recall, not identity recall. |
| Clustering | Pairwise precision/recall and B-cubed precision/recall with declared noise policy | False merges, fragmentation per GT identity, unassigned fraction, unknown absorption, stability across insertion order. Report all-face and assigned-only denominators. |
| Published names | Name precision = correct identity **and person attachment** / all emitted name mentions; named-person coverage = correctly named eligible people / all eligible people | Wrong-name count and abstention rate; label ineligible/unknown people separately. No emitted names → precision null, coverage 0 where eligible targets exist. |
| Positional naming | Correct name/region attachments / eligible labeled person positions | Wrong attachment and abstention counts; left/right swaps cannot pass merely because the name set is correct. |
| Caption factuality | Supported claims / adjudicated emitted claims; required-fact coverage = expressed salient required facts / labeled salient facts | Unsupported-claim count/severity, empty/refused outputs, denominator coverage and blinded human preference. Unannotated facts → not evaluable. |

The existing FIR scorer counts missed detection as FNIR failure, uses `>= tau` for correct mated acceptance and `> tau` for non-mated FPI, and exposes `measured=False` when no mated probes exist. Preserve these exact boundary semantics in legacy replay; any unified comparator requires a versioned change and boundary tests. The existing `GateContract.metric` string is `FNIR@FPIR` while its operational budget is `max_fpi` plus `n_nonmated_declared`: display both, and explain their relationship rather than silently renaming stored fields. For a fixed population, an FPIR target implies an integer FPI budget; round and freeze it before calibration.

Choose each stack's threshold on calibration data, then freeze it for the test. Plot test curves as diagnostics, but do not sweep test thresholds and call the selected point a validated deployment policy. Track wrong identities on mated probes separately from unknown-probe FPI. Add image-level false-name counts for detector-originated spurious faces. The terminology agrees with [NIST 1:N evaluation](https://pages.nist.gov/frvt/html/frvt1N.html); IJB-C's detector-dependent denominator warning is retained through the canon's `janus-benchmark-c.md` source.

## Detector-first measurement and remediation

The user's follow-up identifies missed occluded faces as an observed failure upstream of clustering. Give it an explicit first quality experiment: [FIRDV-2 S3a](../../tasks/firdv/FIRDV-2-comparative-harness-and-bakeoff-task-plan.md#s3a--detector-only-occlusion-benchmark-and-localization-diagnosis), with scope SC-10. S3 already named detection recall, but an undifferentiated configuration grid was insufficient execution guidance. A face never detected cannot be recovered by changing embedding dimensions or regrouping the surviving embeddings.

Preserve the v11 qualification: the historical 0.504-versus-0.995 number was withdrawn because the reference largely consisted of buffalo detections. This does not establish that YuNet has no occlusion problem; it means the population recall gap needs independent evidence. The D-01/T-14 independently exhaustive audit remains the governing protection. Detecting the same proposal as the reference is not finding every real face.

### Independent detection truth and cohort

Review complete original images for all eligible faces, regardless of identity or gallery membership. Include unknown people, small/partial faces and shared detector misses. Freeze the face-box convention (including occluded extent where the rubric supports it), visible-support annotation, min-size/ignore rules and coordinate transform. Do not compare a detector's full-face box against a tight visible-fragment box without accounting for the annotation convention. Fully hidden faces/head-only observations have explicit head/person or ignore outcomes, not invented face truth. Double-review difficult cases and a bounded random subset; retain uncertainty and reviewer disagreement.

The original 263-image annotation union is retained as a named pilot. The detector-priority pass adds **all 40 existing zero-detection personal images**, yielding **286 distinct images** after overlap; the additional 23 IDs are in the [allocation assessment](fir-corpus-population-allocation-2026-09-19.md#detector-priority-extension). Zero detections is a mining signal, not a no-face label. Continue independent full-image review of the 120-image probability arm, because images with one detected person can still hide a missed second person. The hard/negative enrichment and editorial fixtures remain separate from deployment-rate estimation. This is a proposed labeling workload, not a powered acceptance sample; the missing-pixels dependency is unchanged.

### Detector contract and attribution

| Measurement / intervention | Frozen elements | What it establishes |
| --- | --- | --- |
| Detector-only baseline and candidate | Same human GT, image bytes, eligibility, matching convention and calibration FPPI budget | Recall/sensitivity, precision, false proposals per image, localization and missed-face distribution, independent of identities/clusters |
| Localization rescue | Same YuNet weights; bounded input-scale/tiling/threshold/NMS changes declared | Whether inexpensive inference changes recover occluded faces within false-positive and latency budgets |
| Detector challenger | Exact permitted model artifact and preprocessing; same GT and budgets | Whether another detector improves detection; landmark/alignment compatibility remains separately tested |
| Controlled downstream detector comparison | Fixed SFace, gallery, identity threshold and assignment; documented compatible alignment | Identity impact of the actual detection/localization pipeline change; if landmark generation changes, label the combined intervention |
| Reference geometry rescue | Verified boxes plus independent reference alignment only where support exists; same encoder/gallery/identity threshold | Potential recoverable localization/alignment loss; not a pure detector effect when both geometry stages change |
| Reference alignment on already matched faces | Same detected face set, boxes, encoder/gallery and threshold | Alignment effect conditional on detections; cannot estimate missed-face recall |

Direct source inspection found `face_metrics.py::detection_pr` permits count-only fallback when `matched_faces=None`. That branch uses `TP=min(pred_faces,labeled_faces)` and can credit wrong locations. The new strict comparison adapter requires one-to-one spatial assignments with IDs/IoUs and independent annotation provenance; equal counts do not prove matching. Keep historical replay intact. Existing `require_exhaustive_box_coverage` checks box-count consistency but cannot prove a human searched the whole image. Reuse these primitives with the stricter protocol rather than building a second metric system.

Report clean/mask/sunglasses/hand-object/mixed/severity cells, size/pose controls, numerator/denominator and design-appropriate uncertainty. Recall is `matched eligible GT faces / all eligible GT faces`. Precision is `matched predictions / all scored predictions`; FPPI is `unmatched scored predictions / all declared images`, including no-face images. Duplicate detections count as false proposals under the frozen one-to-one/ignore rule. No general image-region true-negative count exists to make “accuracy” informative here.

A proposed IoU 0.50 diagnostic point is explicit, not a silently adopted production gate. Report localization sensitivity and freeze the final rule before evaluation. Compare operating points selected on calibration under a common FPPI budget, then report held-out recall **and actual FPPI** without retuning to make the test meet budget. PR/AP and recall-versus-FPPI plots are diagnostic companions. Log successful empty detections separately from decode/service failures; both stay in end-to-end workload accounting, while pure-detector metrics display their coverage. Missing evidence or an incomplete run cannot qualify a candidate.

Each detector report must show original-image overlays and galleries of missed faces, false/duplicate detections and unusable landmarks, including faces absent from every model's embedding table. The first-failure ledger distinguishes localization, alignment, identity rejection/wrong match and clustering/assignment; all eligible GT faces remain traceable. Conditional-on-detection recognition scores accompany, and never replace, all-face end-to-end scores. For the same eligible person population, correct identity coverage cannot exceed the fraction detected unless the system has a separately declared non-face route.

### Decision before model-capacity claims

Run baseline → inexpensive localization rescue → exact-artifact-cleared challenger where justified. Record gain/no gain by occlusion cell, clean-face regression, FPPI and latency. If detection remains the measured limiting stage, follow the existing D-01/T-15 and FIR-7 detector/data evidence gates before a training proposal; detector training is separate from a higher-dimensional identity encoder. If detection improves but reference alignment rescues remaining failures, address alignment. Evaluate an embedder improvement on a controlled face population only after this attribution is available. A whole-pipeline buffalo reference cannot isolate the embedder by itself.

Instrument/report completion and candidate adoption are distinct. Adoption needs ratified minimum occluded-face gain, clean non-inferiority, FPPI, latency and sufficient independent evidence. Those values are presently unset; the plan must report “not qualified” instead of inventing numerical pass criteria. This gate does not delay the initial LocalWP development installation.

## OCC research: what changes the implementation choice

All **38 PDFs** in the supplied OCC directory were inventoried and text-extracted read-only. This was a targeted mechanism review, not a full replication or full-text appraisal of every paper. Deep checks covered the occlusion survey, PLGSA, OccFace, S³POT, Head Similarity, SFIQA, OCFR-2022, periocular/attribute material and CoTalk. Source hashes and read depths are in the [register](../../research/firwave-source-register-2026-09-19.json). The PDF-reading workflow was used for extraction; numerical PLGSA/S³POT cautions were already visually checked in v11 and were rechecked in extracted source text here.

| Original source / sections | Finding and limit | Phase decision |
| --- | --- | --- |
| Zeng et al., *A survey of face recognition techniques under occlusion*, §§II, IV, VII; canon `occluded-face-recognition-survey.md` | Detection/alignment precede matching; real accessory protocols differ from rectangles/noise; partial matching needs anatomical correspondence | Name the experimental branch **occlusion-aware face recognition (OAFR)**. Baseline full-face FIR does not itself become spatially occlusion-aware. Use real challenge cells plus synthetic diagnostics. |
| PLGSA, §§3.6, 5.6, 6 | Narrow predicted severity range (0.43–0.52) yields only a small threshold adjustment; limited isolated evidence for OACT. Genuine-pair acceptance/rank results do not establish ACX unknown rejection | Periocular is a lower-face-mask hypothesis. Sunglasses may remove its input. Do not transplant leniency, scores or a claimed 97.2% recovery rate. |
| OccFace, §§3.3, 4.1–4.2 | Per-point visibility is measured separately from visible/occluded landmark error; domain includes stylized human-like faces, not just ACX people | Add visibility labels and alignment diagnostics; a visibility predictor must earn a downstream identification improvement. Do not confuse low landmark error with correct identity. |
| S³POT, §4/Table 1 | Standard segmentation and per-image overfitting are different regimes; generated reference supports masks, not identity evidence | Offline annotation-assistance candidate only. Preserve oracle/predicted masks; never embed generated hidden facial texture as observed identity. |
| [Head Similarity](https://arxiv.org/abs/2605.07766), §§3, 5, 7 | Explicitly preserves appearance-state differences; R1 same identity/same appearance > R2 same identity/different appearance > R3 different identity. Weak temporal grouping and limited diversity are stated limitations | Stronger caution than a generic “head embedding” recommendation: its objective can encourage persistent-person fragmentation across hairstyle/appearance changes. Test separately as provisional association; do not replace the FIR identity space or naming gate. |
| SFIQA, abstract and benchmark/method sections | Perceptual restoration can improve appearance while harming identity fidelity; the paper separates multiple quality dimensions | A sharper restored face is not reliable identity evidence. Keep raw-vs-restored artifacts separate and measure identity preservation before a restoration branch. Do not treat a visual quality score as a recognition probability. |
| OCFR-2022, protocols and result tables | Structure-aware synthetic accessories and several enrollment/probe conditions are more informative than a single “masked” score, but still a synthetic benchmark | Adopt the condition-matrix idea; do not import its scores, pretrained weights or real-world claims without matching data/rights/protocol. |
| Periocular surveys; attribute-based periocular paper | Resolution/spectrum/capture matter; some methods explicitly exploit soft biometric attributes | Record pixel support and capture mismatch. Do not introduce inferred gender/ethnicity features into this publisher pipeline to imitate a paper's result. |
| CoTalk, abstract/method | Sequential residual annotation may improve coverage under a fixed human time budget; small study is not proof for this corpus | Pilot image-first fact collection followed by residual review. Measure minutes/image and agreement. Keep final correctness adjudication independent of candidate captions. |
| FER, gaze, rPPG and age papers in OCC | These are expression, gaze, pulse or age tasks, not identity rejection studies | Useful labeling/visibility ideas only; their accuracy does not rank FIR recognizers. |

Two errors in older planning deserve explicit rejection: an eye-region method is not a universal mask-and-sunglasses rescue, and dense SFace coordinates are not a spatial feature map. Any pixel/landmark-to-vector support map must be learned or independently validated before runtime masking. The oracle ladder must use a compatible local-feature representation; otherwise the experiment tests an invalid intervention.

## Measurement ladder and stop rules

1. Actual detection/alignment → existing SFace → exact search → frozen acceptance policy.
2. Oracle face boxes, then trusted visible landmarks, holding the embedder fixed: attribute localization vs alignment loss.
3. Compatible oracle visible-region/mask matching, then predicted-region/mask matching: measure headroom and predictor tax separately.
4. Only if oracle head regions help, test bounded person/pose head proposals against full-frame detection at matched FPPI and crop budget.
5. Freeze features and ablate conservative clustering/exemplar recovery separately. Weak bridge faces must not merge identities by transitive connectivity.
6. Freeze accepted recognition evidence before comparing VLMs; then run a combined product arm that counts all upstream failures.

Every arm reports paired deltas with grouped intervals, clean-cell regression, hard-cell coverage, wrong-name/false-merge budget, whole-request latency and cost. A CI that includes no benefit or insufficient independent units yields **inconclusive**, not a win. Segmentation quality, ranking, projection separation and cluster count are supporting diagnostics, never substitutes for fewer wrong names and more correctly described people.
