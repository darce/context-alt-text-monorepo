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

## Objective

The recognition-target settings surface becomes visible, honest, and environment-aware: the invisible Service/Local toggle is fixed immediately, the settings page is rebuilt around selectable target cards with live health state, and the resolver loses its inferred-source special case. An operator can always answer "which service will my next scan hit, and is it healthy?" at a glance.

## Problem Statement

Two layers of failure. Acute: the Radix radio group (`js/components/ui/radio-group.tsx:17-18`) references `.acx-radio-group__item` / `__indicator` classes that no stylesheet defines — no `_radio-group.scss` exists and `js/admin/styles/components/index.scss` never imports one — so the toggle renders as two unstyled zero-affordance buttons; users cannot escape local mode from the UI. Structural: the page shows inert credentials at equal weight to active routing ("Service URL … not used while Local is selected"), `effective_target` is buried in prose, and the resolver (`class-recognition-endpoint-resolver.php:69-97`) infers `service` mode from a non-empty service URL only when that URL came from constant/filter — an asymmetry that makes routing unpredictable across config sources. The backend exposes three environments (prod/staging/dev subdomains, `infra/oci/README.md:324-333`) but nothing in the plugin acknowledges environments; local dev was found pointed at prod (assessment S3).

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

- **Mode**: `local` | `service` — which resolver branch routes requests (existing `acx_recognition_source`).
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

- Rules: `docs/workstate/rules/frontend-guidelines.md`, `docs/workstate/rules/testing-typescript.md`, `docs/workstate/rules/backend-php-guidelines.md`
- Contracts: `SettingsResponse` (`js/admin/api/settingsApi.ts:4-16`), settings REST controller GET/POST/test
- Handoff/MCP: E15-25 task ref; E15-1b plan for shipped UX scope; E15-24 plan for tenant fields.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `GET /acx/v1/settings` | plugin REST | url/source/effective fields | none beyond E15-24 additive tenant fields | yes — UI consumes existing fields | TS type test + PHPUnit shape test |
| Resolver mode semantics | PHP resolver | URL-presence infers service (constant/filter only) | inference removed; explicit chain only | No (greenfield); behavior change documented in epic | PHPUnit resolver matrix |
| `POST /acx/v1/settings/test` | plugin REST | probe outcome + probed_url | unchanged | yes | existing tests |

## Proposed Solution

Slice 1 ships `_radio-group.scss` (token-based, focus-visible ring, checked indicator) + index import — restores the shipped control. Slice 2 removes resolver inference with a full precedence-matrix PHPUnit characterization (before/after). Slice 3 rebuilds the page: `TargetCard` component (selectable card pattern; radio semantics preserved for a11y via Radix under the hood), health chip wired to the test mutation per card, hierarchy per Refactoring UI (de-emphasize inactive credentials instead of warning prose), explicit unconfigured empty state with CTA. Status enums centralized per sr-007.

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

Changes: characterization tests for current matrix first, then delete inference branch, update tests to target semantics.
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
