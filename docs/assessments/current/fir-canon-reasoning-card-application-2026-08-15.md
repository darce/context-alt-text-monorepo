# FIR against three uncited canon reasoning cards — Assessment (2026-08-15)

**Task**: canon corpus issue 6 · **Status**: assessment · **Canon repo**: `../../../../heuristics-canon-research`

Three cards in the engineering-heuristics canon are written about decisions the
FIR line makes, and none of the three is cited in any FIR document. This
assessment reads each card against the code and reports as they actually stand.

The headline is not that FIR ignored these cards. Two of the three were
independently rediscovered by the FIR programme, at cost, and are honoured in
substance — the transitive-licence reasoning in the FIR-1 assessment and the
pre-sealed margin in the v8 executive summary are both stronger than the card
text asks for. The value of citing them is the residual: the specific
requirements the FIR work has *not* closed are currently invisible as gaps,
because nothing in the tree states the standard they fall short of.

| Card | ID | Bears on | Verdict |
|---|---|---|---|
| [`synthetic-artifact-control-arm`](../../../../heuristics-canon-research/reasoning/synthetic-artifact-control-arm.md) | CARD-31 | `eval_harness/synthetic_occlusion.py` | **Partial** — real-occlusion arm automated; no artifact-only control arm |
| [`licence-provenance-is-transitive`](../../../../heuristics-canon-research/reasoning/licence-provenance-is-transitive.md) | CARD-26 | `face_pipeline/provenance.py`, profile default | **Partial** — closure reasoning is sound but lives in prose; the gate covers the non-default profile |
| [`margin-and-design-effect-before-the-run`](../../../../heuristics-canon-research/reasoning/margin-and-design-effect-before-the-run.md) | CARD-27 | `eval_harness/report.py` floor policy | **Partial** — margin sealing honoured; headline floor sized on raw n |

---

## 1. CARD-31 — artifact-only control for synthetic occlusion

**Claim.** A model can hit a synthetic-occlusion metric by detecting the
compositing signature rather than the occlusion, so gains need an artifact-only
control arm *and* a real-occlusion holdout.

### The trigger fires

`apply_occlusion` (`scripts/eval_harness/synthetic_occlusion.py:269`) warps a
64 px solid-fill template onto the face via `cv2.warpAffine` with
`INTER_LINEAR`, `BORDER_CONSTANT`, border value `(0,0,0)`
(`synthetic_occlusion.py:115-120`), then composites with

```python
mask = np.any(warped != 0, axis=2)
out[mask] = warped[mask]
```

The card excludes "pure hard binary paste with no alpha, resample, or blend
stage". That exclusion does **not** apply here: there is no alpha, but there is
a resample stage. Linear interpolation of a solid template against a zero border
produces a graded rim of partially-interpolated pixels at the occluder edge, and
the `!= 0` test admits them. The occluder therefore carries a resample-dependent
boundary signature whose geometry is a deterministic function of `(kind, seed,
landmarks)`.

### What is already met — requirement 3, and it is automated

The harness does not merely keep a real-occlusion holdout; it mechanises the
comparison. `build_real_occlusion_pairs` (`report.py:1273`) extracts real
occluded pairs from the run record by slice tag, the report emits synthetic and
real arms side by side per tag (`report.py:1566`), and
`synthetic_real_divergence` auto-demotes the synthetic arm when
`d = |a_s − a_r|` exceeds its threshold. This is a stronger implementation of
the card's requirement 3 than the card describes.

### What is open — requirements 1 and 2

`OCCLUSION_KINDS = ("masked", "sunglasses", "occlusion_other")`
(`synthetic_occlusion.py:54`). All three occlude. There is no identity-preserving
kind that runs the *same* operator, so no measurement separates "accuracy fell
because the face is occluded" from "accuracy fell because the composite left a
rim".

Requirements 4 (premultiplied RGBA) and 5 (hard-vs-blended ablation, automatic
mask-fidelity audit) are **not applicable**: there is no fractional alpha and no
automatic matte — the occluder is a geometric template placed from YuNet's
5-point landmarks.

### Standing mitigation, stated so the gap is not overrated

Nothing trains on these composites. The harness scores frozen weights, so the
card's central mechanism — a model learning the compositing cue because train
and synthetic-eval share the operator — cannot fire through training here. The
residual exposure is narrower and is a measurement-validity question: the
reported occlusion drop conflates occlusion with the compositing artifact, and
neither the size nor the sign of the artifact term is known.

### Cheapest close

Add a fourth kind that warps a patch of the *underlying face pixels* through the
identical path — same template geometry, same `getAffineTransform`, same
`warpAffine` flags, same `!= 0` overwrite — so the output is identity-preserving
and the only difference from the source is the operator's own rim. Any accuracy
drop on that arm is the artifact term, measured directly. It reuses
`apply_occlusion`'s existing machinery and adds no new scoring path.

---

## 2. CARD-26 — licence provenance is transitive

**Claim.** A permissive direct licence does not launder the terms of what a
package calls, embeds, or was trained on; only a machine-checked transitive
closure at the registry can refuse a ban-list hit before ship.

### The programme already reasons this way, and well

`docs/assessments/current/commercial-face-pipeline-replacement-assessment-2026-07-15.md`
§2 states the closure position explicitly — "Fine-tuning does not launder the
restriction", "ArcFace/RetinaFace are algorithms, not licenses; clearance comes
from specific weights + training-data provenance". The v8 executive summary
applies it: `faces4coco` and `coco-faces` are rejected because their boxes
descend from yoloface/YOLOv3 trained on WIDER FACE (CC BY-NC-ND), and the
summary is careful to label the reach-through argument "our policy, not a legal
finding". That is the card's mechanism, applied two hops down a derivation
graph, before intake.

### A real gate exists, over part of the surface

`recognition/infrastructure/face_pipeline/provenance.py` carries `license_id`,
`license_file` and `license_sha256` on each registry entry (`:58-60`), pins
YuNet as MIT (`:77-79`) and SFace as Apache-2.0 (`:91-93`), and refuses to load
on a licence-file hash mismatch (`:176`). `recognition/tests/deploy/
test_dockerignore_weight_exclusions.py` machine-checks that weight artifacts are
excluded from deploy images across both writers.

### What is open

1. **The gate covers the profile that is not the default.**
   `_resolve_face_pipeline_profile` defaults `RECOGNITION_FACE_PIPELINE_PROFILE`
   to `"insightface"` (`recognition/config/settings.py:64`); the code calls
   `face_pipeline` the "dark" profile and `.env.fir.example` opts into it
   explicitly. The default production path therefore runs the weights the FIR-1
   assessment calls non-commercial, and `provenance.py` has **no registry row for
   it at all** — no `license_id`, no hashed licence file, nothing for a gate to
   read. This is the card's named trigger: the licence basis lives in prose, not
   on the row the gate reads.
2. **There is no ban list.** The gate refuses on hash *mismatch* — drift
   detection — not on a terms intersection. Nothing fails when a restricted
   `license_id` is the active one.
3. **Closure is not computed.** `license_id` records the direct SPDX string for
   each ONNX file. The training-data lineage that the assessment prose reasons
   about is not a field.

The weight-exclusion test enforces *packaging*, not *terms*: it keeps weights out
of an image, which is a different guarantee from refusing to run under a
restrictive licence.

### Cheapest close

Give `insightface` a provenance row whose `license_id` is the restrictive term
rather than leaving it absent, and add one assertion that fails when an active
profile's `license_id` is on a ban list without a dated, scoped clearance
artifact. The clearance decision already exists in prose; the card's ask is that
it become the config CI reads.

---

## 3. CARD-27 — seal the margin, size the floor from design-effect n_eff

**Claim.** A non-inferiority margin sealed after the data, or a floor sized from
clustered row count instead of design-effect n_eff, both move the gate toward a
false pass.

### The margin half is honoured, and was arrived at independently

The v8 executive summary makes pre-run sealing a scheduled, blocking step: step
3a requires the operator to state in writing what a bootstrap UCL landing in
0.05–0.10 means **before** T-14 runs, and "unsigned ⇒ T-14 does not start". Harm
direction is named and its bias declared ("the raw bound is biased toward
killing and must not be used as stated"). The estimator is an image-level
cluster bootstrap at B=2000 with `resampling_unit = image`, and the resolvable
floor is defined as the CI half-width on Δ. That is requirements 1, 3 and 4 of
the card, met without reference to it.

### The design-effect half is open at one specific site

`report.py:900-904` sets `HEADLINE_ID_RECALL_ELIGIBLE_FLOOR = 100` with the
error target `"Wilson_95_halfwidth_le_10pct_at_p0.5 (n≈96–100 → ±9.8%)"`. The n
counted there is eligible **faces**, and faces cluster within image and within
identity. The module already knows this — for the neighbouring unknown-rejection
slice it discloses that "stranger probes cluster within images and within
individuals, so the Wilson error target's nominal n overstates the effective
sample size" (`report.py:97-101`) — but the disclosure is prose attached to one
slice, while the headline floor is still sized on raw count. At a design effect
of 2, a 100-face floor is n_eff 50 and the half-width is ±13.7%, not ±9.8%: a
slice can be labelled `gating_candidate` while missing its own declared
precision. That is the card's false-pass direction.

### Where the card does *not* bite — recorded so nobody spends a day on it

`synthetic_real_divergence` (`report.py`) computes
`threshold = max(wilson_half_width(a_r, n_real), DIVERGENCE_ABS_FLOOR)` with
`DIVERGENCE_ABS_FLOOR = 0.20`, and returns early as qualitative-only when
`n_real < ELIGIBLE_PAIR_FLOOR = 90` (`synthetic_occlusion.py:70`). At n = 90 and
p̂ = 0.5 the Wilson half-width is 0.101, and it falls with n. The absolute floor
therefore always dominates for every n the function can be reached with, so the
Wilson term is inert and a design-effect correction to it would change no
outcome. It reads like a CARD-27 hit and is not one.

### Cheapest close

Estimate deff (or ICC) on the headline identification slice with clusters taken
as image, and separately as identity; publish n_eff beside n on the slice's
`error_target`; re-express `HEADLINE_ID_RECALL_ELIGIBLE_FLOOR` in n_eff. The
disclosure already written for unknown-rejection becomes a number rather than a
caveat.

---

## Summary of open items

| # | Card | Open requirement | Site |
|---|---|---|---|
| 1 | CARD-31 | Artifact-only control arm (req. 1–2) | `synthetic_occlusion.py:54` — `OCCLUSION_KINDS` |
| 2 | CARD-26 | Registry row + ban-list gate for the default profile | `provenance.py:73-93`, `settings.py:64` |
| 3 | CARD-26 | Transitive closure as a field, not prose | `provenance.py:58-60` |
| 4 | CARD-27 | Floor sized from n_eff, not raw face count | `report.py:900-904` |

None of the four is a defect in shipped behaviour. Each is a gate that would not
catch the failure its card describes.
