# Heuristics canon extract — GUIDEV3-1 review basis
Source root: ~/Development/heuristics-canon-research
Cite findings with these ids. Do not invent ids.

## Lexicon: interaction-ux.md
- NAV-09 (:136) Progress Indicator — linear multi-step flows show where the user is and how many steps remain.
- NAV-13 (:140) Controlled vocabulary before label freeze — step names and control labels come from one catalog, not ad-hoc strings.
- FORM-09 (:193) Responsive enabling — a primary action enables the moment its precondition is satisfied, and its disabled state names the missing precondition.
- INT-05 (:162) Prominent Done — the committing action is the visually dominant control on its surface.
- INT-06 (:163) Smart action labels — the label states the outcome, not the mechanism.
- INT-07 (:164) Preview before commit — when cost or unpredictability is high, show the outcome with commit and back-out on the same surface.
- INT-09 (:166) Reversible command stack — every committing action has a matching undo reachable from the same place.
- INT-11 (:168) Refine over restart — a wrong result is edited, not thrown away and redone.

## Lexicon: interaction-ux.md (human-AI)
- HAI-01 (:210) Evidence before label — show what the system saw before the name it assigned.
- HAI-05 (:214) Imperceptible AI is not ethical — generated content is disclosed at the point of use.
- HAI-08 (:217) Uncertainty at the decision granularity — confidence is expressed per decision the user makes, not globally.
- HAI-12 (:221) Output is a proposal, not the answer — model output arrives as an editable draft.
- HAI-15 (:224) Commit before reveal — ask for the user's judgement before showing the system's, to avoid anchoring.

## Lexicon: business-marketing.md
- GTM-07 (:170) Title = emotional first line — the title carries the claim, not the category.
- GTM-08 (:171) Novelty beats craft — lead with what is new, not with how well it is made.

## Lexicon: graph-theory.md
- GRPH-01 (:71) Topological sort — dependency order before execution order.
- GRPH-09 (:93) Conflict-graph colouring — disjoint owned paths let lanes run concurrently.
- GRPH-31 (:182) Layered DAG, ready frontier, critical path — schedule by layer; admit only what downstream capacity can absorb.

## Reasoning cards
- CARD-15 reasoning/reversible-commitments.md — prefer the cheap reversible option while the irreversible path is underpriced; write the soft side and the rollback before freeze.
- CARD-18 reasoning/attribute-claims-to-their-bearer.md — every non-visual claim in a description is attributed to the artefact, the source, or the viewer, never to the depicted person as fact-owner.
- CARD-30 reasoning/signal-density-not-length.md — shorter with the same signal wins; length is not evidence of care.

## Distilled corpus
- distilled/engineering/implementing-effective-code-reviews.md:266 — small-batch review: review each delta once, keep batches small, defects are found per unit of change not per unit of time.
- distilled/data/ddia — invariants that must hold across a state transition are stated and enforced at one place.
- distilled/engineering/release-it — every outward action needs a bounded failure mode and an explicit back-out.
- distilled/performance/latency — a user-visible action gives feedback within the perception budget or it announces that it is working.

## Project short rules (binding)
- [sr-004] CSS/SCSS uses --acx-* design tokens. No raw hex, no raw shadow, no raw radius, no raw font-weight. Status indicators pair colour with an icon, never colour alone.
- [sr-007] Domain status values are centralised as `as const` objects or enums, never scattered string comparisons.
- [rg-003] Primary controls reachable from zero state. Never gate a primary action behind non-zero selection.
- [rg-004] Role semantics match behaviour. Controlled dialogs must wire onOpenChange.
