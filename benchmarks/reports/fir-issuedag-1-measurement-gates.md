# FIR measurement gates still open (ISSUEDAG-1, 2026-09-09)

The HTML register `benchmarks/reports/fir-embeddings-dims-detectors-qa-20260723.html`
is gitignored (`/benchmarks/reports/*.html`) and uncommitted by design. This
tracked file is the clearance record for the medium findings that pointed at
that HTML. **No new measurements were taken.**

| Gate | Still true | Closes only on | Do not treat as closed by |
| --- | --- | --- | --- |
| Deployment-corpus face prevalence | 2.73 faces/image is YuNet-apparent at t=0.30, not a human count. [MLDATA-10] matching of training degradation to target statistics is unsupported until a design-based sample is counted. | Direct count on the T-04 sample (D-03 / M-01 / T-04) | Order-of-magnitude comparison to WIDER (withdrawn in v7 as a units error) |
| Named detector-corpus alternatives | CrowdHuman, COCO-WholeBody, FDDB, AFLW, MAFA, UFDD have no verified terms in-tree. "Open Images is the only viable corpus" is not substantiated. | Per-corpus licence read + lawful-substitute column (D-07 / T-11) | The evaluated-set rejection of WIDER / faces4coco / coco-faces |
| COCO licence and keypoint counts | 69.0% NC, 26.1% usable, 30,836 images, 16,513 with a person, 33,193 head-bearing instances, 48.6% keypoint coverage have no persisted script and no pinned annotation-JSON revision | Replication script + pinned revision + BY-SA policy call (D-05 / T-07). See also `openimages-occlusion-MEASUREMENTS.md`. | Open Images tables in that file (those are also unscripted: methodology-documented, no committed reproducer) |
| Per-image Open Images pixel licence | No verification pass, no attribution manifest. Google disclaims per-image warranty. Hard gate: no pixel may be trained on until this runs. | T-06 attribution manifest + capture-basis / deletion-reach / retention exits | Annotation-layer analysis (everything in the Open Images measurements file) |
| Train vs val/test `IsOccluded` mechanism | Four rivals unexcluded. Dual-label pilot unfunded. Calibration reading is not a quantitative correction. | T-15 dual-label pilot (D-06) | The operational rule that the two strata are not interchangeable (that rule still holds on the rate gap alone) |

Companion: `openimages-occlusion-MEASUREMENTS.md` § Still-open measurement gates
(COCO script gap, T-15 unfunded, COCO `v=0` unaudited).
