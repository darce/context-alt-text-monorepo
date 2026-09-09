# Open Images occlusion measurements — reproduction record

Backs §19b/§19c/§19e of `fir-embeddings-dims-detectors-qa-20260723.html` (v5).
Written 2026-07-28 in response to an adversarial review finding that `PROVENANCE.md`
carried only aggregate flag rates and could not substantiate the single-face,
Source-stratified, or crowd-size figures the report cites.

**Status: first-party, unreplicated.** Author-run, from the shipped annotation CSVs.
No second party has rerun these counts. They are reproducible by anyone with the CSVs —
that is the claim being made, not that they have been independently confirmed.

## Reproduce

```bash
benchmarks/tools/openimages_occlusion_measure.sh [ANNOTATION_DIR]
```

Runs on the OCI VM (`acx-backend:~/data/open-images`, annotations fetched from
`storage.googleapis.com/openimages`) or from any local copy. ~10 min single-threaded,
dominated by two full passes over the 2.26 GB train CSV. Requires `awk` and `numpy`.
Bootstrap seed is fixed (`20260728`), so intervals reproduce bit-for-bit.

## Measurement caveats that changed the conclusions

1. **`IsOccluded` is tri-valued: `1` / `0` / `-1` (not annotated).** Train carries 5,644
   `-1` face boxes (0.54%); validation and test carry none. Every rate below excludes
   `-1` from the denominator. An earlier draft did not, which shifted train's rates ~0.3–0.8pp
   low and is the reason some figures here differ from the first published version.
2. **Aggregate box-area ratios are confounded by crowd composition.** Restricting to
   single-face images changes train's ratio from 1.04 to 0.927 and val/test's from
   0.76–0.79 to 0.683–0.685. The uncontrolled numbers must not be compared across splits.
3. **Single-face images carry exactly one box**, so box-level bootstrap resampling *is*
   image-level resampling. No cluster correction is needed for section [4]. It *would* be
   needed for any statistic computed over multi-face images.

## Results

### [1] Flag values over all face boxes (`/m/0dzct`)

| split | face boxes | `1` occluded | `0` | `-1` unannotated |
|---|---|---|---|---|
| validation | 5,594 | 1,737 (31.05%) | 3,857 (68.95%) | 0 |
| test | 17,008 | 5,390 (31.69%) | 11,618 (68.31%) | 0 |
| train | 1,037,710 | 518,469 (49.96%) | 513,597 (49.49%) | 5,644 (0.54%) |

Excluding `-1`, train's occlusion rate is 518,469 / 1,032,066 = **50.24%**.

Validation vs test: Δ = 0.64pp against SE(Δ) ≈ 0.71pp (binomial, treating boxes as
independent — the true SE is larger because boxes cluster within images). The two
splits are **sampling-compatible**, which is weaker than the "agree to within 0.6pp"
phrasing an earlier draft used and than `PROVENANCE.md`'s "tenth of a percent on every
flag". Both have been corrected.

### [2] Occlusion rate by crowd size (denominator excludes `-1`)

| faces/image | val boxes | val occ% | test boxes | test occ% | train boxes | train occ% |
|---|---|---|---|---|---|---|
| 1 | 2,088 | 32.6% | 6,176 | 32.0% | 143,346 | 53.9% |
| 2 | 1,128 | 34.8% | 3,238 | 33.4% | 136,803 | 51.2% |
| 3 | 561 | 30.8% | 1,884 | 32.6% | 105,849 | 48.8% |
| 4–5 | 726 | 28.8% | 2,073 | 31.6% | 166,476 | 48.5% |
| 6–10 | 656 | 29.4% | 2,215 | 30.5% | 218,390 | 48.7% |
| 11+ | 435 | 20.2% | 1,422 | 27.0% | 261,202 | 50.7% |

Occlusion rate is **flat across crowd size in every split**. Inter-face (crowd) occlusion
is therefore not what drives the flag anywhere — the regime is object occlusion and pose.
This falsifies the crowd-composition explanation for the train/val gap, and it is the one
inference in this record that a single check settles cleanly.

Split densities: train 3.13 faces/image (331,627 images / 1,037,710 boxes, **non-exhaustive
protocol**); validation 1.79 (3,124 / 5,594); test 1.83 (9,292 / 17,008). Exhaustive
val+test total 22,602 boxes — the entire trustworthy evaluation surface.

### [3] Train Source stratification (denominator excludes `-1`)

| Source | boxes | share | occ% | area ratio |
|---|---|---|---|---|
| `xclick` | 1,023,165 | 99.14% | 50.40% | 1.06 |
| `activemil` | 8,901 | 0.86% | **31.32%** | 0.97 |

**Correction to an earlier draft**, which reported 99.0% / 1.0% and an `activemil` rate of
26.2%, and concluded "neither reproduces the val/test signature, so there is no clean
sub-slice to fall back to." With the `-1` rows excluded, `activemil` reads 31.32% against
validation's 31.05% and test's 31.69% — it **does** reproduce the val/test occlusion *rate*,
near-exactly. It does not reproduce their size-discrimination signal (ratio 0.97 vs
0.683–0.685). So the corrected reading is narrower and more interesting: the rate gap is
concentrated in the `xclick` flow, but no train sub-slice reproduces *both* val/test
signatures, and `activemil` is 0.86% of train (n=8,901) — a lead worth an audit, not a
supervision set.

### [4] Composition control + bootstrap (single-face images only)

B = 4,000 percentile bootstrap, seed 20260728.

| split | n | occ% (95% CI) | mean area occ | mean area unocc | ratio (95% CI) |
|---|---|---|---|---|---|
| train | 143,346 | 53.91% [53.66, 54.17] | 0.10307 | 0.11122 | **0.927** [0.914, 0.940] |
| validation | 2,088 | 32.61% [30.60, 34.63] | 0.12400 | 0.18093 | **0.685** [0.607, 0.773] |
| test | 6,176 | 32.04% [30.88, 33.21] | 0.12405 | 0.18151 | **0.683** [0.636, 0.733] |

Size-discrimination deficit = 1 − ratio. Attenuation = deficit(split) / deficit(train):

| contrast | deficit gap (95% CI) | attenuation (95% CI) |
|---|---|---|
| train vs validation | +0.242 [+0.168, +0.307] | ×4.31 [3.80, 4.57] |
| train vs test | +0.244 [+0.207, +0.278] | ×4.33 [4.24, 4.46] |

Both attenuation intervals exclude ×1 by a wide margin, and the two contrasts agree
despite validation's n being 3× smaller. The "~4–5× weaker" magnitude **survives interval
estimation**; it was previously asserted from three point estimates, which was not
sufficient to carry it.

Note the precision asymmetry the review flagged: the binding arm is validation
(single-face n = 2,088; occluded n = 681), not train's n = 143,346. Citing train's n for a
cross-split contrast overstates the precision of the contrast.

## What these numbers do and do not establish

**Established.** Train's `IsOccluded` fires ~21pp more often than val/test's on
composition-matched single-face images, and discriminates ~4.3× less on box size, with
intervals. Crowd composition does not explain it. Train and val/test occlusion strata are
**not interchangeable** — supervising on one and evaluating on the other optimises a
quantity the benchmark does not report. That operational rule is what the program needs
and it holds on the rate gap and protocol difference alone.

**Not established.** *Why* they differ. "Differently calibrated" (same latent, shifted
threshold) is one mechanism among several that all predict this pattern:

- **Different image populations.** Train is not exhaustively annotated and is not a random
  sample of the same distribution. Scale-independent object occlusion (hands, phones, masks)
  raises prevalence at all sizes and *flattens* the size coupling — exactly the observed
  pattern. An earlier draft argued this rival could not explain the attenuated size signal
  because "harder images should sharpen the size/occlusion coupling"; that argument assumes
  hardness means small/distant faces, and is **withdrawn**.
- **Proposal-stage selection on box size**, which compresses train's size support
  (single-face mean area 0.107 vs val/test 0.163) and can flatten coupling mechanically.
- **Rubric difference** — self-occlusion and pose treated differently from object occlusion.
- **Normalized vs absolute size.** All areas here are normalized (`XMax−XMin`)×(`YMax−YMin`)
  in unit-image coordinates, a function of framing, FOV, and aspect ratio, none of which
  are stratified.

Nothing here identifies which. The mechanism is **unidentified**, and the decisive
experiment remains: exhaustively re-annotate a few hundred train images under the val/test
rubric and compare to the shipped labels. Until that runs, the calibration reading is a
*preferred hypothesis with unexcluded rivals*, not a result.

## Still-open measurement gates (ISSUEDAG-1, 2026-09-09)

Tracked companion (the HTML register is gitignored):
`benchmarks/reports/fir-issuedag-1-measurement-gates.md`.

These are not closed by this document. No new counts were taken in this pass.

**COCO licence and keypoint counts are not first-party here.** The HTML report cites
69.0% NC, 26.1% usable, 30,836 images, 16,513 with a person, 33,193 head-bearing
instances, 48.6% keypoint coverage. Unlike the Open Images figures above, those
COCO numbers have **no persisted script in this tree and no pinned annotation-JSON
revision**. Do not treat them as audited. Closing that gate needs a committed
reproducer plus a pinned COCO annotation SHA (the same auditability bar this file
already meets for Open Images).

**Train vs val/test `IsOccluded` mechanism (T-15) is unfunded and unscheduled.**
Four rivals remain unexcluded. Supervision must stay conservative (positives-only
with ignore-regions). Do not apply a quantitative calibration correction from this
record.

**COCO facial keypoint `v=0` cause distribution is unaudited** (occlusion vs
out-of-frame vs annotator skip vs protocol). `v=0` means "not labelled", not
"occluded". The usable hard-occlusion pool inside COCO cannot be sized until that
is measured. Deferred until COCO is actually proposed as an occlusion-stratum
source.
