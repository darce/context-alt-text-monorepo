# Concrete corpus populations for the FIR development wave

Date: 2026-09-19 · Status: metadata-based review allocation; not gold labels or final experiment splits

The 646-image inventory can support a concrete annotation queue now. It cannot yet support an honest face-level occlusion or sealed-test assignment. The recorded image root in the removed `context-alt-text-monorepo-vlm-6` worktree is absent; current originals were requested from the operator. No fresh pixel review, face identification or inference was performed here.

Exact per-image membership and reasons are in the private/local [646-row CSV](../../../benchmarks/private/fir-capacity-20260919/fir-occ-population-review-draft-20260919.csv) and [full JSON](../../../benchmarks/private/fir-capacity-20260919/fir-occ-population-review-draft-20260919.json). The JSON also contains challenge-to-mate candidate lists and source hashes. [Generator](../../../benchmarks/tools/fir_corpus_population_draft_20260919.py) and [summary](../../../benchmarks/private/fir-capacity-20260919/fir-occ-population-review-summary-20260919.json) are reproducible local artifacts. They are ignored benchmark data; do not force-add them to Git or treat this draft schema as the eventual executable harness manifest.

## Population is different from experiment split

**Population/arm** asks which kind of images a result describes: a personal-library proxy, an enriched hard-case challenge, or external editorial fixtures. **Split** asks which observations may be used for fitting, calibration or final evaluation. **Gallery/probe** is a further role within an identity evaluation. One image may belong to several annotation queues, but it must not leak across a forbidden split or be counted repeatedly as independent evidence.

| Population / queue | Exact current membership | Use and limit |
| --- | --- | --- |
| Personal-library proxy frame | All **591** `bucket=personal` records, represented by **588** distinct contents | Preserve ordinary, difficult, unknown-label and zero-detection examples. This convenience collection is not proven representative of future customer uploads. |
| First probability review sample | **120** uniformly selected canonical images from the 588; IDs in CSV/JSON | Seed 20260919, without replacement; inclusion probability 120/588. A proposed annotation pilot budget, not a powered acceptance sample. Estimate only within this defined legacy frame. |
| Enriched occlusion/head challenge review | **107 personal records / 106 unique contents**: union of personal saved-caption hits and existing mask/sunglasses/other-occlusion image tags | Review the exact wearer/visible regions. Candidate evidence may be wrong; absent tag does not mean clear face. Scores stay separate from the probability arm. |
| Keyword-negative audit | **60** additional draws from **489** unique successful personal caption keyword negatives, seed 20260920 | Find occlusion that text mining missed; include old image tags missed by caption mining. Preserve its own frame and inclusion probability 60/489. |
| Caption failure audit | **87, 172, 212, 330, 584, 610** | Inspect all six. Failure is an outcome, never an exclusion from the original workload denominator. |
| Unresolved-identity audit | **111 personal records / 110 unique contents** with no recorded named identity | Determine unknown vs unlabeled known person vs no visible face. These are **not** automatically valid non-mated probes. |
| Detector-negative audit | **40 unique personal images** with zero recorded detections; **37** have the older `no_faces` flag | Inspect pixels for shared detector misses and actual no-face controls. The flags are not independent ground truth. |
| Gallery/mate review pool | **338 unique personal images** share a recorded identity with at least one challenge candidate, excluding the same content for that candidate | Review possible clear/occluded mates and capture/session independence. This is a candidate pool, not 338 approved gallery images. |
| Additional quality controls | **56 unique personal images** with profile/blur/low-resolution tags outside the challenge union | Separate pose/resolution failures from physical occlusion; stage these after the core pilot or where strata are thin. |
| Editorial research fixtures | All **55** `bucket=celebs` records | Separate research stress/reference arm; not personal-consent equivalents and not authorized training data. Do not blend their prevalence into the personal arm. |
| Historical baseline | Original **150** Golden-150 records, including 142 personal and 8 editorial | Preserve exactly for regression lineage. It overlaps other queues; it is not a fresh blind benchmark. |

The first annotation wave is the union of the 120 probability draws, 106 challenge candidates, six failures and 60 keyword-negative draws: **263 unique images**, after overlap. This is a proposed workload, not a claim that 263 is statistically sufficient. There are 19 images shared by the probability and challenge arms, and 10 shared by the probability and keyword-negative samples. Label once; retain each arm's membership and estimator. The gallery/mate, unresolved-identity and quality-control pools may add images after this wave.

## Detector-priority extension

The detector-first follow-up requires all 40 `zero_detection_audit` images alongside the original 263-image pilot, a **286-image union**. The 23 additional canonical IDs are **202, 221, 298, 300, 372, 375, 378, 379, 381, 385, 394, 395, 396, 405, 417, 450, 486, 509, 541, 548, 558, 628, 635**. Existing CSV/JSON memberships identify this queue; their original `first_annotation_wave_unique=263` field remains the reproducible base pilot, not the expanded union. Do not overwrite that historical count.

This enrichment is for failure discovery. It cannot replace full-image review of the probability sample or reveal its own deployment prevalence. Images with some detections can still contain missed faces. Human review determines true no-face controls versus detector misses. The original pixels are still needed before any such labels or results exist.

## Concrete high-priority occlusion candidates

Start with these existing image-tag positives and newly mined candidates. Every item still needs person/face-level confirmation; the labels below identify the **source of the queue**, not a new visual judgment.

- Existing mask-tagged IDs: **162, 271, 276, 512, 536**. ID 271 has zero recorded detections and must remain in the audit.
- Previously untriaged mask-caption candidates: **464, 470, 485, 593, 623, 646, 650**. All are review candidates; a caption mentioning a mask/scarf is not proof of a masked face.
- Existing sunglasses-tagged IDs: **93, 118, 128, 214, 244, 305, 323, 334, 388, 398, 414, 532, 589**.
- Previously untriaged sunglasses-caption IDs: **66, 116, 119, 160, 236, 302, 304, 310, 314, 320, 326, 331, 340, 386, 401, 449, 468, 497, 502, 508, 577, 593, 622, 623, 637**. ID 468 is a content duplicate of 93; review once.
- Personal other-occlusion tags missed by caption mining: **140, 192, 201, 256, 258, 293, 306, 387, 422, 429, 454, 504, 535, 587, 616**. Editorial IDs 21/22 remain in their separate fixture arm.
- IDs **593/623** occur in both mask and sunglasses mining channels: prioritize checking for actual combined occlusion, multiple people or a caption error. Do not automatically label them “mixed.”

Preserve three exact duplicate groups: **93↔468**, **196↔471**, **486↔488**. Use the smaller ID as canonical for this draft and retain alias provenance. Near duplicates and same-session relationships remain unresolved, so exact deduplication is only the first step.

## What can enter development, calibration, training and final test?

| Role | Assignment now | What must happen before freezing it |
| --- | --- | --- |
| Development / diagnostic evaluation | Legacy corpus, through the defined populations and review queues | Restore and hash-match pixels, validate coordinates, annotate face instances and relevant caption facts |
| Calibration | **No final membership assigned yet** | Resolve identity/session/near-duplicate components, select sufficient mated/nonmated groups, freeze the gallery and operating policy before fitting thresholds |
| Gallery vs mated probe | Candidate lists provided, no final crop/face allocation | Verify identity from authorized ground truth, distinct capture/session and actual visible support; a duplicate cannot be its own mate |
| Unknown / non-mated probes | Unresolved-identity audit candidates only | Establish that the person is outside the frozen gallery; deliberately held-out known identities can supply nonmates, while “unlabeled” alone cannot |
| New weight training | **Zero currently assigned/authorized** | Separate sufficiently diverse training cohort, purpose-specific rights, trainable implementation and independent evaluation; do not consume the only useful benchmark to train a new foundation recognizer |
| Sealed confirmatory test | **Zero of these 646 represented as a new blind test** | Acquire independent, previously unexamined identity/capture groups; lock annotations/protocol and keep them out of tuning |
| Oracle visibility subset | Select from newly verified challenge faces, not captions | Paired useful captures in clear/mask/sunglasses/mixed cells, reliable landmarks/masks and adjudication; absence of a cell triggers collection, not invented labels |

Known recorded-identity plus exact-duplicate links already connect these images into **231 components**, the largest containing **79 images**, before accounting for sessions or unknown people. Randomly assigning image rows 80/10/10 would ignore those dependencies. These component counts are a lower-bound linkage analysis from existing metadata, not proof of independent subjects.

Twenty-seven challenge candidates have no other recorded personal-image mate in this inventory. Their IDs are recorded in the JSON summary. They may support detection, visibility or description evaluation after labeling, but cannot yield a same-person verification pair without identity adjudication or new captures. The personal frame has 87 recorded identities; 72 have at least two image appearances before exact-capture/session qualification. Neither count is a completed open-set protocol.

For claim scope, distinguish **new-person generalization** from **future-photo recognition of enrolled people**. The former needs held-out identities; the latter permits shared identity with enrollment but requires held-out sessions/captures and no adaptive tuning on the final photos. The current historical collection can diagnose both, but cannot be retroactively described as unseen after repeated selection and inspection.

## Execution sequence

1. Recover originals/downscaled mirrors and join them by content hash. Verify source/downscaled coordinate transforms; existing `named_boxes` and detector boxes must not be assumed to share pixel space.
2. Human-review the 263-image base pilot plus 23 detector-priority additions (286 total) from original pixels, without detector proposals as the sole search area. Annotate all eligible faces and person attachments, not only the expected tagged face. Record nonresponse.
3. Resolve mate pools and dependency components. Freeze calibration/gallery/probe roles for the declared diagnostic experiment; keep test-specific exploration out of calibration.
4. Fill actual verified thin cells through new capture/acquisition. Count independent identities and sessions, not only rendered variants or pair combinations.
5. Draw and seal the new confirmatory population before any new-model tuning. Preserve the probability/challenge distinction and report missing evidence explicitly.

This adds concrete queues to the [corpus/metrics protocol](fir-occlusion-corpus-and-metrics-2026-09-19.md); it does not replace its face-level rubric or numerical gate ratification.
