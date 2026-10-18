# T-09 face-label rule — frozen rubric

**RUBRIC_VERSION:** `RUBRIC_VERSION = "face-label-rule/v2"`
**Status:** frozen before any evaluation sample is drawn
**Artifact owner:** FIR open-set gate

This document defines the prospective v2 face-label rubric for T-09 and later
adjudication that contributes to the FIR open-set gate. The version is part of
the measurement identity: every prospective v2 scored row must retain
`rubric_version: "face-label-rule/v2"`.

## What counts as a face

A face is a visible human face in the image, with enough facial evidence to
support a human face decision under this rubric. Label the face once, using one
box around the visible facial extent. Faces are counted from the pixels, not
from detector proposals, identity claims, or a roster. A face that no detector
proposed is still a face and must be included when it is visible under this
rule.

A face is eligible for the face-label set only when the annotator can
reasonably identify facial structure from the image. When an item falls into a
refusal class below, do not invent a box or identity label. Record the refusal
class instead.

Face presence and identity eligibility are separate decisions. Tiny or partially
occluded faces with recognizable human facial structure retain face presence;
identity may remain unknown, unresolved, or subject to abstention under the
existing identity rules. No identity label or recognition threshold is added.
Uncertain facial structure stays uncertain and unresolved for adjudication,
not automatically nonface or a forced positive; uncertainty is not a sixth
refusal class. Context or noise alone does not establish facial structure.
Profiles and occluded faces use the same visible-facial-extent box geometry.
Magnification may aid inspection but cannot create observed face or identity
evidence absent from the original pixels.

## Refusal classes

The inventory retains five classes: classes 1–4 are active refusals in v2,
not negative evidence about a detector or an embedder. Class 5 is inactive in v2
and retained only to explain historical v1 records:

1. **Hand-only** — only a hand, fingers, or a hand-shaped obstruction is
   visible; no facial evidence is available.
2. **Back-of-head** — the subject is turned away and only the back of the head
   or hair is visible; no face is visible.
3. **Heavy occlusion** — an obstruction hides facial structure so extensively
   that the remaining pixels cannot support a reliable face decision. Ordinary
   partial occlusion is not automatically a refusal when facial structure is
   still visible.
4. **Depiction** — the apparent face is a drawing, photograph within the
   scene, statue, mask, mannequin, emoji, or other depiction rather than a
   live human face in the image.
5. **Sub-threshold size — INACTIVE for v2** — no size-only exclusion applies.
   Historically in v1 this class meant a face too small in the source image to
   meet the adjudication size floor, with measured or reasoned size evidence
   retained and no enlargement used to confer eligibility. The v1 floor was
   unratified; this historical description does not validate any v1 run.

Active classes are mutually recorded at the point of refusal. If more than one
class appears applicable, record the primary class and preserve the annotator's
note describing the ambiguity.

## Adjudication size floor — ratified 0 source-pixel²

- Minimum source-image bounding-box area: **0 source-pixel²** (scalar `0`).
- Comparison: `width * height >= 0`.
- `ratified_by_decision_id: 17787`
- Ratification date: **2026-10-17**.

Require valid boxes with strictly positive width and height. Record coordinates,
width, height, and area in the original source-image coordinate system before
any crop, resize, or enlargement; that source-pixel measurement stays stable
when display magnification changes. No side-length or aspect-ratio cutoff is
introduced. Zero disables size-only exclusion; the live visible human
facial-structure criterion and active refusal classes still apply. This is an
administrative policy, not a scientifically optimal size threshold.

Decision 17787 ratifies this rule definition only; recommendation 17783 was
not operator ratification. This documentation does not authorize an annotation
run, sample draw, loader qualification, calibration, or recognition gate.
Loader/runtime compatibility qualification remains separately pending: the
current loader requires `face-label-rule/v1` and rejects unequal versions.
This prospective v2 definition does not admit v2 rows to that runtime, migrate
historical rows, or change the frozen v1 gate contract. Its D3 ratification
field concerns the metric budget, not this face-area decision; decision 17787
does not ratify FPI/FPIR budgets, non-mated denominators, or recognition
thresholds.

## Disputes and arbitration

Two annotators label independently before either sees the other's labels or
detector output. A disagreement is any difference in face presence, box
placement, refusal class, or identity eligibility. Do not average disagreeing
boxes and do not resolve a disagreement by treating one detector's output as
ground truth.

For each disagreement, retain both original labels and route the item to the
designated adjudicator. The adjudicator records the decision, the reason, and
the labels considered. If the adjudicator cannot apply this rubric
unambiguously, escalate the item to the HITL dispute queue and leave the gate
unresolved for that item until the escalation is decided. A later adjudication
may correct an earlier decision only through a recorded dispute resolution; it
must not overwrite the audit trail silently.

## Retention and freeze policy

Pre-adjudication labels are retained by policy. Preserve each annotator's
original label, refusal class, box (when present), note, timestamp, and
adjudicator outcome alongside the final label. The final label is the value
used for a scored measurement; the pre-adjudication labels remain available
for agreement, dispute, and audit analysis.

The v2 freeze applies to prospective annotations and must precede any sample
draw. Existing rows retain their original rubric version, including historical
`face-label-rule/v1`; they are not rewritten as v2. This rubric and its version
are frozen before any sample is drawn. Changes
require a new rubric version and a new documented freeze; an existing scored
row is never silently reinterpreted under a later version.
