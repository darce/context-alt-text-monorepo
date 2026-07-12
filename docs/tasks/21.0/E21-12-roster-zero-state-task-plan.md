# Task Plan — E21-12

> **Metadata**
>
> - **Date**: 2026-07-12 09:35 EST
> - **Author**: Claude Fable 5 (claude-fable-5)
> - **Owning Epic**: [docs/epics/v0.4.1/public-mvp-ux-polish-epic.md](../../epics/v0.4.1/public-mvp-ux-polish-epic.md)
> - **Epic Short ID**: E21
> - **Target Branch**: `feature/e21-12`
> - **Review Coverage Target**: 2

---

## E21-12. Roster Zero-State Reachability (rg-003) + Retention Discoverability

## Objective

Make the Roster's person list and `Add Person` control reachable from every state — including the auto-opened default-workspace state and the true zero-person state — with a designed empty state. Resolve the Retention page's discoverability gap (page routed but absent from the WP admin menu).

## Problem Statement

`RosterPage.tsx` auto-selects a default person when the projection is current (`selectDeterministicDefaultWorkspaceEntry`, `js/admin/pages/roster/rosterRoute.ts:58-89`, invoked at `RosterPage.tsx:106`), and in that default-workspace mode the entries section is unmounted: `RosterPage.tsx:269` renders `RosterEntriesSection` only when `!defaultWorkspaceMode`. That hides the "Managed Identities" list and the primary `Add Person` button (`RosterEntriesSection.tsx:186-190`) behind a non-obvious escape from the workspace — a standing rg-003 violation (primary controls must be reachable from zero state, never gated behind selection). The true zero-person state has no designed empty state ([RLSE-04] undesigned state is a bug). Separately, the Retention page is routed (`App.tsx:59-66`, slug mapping `:108-109`) but `class-menu.php` registers no submenu entry for it — the page is unreachable by navigation.

## Constraints

- **No backend contract changes** (rg-015); presentation and menu registration only.
- **Data sovereignty**: roster renders offline from local projection (`acx_persons` et al.); unchanged.
- **rg-003 is the gate**: person list + `Add Person` visible and operable in *every* roster state (zero persons, default-workspace, filtered, error/offline).
- **A11y floor**: keyboard-only walk of the changed flow + live-region coverage for async status ([A11Y-11], [A11Y-21]); extends the shared harness seeded by E21-1 — if E21-1 has not merged yet, this task lands its specs in the same `tests/e2e/a11y/` pattern (`.press()`/`toBeFocused()`, `role="status"`), no dependency taken.
- **Menu naming**: submenu follows existing `alt-context-*` slug + `acx_*`/text-domain conventions in `class-menu.php`.
- **No visual re-baseline** (E21-4 owns it).

## Workflow Principles

- Zero state is the first state a visitor meets; it must teach the next action ([PROD-01] outcome over output, [RLSE-06] the adversarial user is in a hurry).
- Show, don't gate: the workspace panel is an enhancement layered *above* the always-visible list, not a mode that replaces it ([LAY-06] hierarchy without ornament).
- Delete-over-flag: `defaultWorkspaceMode`'s unmount branch is removed, not configured around.

## Terminology

- **Default-workspace mode**: roster state where a deterministic person auto-opens (`rosterRoute.ts:58-89`) and currently unmounts the entries list.
- **Zero state**: no persons exist in the local projection.
- **Empty state (designed)**: intentional zero-state composition — headline, one-line explanation, primary `Add Person` CTA, secondary "run a scan" pointer.

## Current State Analysis

- `RosterEntriesSection` already owns the list, the `Add Person` primary button (:186-190), filter badges, and a `role="status"` filter notice — it is hidden, not missing.
- `RosterPage.tsx:269`: `{!defaultWorkspaceMode && <RosterEntriesSection ... />}` is the rg-003 violation.
- Zero-person rendering falls through to an undesigned early return in `RosterEntriesSection` (empty branch around :175, no CTA composition).
- Retention: route + slug mapping live in `App.tsx` (:59-66, :108-117); `class-menu.php::register_menu` (:33-87) registers Dashboard and sibling pages but no Retention submenu.

## Target Outcome

Roster always renders the person list; selecting a person opens the workspace panel alongside/above the list rather than replacing it. Zero-person visitors see a designed empty state whose primary CTA is `Add Person` and whose secondary path points at scanning. Retention is reachable from the WP admin submenu. Keyboard users can reach `Add Person` from page load in every state.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/rules/backend-php-guidelines.md` (menu change), `docs/workbay/rules/testing-typescript.md`, `docs/workbay/rules/testing-php.md`
- Epic: `docs/epics/v0.4.1/public-mvp-ux-polish-epic.md` (Re-baseline row E21-12)
- Grounding: WBUX-2 roster assessment (`docs/assessments/current/roster-dashboard-workbench-ux-assessment-2026-07-04.md`)
- Handoff/MCP: task ref `E21-12`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WP admin menu registration | PHP plugin | `class-menu.php` submenu set | add Retention submenu entry (slug `alt-context-retention`, already mapped in `App.tsx:108`) | no — additive | PHP unit test on registered submenus |
| Roster route contract (`?person=`, tabs) | frontend | `rosterRoute.ts` parsing | none — default-selection behavior may relax, parsing unchanged | yes — existing route tests stay green | `rosterRoute.test.ts` |

## Proposed Solution

Remove the `!defaultWorkspaceMode` unmount at `RosterPage.tsx:269` so `RosterEntriesSection` always renders; adjust layout so `PersonWorkspacePanel` and the list coexist (workspace above list, list collapsed-but-present or fully visible — decided by existing layout tokens, no new design system). Add a designed empty-state composition to `RosterEntriesSection`'s zero branch (headline + explanation + primary `Add Person` + secondary scan pointer, icon+color+word per sr-004). Register the Retention submenu in `class-menu.php` (decision: **menu item**, not dashboard footer link — it is a durable operator surface, and a routed page with no navigation entry is the actual defect; record as a handoff decision). Extend the a11y harness with a roster keyboard-walk (load → tab to `Add Person` → open form) and empty/default-state assertions.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| frontend | `js/admin/pages/RosterPage.tsx` (:269) | always render `RosterEntriesSection`; layout coexistence with `PersonWorkspacePanel` |
| frontend | `js/admin/pages/roster/RosterEntriesSection.tsx` | designed empty state in zero branch; `Add Person` reachable in all states |
| frontend | `js/admin/pages/roster/rosterRoute.ts` | only if needed: default-selection guard so auto-open never hides the list (parsing unchanged) |
| PHP | `src/admin/class-menu.php` | add Retention submenu (`alt-context-retention`) |
| tests | `js/admin/pages/roster/__tests__/RosterPage*.test.tsx` | state-matrix: zero / default-workspace / filtered / offline all show list + `Add Person` |
| tests | PHP menu test (existing suite location) | asserts Retention submenu registered |
| tests | `tests/e2e/a11y/roster-keyboard-walk.spec.ts` (new) | keyboard path to `Add Person` from load ([A11Y-11]) |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/pages/roster/PersonWorkspacePanel.tsx` | coexists with list; content translation is E21-9 scope — do not touch copy here |
| `js/admin/pages/roster/__tests__/rosterRoute.test.ts` | must stay green; route contract unchanged |
| `js/admin/App.tsx` (:59-66, :108-117) | Retention route + slug mapping already exist; reference only |

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-wp-alt-context && npm run test:agent -- RosterPage RosterEntriesSection rosterRoute`
  - `cd apps/prototype-wp-alt-context && composer test:unit` (menu registration)
  - full gate: `npm run check`
- Runtime-parity / environment checks:
  - `npx playwright test tests/e2e/a11y` (roster keyboard-walk + axe)
- Manual verification:
  - fresh install (zero persons): Roster shows designed empty state with reachable `Add Person`; Retention visible in WP admin menu

## Slice Delivery

### Slice 1: Always-visible person list + designed empty state (rg-003)

**Goal**: Person list and `Add Person` reachable in every roster state, with a designed zero state.

Changes:

- Remove `!defaultWorkspaceMode` gate (`RosterPage.tsx:269`); layout coexistence.
- Designed empty-state composition in `RosterEntriesSection` zero branch.
- Unit state-matrix tests (zero / default-workspace / filtered / offline).

Proof:

- `npm run test:agent -- RosterPage RosterEntriesSection` green, including a test that fails on the old unmount behavior ([AGT-03]).

### Slice 2: Retention menu entry + a11y walk

**Goal**: Retention reachable by navigation; changed roster flow passes the keyboard gate.

Changes:

- `class-menu.php` Retention submenu + PHP test.
- `roster-keyboard-walk.spec.ts` (load → `Add Person` focusable/operable; empty state announced).
- Handoff decision recording the menu-vs-footer-link choice.

Proof:

- `composer test:unit` + `npx playwright test tests/e2e/a11y` green.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded frontend + PHP guidelines, epic re-baseline row, WBUX-2 grounding.
- [ ] Menu boundary change recorded (additive, no compat risk).

### Checklist for Slice 1: Always-visible list + empty state

- [ ] Unmount gate removed; workspace + list coexist
- [ ] Designed empty state (headline, explanation, primary `Add Person`, secondary scan pointer; sr-004 tokens)
- [ ] State-matrix unit tests green; old-behavior regression test demonstrated failing first

### Checklist for Slice 2: Retention menu + a11y

- [ ] Retention submenu registered + PHP test
- [ ] Roster keyboard-walk spec green and non-vacuous
- [ ] Decision recorded (menu item over footer link, rationale)

## Review Readiness

- [ ] No state leaves `Add Person` unreachable (rg-003 verified per state, not just zero).
- [ ] Runtime-parity: keyboard walk in Playwright, not only unit render.
- [ ] Handoff decision records change, verification, and menu decision.

## Success Criteria

- [ ] `Add Person` + person list visible/operable in zero, default-workspace, filtered, and offline states.
- [ ] Designed empty state ships; Retention appears in WP admin menu.
- [ ] Route contract tests unchanged and green; `handoff_close_check(enforce=True)` passes.
