# UXW2-6. Lightbox face naming with a “?” chip applied to the whole review group + group accept of close matches

**Wave**: UX/UI wave 2 (orchestration task `MAINT-uxui-wave2-orch-20260818`, decision 5678) · **Date**: 2026-08-18 · **Author**: Claude (Fable 5)
**Target Branch**: `feature/uxw2-6` · **Worktree**: `context-alt-text-monorepo-uxw2-6` · **Baseline**: main @442d99f93
**Review Coverage Target**: 2 (adversarial `/review-parallel`: 1 local Claude + remote grok-4.6 + kimi-k3 reviewers, canon-cited)
**Diagnosis**: session scratchpad `diag/REPORT_B.md` (root causes with file:line evidence); prior art digest `diag/PRIOR_ART.md`
**Depends on**: UXW2-3 (NameFaceControl), UXW2-2 (cache drops) · **Blocks**: none

## Objective

Clicking a face in Review Suggestions opens the full media item with every detected face boxed; the face under review carries a "?" chip; naming inside the box applies to all items in the review group (auto-merges with an existing roster person or creates one). "Is this X?" Yes offers to also accept the group's close matches with a preview count.

## Problem Statement (root cause, verified against main @442d99f93)

B3: `FaceLightbox.tsx:68-81` draws one aria-hidden bbox; `FaceOverlayLayer.tsx` (chips, `onActivate`) + `faceGeometry.ts` exist but the lightbox has no `identities` prop, no editable chip, no group naming; per-face data available via `GET recognition/media-identities`. B7: bulk-accept endpoint is tenant-wide only (`class-suggestions-controller.php:512-560`, `routers/suggestions.py:350-390`); `useBulkReviewCommit` is sequential per-id with no UI caller for groups; thresholds `STRONG_SIMILARITY_MIN=0.45`, `LOW_CONFIDENCE_THRESHOLD=0.6`, `MATCH_BAND_HIGH_THRESHOLD=0.7` uncentralised.

## Decisions (canon defaults recorded in decision 5678 — not re-litigated here)

- Extend `FaceLightbox` with `identities` + `activeFaceId`, render `FaceOverlayLayer` inside the frame; "?" chip for the reviewed face; naming mounts `NameFaceControl` anchored to the chip; commit → existing person-commit path (roster match → `rosterEntryId`, else create) ([HAI-01], [INT-01], [A11Y-14]).
- Group accept = sequential per-id `useBulkReviewCommit` over pending assignment suggestions sharing `clusterId` with `band ≥ threshold` (thresholds from UXW2-5 `bandFor`), with "Also accept N close matches" preview ([INT-07], [INT-06], [HAI-16], [rg-002]); no new batch endpoint.

## Constraints

- Frontend only unless the media-identities read proves too heavy for the queue (then flag a shared-contracts change; do not do it silently). Group size >25 → cap + explicit truncation signal ([API-01], [RES-12]).
- Findings live in workbay-handoff by ID only; this plan tracks work, not finding status.
- No `Co-Authored-By` trailers. Full SHAs in handoff writes. Slice = one user-visible path, RED test first (`/tdd`).

## Slices

### Slice 1 — `feat(workbench): UXW2-6 lightbox shows all faces with a ? chip on the reviewed face` (RED `FaceLightbox.test.tsx`/`ReviewQueue` lightbox wiring)
### Slice 2 — `feat(workbench): UXW2-6 name inside the box applies to the review group` (RED: naming commits for every group item; roster match merges)
### Slice 3 — `feat(workbench): UXW2-6 Yes offers to accept N close matches with preview` (RED `useBulkReviewCommit.test.tsx`, `SuggestionCards.test.tsx`)

## Verification

`npm test`/lint/typecheck green; RED→GREEN per slice; manual: click avatar → full image with boxes; name in the ? box → all group items resolved; Yes → preview count then accepted.

## Prior art

E21-5 PR-32 click-to-original lightbox; UXP-5 FaceOverlayLayer; E21-5-REVA-02/dec 2494 (per-card atomic POST, grouped accept-all dropped then; server-side group accept anticipated); AttachmentFacesApp consumer of media-identities.

## Open questions

If runtime shows media-identities latency in the queue, add `identities` to the suggestion projection (contract change) in a follow-up.
