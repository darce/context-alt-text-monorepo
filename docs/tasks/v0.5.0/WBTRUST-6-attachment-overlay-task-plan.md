# Task Plan — WBTRUST-6

> **Date:** 2026-10-15
> **Author:** claude (Sonnet 5.5)
> **Owning Epic:** none yet — umbrella scope [workbench-curation-trust-scope.md](../../scopes/workbench-curation-trust-scope.md)
> **Task ID:** WBTRUST-6
> **Target Branch:** feature/wbtrust-6
> **Base SHA:** 372a6413a7ae0eb71baa3566716546684bac5a58
> **Revision:** 2
> **Review Coverage Target:** frontend + one PHP read; browser pass on `post.php?post=107&action=edit` required
> **Depends on:** none (Wave A). Shares `components/ui/FaceOverlayLayer.tsx` with the review queue and the lightbox; no other WBTRUST task edits it.
> **Executor:** `claude-remote` `claude-haiku-5-5`, effort `xhigh` for implementation and grunt work (operator order 2026-10-15). Brief each slice separately (1–3 files), inline the slice text plus codemap snippets; if the write-enabled remote Claude harness is denied or unavailable, record a blocker and ask the operator — no silent fallback to another model.
> **Prior art:** [scope](../../scopes/workbench-curation-trust-scope.md) (R7, root cause 11), [UX-map evaluation](../../assessments/current/workbench-curation-trust-uxmap-evaluation-2026-10-15.md) (B5, C5), [workbench-identity-chips map](../../../apps/prototype-wp-alt-context/docs/ux-maps/workbench-identity-chips.md). Semantic prior art (handoff, by ID only): decision 10726 (GUIDE2IMG-1 `g2i-fitbox`: boxes drift when the overlay is sized to a wrapper whose painted image no longer has its natural aspect ratio), findings 4576 and 4477 (UXP-5: `faceOverlayDomId` id safety; `FaceOverlayLayer` prop contract vs list↔overlay cross-highlight), finding 3776 (E21-5: media-detail payload carries no bbox).
> **Carried findings (by ID only):** none recorded yet; query `review_findings(list, task_ref="WBTRUST-6")`

## WBTRUST-6. Attachment overlay — over the real image, labels outside the face

Paths are relative to `apps/prototype-wp-alt-context/` (JS under `js/`, PHP under `src/`).

## Objective

On the attachment edit screen the face overlay sits on WordPress's own preview image (`#media-head-<id>`) and no rendered face label intersects any face bounding box. If no valid placement exists, suppress the visual chip while retaining the face outline’s accessible identity, activation and focus.

## Problem Statement

`http://localhost:10028/wp-admin/post.php?post=107&action=edit`:

- `#acx-attachment-faces` "should be over the main image `#media-head-107` instead" (today it renders its own copy of the picture in the compat-fields table).
- The overlay label (`#acx-face-overlay-<uuid> > span`) "should not obscure the face; it must be outside the bounding box."

## Constraints

- Keep `faceOverlayDomId` ids and DOM reading order (left-to-right by bbox x). Keep the bbox coordinate contract of `components/ui/faceGeometry.ts` (`overlayRectFor`, `NaturalSize`).
- ≥ 24×24 CSS px interactive target (A11Y-14) without a centred chip: the bbox outline is the control, padded to the minimum.
- One-shot fetch contract of `ATTACHMENT_FACES_QUERY_OPTIONS` stays (no polling).
- sr-004 tokens (`--acx-*`), status = colour + icon. No raw hex in new SCSS.
- Do not edit WordPress core, LocalWP config or `~/Local Sites/`. The host element is created by our JS inside the page DOM only.
- PHP: `composer test`; JS: `vitest run`; both on the remote VM lane.

## Workflow Principles

- Pure placement logic is a separate, unit-tested function (S2); the DOM wiring is thin.
- Read the real `post.php` DOM before choosing selectors (S1) — WordPress markup varies by version and by the image editor.
- Greenfield: replace the duplicate `<figure>`; no feature flag.

## Terminology

**Host** = our absolutely positioned div over WP's preview image. **bbox** = face bounding box in natural-pixel coordinates. **Label** = the text chip for a curated face.

## Current State Analysis

(Symbols, not line numbers.)

- `src/admin/class-attachment-fields.php` registers the compat field `acx_attachment_faces` (`input: html`, `show_in_modal: false`) containing `<div id="acx-attachment-faces" data-attachment-id="…" hidden></div>` for image attachments (filter `attachment_fields_to_edit`). Test: `tests/Unit/AttachmentFieldsTest.php`.
- `js/attachment-edit/main.tsx` (`mountAttachmentEdit`) validates localized config (`nonce`, `ajaxUrl`, `endpoints`), `attachmentId`, registers config, then mounts `AttachmentFacesApp` into `#acx-attachment-faces` and removes `hidden` after a successful render.
- `js/attachment-edit/AttachmentFacesApp.tsx`: five states (loading, error/session-expired, degraded, empty, faces). In the faces state it renders its own `<figure className="acx-attachment-faces__figure"><div className="acx-attachment-faces__image-wrap"><img/><FaceOverlayLayer/></div></figure>` — a duplicate of core's preview — then `UncuratedFaceList`.
- `js/components/ui/FaceOverlayLayer.tsx`: `controlStyle` places each chip at the bbox **centre** (`translate(-50%, -50%)` in `js/admin/styles/components/_face-overlay.scss`), so the label text (`acx-face-overlay__chip-label`, curated) sits on the face. Variants: curated chip with label, uncurated marker (`acx-face-overlay__marker-label` is sr-only), review "?" chip (`reviewFaceId`). Other consumers: `ReviewQueue.tsx`, `FaceLightbox.tsx`, `UncuratedFaceList.tsx`, `faceGeometry.ts`.
- Tests: `js/attachment-edit/__tests__/AttachmentFacesApp.test.tsx`, `UncuratedFaceList.test.tsx`, `keyboardWalk.test.tsx`; `js/components/ui/__tests__/FaceOverlayLayer.test.tsx`, `FaceLightbox.test.tsx`.
- Landed analogue to reuse, not copy: the guided press-photo overlay (`js/admin/pages/guided/GuidedFaceOverlay.tsx`, `GuidedSamplePhoto.tsx`) hit the same failure class (percent boxes resolved against a wrapper that is not the painted image) and was fixed by carrying the natural aspect ratio on the wrapper and `object-fit: contain` (decision 10726). The attachment host must be sized to the **displayed image rect**, never to a stretched container.
- Dev-site caveat: `:10028` serves a pinned release (see scope § Step 0), so a defect seen there may predate `main`. S1 records the served build before reading the DOM.
- `faceOverlayDomId` is the single id helper (three call sites in `FaceOverlayLayer.tsx`); it is also read by `UncuratedFaceList.tsx` and `ReviewQueue.tsx`. Keep it as is.
- Unverified: which element WordPress renders as the preview inside `#media-head-107` on this site (the operator's DOM paste names only the container), and whether the image editor (`imgedit`) swaps the `<img>` after crop/rotate.

## Target Outcome

- The overlay host is a child of the element wrapping WP's preview `<img>` inside `#media-head-<id>`, sized to the actual painted image rect, including object-fit/letterboxing offsets (kept in sync by `ResizeObserver` and image `load`).
- Each face is a transparent-fill bbox outline (2 px line + halo, focus ring), padded to ≥ 24×24; a curated label renders only at a validated `placed` result outside all face bboxes and within the painted image. A `noFit` result draws no visual label; the same outline retains its accessible identity, activation and focus. Icon-only markers straddle the bbox's top-right corner point.
- `#acx-attachment-faces` keeps the status messages and the uncurated list; it no longer draws a second image.

## Context Loading

`class-attachment-fields.php`, `js/attachment-edit/{main.tsx,AttachmentFacesApp.tsx,UncuratedFaceList.tsx,attachment-edit.scss,copy.ts}`, `js/components/ui/{FaceOverlayLayer.tsx,faceGeometry.ts,FaceLightbox.tsx}`, `js/admin/styles/components/_face-overlay.scss`. Canon (v0.26.2): VIZ-12, VIZ-25, PERC-01, INT-22, A11Y-13, A11Y-14, A11Y-16, LAY-24, UI-01.

The outside-bbox, containment and no-fit rules are accepted product requirements. Canon v0.26.2: **PERC-01 — Proximity binds meaning** (`lexicons/interaction-ux.md#perc-01`) checks label-to-target association; **A11Y-13 — Focus not obscured (2.4.11)** (`lexicons/accessibility.md#a11y-13`) checks focus visibility. **VIZ-12 — Layered transparency discipline** (`lexicons/interaction-ux.md#viz-12`) concerns transparent outline/layer legibility, not an outside-bbox placement rule. EVAL-16 does not apply to DOM recon.

## Contract and Boundary Impact

- No API or contract change. `AttachmentEditLocalizedConfig` keeps `imageWidth`/`imageHeight` as the natural size.
- **Open decision:** none for the operator. If S1 shows `#media-head-<id>` is absent for some media types, the fallback is the compat-field figure for that case (documented in the decision, tested).

## Proposed Solution

A portal renders `FaceOverlayLayer` into a host appended to the preview image's positioned parent. The pure `placeLabel(bbox, container, labelSize, faceRects)` uses measured CSS-pixel geometry in the painted image's coordinate space. Its planned result is a typed discriminant:

```ts
type LabelPlacement =
  | { kind: 'placed'; side: 'below' | 'above' | 'right' | 'left';
      left: number; top: number; width: number; height: number }
  | { kind: 'noFit' };
```

Try below, above, right, left. Return `placed` only for a finite, positive-size final label rect wholly contained in the painted image and outside every rect in `faceRects` (including the target bbox). Revalidate after clamping; if all valid sides fail, return `noFit`, never a least-overlap rectangle. Invalid, unavailable or unsupported geometry/label size also returns `noFit`. Any shortening or size constraint must be re-measured under the actual final CSS and passed through the same validation; until validated, draw no visual chip. If it still cannot fit, suppress the visual chip and keep the outline's accessible identity, activation and focus; do not create a hidden functional action or guess a position. The duplicate figure is deleted. No `onLabelPlacement` production callback API is introduced: the browser gate reads actual rendered DOM/CSS geometry (decision 17075).

## Files and Surfaces to Change

Owned paths:

- `js/attachment-edit/main.tsx`, `AttachmentFacesApp.tsx`, `attachment-edit.scss`, new `useMediaHeadHost.ts`, new `OverlayPortal.tsx`
- `js/components/ui/FaceOverlayLayer.tsx`, new `js/components/ui/placeLabel.ts`, `js/admin/styles/components/_face-overlay.scss`
- `src/admin/class-attachment-fields.php` only if S1 requires a localized-config key (e.g. the head selector) — otherwise untouched
- Tests: `AttachmentFacesApp.test.tsx`, `FaceOverlayLayer.test.tsx`, new `placeLabel.test.ts`, `FaceLightbox.test.tsx` and the `ReviewQueue` overlay assertions that read chip position; `tests/Unit/AttachmentFieldsTest.php` if PHP changes
- Docs: `workbench-identity-chips` map text where it describes the overlay chip; `make lint-ux-maps`

## Verification Strategy

- Unit: `placeLabel` table/property tests cover each edge, tiny face, multiple faces, wide label, container smaller than label, face filling the container, and invalid/unsupported sizes. For `placed`, assert finite final dimensions, containment and no intersection with any face bbox. Impossible cases assert `noFit`. Rendering tests assert `noFit` draws no visual chip and retains outline accessible identity, activation, focus, ids and reading order; keyboard walk (`keyboardWalk.test.tsx`) green. Any shortened label is re-measured and revalidated before drawing.
- Integration: host creation/reuse without duplication, `ResizeObserver` resync, image `load` resync, `imgedit` swap handled (re-query the `<img>` via `MutationObserver` on the head element); rebind observers/listeners to the replacement image, invalidate stale label measurements, and clean up only this instance’s host/listeners/observers and owned positioning class.
- Browser (fir site, post 107; decision 17075): measure actual painted image bounds, face outlines and final rendered label rects under production CSS at several window widths, after load/resize and image replacement. For each rendered label assert finite containment and no overlap with any face bbox. Include a controlled impossible-fit case: no visual chip, no visual label/face overlap, and outline identity, keyboard activation and focus retained. Check host reuse/rebinding/scoped cleanup; Tab order matches reading order; review queue and lightbox remain correct. No callback, mocked geometry or offline unit result substitutes for this browser gate.
- `npm run typecheck`, `npm run lint`, `vitest run`, `composer test` (if PHP touched) on the VM; `make lint-ux-maps`.

## Slice Delivery

### Slice S1: dom-recon-and-red-tests

Pin the host element and fail first.
Closes: R7 (diagnosis). Canon: PERC-01.
Design decision (binding): first record the served plugin build (scope § Step 0) so the defect is attributed to `main` or to the pinned release. Then, on `post.php?post=107`, capture the real structure under `#media-head-107` (container classes, the preview `<img>`, whether it has a positioned parent, what `imgedit` replaces); record it in the decision. RED tests: label rect intersects bbox with today's centred chip; the faces state renders a second `<img>`.
Acceptance: decision contains the selector chosen and a fallback; RED tests fail on the base SHA.

### Slice S2: place-label

A pure function, fully tested.
Closes: R7. Canon: VIZ-12, VIZ-25, PERC-01.
Design decision (binding): `placeLabel(bbox, container, labelSize, faceRects)` in `js/components/ui/placeLabel.ts` uses the `LabelPlacement` contract above: `placed` with finite, contained final geometry outside every face rect, or `noFit` with no drawable rectangle. Preference order below, above, right, left; validate after clamping and after any final-size/shortening re-measurement. All sides failing or unsupported size means `noFit`; never return overlap as fallback.
Acceptance: table/property tests cover edge/tiny-face cases and both impossible-fit counterexamples (label wider than image; face fills image). Every `placed` rect is finite, contained and outside all face rects; impossible or unsupported input yields `noFit`. Final-size changes require a new measurement and validation, with no visual label until successful.

### Slice S3: outline-as-control

Take the control off the face.
Closes: R7. Canon: VIZ-12, A11Y-14, A11Y-16, UI-01.
Design decision (binding): in `FaceOverlayLayer` the interactive element is the bbox outline (transparent fill, 2 px line, halo via `--acx-*` tokens, focus ring) with padding to 24×24 for small faces; the curated label renders only for `kind: 'placed'` at its validated final rect, `pointer-events` on the label forwards to the same control; `noFit` renders no visual chip while that outline keeps its accessible identity, activation and focus (no hidden functional action); icon-only markers and the review "?" chip anchor on the bbox's top-right corner point. Applies to every consumer (greenfield; no flag) — update the review-queue and lightbox tests that read chip position.
Acceptance: `FaceOverlayLayer.test.tsx`, `FaceLightbox.test.tsx`, `ReviewQueue` overlay tests green; every rendered label’s full rect is outside all face bboxes and contained in the painted image. No-fit cases draw no visual chip and retain outline identity, activation and focus.

### Slice S4: portal-onto-media-head

Overlay the real image.
Closes: R7. Canon: PERC-01, NAV-19, LAY-21.
Design decision (binding): `useMediaHeadHost(attachmentId)` finds `#media-head-<id>`'s preview `<img>` (selector from S1), appends a host div to its positioned parent (adds `position: relative` via a class, not inline style on core elements), sizes it to the actual painted image rect (account for object-fit/letterboxing and offsets relative to the parent, not just the parent or img element box — decision 10726) with `ResizeObserver` + `load`, and re-resolves/rebinds on `MutationObserver` (imgedit). Reuse this instance’s host without duplication; invalidate stale label measurements on load/resize/rebind. On replacement/unmount disconnect its observers/listeners and remove only its host and positioning class if this instance added it, preserving unrelated hosts/styles. `OverlayPortal` renders `FaceOverlayLayer` into the host. If the head is missing, fall back to the compat-field figure.
Acceptance: portal + load/resize/rebind tests, host reuse and scoped cleanup tests; fallback test; no second `<img>` in the faces state when the head exists. Browser acceptance measures painted geometry under actual CSS; mocked rects alone do not prove alignment.

### Slice S5: remove-duplicate-figure

Delete what the overlay replaces.
Closes: R7. Canon: VIZ-27, LAY-24.
Design decision (binding): remove `acx-attachment-faces__figure`/`image-wrap` and their SCSS when the head host is in use; `#acx-attachment-faces` keeps the status lines and `UncuratedFaceList` (which still receives `mediaUrl`); the `hidden` reveal contract in `main.tsx` is unchanged.
Acceptance: `AttachmentFacesApp.test.tsx` states (loading, error, degraded, empty, faces) green; SCSS has no orphaned selectors.

### Slice S6: browser-check-and-maps

Verify on the real screen.
Closes: R7. Canon: A11Y-13, INT-22.
Design decision (binding): browser walk on post 107 (and one multi-face media item) at three widths, recorded in the decision with actual CSS-rendered image/outline/label rects and the conditional rendered-label checks above (decision 17075). Exercise load/resize/rebind, host reuse/scoped cleanup and an impossible-fit case with no visual chip and outline identity/activation/focus retained; update the identity-chips map text and hand-mirror the `.md`; `make lint-ux-maps`.
Acceptance: walk recorded; map lint green; slice-complete decision per template.
