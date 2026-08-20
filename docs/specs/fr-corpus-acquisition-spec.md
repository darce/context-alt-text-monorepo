# FR Corpus Acquisition Specification

> **Metadata**
>
> - **Date**: 2026-08-20
> - **Author**: Claude Opus 5
> - **Status**: Draft
> - **Assessment**: n/a — derived from the CORPUS-1 manifest-shape probe and a heuristics-canon validation pass
> - **Package version target**: n/a
> - **Task ref**: CORPUS-1

Corpus growth for the face-recognition and captioning benchmark is currently
specified as "more images," which is not actionable and is wrong in one of its two
halves. This spec fixes acquisition targets to numbers derived from the live
selector configuration and from named canon rules, separates the two distinct
claims the corpus is asked to support, and states explicitly which arm cannot be
solved by acquisition at all.

**Constraints:** Greenfield — no production users, no data to preserve. Source
images are private personal media; all counts and derived artifacts stay in
git-ignored `benchmarks/` per the local-only rule. The 128D in-house leg and the
512D InsightFace leg never share a score space ([EMB-01]). Acquisition is
operator-performed; this spec defines the target, not the collection mechanism.

---

## Motivating measurements

Measured from `benchmarks/manifests/corpus-manifest-v3.json` (646 entries):

| quantity | value |
|---|---|
| identities with ≥1 image | 133 |
| singletons (1 image, no mate) | 56 |
| identities with ≥2 (mate-capable) | 77 |
| mated pairs available | 3,233 (heavily skewed; one identity holds 50) |
| occlusion-tagged images | 37 (other 19 / sunglasses 13 / masked 5) |
| images with 0 detected faces | 41 |
| images with a real caption base | 150 of 646 |

Selector limits, from `recognition/application/settings/clustering.py`
(`ClusteringSettings`):

| setting | default |
|---|---|
| `max_representatives_per_cluster` | 10 |
| `pose_diversity_bonus` | 3 |
| `representative_diversity_threshold` | 0.85 |
| `pose_bucket_size` | 30.0° |

These two tables together fix the acquisition ceiling: beyond
`max_representatives_per_cluster + pose_diversity_bonus` = **13** representatives,
`RepresentativeSelector.should_add_representative` can only *replace* an existing
same-pose-bucket representative of lower quality. It can never admit new evidence.

---

## Spec Items

### CORP-001: Target 10–13 images per mate-capable identity

**Trace:** [EMB-07] fuse the retained observations; selector cap at 13
**Priority:** P0

Raise the 77 mate-capable identities from ~2–4 images to **10–13**. Below 10, the
representative set never fills and exemplar pooling has too few atoms to differ
from nearest-neighbour. Above 13, the marginal image is provably inert under the
current selector.

**Done when:** ≥60 of the 77 mate-capable identities hold ≥10 images in the
manifest, and no identity is acquired past 13 unless CORP-005 pose coverage is
still unmet.

**Non-goal:** raising the total image count as such. Total count is not the
binding quantity and must not be reported as progress against this item.

### CORP-002: Eliminate singletons or exclude them explicitly

**Trace:** [MLDATA-02] stratify the rare strata
**Priority:** P0

56 of 133 identities hold one image. A singleton contributes zero mated pairs and
cannot exercise any pooling, threshold, or maturity path. Either promote to ≥2 or
mark as gallery-only in the manifest so it is excluded from mated-pair denominators
rather than silently inflating the identity count.

**Done when:** every identity in the manifest is either ≥2 images or carries an
explicit `gallery_only: true` flag, and reported identity counts distinguish the two.

### CORP-003: Count independent captures, not frames

**Trace:** [EMB-10] weight by independent capture, not sample count
**Priority:** P0

Twelve frames from one session are one capture. Equal per-sample weighting lets
acquisition rate stand in for evidence, and the template ends up describing that
session's conditions rather than the subject.

Acquisition requires, per identity, images spanning **≥3 distinct capture
sessions**, varying at least two of: lighting, camera/device, year.

`representative_diversity_threshold = 0.85` provides partial automatic defence by
rejecting near-duplicate embeddings below the base cap, but it operates on
embedding distance — a genuinely varied burst from a single session still passes
while carrying one session's conditions. The gate does not substitute for this item.

**Done when:** the manifest carries a `capture_session_id` per entry and ≥60 of the
mate-capable identities span ≥3 distinct sessions.

### CORP-004: Grow the real-occlusion stratum

**Trace:** [EVAL-28] real-occlusion protocol for real-occlusion claims; [MLDATA-09] a filter that removes the regime under test deletes the test; [MLDATA-02] minimum stratum counts
**Priority:** P0

37 real-occluded images (19/13/5) is far below any usable stratum floor. This is
the **only** rung-1 cell on the Zeng five-rung realism ladder that the corpus holds,
and it is the cell that certifies the occlusion claim.

Target **≥90 mated occluded images**, distributed across the occluder classes rather
than concentrated in `occlusion_other`.

**Explicitly:** general images acquired under CORP-001 do **not** advance this item.
The two acquisition efforts are disjoint and must be tracked separately.

**Done when:** ≥90 occlusion-tagged images, each belonging to an identity with ≥1
non-occluded mate, with per-class counts reported (not just a total).

### CORP-005: Pose-bucket coverage per identity

**Trace:** `compute_maturity_level` requires `pose_bucket_coverage >= mature_min_pose_coverage` for MATURE
**Priority:** P1

Member count and representative count alone cannot reach MATURE; pose coverage is a
third independent gate. An identity with 13 same-angle images stays below MATURE and
its adaptive threshold never tightens.

Target **≥4 distinct 30° pose buckets** per mate-capable identity.

**Done when:** ≥60 of the mate-capable identities cover ≥4 pose buckets.

### CORP-006: Hold identity breadth constant during this acquisition

**Trace:** [EXP-23] pseudoreplication check
**Priority:** P1

Do not add new identities in the same pass as CORP-001. Depth (images per identity)
and breadth (number of identities) answer different questions; moving both at once
makes any measured delta unattributable.

**Done when:** identity count is 133 ± 0 at the close of the CORP-001 acquisition,
or any change is recorded as a separate, separately-measured pass.

### CORP-007: Label the claim the corpus supports

**Trace:** [EXP-23] set N to the independent unit that matches the claim
**Priority:** P0

Adding images per identity increases mated pairs without increasing independent
units — those stay at 77. Confidence intervals computed over mated pairs will
appear to tighten when nothing generalisable has improved.

Every metric derived from this corpus must be labelled with its claim class:

- **within-unit precision** — "does exemplar pooling beat max-pooling *for these
  identities*." Legitimately answered by dependent remeasures. This is the claim
  CORP-001 is designed to serve.
- **generalisation** — "what is our FR accuracy." Requires N = independent
  identities (77), not mated pairs (3,233). This corpus does not currently support
  it at useful precision, and growing images per identity does not change that.

**Done when:** the eval-harness report emits both denominators side by side and no
headline metric is printed without its claim class.

### CORP-008: Sequence the pooling change behind the quality gate

**Trace:** [EMB-02] robust template not raw mean; [EMB-03] use a validated quality proxy; [EMB-04] quality-gate hard-example mining
**Priority:** P0

`SimilaritySearch.find_all_matches` scores a cluster by `np.max()` over its
representatives — a single best-matching exemplar. Under max-pooling a
low-quality representative is inert: it can only fail to win. Under any
evidence-accumulating pooling (sparse-code energy, sum, weighted mean) the same
representative becomes actively harmful.

Required order:

1. Validate the enrollment quality proxy. `passes_enrollment_floors` exists
   (sharpness / embedding_norm / occlusion_severity), but [EMB-03] requires the
   proxy be *validated*, not merely present. AdaFace's recommended proxy is the
   **pre-L2-normalization** feature norm; `normalize_face_embedding` currently
   discards it, so it is not available to the gate today.
2. Grow the corpus per CORP-001..005.
3. Only then change pooling.

Growing the corpus first is safe but shows no gain under `np.max()`. Changing
pooling first, before the gate is trusted, can regress.

**Done when:** the ordering is reflected in the task plan and no pooling change
merges before a recorded validation of the quality proxy.

---

## Out of scope — cannot be solved by acquisition

**Spatial occlusion handling.** [EMB-11] names the shipped path — scaling a global
similarity by a scalar `occlusion_severity` — as its own anti-pattern. Occlusion is
spatial support, not a scalar penalty. No quantity of images closes an architectural
gap; CORP-004 supplies the cell that *measures* it.

**Synthetic occlusion as certification.** Structure-aware synthetic occlusion
(rung 3 on the Zeng ladder; cf. [EMB-16] predictable occluders as structured
classes) is the correct instrument for a **paired ablation** — it is the only way
to move occlusion while holding lighting and pose fixed. It does **not** certify
real-accessory performance ([EVAL-28]). Both cells are required; neither
substitutes for the other. If synthetic occlusion is ever used for *training*
rather than evaluation, [MLDATA-31] applies: fuse a virtual occlusion class into
the target rather than keeping the clean one-hot.

**Captioning.** 150 of 646 entries carry a caption base. The captioning harness is
bound by *captions*, not images; acquiring images does not advance it. Tracked
separately.

---

## Verification

All counts are derivable from the manifest without decoding images. The
verification script should emit, per item, the measured value and the target, and
exit non-zero on any P0 miss. It must report per-class occlusion counts and the
two denominators from CORP-007 rather than a single aggregate.

Per [MLDATA-09], hard cells (occluded, low-res, blur, the 41 zero-detection images)
are strata to be reported, never filtered out of the corpus.

---

## Canon references

Rule IDs verified present in `heuristics-canon-research/lexicons/` on 2026-08-20:
EMB-01, EMB-02, EMB-03, EMB-04, EMB-07, EMB-08, EMB-10, EMB-11, EMB-16, EMB-18,
CAL-01, EVAL-28, MLDATA-02, MLDATA-09, MLDATA-10, MLDATA-31, EXP-12, EXP-18, EXP-23.

Primary sources behind the load-bearing rows: Kim/Jain/Liu, *AdaFace* (CVPR 2022);
Zeng/Veldhuis/Spreeuwers, *A survey of face recognition techniques under occlusion*
(arXiv:2006.11366); Zhao et al., *Corrupted and Occluded Face Recognition via
Cooperative Sparse Representation* (Pattern Recognition 2016); Apple ML Research,
*Recognizing People in Photos Through Private On-Device Machine Learning*;
Reinhart, *Statistics Done Wrong*.
