# UXP-5. Attachment-Edit Face Overlays on post.php

> **Metadata**
>
> - **Date**: 2026-07-22
> - **Author**: Claude (Fable 5)
> - **Project**: prototype-wp-alt-context (PHP plugin + admin JS)
> - **Task ID**: `UXP-5`
> - **Target Branch**: `feature/uxp-5`
> - **Review Coverage Target**: 2

---

## Objective

On the attachment edit screen (`post.php`), curated faces render as always-on named overlays over the image; uncurated faces show their bbox on hover **and on keyboard focus**, plus a list in the compat-fields area with a "Name this person" deep link into the workbench. All of it net-new: no `attachment_fields_to_edit` surface exists today.

## Intake

- **Scope one-pager**: `docs/scopes/uxp-ux-pass-decomposition.md` (§ UXP-5, UXA-13 full spec)
- **Source assessment**: `docs/assessments/current/ux-ui-pass-assessment-2026-07-15.md` (**UXA-13**)
- **Key decisions**: UXP-1 `claude_uxp1_scope_intake_v1` (overlay = full spec)
- **Not-Doing**:
  - Editing/curation inside post.php beyond deep links.
  - Media list-table columns (E20-5 amendment).
  - Front-end/theme rendering.
  - Overlays inside the media **modal** — the field is registered `show_in_modal => false`; the modal only has to not break (scope success criterion). Modal overlay support is a possible follow-up, not this task.
  - Any change to `js/admin/pages/workbench/**` — this task is independent of the workbench-serial track (E15-37-FE / E21-9 / E21-10).

## Problem Statement

An editor opening an attachment in `post.php` sees nothing of what the recognition pipeline knows about it. The plugin has zero presence on that screen: no `attachment_fields_to_edit` filter anywhere in `src/` (verified by repo-wide grep), and `Admin::should_enqueue_assets` (`src/admin/class-admin.php` : `should_enqueue_assets`, ~line 100) only loads the SPA bundle for the five `SUPPORTED_PAGE_SLUGS` plugin pages. The data already exists one call away: `GET acx/v1/recognition/media-identities` (`src/api/class-media-identities-controller.php` : `register_routes`, ~line 49) returns per-attachment identities with pixel-space `bbox`, `cluster_label`, and `is_auto_label` — and the bbox-over-image math is already written in `FaceThumbnail` (`js/components/ui/FaceThumbnail.tsx`, scale/offset block ~lines 58–66). The gap is a mount surface, not a data model.

## Constraints

- **Greenfield** (CLAUDE.md): no compatibility shims; additive-only on the wire ([API-09] — the existing `media-identities` contract is consumed as-is, no field added or retyped).
- **Independent of the workbench-serial track.** `FaceThumbnail` lives in `js/components/ui/` (shared, **not** under `js/admin/pages/workbench/`), so reuse causes no collision. The extraction slice touches `js/components/ui/` only; any workbench file appearing in this branch's diff is a review-blocking defect.
- **No poller on post.php.** The screen renders once for one attachment; identity data is fetched exactly once ([RES-12]: one batch call for the one media id, never per-face). No `refetchInterval` at all — which also structurally avoids the UXP-NET-1 bare-`false` `refetchInterval` freeze trap. If `clustering_pending` is true, the face lists as uncurated with a "still clustering — reload to refresh" note; we do not poll for it.
- **PSR-4 / autoload parity (rg-016).** New runtime classes use WordPress-style `class-*.php` names, which are not PSR-4-resolvable — but `composer.json` declares `classmap: ["src/"]` alongside PSR-4, so classmap autoload covers them after `composer dump-autoload -o`. Verification is still mandatory and real: `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\Admin\\AttachmentFields'));"` must print `true` in the slice-1 proof. No `run_transactional` concern: this task is read-path only, zero DB writes (sr-009 not in play).
- Status/state indicators pair icon with color, tokens only (`--acx-*`) — sr-004.
- Prefer symbol names over line numbers in change sites; line anchors cited here were read against this tree and will drift.

## Current State Analysis

**Exists and is reused:** the `media-identities` route with its four `data_source` states (`local_projection`, `backend_proxy`, `endpoint_error`, `unavailable` — `RecognitionDataSource` constants, degraded responses at `MediaIdentitiesController::degraded_media_identities_response`); the TS client `fetchMediaIdentities` (`js/admin/api/recognition/identityQueriesApi.ts` : line ~31) and types `BoundingBox` / `ClusterIdentity` (`js/admin/api/recognition/types/identity.ts`); `FaceThumbnail`'s bbox scale math; the curated/uncurated rule already computed server-side (`src/sovereign/mappers/class-member-response-mapper.php` : `map_cluster_identity` — `is_auto_label` = has label ∧ not user-confirmed ∧ system-shaped).

**Missing:** any `attachment_fields_to_edit` registration; any enqueue path for `post.php` (the Vite build has a single `admin` entry — `vite.config.ts` `rollupOptions.input`); any overlay-positioning component (FaceThumbnail *crops into* a fixed square; nobody currently *positions boxes over* a displayed image).

**Definition used throughout:** **curated** = `cluster_label` truthy ∧ `is_auto_label === false`. **Uncurated** = everything else (no cluster, auto-label `cluster-…` style, or `clustering_pending`).

## Target Outcome

Open an attachment with curated + uncurated faces on `post.php`: curated names are visible in place without interaction; every uncurated face is listed below the image metadata and its bbox is revealable by hover **or** keyboard focus; the whole surface is operable from the keyboard alone; the media modal renders exactly as before; when identity data is unreachable the surface says so instead of rendering blank.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-php.md`, `docs/workbay/rules/testing-typescript.md`
- Heuristics: `heuristics-canon` `engineering.md` ([API-09], [RES-12], [REF-05], [RLSE-04], [TEST-06], [TEST-15]) and `accessibility.md` ([A11Y-01], [A11Y-04], [A11Y-06], [A11Y-10], [A11Y-11], [A11Y-12], [A11Y-14], [A11Y-21], [A11Y-24]). Every ID grep-verified against `~/Development/heuristics-canon/lexicons/` anchors before citation.
- Handoff/MCP: task ref `UXP-5`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET acx/v1/recognition/media-identities` | proxy (PHP) | `media_ids[]` ≤100, `identities_by_media` map + `data_source` | **none** — read as-is with a single id | n/a ([API-09]: nothing taken away) | existing controller tests stay green; new consumer test uses recorded fixture of the real envelope |
| `attachment_fields_to_edit` filter | WordPress core ↔ plugin (**new**) | not implemented | one field: inert container `<div>` + data attributes, `input => 'html'`, `show_in_modal => false` | n/a — additive filter | PHP unit test on filter output; manual modal check |
| Vite manifest | build ↔ `Admin` enqueue (**new entry**) | single `admin` entry keyed `js/admin/main.tsx` | second entry `attachment-edit` keyed `js/attachment-edit/main.tsx`; enqueue resolves it by its own key | n/a | PHP test: manifest with both entries resolves each; missing entry → existing `report_asset_bootstrap_failure` path |
| Workbench deep link | admin URL (informal) | `admin.php?page=alt-context-workbench` + hash routes (`extractRouteFromHash`) | link only — no new params invented. E21-10's link/URL-state contract has **not landed** (no plan doc in tree); until it does, the deep link targets the workbench scan tab without a media filter | n/a | link href asserted in component test; open question below |

## Proposed Solution

Four slices: PHP surface, shared geometry extraction, the post.php app, then list + deep link + keyboard hardening.

**PHP surface is a container, not markup.** `AltContext\Admin\AttachmentFields` (`src/admin/class-attachment-fields.php`) hooks `attachment_fields_to_edit` and emits a single field whose `html` is an empty `<div id="acx-attachment-faces" data-attachment-id="…" hidden>` — all rendering happens in React. `show_in_modal => false` keeps the field out of the media modal entirely, which is the cheapest correct way to guarantee "zero layout breakage on core media modal": core simply never renders it there. The class is wired from `AltContext::init()` (`src/class-alt-context.php` : `init`, alongside `admin`/`menu`/`api`).

**Enqueue is a second small entry, not the SPA.** The admin SPA (`js/admin/main.tsx`) drags in the router, QueryClient wiring, and every page; loading it on `post.php` to draw overlays is the wrong tool. A new Vite input `attachment-edit: js/attachment-edit/main.tsx` produces its own manifest entry; `Admin` gains an enqueue branch gated on `hookSuffix === 'post.php'` ∧ `get_post_type() === 'attachment'`, reusing the existing dev-server/manifest machinery (`enqueue_dev_assets` / `enqueue_build_assets` parameterized by entry key — a refactor of the `ENTRY_POINT` constant into a per-entry argument). A dedicated `wp_localize_script` payload (`AltContextAttachmentEdit`) carries only: REST nonce, the `media-identities` endpoint URL, attachment id, full-size image URL + natural width/height (`wp_get_attachment_image_src(..., 'full')`), and the workbench admin URL. Structural move (entry-key parameterization) and new behavior (second entry) land as two commits ([REF-05]).

**Geometry is extracted, not duplicated.** `FaceThumbnail`'s scale/offset math crops a face *into* a fixed square. The overlay needs the inverse mapping — bbox pixel coords in the natural image → percentage position on the displayed image. Both are projections of the same bbox model, so slice 2 extracts pure functions into `js/components/ui/faceGeometry.ts` (`cropTransformFor(bbox, displaySize)` consumed by `FaceThumbnail`, `overlayRectFor(bbox, naturalSize)` returning `%`-based `{left, top, width, height}` for the new layer). Extraction first with `FaceThumbnail` behavior pinned by its existing test, then the new function — two commits, same [REF-05] discipline. Percentage-based rects make the overlay layer resize-independent with zero `ResizeObserver` code.

**The overlay owns its image.** The React app renders its own `<figure>` (full-size image + absolutely-positioned overlay layer) inside the field container, **not** a wrapper injected around core's `.wp_attachment_image` markup. Rationale: mutating core DOM is exactly how "zero layout breakage" fails, core's edit-image flow replaces that node at will, and the compat-fields row below the media metadata is where the scope places the uncurated list anyway — image and list stay one coherent, self-contained widget. The trade-off (the image appears twice on the screen) is accepted and stated for review.

**Overlay semantics, per face class:**
- **Curated**: always-on bbox outline + name chip. The chip is a native `<button>` ([A11Y-12]) whose accessible name is the person label ([A11Y-04]); activating it follows the workbench deep link. Chip styling: token-backed background/text (`--acx-*`, sr-004) at ≥4.5:1 text contrast, outline ≥3:1 against the image via a 1px contrast halo ([A11Y-01] — a colored line over an arbitrary photo cannot meet 3:1 by hue choice alone).
- **Uncurated**: no permanent bbox. Each uncurated face gets a marker `<button>` (accessible name "Unnamed face N of M"); its bbox outline renders while the button is hovered **or focused** — the keyboard equivalent the scope demands ([A11Y-10]/[A11Y-11]). The revealed outline is content anchored to the trigger, dismissible with `Esc` ([A11Y-10]). Curated vs uncurated markers differ by icon + label, never color alone ([A11Y-06], sr-004). Every marker's hit target is ≥24×24 px regardless of bbox size ([A11Y-14]).
- Focus order: curated chips in reading order, then uncurated markers, then the list ([A11Y-11] keyboard walk is a slice-4 proof, not an aspiration).

**Data flow and degraded states.** One `fetchMediaIdentities([attachmentId])` call on mount (light `useQuery` with `retry: false`, no `refetchInterval` — the post.php bundle instantiates its own minimal QueryClient, not the SPA's). Four rendered states, each designed ([RLSE-04]/[A11Y-24]): loading (skeleton + `role="status"` announcement [A11Y-21]); loaded-with-faces; loaded-empty ("No faces detected"); degraded — `data_source` ∈ {`endpoint_error`, `unavailable`} arrives as HTTP 200 with an empty map (`MediaIdentitiesController::degraded_media_identities_response`), so the client **must** branch on `data_source`, not on emptiness: degraded renders "Face data unavailable right now" + icon, never a silent blank, and never retries in a loop. `local_projection` and `backend_proxy` are both healthy and render identically.

**Right-pane list + deep link.** Below the figure (same field container, which post.php renders under the media metadata column): one row per uncurated face — `FaceThumbnail` crop (`sm`), "Unnamed face N" text, and a "Name this person" link. Hovering/focusing a row highlights the corresponding overlay marker and vice versa (`aria-describedby` pairing). The link targets `admin_url('admin.php?page=alt-context-workbench')` (pattern of `adminUrls` in `Admin::localize_spa_config`); no invented query params — when E21-10's link contract lands, the href gains its media-filter param in that task, not this one.

## Files and Surfaces to Change

| Surface | File : symbol | Change |
| --- | --- | --- |
| php | `src/admin/class-attachment-fields.php` : `AttachmentFields` (**new**) | `attachment_fields_to_edit` filter; container field, `show_in_modal => false`; only for `image/*` attachments |
| php | `src/class-alt-context.php` : `init` | instantiate + init `AttachmentFields` |
| php | `src/admin/class-admin.php` : `enqueue_scripts`, `should_enqueue_assets`, `enqueue_build_assets`, `enqueue_dev_assets`, `get_manifest_entry` | parameterize by entry key; add `post.php` + attachment gate; `localize_attachment_edit_config` (**new**) |
| build | `vite.config.ts` : `rollupOptions.input` | add `attachment-edit` entry |
| frontend | `js/components/ui/faceGeometry.ts` (**new**) : `cropTransformFor`, `overlayRectFor` | extracted crop math + new overlay projection (pure) |
| frontend | `js/components/ui/FaceThumbnail.tsx` : `FaceThumbnail` | consume `cropTransformFor`; behavior unchanged (pinned by existing test) |
| frontend | `js/components/ui/FaceOverlayLayer.tsx` (**new**) : `FaceOverlayLayer` | presentational: identities + natural size → chips/markers/outlines |
| frontend | `js/attachment-edit/main.tsx` (**new**) | mount into `#acx-attachment-faces`; read localized config |
| frontend | `js/attachment-edit/AttachmentFacesApp.tsx` (**new**) | one-shot query, state machine (loading/faces/empty/degraded), figure + list |
| frontend | `js/attachment-edit/UncuratedFaceList.tsx` (**new**) | list rows + deep link + cross-highlight |
| styles | `js/admin/styles/` (new partial) | token-only chip/outline/marker styles |
| tests | PHP `tests/`, TS `js/**/__tests__` | per slice, below |

## Related Files

| File : symbol | Note |
| --- | --- |
| `src/api/class-media-identities-controller.php` : `get_media_identities`, `degraded_media_identities_response` | the read contract incl. degraded 200s. **Not modified.** |
| `src/sovereign/mappers/class-member-response-mapper.php` : `map_cluster_identity` | source of `cluster_label` / `is_auto_label`; curated rule derives from it. Not modified. |
| `js/admin/api/recognition/identityQueriesApi.ts` : `fetchMediaIdentities` | reused client fn (module must not drag SPA-only imports into the new bundle; if it does, split the import seam, don't fork the fn) |
| `js/admin/hooks/useMediaIdentities.ts` | the SPA's cooldown-gated poller — deliberately **not** reused; post.php does not poll |
| `js/admin/pages/workbench/**` | out of bounds for this branch (independence constraint) |

## Verification Strategy

- Deterministic tests:
  - `composer --working-dir=apps/prototype-wp-alt-context test` (scoped per slice via `-- --filter`)
  - `npm --prefix apps/prototype-wp-alt-context test` (scoped per slice via path args)
- Falsifiability: every new test observed failing once ([TEST-06]); for invariant guards (modal absence, degraded-not-blank, keyboard reveal) the proof states the mutation that flips them red ([TEST-15]).
- Runtime parity: `php -r` autoload check (rg-016); `npm run build` produces both manifest entries; `make check-remote` on the committed HEAD.
- Manual (LocalWP): attachment with curated + uncurated faces on post.php; media modal before/after screenshot; full keyboard walk ([A11Y-11]); recognition service stopped → degraded copy renders.

## Slice Delivery

### Slice 1: PHP surface — field + enqueue seam

**Goal**: `post.php` for an image attachment loads the (stub) attachment-edit bundle and renders the container field; the media modal is untouched.

Changes: `AttachmentFields` class + bootstrap wiring; `Admin` entry-key parameterization (commit 1, structural, [REF-05]) then the `post.php` gate + `attachment-edit` Vite entry with a stub `main.tsx` + localized config (commit 2); `composer dump-autoload -o`.

Proof (`TEST_CMD: composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'AttachmentFields|AdminEnqueue'`):
- Filter output: container div with attachment id, `show_in_modal === false`, absent for non-image attachments. Red-path ([TEST-15]): flipping `show_in_modal` to `true` fails the test.
- Enqueue: gate fires only on `post.php` + attachment; manifest with two entries resolves each independently; missing `attachment-edit` entry routes into `report_asset_bootstrap_failure`.
- rg-016: `class_exists('AltContext\Admin\AttachmentFields')` via `php -r` against the real autoloader, output pasted in the slice evidence.

### Slice 2: Geometry extraction + FaceOverlayLayer

**Goal**: shared pure geometry, and a presentational overlay layer that positions correct boxes for arbitrary bbox/natural-size inputs. `js/components/ui/` only.

Changes: extract `cropTransformFor` (commit 1 — `FaceThumbnail` pinned green before and after); add `overlayRectFor` + `FaceOverlayLayer` (commit 2): props `{identities, naturalSize, onActivate}`; renders curated chips (native buttons, icon+label), uncurated markers with hover/focus-revealed outlines, `Esc` dismissal, ≥24px targets.

Proof (`TEST_CMD: npm --prefix apps/prototype-wp-alt-context test -- js/components/ui`):
- Unit: `overlayRectFor` known-value cases incl. degenerate bbox (zero-area, out-of-bounds clamp). [TEST-06]: assert exact percentages, not truthiness.
- Component: curated chip carries the person name as accessible name ([A11Y-04]); uncurated outline hidden by default, visible on focus **and** on hover, hidden again on `Esc` ([A11Y-10]) — red-path: removing the focus handler must fail the focus case while hover stays green ([TEST-15] discrimination).
- Existing `FaceThumbnail.test.tsx` green, unmodified, across the extraction commit.

### Slice 3: post.php app — fetch, states, mount

**Goal**: real data on the real screen with all four states designed.

Changes: `AttachmentFacesApp` + `main.tsx` mount (own minimal QueryClient; `retry: false`; **no** `refetchInterval`); branch on `data_source` for degraded vs empty; `role="status"` announcements ([A11Y-21]); `clustering_pending` faces listed uncurated with reload hint; token-only styles.

Proof (`TEST_CMD: npm --prefix apps/prototype-wp-alt-context test -- js/attachment-edit`):
- Component with fixture envelopes: curated/uncurated split matches the `is_auto_label` rule; empty map + `data_source: unavailable` renders the degraded copy while empty map + `local_projection` renders "No faces detected" — red-path: collapsing the branch to emptiness-only fails exactly one of the pair ([TEST-15]).
- Exactly one fetch per mount (mock call count); no timer scheduled (fake timers advance → zero further calls).
- Mount is a no-op when the container div is absent (modal / non-attachment safety).

### Slice 4: Uncurated list, deep link, keyboard walk

**Goal**: the right-pane list, cross-highlighting, and a passing end-to-end keyboard walk.

Changes: `UncuratedFaceList` (FaceThumbnail `sm` crops, "Name this person" links to the workbench admin URL, list↔overlay cross-highlight via shared hover/focus state); focus-order audit; contrast tokens finalized ([A11Y-01]).

Proof (`TEST_CMD: npm --prefix apps/prototype-wp-alt-context test -- js/attachment-edit js/components/ui`):
- Component: one row per uncurated face; link href equals the localized workbench URL; focusing a row highlights its overlay marker and vice versa.
- Keyboard walk test: `Tab` sequence reaches every chip, marker, and row with visible focus; no trap ([A11Y-11]) — red-path: setting `tabIndex={-1}` on a marker fails the walk.
- Manual evidence recorded in handoff: post.php screenshot with both face classes; media-modal parity screenshot; degraded-state screenshot; AT spot-check of the status announcements ([A11Y-23]-spirit: a human verified what the scanner cannot — noted, not cited as a checklist row since automated + walk are the floor here).

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded PHP/frontend rules and the `media-identities` degraded-response contract before editing.
- [ ] Confirmed no file under `js/admin/pages/workbench/**` appears in the branch diff.

### Checklist for Slice 1: PHP surface

- [ ] `AttachmentFields` registered from `AltContext::init`; image attachments only; `show_in_modal => false`.
- [ ] `Admin` enqueue parameterized by entry key (structural commit separate, [REF-05]); `post.php` + attachment gate; localized `AltContextAttachmentEdit` payload (nonce, endpoint, attachment id, full-size URL + natural dimensions, workbench URL).
- [ ] `attachment-edit` Vite entry builds; missing-manifest-entry path reuses the bootstrap-failure notice.
- [ ] rg-016 autoload proof (`php -r` `class_exists`) recorded.

### Checklist for Slice 2: Geometry + overlay layer

- [ ] `faceGeometry.ts` pure functions; `FaceThumbnail` consumes `cropTransformFor` with its existing test green and unmodified.
- [ ] `FaceOverlayLayer`: native buttons ([A11Y-12]), accessible names ([A11Y-04]), hover **and** focus reveal + `Esc` ([A11Y-10]), ≥24px targets ([A11Y-14]), icon+color pairing ([A11Y-06]/sr-004), token-only styles.
- [ ] Overlay rect unit tests with exact-value assertions, each watched failing once ([TEST-06]).

### Checklist for Slice 3: post.php app

- [ ] One-shot fetch; `retry: false`; no `refetchInterval`; no timers scheduled.
- [ ] Four states designed and rendered ([RLSE-04]/[A11Y-24]); degraded branches on `data_source`, not emptiness; announcements via `role="status"` ([A11Y-21]).
- [ ] Mount no-ops without the container div.

### Checklist for Slice 4: List + keyboard walk

- [ ] Uncurated list rows with FaceThumbnail crops and workbench deep links (no invented URL params).
- [ ] List↔overlay cross-highlight wired both directions.
- [ ] Keyboard walk test green and observed failing under a `tabIndex` mutation ([A11Y-11]/[TEST-15]).
- [ ] Manual evidence set (post.php, modal parity, degraded, AT spot-check) recorded in handoff.

## Review Readiness

- [ ] Every new PHP class autoload-verified per rg-016.
- [ ] The wire contract is provably unchanged (no proxy/controller diff).
- [ ] Independence constraint verified against the diff, not asserted.
- [ ] Handoff decisions record each slice with verification evidence and the deep-link deferral to E21-10.

## Success Criteria

- [ ] Opening an attachment with curated + uncurated faces on `post.php` shows curated names in place with zero interaction.
- [ ] Every uncurated face is listed below the image metadata and reachable by keyboard; its bbox reveals on hover and on focus identically.
- [ ] The whole surface completes a keyboard-only walk: reach, reveal, dismiss, and follow a deep link without a mouse.
- [ ] The media modal renders byte-identically to pre-branch (field suppressed via `show_in_modal`).
- [ ] With the recognition backend unreachable and no local projection, the surface states that face data is unavailable — no blank, no retry loop, no console 429/timeout spam.
- [ ] post.php issues exactly one identities request per page load.

## Open Questions

- **Deep-link media filter**: the workbench cannot yet filter to a specific attachment (E21-10 not landed). Ship the plain workbench link now, or block slice 4's link on E21-10? Plan assumes ship-now.
- **Duplicate image render**: the overlay figure duplicates core's attachment preview rather than wrapping it. Accepted trade-off for zero core-DOM surgery — reviewer may prefer wrapping `.wp_attachment_image` with a fallback; the plan's default is the self-contained figure.
- **Modal follow-up**: is overlay support inside the media modal wanted as a later task, or is post.php the terminal surface for this feature?
