# T-09 face-label rule — frozen rubric

**RUBRIC_VERSION:** `RUBRIC_VERSION = "face-label-rule/v1"`
**Status:** frozen before any evaluation sample is drawn
**Artifact owner:** FIR open-set gate

This document is the face-label rubric used for T-09 and for every later
adjudication that contributes to the FIR open-set gate. The version is part of
the measurement identity: every scored row must retain
`rubric_version: "face-label-rule/v1"`.

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

## Refusal classes

The following five classes are explicit refusals, not negative evidence about a
detector or an embedder:

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
5. **Sub-threshold size** — the face is too small in the source image to meet
   the adjudication size floor. Record the measured or reasoned size evidence
   with the refusal; do not enlarge a crop and silently turn it into an
   eligible face.

These classes are mutually recorded at the point of refusal. If more than one
class appears applicable, record the primary class and preserve the annotator's
note describing the ambiguity.

## Adjudication size floor — UNSET

The adjudication size floor is currently **UNSET** (`null`) pending a separate
operator ratification. No annotation run may proceed until the floor is
ratified; this requirement is fail-closed. The future floor will be expressed as a scalar
minimum face bounding-box area in source-image pixels, measured as box width
times box height on the original source image before any crop, resize, or
enlargement.

Ratification must edit this file in place, supply the scalar floor, and bump
the `rubric_version`/`RUBRIC_VERSION` value from the current value
`face-label-rule/v1` to a new version. Record the ratification decision in the
`ratified_by_decision_id` field. Until that edit and version bump occur, refusal
class 5 remains unratifiable and no annotation run may use this floor.

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

This rubric and its version are frozen before any sample is drawn. Changes
require a new rubric version and a new documented freeze; an existing scored
row is never silently reinterpreted under a later version.
