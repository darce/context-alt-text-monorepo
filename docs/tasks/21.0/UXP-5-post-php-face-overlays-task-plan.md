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
- **No poller on post.php.** The screen renders once for one attachment; identity data is fetched exactly once ([RES-12]: one batch call for the one media id, never per-face). The one-shot query contract is **fully pinned**, not implied: `retry: false`, `refetchOnWindowFocus: false`, `refetchOnReconnect: false`, `staleTime: Infinity`, and no `refetchInterval` (which also structurally avoids the UXP-NET-1 bare-`false` `refetchInterval` freeze trap). React Query's *defaults* refetch on window focus/reconnect — omitting these options would re-fetch on every editor tab refocus, so the slice-3 proof fires a focus event and asserts zero additional calls. If `clustering_pending` is true (see the backend-proxy provenance note in Current State Analysis), the face lists as uncurated with a "still clustering — reload to refresh" note; we do not poll for it.
- **Autoload parity (rg-016) via explicit `require_once`.** New runtime classes use WordPress-style `class-*.php` names, which are not PSR-4-resolvable, and `alt-context.php` (~lines 106–145) already documents that the Composer classmap goes stale after `git pull` until `composer dump-autoload` runs — which is why `class-telemetry.php` and the whole bootstrap chain are loaded via explicit `require_once`. `src/admin/class-attachment-fields.php` follows that same pattern: an explicit `require_once ACX_PLUGIN_DIR . 'src/admin/class-attachment-fields.php'` joins the bootstrap chain in `alt-context.php`. The `php -r "require 'vendor/autoload.php'; var_export(class_exists('AltContext\\Admin\\AttachmentFields'));"` proof stays mandatory in slice 1. No `run_transactional` concern: this task is read-path only, zero DB writes (sr-009 not in play).
- **Capability parity.** The `media-identities` route's `permission_callback` is `current_user_can('manage_options')` (`class-abstract-recognition-proxy-controller.php` : `can_manage_recognition`). post.php for an attachment is reachable by editors/authors, who would receive a REST 403 — so both the `attachment_fields_to_edit` field and the post.php enqueue branch are gated on the **same** `current_user_can('manage_options')` check. Non-admins never load a bundle guaranteed to 403.
- Status/state indicators pair icon with color, tokens only (`--acx-*`) — sr-004.
- Prefer symbol names over line numbers in change sites; line anchors cited here were read against this tree and will drift.

## Current State Analysis

**Exists and is reused:** the `media-identities` route with its four `data_source` states (`local_projection`, `backend_proxy`, `endpoint_error`, `unavailable` — `RecognitionDataSource` constants, degraded responses at `MediaIdentitiesController::degraded_media_identities_response`); the TS client `fetchMediaIdentities` (`js/admin/api/recognition/identityQueriesApi.ts` : line ~31) and types `BoundingBox` / `ClusterIdentity` (`js/admin/api/recognition/types/identity.ts`); `FaceThumbnail`'s bbox scale math; the curated/uncurated rule already computed server-side (`src/sovereign/mappers/class-member-response-mapper.php` : `map_cluster_identity` — `is_auto_label` = has label ∧ not user-confirmed ∧ system-shaped).

**Missing:** any `attachment_fields_to_edit` registration; any enqueue path for `post.php` (the Vite build has a single `admin` entry — `vite.config.ts` `rollupOptions.input`); any overlay-positioning component (FaceThumbnail *crops into* a fixed square; nobody currently *positions boxes over* a displayed image).

**Definition used throughout:** **curated** = `cluster_label` truthy ∧ `is_auto_label === false`. **Uncurated** = everything else (no cluster, auto-label `cluster-…` style, or `clustering_pending`). This is [AIPX-07] precision-first: a `cluster-…` auto label is a guess, and painting a guessed name as an always-on chip is wrong advice that costs more than silence — auto-labels render as *unnamed* even when `cluster_label` is truthy, and a slice-3 fixture (`cluster_label` set + `is_auto_label: true`) must **not** render a curated name chip.

**`clustering_pending` provenance:** the field lives on `ClusterIdentity` (`js/admin/api/recognition/types/identity.ts`), but both local mappers hardcode it `false` (`class-member-response-mapper.php` : line ~72, `class-cluster-response-mapper.php` : line ~159) — it can only be `true` via the `backend_proxy` passthrough path. The reload-hint branch is therefore **unreachable under `local_projection`**; the slice-3 fixture for it explicitly models the `backend_proxy` envelope, and this limitation is recorded so the test's red-path claim stays honest ([TEST-15]).

## Target Outcome

Open an attachment with curated + uncurated faces on `post.php`: curated names are visible in place without interaction; every uncurated face is listed below the image metadata and its bbox is revealable by hover **or** keyboard focus; the whole surface is operable from the keyboard alone; the media modal never receives the field (`show_in_modal => false`); when identity data is unreachable — degraded envelope or rejected fetch alike — the surface says so instead of rendering blank.

## Context Loading

- Rules: `docs/workbay/rules/backend-php-guidelines.md`, `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-php.md`, `docs/workbay/rules/testing-typescript.md`
- Heuristics: `heuristics-canon` `engineering.md` ([API-09], [RES-12], [REF-05], [RLSE-04], [TEST-06], [TEST-15]), `accessibility.md` ([A11Y-01], [A11Y-04], [A11Y-06], [A11Y-10], [A11Y-11], [A11Y-12], [A11Y-14], [A11Y-21], [A11Y-24]), and `business-marketing.md` ([AIPX-07] — precision-first guidance backing the curated predicate). Every ID grep-verified against `~/Development/heuristics-canon/lexicons/` anchors before citation.
- Handoff/MCP: task ref `UXP-5`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET acx/v1/recognition/media-identities` | proxy (PHP) | `media_ids[]` ≤100, `identities_by_media` map + `data_source` | **none** — read as-is with a single id | n/a ([API-09]: nothing taken away) | existing controller tests stay green; new consumer test uses recorded fixture of the real envelope |
| `attachment_fields_to_edit` filter | WordPress core ↔ plugin (**new**) | not implemented | one field (admins only, `current_user_can('manage_options')`): inert container `<div>` + data attributes, `input => 'html'`, `show_in_modal => false` | n/a — additive filter | PHP unit test on filter output (gating); modal screenshot = **non-gating manual evidence** |
| Vite manifest | build ↔ `Admin` enqueue (**new entry**) | single `admin` entry keyed `js/admin/main.tsx` | second entry `attachment-edit` keyed `js/attachment-edit/main.tsx`; enqueue resolves it by its own key | n/a | PHP test: manifest with both entries resolves each; missing entry → existing `report_asset_bootstrap_failure` path |
| Workbench deep link | admin URL (informal) | `admin.php?page=alt-context-workbench` + hash routes (`extractRouteFromHash`) | link only — no new params invented. E21-10's link/URL-state contract has **not landed** (no plan doc in tree); until it does, the deep link targets the workbench scan tab without a media filter | n/a | closed decision: href = the workbench admin URL only; media-filter param deferred to E21-10; component test asserts the href |

## Proposed Solution

Four slices: PHP surface, shared geometry extraction, the post.php app, then list + deep link + keyboard hardening.

**PHP surface is a container, not markup.** `AltContext\Admin\AttachmentFields` (`src/admin/class-attachment-fields.php`) hooks `attachment_fields_to_edit` and emits a single field — only when `current_user_can('manage_options')` (capability parity with the route, see Constraints) — whose `html` is an empty `<div id="acx-attachment-faces" data-attachment-id="…" hidden>` — all rendering happens in React. **Reveal contract:** the container ships `hidden`; `js/attachment-edit/main.tsx` removes the `hidden` attribute immediately after a successful `createRoot(…).render(…)`, so React owns first paint and a failed bootstrap leaves core's layout untouched. A slice-3 assertion verifies the container is no longer `hidden` (exposed to the accessibility tree) after mount. `show_in_modal => false` keeps the field out of the media modal entirely, which is the cheapest correct way to guarantee zero layout breakage there: core simply never renders it. The class is wired from `AltContext::init()` (`src/class-alt-context.php` : `init`, alongside `admin`/`menu`/`api`) and loaded via explicit `require_once` in `alt-context.php` (rg-016, class-telemetry pattern).

**Enqueue is a second small entry, not the SPA.** The admin SPA (`js/admin/main.tsx`) drags in the router, QueryClient wiring, and every page; loading it on `post.php` to draw overlays is the wrong tool. A new Vite input `attachment-edit: js/attachment-edit/main.tsx` produces its own manifest entry; `Admin` gains an enqueue branch gated on `hookSuffix === 'post.php'` ∧ `get_post_type() === 'attachment'` ∧ `current_user_can('manage_options')`, reusing the existing dev-server/manifest machinery (`enqueue_dev_assets` / `enqueue_build_assets` parameterized by entry key — a refactor of the `ENTRY_POINT` constant into a per-entry argument). A dedicated `wp_localize_script` payload (`AltContextAttachmentEdit`) carries only: REST nonce, the `media-identities` endpoint URL, attachment id, full-size image URL + natural width/height (`wp_get_attachment_image_src(..., 'full')`), and the workbench admin URL. **CSS packaging:** the attachment-edit entry owns its own stylesheet — `js/attachment-edit/main.tsx` imports `js/attachment-edit/attachment-edit.scss`, which `@use`s the shared token partial from `js/admin/styles/tokens` — because the `--acx-*` custom properties otherwise ship only via the SPA bundle (`js/admin/main.tsx` → `styles/main.scss`) and every `var(--acx-*)` would silently resolve to nothing on post.php. The PHP enqueue loads both js and css from the same manifest entry. Structural move (entry-key parameterization) and new behavior (second entry) land as two commits ([REF-05]).

**Geometry is extracted, not duplicated.** `FaceThumbnail`'s scale/offset math crops a face *into* a fixed square. The overlay needs the inverse mapping — bbox pixel coords in the natural image → percentage position on the displayed image. Both are projections of the same bbox model, so slice 2 extracts pure functions into `js/components/ui/faceGeometry.ts` (`cropTransformFor(bbox, displaySize)` consumed by `FaceThumbnail`, `overlayRectFor(bbox, naturalSize)` returning `%`-based `{left, top, width, height}` for the new layer). Extraction first with `FaceThumbnail` behavior pinned by its existing test, then the new function — two commits, same [REF-05] discipline. Percentage-based rects make the overlay layer resize-independent with zero `ResizeObserver` code.

**The overlay owns its image.** The React app renders its own `<figure>` (full-size image + absolutely-positioned overlay layer) inside the field container, **not** a wrapper injected around core's `.wp_attachment_image` markup. Rationale: mutating core DOM is exactly how "zero layout breakage" fails, core's edit-image flow replaces that node at will, and the compat-fields row below the media metadata is where the scope places the uncurated list anyway — image and list stay one coherent, self-contained widget. The trade-off (the image appears twice on the screen) is the plan default pending the owner decision before slice 3 — status single-sourced in the Open Questions duplicate-preview gate.

**Overlay semantics, per face class:**
- **Curated**: always-on bbox outline + name chip. The chip is a native `<button>` ([A11Y-12]) whose accessible name is the person label ([A11Y-04]); activating it follows the workbench deep link. Chip styling: token-backed background/text (`--acx-*`, sr-004) at ≥4.5:1 text contrast, outline ≥3:1 against the image via a 1px contrast halo ([A11Y-01] — a colored line over an arbitrary photo cannot meet 3:1 by hue choice alone). **Verification split:** the automated gate is structural — the halo utility class is present on every outline and chips pair icon+text ([A11Y-06]), both mutation-flippable; the numeric contrast ratios themselves are **non-gating manual evidence** recorded in handoff.
- **Uncurated**: no permanent bbox. Each uncurated face gets a marker `<button>` (accessible name "Unnamed face N of M"); its bbox outline renders while the button is hovered **or focused** — the keyboard equivalent the scope demands ([A11Y-10]/[A11Y-11]). The revealed outline is content anchored to the trigger, dismissible with `Esc` — `Esc` blurs the active marker, so the outline hides because focus ended; the focus-reveal and `Esc`-dismiss gates hold together ([A11Y-10]). Curated vs uncurated markers differ by icon + label, never color alone ([A11Y-06], sr-004). Every marker's hit target is ≥24×24 px regardless of bbox size ([A11Y-14]).
- **Controlled highlight API** (designed now, not invented mid-slice-4): `FaceOverlayLayer` props are `{identities, naturalSize, onActivate, highlightedFaceId, onHighlightChange}`. Each face gets a stable id (identity id from the envelope); the layer renders marker/chip DOM ids from it so list rows can reference them via `aria-describedby`/`aria-controls`, and hover/focus inside the layer calls `onHighlightChange` so the list can mirror. A slice-2 test sets `highlightedFaceId` from outside and asserts the matching marker enters its highlighted state.
- **Reading order is an algorithm, not a vibe:** within each group, stable sort by `bbox.y` then `bbox.x`; DOM order = curated chips (sorted), then uncurated markers (sorted), then list rows in the same uncurated order. Focus order follows DOM order. The slice-4 walk test uses a fixture whose API array order ≠ visual order and asserts the sorted sequence ([A11Y-11]).

**Data flow and degraded states.** The reuse of `fetchMediaIdentities` is **not free**: `getConfig()` (`js/admin/api/config.ts` : `getConfig`, ~lines 70–73) reads `window.AltContextAdmin` and throws if absent, and `fetchRequiredApi` sources the REST nonce from it — so on post.php, where only `AltContextAttachmentEdit` is localized, every fetch would throw as written. **Slice 3 commit 0 is the config seam:** refactor `js/admin/api/config.ts` to accept an injected config source (`registerConfig(payload)`), with the SPA path unchanged (falls back to `window.AltContextAdmin`); `js/attachment-edit/main.tsx` registers the `AltContextAttachmentEdit` payload (nonce + `media-identities` endpoint) before the first fetch. A jsdom test proves `fetchMediaIdentities` resolves endpoint and nonce with **no** `window.AltContextAdmin` present ([REF-05], rg-001 — real seam, no fork of the fn).

One `fetchMediaIdentities([attachmentId])` call on mount, with the full one-shot contract from Constraints (`retry: false`, `refetchOnWindowFocus: false`, `refetchOnReconnect: false`, `staleTime: Infinity`, no `refetchInterval`) — the post.php bundle instantiates its own minimal QueryClient, not the SPA's. **Five** rendered states, each designed ([RLSE-04]/[A11Y-24]): loading (skeleton + `role="status"` announcement [A11Y-21]); loaded-with-faces; loaded-empty ("No faces detected"); degraded — `data_source` ∈ {`endpoint_error`, `unavailable`} arrives as HTTP 200 with an empty map (`MediaIdentitiesController::degraded_media_identities_response`), so the client **must** branch on `data_source`, not on emptiness; and **query-error** — a *rejected* fetch (REST 403, network failure, or the client's 2s `createRecognitionTimeoutSignal` timeout) never produces a degraded 200 envelope and lands in `useQuery`'s error state instead: it renders the same "Face data unavailable right now" copy + icon. Neither degraded nor error is ever a silent blank, and neither retries in a loop. `local_projection` and `backend_proxy` are both healthy and render identically.

**Right-pane list + deep link.** Below the figure (same field container, which post.php renders under the media metadata column): one row per uncurated face — `FaceThumbnail` crop (`sm`), "Unnamed face N" text, and a "Name this person" link. Hovering/focusing a row highlights the corresponding overlay marker and vice versa (`aria-describedby` pairing). The link targets `admin_url('admin.php?page=alt-context-workbench')` (pattern of `adminUrls` in `Admin::localize_spa_config`); no invented query params — when E21-10's link contract lands, the href gains its media-filter param in that task, not this one.

**String ownership (UXP-4 boundary).** UXP-4 owns the copy/disclosure pass with one copy module per surface. This surface's strings live in a local `js/attachment-edit/copy.ts` — the single copy source for post.php — and the set is frozen here: "Face data unavailable right now", "No faces detected", "still clustering — reload to refresh", "Unnamed face N of M", "Name this person", plus the loading announcement. This module is explicitly **out of UXP-4 scope** until a later copy pass folds it into the shared vocabulary; the deferral is recorded in handoff so UXP-4 and UXP-5 do not fight over the lexicon.

## Files and Surfaces to Change

| Surface | File : symbol | Change |
| --- | --- | --- |
| php | `src/admin/class-attachment-fields.php` : `AttachmentFields` (**new**) | `attachment_fields_to_edit` filter; container field, `show_in_modal => false`; only for `image/*` attachments; gated on `current_user_can('manage_options')` |
| php | `src/class-alt-context.php` : `init` | instantiate + init `AttachmentFields` |
| php | `alt-context.php` (bootstrap chain) | explicit `require_once` for `class-attachment-fields.php` (rg-016, class-telemetry pattern) |
| php | `src/admin/class-admin.php` : `enqueue_scripts`, `should_enqueue_assets`, `enqueue_build_assets`, `enqueue_dev_assets`, `get_manifest_entry` | parameterize by entry key; add `post.php` + attachment gate; `localize_attachment_edit_config` (**new**) |
| build | `vite.config.ts` : `rollupOptions.input` | add `attachment-edit` entry |
| frontend | `js/components/ui/faceGeometry.ts` (**new**) : `cropTransformFor`, `overlayRectFor` | extracted crop math + new overlay projection (pure) |
| frontend | `js/components/ui/FaceThumbnail.tsx` : `FaceThumbnail` | consume `cropTransformFor`; behavior unchanged (pinned by existing test) |
| frontend | `js/admin/api/config.ts` : `getConfig`, `registerConfig` (**new fn**) | injected-config seam; SPA path unchanged (falls back to `window.AltContextAdmin`) |
| frontend | `js/components/ui/FaceOverlayLayer.tsx` (**new**) : `FaceOverlayLayer` | presentational: identities + natural size + controlled `highlightedFaceId`/`onHighlightChange` → chips/markers/outlines |
| frontend | `js/attachment-edit/main.tsx` (**new**) | mount into `#acx-attachment-faces`; `registerConfig` before first fetch; remove `hidden` after successful render; import stylesheet |
| frontend | `js/attachment-edit/AttachmentFacesApp.tsx` (**new**) | one-shot query, state machine (loading/faces/empty/degraded/query-error), figure + list |
| frontend | `js/attachment-edit/UncuratedFaceList.tsx` (**new**) | list rows + deep link + cross-highlight |
| frontend | `js/attachment-edit/copy.ts` (**new**) | single copy source for this surface (UXP-4 deferral recorded) |
| styles | `js/attachment-edit/attachment-edit.scss` (**new**) | imported by `main.tsx`; `@use`s the shared token partial from `js/admin/styles/tokens`; token-only chip/outline/marker styles |
| tests | PHP `tests/`, TS `js/**/__tests__` | per slice, below |

## Related Files

| File : symbol | Note |
| --- | --- |
| `src/api/class-media-identities-controller.php` : `get_media_identities`, `degraded_media_identities_response` | the read contract incl. degraded 200s. **Not modified.** |
| `src/sovereign/mappers/class-member-response-mapper.php` : `map_cluster_identity` | source of `cluster_label` / `is_auto_label`; curated rule derives from it. Not modified. |
| `js/admin/api/recognition/identityQueriesApi.ts` : `fetchMediaIdentities` | reused client fn. Verified coupling: it resolves endpoint + nonce via `getConfig()`, which throws without `window.AltContextAdmin` — hence the slice-3 commit-0 `registerConfig` seam (not a fork of the fn) |
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

Changes: `AttachmentFields` class + bootstrap wiring (explicit `require_once` in `alt-context.php`, class-telemetry pattern); `Admin` entry-key parameterization (commit 1, structural, [REF-05]) then the `post.php` gate + capability gate + `attachment-edit` Vite entry with a stub `main.tsx` (importing the stub stylesheet with the token partial) + localized config (commit 2); `composer dump-autoload -o`.

Proof (`TEST_CMD: composer --working-dir=apps/prototype-wp-alt-context test -- --filter 'AttachmentFields|AdminEnqueue'`):
- Filter output: container div with attachment id, `show_in_modal === false`, absent for non-image attachments, absent for users without `manage_options`. Red-path ([TEST-15]): flipping `show_in_modal` to `true` fails the test.
- Enqueue: gate fires only on `post.php` + attachment + `manage_options`; manifest with two entries resolves each independently (js **and** css from the `attachment-edit` entry); missing `attachment-edit` entry routes into `report_asset_bootstrap_failure`.
- rg-016: explicit `require_once` present in the bootstrap chain **and** `class_exists('AltContext\Admin\AttachmentFields')` via `php -r` against the real autoloader, output pasted in the slice evidence.
- Modal visual check: **non-gating manual evidence** (screenshot in handoff); the gating proof is the filter test above.

### Slice 2: Geometry extraction + FaceOverlayLayer

**Goal**: shared pure geometry, and a presentational overlay layer that positions correct boxes for arbitrary bbox/natural-size inputs. `js/components/ui/` only.

Changes: extract `cropTransformFor` (commit 1 — `FaceThumbnail` pinned green before and after); add `overlayRectFor` + `FaceOverlayLayer` (commit 2): props `{identities, naturalSize, onActivate, highlightedFaceId, onHighlightChange}` with stable per-face ids (DOM ids referenceable via `aria-describedby`/`aria-controls`); renders curated chips (native buttons, icon+label), uncurated markers with hover/focus-revealed outlines, `Esc` dismissal, ≥24px targets; group-internal DOM order = stable sort by `bbox.y` then `bbox.x`.

Proof (`TEST_CMD: npm --prefix apps/prototype-wp-alt-context test -- js/components/ui`):
- Unit: `overlayRectFor` known-value cases incl. degenerate bbox (zero-area, out-of-bounds clamp). [TEST-06]: assert exact percentages, not truthiness.
- Component: curated chip carries the person name as accessible name ([A11Y-04]); uncurated outline hidden by default, visible on focus **and** on hover, hidden again on `Esc` because `Esc` blurs the active marker — the test asserts focus leaves the marker and the outline hides as a consequence, so the focus-reveal and `Esc`-dismiss assertions cannot contradict ([A11Y-10]) — red-path: removing the focus handler must fail the focus case while hover stays green ([TEST-15] discrimination).
- Controlled highlight: setting `highlightedFaceId` from outside puts the matching marker in its highlighted state; hover/focus inside the layer fires `onHighlightChange` with the face id.
- Structural a11y gates: every outline carries the 1px contrast-halo utility class; chips pair icon+text (both mutation-flippable). Numeric contrast ratios are **non-gating manual evidence**.
- Existing `FaceThumbnail.test.tsx` green, unmodified, across the extraction commit.

### Slice 3: post.php app — fetch, states, mount

**Goal**: real data on the real screen with all five states designed.

Changes: **commit 0 — config seam**: `registerConfig(payload)` injection in `js/admin/api/config.ts` (SPA fallback to `window.AltContextAdmin` unchanged), `main.tsx` registers the `AltContextAttachmentEdit` payload before first fetch. Then `AttachmentFacesApp` + `main.tsx` mount (own minimal QueryClient; `retry: false`, `refetchOnWindowFocus: false`, `refetchOnReconnect: false`, `staleTime: Infinity`, **no** `refetchInterval`); `hidden` removed from the container after successful render; branch on `data_source` for degraded vs empty; query-error (rejected fetch) renders the unavailable copy; `role="status"` announcements ([A11Y-21]); `clustering_pending` faces listed uncurated with reload hint; strings from `copy.ts`; token-only styles via the entry stylesheet.

Proof (`TEST_CMD: npm --prefix apps/prototype-wp-alt-context test -- js/attachment-edit js/admin/api`):
- Config seam (jsdom): `fetchMediaIdentities` resolves endpoint + nonce from the registered payload with **no** `window.AltContextAdmin` global — red-path: skipping `registerConfig` reproduces the 'AltContextAdmin configuration is missing.' throw ([TEST-15]). Existing SPA config tests stay green.
- Component with fixture envelopes: curated/uncurated split matches the `is_auto_label` rule, including the [AIPX-07] discriminator: `cluster_label` set + `is_auto_label: true` renders **no** curated name chip; empty map + `data_source: unavailable` renders the degraded copy while empty map + `local_projection` renders "No faces detected" — red-path: collapsing the branch to emptiness-only fails exactly one of the pair ([TEST-15]).
- Query-error state: a rejecting fetch (403 / timeout) renders "Face data unavailable right now", no retry ([RLSE-04]).
- Exactly one fetch per mount (mock call count); firing a window `focus` event → zero further calls; fake timers advance → zero further calls.
- `clustering_pending` fixture explicitly models the `backend_proxy` envelope (local mappers hardcode `false`; branch unreachable under `local_projection` — recorded limitation).
- After mount the container is not `hidden`; mount is a no-op when the container div is absent (modal / non-attachment safety).
- Rendered-style assertion: a token-backed property (e.g. chip background) resolves to a concrete value, proving the token partial is in the attachment-edit graph.

### Slice 4: Uncurated list, deep link, keyboard walk

**Goal**: the right-pane list, cross-highlighting, and a passing end-to-end keyboard walk.

Changes: `UncuratedFaceList` (FaceThumbnail `sm` crops, "Name this person" links to the workbench admin URL, list↔overlay cross-highlight via the slice-2 `highlightedFaceId`/`onHighlightChange` API and `aria-describedby` ids); focus-order audit against the bbox-sort algorithm; contrast tokens finalized ([A11Y-01], numeric ratios verified manually, non-gating).

Proof (`TEST_CMD: npm --prefix apps/prototype-wp-alt-context test -- js/attachment-edit js/components/ui`):
- Component: one row per uncurated face; link href equals the localized workbench URL; focusing a row highlights its overlay marker and vice versa (through the controlled API).
- Keyboard walk test: `Tab` sequence reaches every chip, marker, and row with visible focus; no trap ([A11Y-11]) — red-path: setting `tabIndex={-1}` on a marker fails the walk. The walk fixture's API order ≠ visual order and the test asserts the sorted (bbox.y, bbox.x) sequence, so response-order DOM would fail.
- Manual evidence recorded in handoff (**all non-gating**): post.php screenshot with both face classes; media-modal parity screenshot; degraded-state screenshot; contrast-ratio spot check; AT spot-check of the status announcements ([A11Y-23]-spirit: a human verified what the scanner cannot — noted, not cited as a checklist row since automated + walk are the floor here).

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded PHP/frontend rules and the `media-identities` degraded-response contract before editing.
- [ ] Confirmed no file under `js/admin/pages/workbench/**` appears in the branch diff.

### Checklist for Slice 1: PHP surface

- [ ] `AttachmentFields` registered from `AltContext::init`; explicit `require_once` in the `alt-context.php` bootstrap chain; image attachments only; `show_in_modal => false`; field gated on `manage_options`.
- [ ] `Admin` enqueue parameterized by entry key (structural commit separate, [REF-05]); `post.php` + attachment + `manage_options` gate; localized `AltContextAttachmentEdit` payload (nonce, endpoint, attachment id, full-size URL + natural dimensions, workbench URL).
- [ ] `attachment-edit` Vite entry builds with js + css (token partial imported); missing-manifest-entry path reuses the bootstrap-failure notice.
- [ ] rg-016 autoload proof (`php -r` `class_exists`) recorded; modal screenshot recorded as non-gating manual evidence.

### Checklist for Slice 2: Geometry + overlay layer

- [ ] `faceGeometry.ts` pure functions; `FaceThumbnail` consumes `cropTransformFor` with its existing test green and unmodified.
- [ ] `FaceOverlayLayer`: native buttons ([A11Y-12]), accessible names ([A11Y-04]), hover **and** focus reveal + `Esc` ([A11Y-10]), ≥24px targets ([A11Y-14]), icon+color pairing ([A11Y-06]/sr-004), token-only styles, controlled `highlightedFaceId`/`onHighlightChange` API with stable face ids, bbox-sorted DOM order.
- [ ] Overlay rect unit tests with exact-value assertions, each watched failing once ([TEST-06]); external-highlight test green; halo-class structural gate green.

### Checklist for Slice 3: post.php app

- [ ] Config seam landed as commit 0: `registerConfig` injection, jsdom proof with no `window.AltContextAdmin`, SPA config tests untouched-green.
- [ ] One-shot fetch with the full contract (`retry: false`, `refetchOnWindowFocus: false`, `refetchOnReconnect: false`, `staleTime: Infinity`, no `refetchInterval`); focus-event and fake-timer assertions both green.
- [ ] Five states designed and rendered ([RLSE-04]/[A11Y-24]); degraded branches on `data_source`, not emptiness; query-error (rejected fetch) renders the unavailable copy; announcements via `role="status"` ([A11Y-21]); strings sourced from `copy.ts`.
- [ ] `clustering_pending` fixture labeled backend_proxy-only; local-projection unreachability recorded.
- [ ] Container un-hidden after successful mount; mount no-ops without the container div; token-backed rendered-style assertion green.

### Checklist for Slice 4: List + keyboard walk

- [ ] Uncurated list rows with FaceThumbnail crops and workbench deep links (no invented URL params).
- [ ] List↔overlay cross-highlight wired both directions through the slice-2 controlled API.
- [ ] Keyboard walk test green, observed failing under a `tabIndex` mutation, and asserting the bbox-sort order against an out-of-order fixture ([A11Y-11]/[TEST-15]).
- [ ] Non-gating manual evidence set (post.php, modal parity, degraded, contrast ratios, AT spot-check) recorded in handoff.

## Review Readiness

- [ ] Every new PHP class autoload-verified per rg-016.
- [ ] The wire contract is provably unchanged (no proxy/controller diff).
- [ ] Independence constraint verified against the diff, not asserted.
- [ ] Handoff decisions record each slice with verification evidence and the deep-link deferral to E21-10.

## Success Criteria

- [ ] Opening an attachment with curated + uncurated faces on `post.php` shows curated names in place with zero interaction.
- [ ] Every uncurated face is listed below the image metadata and reachable by keyboard; its bbox reveals on hover and on focus identically.
- [ ] The whole surface completes a keyboard-only walk: reach, reveal, dismiss, and follow a deep link without a mouse.
- [ ] The new field is provably absent from the media modal (`show_in_modal === false` + filter red-path test); modal parity screenshots are non-gating supporting evidence.
- [ ] With the recognition backend unreachable and no local projection — or the query itself rejecting (403/timeout) — the surface states that face data is unavailable: no blank, no retry loop, no console 429/timeout spam.
- [ ] post.php issues exactly one identities request per page load, including across window focus/reconnect events.

## Open Questions

- **Duplicate image render** (the only open question; **decision owner: task requester / UXA-13 scope owner, decided in handoff before slice 3 coding**): the overlay figure duplicates core's attachment preview rather than wrapping it. Plan default is the self-contained `<figure>` (zero core-DOM surgery; core's edit-image flow replaces `.wp_attachment_image` at will). If the owner rejects the duplicate preview, the plan must first gain a wrap strategy plus an edit-image resilience test — both options must not stay live at implementation time.

### Closed during planning review

- **Deep-link media filter — closed: ship-now.** E21-10 has not landed (no plan doc in tree), the contract table forbids invented params, and the independence constraint forbids workbench changes. Slice 4 ships `admin.php?page=alt-context-workbench` only; the media-filter param is E21-10's job when its contract lands.
- **Modal follow-up — closed: post.php is the terminal surface for UXP-5.** Intake Not-Doing already excludes modal overlays; `show_in_modal => false` is registered; modal overlays are optional future backlog outside this plan.
- **Copy ownership — closed: local `copy.ts`, UXP-4 deferral recorded in handoff** (see String ownership above).
