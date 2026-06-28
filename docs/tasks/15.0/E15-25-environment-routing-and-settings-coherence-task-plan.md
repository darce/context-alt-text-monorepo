# E15-25. Environment Routing and Settings Coherence

> **Metadata**
>
> - **Date**: 2026-06-10
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
> - **Epic Short ID**: E15
> - **Target Branch**: `feature/e15-25`
> - **Review Coverage Target**: 2
> - **Companion assessment**: [E15-24-architecture-coherence-assessment.md](E15-24-architecture-coherence-assessment.md)
> - **Literature citation convention**: short form `refactoring-ui.md §Hierarchy is Everything` refers to `literature/extracted/refactoring/distilled/refactoring-ui.md`. **The `literature/` directory is gitignored and exists only in the root checkout** (`~/Development/context-alt-text-monorepo/literature/...`) — read it from there, not from your task worktree.

## Objective

The recognition-target settings surface becomes visible, honest, and environment-aware: the invisible Service/Local toggle is fixed immediately, the settings page is rebuilt around selectable target cards with live health state, and the resolver loses its inferred-source special case. An operator can always answer "which service will my next scan hit, and is it healthy?" at a glance.

## Problem Statement

Two layers of failure. Acute: the Radix radio group (`js/components/ui/radio-group.tsx:17-18`) references `.acx-radio-group__item` / `__indicator` classes that no stylesheet defines — no `_radio-group.scss` exists and `js/admin/styles/components/index.scss` never imports one — so the toggle renders as two unstyled zero-affordance buttons; users cannot escape local mode from the UI. Structural: the page shows inert credentials at equal weight to active routing ("Service URL … not used while Local is selected"), `effective_target` is buried in prose, and the resolver (`class-recognition-endpoint-resolver.php:69-97`) infers `service` mode from a non-empty service URL at **two** precedence points: lines 75-77 (constant/filter-sourced URL outranks even an explicitly saved source option) and lines 89-94 (option-sourced URL implies service when no explicit source is set). Explicit user intent is sandwiched between two layers of inference — routing is unpredictable across config sources. The backend exposes three environments (prod/staging/dev subdomains, `infra/oci/README.md:324-333`) but nothing in the plugin acknowledges environments; local dev was found pointed at prod (assessment S3).

## Constraints

- sr-004: all new CSS uses `--acx-*` tokens; status indicators pair color with icon, never color alone.
- sr-007: recognition source values come from one canonical `as const` / enum definition, not scattered string literals.
- rg-003: primary controls reachable from zero state (unconfigured service must still show a designed empty state with a CTA, not a dead form).
- Constant/filter overrides remain read-only in the UI (existing `isReadOnly()` behavior preserved).
- E15-1b already shipped URL/key validation UX; this task reshapes presentation and routing semantics, it must not regress the `/settings/test` probe contract.

## Workflow Principles

- Hotfix before redesign: restore the existing control's visibility in its own slice so operators are unblocked even if the redesign slips (Release It: separate restoring service from correcting the defect).
- Refactoring UI: communicate state by hierarchy (active target prominent, inactive recessed), design the offline/unconfigured states explicitly, prefer selectable cards over bare radios.
- Release It: explicit environment configuration; handshaking — show `/health` state per target before the user commits to it.

## Terminology

- **Mode**: shorthand used by this plan for the value of `acx_recognition_source` (`local` | `service`) — the same concept the code, options, and all user-facing copy call **Recognition source**; UI copy keeps "Recognition source", and values come from the single canonical constants definition (sr-007).
- **Target card**: UI unit representing one routable destination (Local dev, Hosted service) with URL, credential state, and live health.
- **Effective target**: the URL+mode the next request will actually use (`effective_target_url`/`effective_target_mode` in settings GET).

## Current State Analysis

- Resolver chains (URL, local URL, key) are sound 4-level chains; only the source-inference special case is asymmetric.
- Settings GET already returns `url_source`, `effective_target_url`, `effective_target_mode` — the data for an honest UI exists; the presentation discards it.
- `/settings/test` probes `/health` (local) or `/health/detailed` (service) and returns outcome + probed URL.
- Radio CSS missing as described; all other Radix wrappers (checkbox, tabs, dialog…) have component SCSS files.

## Target Outcome

Settings page: a "Recognition target" section with two cards — Local development / Hosted service — where the active card is visually primary (token-based accent border + check icon + "Active" label) and the inactive card recessed. Each card shows its URL, credential/configured state, and a health chip (green check "Reachable" / red alert "Unreachable" / neutral "Not checked") fed by the existing test endpoint. Selecting a card is the mode switch. Below, a single "Effective target" line states exactly where the next request goes. Tenant id + provenance (from E15-24) render in an identity block. Resolver: inference special case removed — mode comes only from constant → filter → option → default `local`; a saved service URL no longer implies service mode.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/backend-php-guidelines.md`
- Contracts: `SettingsResponse` (`js/admin/api/settingsApi.ts:4-16`), settings REST controller GET/POST/test
- E15-12 contract: [E15-12-standard-deployment-reset-and-recognition-source-task-plan.md](E15-12-standard-deployment-reset-and-recognition-source-task-plan.md) — its shipped reset/deployment flows may rely on saved-URL-implies-service inference; characterize before Slice 2 (rg-006).
- Handoff/MCP: E15-25 task ref; E15-1b plan for shipped UX scope; E15-24 plan for tenant fields.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET /acx/v1/settings` | plugin REST | url/source/effective fields | none beyond E15-24 additive tenant fields | yes — UI consumes existing fields | TS type test + PHPUnit shape test |
| Resolver mode semantics | PHP resolver | URL-presence infers service (constant/filter only) | inference removed; explicit chain only | No (greenfield); behavior change documented in epic | PHPUnit resolver matrix |
| `POST /acx/v1/settings/test` | plugin REST | probe outcome + probed_url | unchanged | yes | existing tests |

## Proposed Solution

Slice 1 ships `_radio-group.scss` (token-based, focus-visible ring, checked indicator) + index import — restores the shipped control. Slice 2 removes resolver inference with a full precedence-matrix PHPUnit characterization (before/after). Slice 3 rebuilds the page: `TargetCard` component (selectable card pattern; radio semantics preserved for a11y via Radix under the hood), health chip wired to the test mutation per card, hierarchy per Refactoring UI (de-emphasize inactive credentials instead of warning prose), explicit unconfigured empty state with CTA. Status enums centralized per sr-007.

## Junior Implementer Guide

> Read this before touching code. **Rule zero: re-verify every anchor with the grep provided** — if it misses, search the symbol name and continue from reality (rg-010). If reality contradicts a slice's design, STOP and record a blocker instead of improvising.

### Why this task exists (didactic)

The acute bug is a control with zero affordance: the radio renders but has no stylesheet, so the user cannot see there is a choice. `refactoring-ui.md §Think Outside the Box` is the redesign lesson (radio semantics can wear richer clothing — selectable cards), and §Hierarchy is Everything / §Emphasize by De-emphasizing drive the page restructure: the *active* target should dominate visually; inert credentials should recede instead of being explained away in warning prose. The health chip is `release-it.md §Handshaking (5.6)` — let the user see target readiness before committing to it. The resolver cleanup is `release-it.md §Configuration Files (14.2)` discipline: environment routing must be explicit, never inferred from which config field happens to be non-empty.

### Assumed setup

Same workflow as all E15 tasks: `make task-start TASK=E15-25 …` → work in the worktree → per slice `composer test` / `npm test` from `apps/prototype-wp-alt-context/` → `record_event(test_result)` → `close_slice` → `render_handoff(kind='dashboard')`.

### Verified code anchors (as of commit `81de3127`; re-verify each)

| What | Where | Verified content | Re-verify with |
| --- | --- | --- | --- |
| Radio wrapper | `js/components/ui/radio-group.tsx` (24 lines) | `Root` gets class `acx-radio-group`; `Item` gets `acx-radio-group__item` and ALWAYS renders `<span aria-hidden className="acx-radio-group__indicator" />` — the indicator is a plain span, **not** `RadioGroupPrimitive.Indicator` | read the file; it is short |
| Missing stylesheet | `js/admin/styles/components/` | no `_radio-group.scss`; `index.scss` has `@use './checkbox';` etc. but no radio import | `ls js/admin/styles/components/ && grep -n "radio" js/admin/styles/components/index.scss` (expect: no match) |
| Style model to copy | `js/admin/styles/components/_checkbox.scss` | token usage: `--acx-color-border`, `--acx-color-surface-alt`, `--acx-color-accent`, `--acx-color-accent-contrast`; hover/focus/disabled states | read the file |
| Resolver inference | `src/api/class-recognition-endpoint-resolver.php:69-97` | TWO inference branches: 75-77 (constant/filter URL → service, ABOVE source filter/option) and 89-94 (any URL incl. option → service, BELOW source option, ABOVE `local` default) | `grep -n "service_url_resolution" src/api/class-recognition-endpoint-resolver.php` |
| Settings GET shape | `src/api/class-settings-controller.php:83-103` | returns url/source/effective/recognition_source fields the redesign needs — data already exists | read `get_settings()` |
| Settings save | `class-settings-controller.php:105-161` | per-field option writes with validation errors | read `save_settings()` |
| Probe endpoint | `class-settings-controller.php:163-217` | local → `GET <local>/health` (10s); service → `GET <service>/health/detailed` with derived `X-Tenant-ID` + key | read `test_connection()` |

### Slice 1 walkthrough — CSS hotfix (do this first; it unblocks a real operator today)

1. Create `js/admin/styles/components/_radio-group.scss` modeled on `_checkbox.scss`'s token discipline. Because the indicator is a plain span (see anchor), the checked state must key off Radix's data attribute on the Item button: `.acx-radio-group__item[data-state='checked'] .acx-radio-group__indicator { … }`. Radix sets `data-state="checked|unchecked"` automatically; no JS change is needed.
2. Minimum states: unchecked ring (border token), checked dot (accent token), `:focus-visible` ring (accent, offset 2px like checkbox), `:disabled` 0.5 opacity, hover border accent. Color alone must not carry state — the dot is the second channel (sr-004).
3. Register `@use './radio-group';` in `index.scss` next to the checkbox import.
4. Build and verify the artifact, not just the source: `npm run build` then `grep -c "acx-radio-group" <built css under the plugin's dist/build dir>` must be > 0. The original bug shipped because nobody checked the built CSS.
5. Manual proof in LocalWP: toggle visible, clickable, persists through Save (POST writes `acx_recognition_source`, anchor above).

### Slice 2 walkthrough — resolver inference removal

1. FIRST write characterization tests pinning the CURRENT matrix including both inference branches (this is the refa-6 discipline: pin behavior, then change it). Find the existing resolver tests with `grep -rln "RecognitionEndpointResolver" tests/`.
2. Precondition from the plan: audit E15-12's reset/deployment flows (`docs/tasks/15.0/E15-12-standard-deployment-reset-and-recognition-source-task-plan.md`) and any docs that say "save the service URL to switch to service mode" (`grep -rn "recognition_source" docs/ scripts/ Makefile`) — rg-006: documented commands must keep running as written. Record the audit result in the slice decision.
3. Delete BOTH branches (75-77 and 89-94). Target semantics: constant → filter → option → default `local`. Update the matrix tests to the new truth table and update `resolve_settings_snapshot()` consumers if any relied on the inferred `source` field value.
4. Behavior change to call out in the slice decision: installs that relied on "saved URL implies service" now resolve `local` until they explicitly set the source — the Slice 3 UI makes that choice obvious, which is why Slice 2 and 3 ship in the same task.

### Slice 3 walkthrough — target-card redesign

1. New `js/components/ui/target-card.tsx`: a selectable card pair that KEEPS Radix radio semantics underneath (wrap `RadioGroupPrimitive.Item` so keyboard/a11y arrive free; rg-004: controlled components must wire their change handlers). Cards: "Local development" / "Hosted service".
2. Card content per `refactoring-ui.md`: active card gets accent border + check icon + "Active" label (§Hierarchy); inactive card's credential fields render at reduced emphasis instead of the current warning prose (§Emphasize by De-emphasizing); unconfigured service card shows a designed empty state with a "Configure service URL" CTA (§Don't Overlook Empty States; rg-003: primary controls reachable from zero state).
3. Health chip per card: reuse the existing `/settings/test` mutation per target; states `Not checked` (neutral) / `Reachable` (green + check icon) / `Unreachable` (red + alert icon) — icon + color + text, never color alone (sr-004; `refactoring-ui.md §Don't Rely on Color Alone`).
4. One "Effective target" line under the cards sourced from `effective_target_url`/`effective_target_mode` (already in the GET response — anchor above).
5. Tenant identity block renders `tenant_id` + `tenant_id_source` from E15-24's fields IF E15-24 has merged; otherwise render nothing and note the dependency in the slice decision (do not stub fake fields).
6. Keep `settingsConstants.ts` as the single source for mode/health string values (sr-007); the plan's word "mode" == `acx_recognition_source` everywhere.

### Pitfalls / stop conditions

- Do not restyle by replacing the Radix primitives with divs — you will destroy keyboard navigation and `role="radio"` semantics that WP a11y review expects.
- `isReadOnly()` (constant/filter-sourced values disable inputs, `js/admin/api/settingsConstants.ts`) must keep working on the cards — constant-provenance deployments (E15-28 demo) render read-only cards with a provenance note.
- If the built-CSS grep in Slice 1 step 4 finds zero matches, the SCSS pipeline has an entry-point you haven't found — stop and locate the real build entry before assuming the import path.
- Slice 2 ships only with its E15-12 audit recorded; skipping it risks breaking documented deployment flows silently.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| CSS hotfix | `apps/prototype-wp-alt-context/js/admin/styles/components/_radio-group.scss` (new) + `index.scss` | token-based radio styles |
| PHP resolver | `apps/prototype-wp-alt-context/src/api/class-recognition-endpoint-resolver.php` | delete URL-presence inference |
| Settings UI | `apps/prototype-wp-alt-context/js/admin/pages/SettingsPage.tsx`, `SettingsForm.tsx` | target-card layout |
| New component | `apps/prototype-wp-alt-context/js/components/ui/target-card.tsx` + SCSS | selectable card + health chip |
| Status enum | `apps/prototype-wp-alt-context/js/admin/api/settingsConstants.ts` | canonical mode/health constants |
| Tests | plugin `tests/` + Vitest | resolver matrix, card interaction, a11y roles |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && composer test` (resolver precedence matrix: every source × mode combination)
  - `cd apps/prototype-wp-alt-context && npm test` (card selection updates mode; health chip states; keyboard/a11y — rg-004 controlled component wiring)
- Contract verification: TS `SettingsResponse` matches PHPUnit-asserted GET shape.
- Manual: LocalWP — toggle visible and clickable post-Slice-1; full redesign walkthrough post-Slice-3 (mode switch, health check both targets, unconfigured empty state).

## Slice Delivery

### Slice 1: Radio-group CSS hotfix

**Goal**: the shipped Service/Local toggle is visible, clickable, and token-compliant.

Changes: `_radio-group.scss` + index import; build verification.
Proof: built CSS contains `.acx-radio-group` rules; manual LocalWP screenshot; mode switch persists via POST.

### Slice 2: Resolver inference removal

**Goal**: mode resolution is the explicit chain only; precedence is fully characterized.

**Precondition**: audit E15-12's shipped reset/deployment flows and documented commands for reliance on URL-presence inference; record the audit result in the slice decision before deleting the branch.

Changes: characterization tests for current matrix first, then delete inference branch, update tests to target semantics; adjust any E15-12 documented flow that relied on inference in the same slice.
Proof: PHPUnit matrix green; saved service URL + no explicit source resolves `local`.

### Slice 3: Target-card settings redesign

**Goal**: settings page communicates active target, health, and identity at a glance.

Changes: TargetCard + health chips + hierarchy restructure + empty states + tenant identity block (E15-24 fields); remove warning-prose for inert credentials in favor of visual de-emphasis.
Proof: Vitest interaction + a11y assertions; manual walkthrough notes recorded as test_result evidence.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded frontend guidelines + resolver code + settings contract before editing.
- [ ] Confirmed `ctx7` not needed (Radix patterns already in-repo).
- [ ] Boundary rows recorded in slice-close decisions.

### Checklist for Slice 1: CSS hotfix

- [ ] Stylesheet created with `--acx-*` tokens and imported
- [ ] Built asset verified to contain the rules
- [ ] Manual toggle proof captured

### Checklist for Slice 2: Resolver

- [ ] Characterization matrix committed before behavior change
- [ ] Inference branch deleted; matrix updated to explicit semantics
- [ ] PHPUnit evidence recorded

### Checklist for Slice 3: Redesign

- [ ] TargetCard + health chip + hierarchy landed with token compliance
- [ ] Unconfigured/offline states designed and tested
- [ ] Vitest + manual evidence recorded; slice-complete decision

## Review Readiness

- [ ] No resolver change without precedence-matrix coverage.
- [ ] a11y semantics verified (radio role preserved, rg-004).
- [ ] Handoff decisions per slice; dashboard rendered.

## Success Criteria

- [ ] An operator can switch Local ↔ Service from the UI today (Slice 1) and from the redesigned cards (Slice 3).
- [ ] The page states the effective next-request target in one line, with health and identity visible.
- [ ] Mode never changes implicitly from saving a URL.
