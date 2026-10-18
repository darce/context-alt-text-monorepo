# T-14 union-adjudication dead-zone rule

**Protocol version:** T-14 / FIR open-set gate
**Rule status:** operator must sign and date this page before the run

## Operator sign-off

Operator name: `____________________________________________`<br>
Operator signature: `________________________________________`<br>
Run date (UTC): `____________________________________________`<br>
Signed decision ID: `_________________________________________`

The signed decision ID is required by the adjudication harness. An unsigned
run is not adjudicated.

## Required pre-run confirmations

Confirm each condition before T-14 starts. Each confirmation must be recorded
as `true`; a missing or false confirmation is fail-closed and produces no
verdict.

- [ ] `union_uses_human_true_faces`: `U` is the number of human-verified true
  faces in the detector union, not the union box count.
- [ ] `matched_fppi_equal_across_rows`: Buffalo and the candidate ran at the
  same declared matched-FPPI operating point on every image.
- [ ] `verdict_from_bootstrap_ucl`: the decision uses the image-level bootstrap
  95% upper confidence limit, not the point estimate.
- [ ] `thresholds_frozen_before_run`: both detector thresholds were declared
  before the run and are identical on every row.

Declared Buffalo threshold: `________________`<br>
Declared candidate threshold: `______________`<br>
Threshold declaration SHA-256: `______________________________`

Declared exhaustive-image subset count: `________________`<br>
Sorted exhaustive image-id list SHA-256: `______________________________`<br>

The exhaustive-image subset and its hash are declared before the run and never
revised after a result is observed.

## Decision rule

The detector-gap bound is evaluated over human-verified true faces in the
union. The bootstrap uses `B = 2000`, resamples images with replacement, and
reports the 95th percentile upper confidence limit (`resampling_unit =
image`). The bound is miss-inflated when the exhaustive-image correction is
available; the correction itself does not alter the retained input rows.

Each detector's true-positive count must be no greater than the human-verified
union count (`union_boxes`) on that image.

If any sampled replicate has zero total `human_true_faces`, its gap is
undefined. The harness conservatively raises `UnionAdjudicationError` with
the replicate number and seed and produces no verdict. This documents the
existing refusal behavior: retain empty input rows and whole-image replacement
sampling with `B = 2000`; never discard, condition, retry, or fill undefined
replicates, select a new seed, or substitute OPEN or DEAD_ZONE. Changing this
estimator requires a versioned protocol and operator ratification.

- **KILL** only when the miss-inflated bootstrap 95% UCL is `< 0.05`.
- **DEAD_ZONE** when the UCL is `>= 0.05` and `< 0.10`; this is neither kill
  nor pass.
- **OPEN** when the UCL is `>= 0.10`; D-01 is not killed and the detector line
  stays open.

The 0.05–0.10 band is provisional until the realized bootstrap interval is
known. If the realized interval is wider than this signed scope, do not
reinterpret the result after seeing it; record the limitation and escalate to
the larger adjudication frame.

> “A T-14 bound landing in that band is neither kill nor pass — it is an
> operator decision, stated in writing *before* the run.”

> “Thresholds 0.05 and 30% are proposed, not measured — they are stated up
> front so the decision is falsifiable rather than argued after the fact.
> Revising them is legitimate; revising them after seeing the result is not.”

The thresholds and conditions are **declared before the run, never revised**
after any result is observed. A later protocol version may change the rule,
but it cannot retroactively change this run's signed declaration.
