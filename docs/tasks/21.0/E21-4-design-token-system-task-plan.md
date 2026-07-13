# E21-4. Design-token system + sr-004 sweep

> **Metadata**
>
> - **Date**: 2026-07-13 EST
> - **Author**: claude-fable-5
> - **Owning Epic**: [docs/epics/v0.4.1/public-mvp-ux-polish-epic.md](../../epics/v0.4.1/public-mvp-ux-polish-epic.md)
> - **Epic Short ID**: E21
> - **Target Branch**: `feature/e21-4`
> - **Review Coverage Target**: 2

## Objective

Replace the frontend's framework-default token surface with a chosen design direction: value-ranked grey/functional ramps, one modular type scale, an elevation scale — then sweep all raw SCSS literals onto tokens (sr-004), with contrast acceptance computed in tests. One visual re-baseline lands here and unlocks the rest of E21 Phase 3-4.

## Problem Statement

`tokens/_colors.scss` is 27 flat tokens of unaudited Tailwind defaults; the type ramp is ad-hoc with an sm/md near-inversion; 82 raw hex + ~166 other raw literals live in `components/*.scss`; several functional colors fail their WCAG duty floors (success `#10b981` 2.54:1 as glyph, warning-border `#f59e0b` 2.15:1, success-border `#22c55e` 2.28:1). Every later E21 visual task would re-litigate these values; the epic mandates the single re-baseline happens here.

## Design-direction preamble (required by epic amendment 2026-07-12)

Tokens encode a chosen direction, not framework defaults [LAY-10]:

1. **Grey temperature [COL-05]**: neutrals stay **cool, blue-biased** toward the accent's hue family [COL-06]. This is a *chosen* temperature: the ramp is ranked by value and documented below; several values coincide with incumbent slate greys because slate already sits on the chosen hue/value curve — the choice is temperature + value ranking + contrast acceptance, not novelty. Rationale: an accessibility workbench wants a cool, quiet neutral field, keeping chroma budget for status semantics and the single accent [COL-09].
2. **Anchor + roles [COL-03]**: one identity anchor — `--acx-color-accent` `#2563eb`. **Dominant** = neutral surfaces (grey ramp); **support** = indigo panel tints (`--acx-color-panel*`); **accent** = the blue anchor, sparse, for primary actions and selection [COL-09]; **functional** = danger/success/warning/info, value-ranked to duty (text vs border vs fill).
3. **Value-ranked ramps [COL-04]**: ramps ordered by value before hue; hierarchy survives desaturation; contrast passes by construction and the acceptance test is the readout that this step happened [A11Y-01].
4. **Modular type scale [TYPE-05]**: one harmonic ladder, ratio **1.125 (major second)**, base `1rem`: `0.702 / 0.79 / 0.889 / 1 / 1.125 / 1.266`. Leading rebalances with size where a step moves [TYPE-02].

## Constraints

- Single visual re-baseline for the epic happens in this task (epic Phase 2 premise); snapshot diffs must be human-reviewed, not stamped (REFA-3 finding 258: definition ≠ render).
- Existing token *names* are load-bearing across 21 component files — role aliases preserve names; churn is bounded to literal swaps.
- No new token without a documented duty row (REFA-3 finding 292: single-use token justified by nothing).
- Strictly frontend-local: no PHP, no service, no contract boundary touched.
- Greenfield policy: no back-compat shims beyond the named aliases that remain in active use.

## Workflow Principles

- Slice-per-commit; no bundling unrelated fixes (REFA-3 finding 294).
- Acceptance tests compute real values (WCAG ratios from resolved hex), never regex-only guards (REFA-3 finding 295; known grok vacuous-test failure mode).
- Orchestrator owns the design-encoding slice (S1); only mechanical, fully-specified sweeps are offloaded.

## Terminology

- **Duty**: the role a color token plays at a call site (text ≥4.5:1, non-text UI ≥3:1, decorative — exempt) [A11Y-01].
- **Snap rule**: deterministic mapping from a raw literal to its token (tables below).
- **Disposition comment**: inline comment marking a deliberately-kept literal (1px hairlines, layout widths), REFA-3 convention.

## Current State Analysis (ground truth, verified 2026-07-13 on `feature/e21-4` @ b11c9a94)

- `apps/prototype-wp-alt-context/js/admin/styles/tokens/_colors.scss` (41 lines): 27 flat tokens, no ramp/roles; 3 aliases from the REFA-3 dangling-token repair (lines 28-36).
- `tokens/_typography.scss:6-19`: snap-map comment + 6-step ad-hoc ramp; `md (0.9rem) > sm (0.875rem)`, `lg (0.95rem) < base (1rem)`.
- Raw hex outside tokens: **67** `components/_identity-cluster-list.scss`, **13** `components/_combobox.scss`, **2** `components/_orientation-card.scss` (= 82).
- Raw literals across `components/`: **54** `font-size`, **30** `font-weight`, **53** `border-radius`, **13** `box-shadow`, **16** `rgb()/rgba()`.
- `components/_workbench.scss` (1194 lines; `.acx-advanced-drawer` at :722) is fully tokenized, guarded by `js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts`; `design-tokens.test.ts` governs required tokens + `--acx-*` prefix discipline. Neither guards the other 20 component files.
- Epic-amended sweep scope includes Description History page, `PersonWorkspacePanel`, `AdvancedDrawer`, roster zero-state — all styled from `components/*.scss`, so the sweep unit is the whole `components/` directory.
- Radius tokens mix semantic (`sm/md/lg/pill/circle`) and numeric (`-8/-10`) names (REFA-3 finding 257, unresolved).

## Target Outcome

A token surface an agent can extend without re-litigating direction: value-documented grey ramp + functional colors with per-duty contrast acceptance executed in CI; one modular type ladder with pinned aliases; a 3-level elevation scale; zero unguarded raw literals in `components/*.scss`; status indicators carry a second channel [A11Y-06]; exactly one reviewed visual re-baseline.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, `docs/workbay/constitution.md` (sr-004), `docs/workbay/rules/testing-typescript.md`
- Epic: `docs/epics/v0.4.1/public-mvp-ux-polish-epic.md` (Phase 2 + 2026-07-12 amendments)
- Handoff: REFA-3 findings 251/254/257/258/292/294/295/315 (prior-defect lineage for this exact surface)

## Contract and Boundary Impact

None — strictly local to `apps/prototype-wp-alt-context/js/admin/styles/` + test harnesses. No cross-service, cross-language, or tool boundary.

## Proposed Solution

Encode the design direction in the token files first with computed acceptance (S1), then run mechanical sweeps file-set by file-set under the extended guards (S2, S3), finish with the sr-004 second-channel audit and the single visual re-baseline (S4).

### Token specification

**Grey ramp** (new; flat surface/border/text tokens become role aliases):

| Token | Value | Duty (acceptance pair) |
| --- | --- | --- |
| `--acx-gray-50` | `#f8fafc` | app surface |
| `--acx-gray-100` | `#eef2f7` | inset/alt surface |
| `--acx-gray-200` | `#e2e8f0` | decorative borders |
| `--acx-gray-300` | `#cbd5e1` | strong borders / disabled fills (non-text) |
| `--acx-gray-400` | `#94a3b8` | placeholder/disabled text (documented exempt duty) |
| `--acx-gray-500` | `#64748b` | secondary UI glyphs ≥3:1 on gray-50/white (4.55/4.76 ✓) |
| `--acx-gray-600` | `#475569` | muted text ≥4.5:1 on white/gray-50/gray-100 (7.58/7.24/6.74 ✓) |
| `--acx-gray-700` | `#334155` | body text on tinted grounds ≥4.5:1 (9.26 on panel ✓) |
| `--acx-gray-900` | `#0f172a` | primary text (≥15.9 on all light grounds ✓) |

Role aliases (names preserved — zero-churn seam): `--acx-color-surface: var(--acx-gray-50)`, `--acx-color-surface-alt: #ffffff`, `--acx-color-border: var(--acx-gray-200)`, `--acx-color-text: var(--acx-gray-900)`, `--acx-color-text-muted: var(--acx-gray-600)`, `--acx-color-text-secondary: var(--acx-gray-600)`, `--acx-color-frame-muted: var(--acx-gray-300)` (re-valued from off-ramp `#e0e0e0` — deliberate visual delta), `--acx-color-data-placeholder: var(--acx-gray-300)`.

**Functional colors** (value-ranked to duty; ratios computed 2026-07-13):

Keep: `danger #b42318` (6.57:1 on white ✓), `danger-strong/hover #991b1b` (7.60:1 on danger-soft ✓), `danger-soft/border`, `success-text #166534` (6.49:1 on success-bg ✓), `success-bg #dcfce7`, `warning-pill-text #92400e` on `warning-pill-bg #fef3c7` (6.37:1 ✓), `info-border #3b82f6` (non-text 3.68:1 ✓), accent `#2563eb` ↔ white (5.17:1 ✓ both directions). Re-value where duty fails its floor [A11Y-01]:

- `--acx-color-success` `#10b981` → **`#047857`** (2.54:1 → 5.48:1 on white, 4.99:1 on success-bg).
- `--acx-color-success-border` `#22c55e` (2.28:1, fails non-text 3:1) → **`#16a34a`** (3.30:1 ✓).
- `--acx-color-warning-border` `#f59e0b` (2.15:1) → **`#b45309`** (5.02:1 ✓); pill/soft fills unchanged (decorative).
- `--acx-color-error` `#ef4444` (3.76:1) → text duty snaps to `--acx-color-danger`; retained for ≥3:1 non-text duty only.

**Typography**: `--acx-text-2xs: 0.702rem`, `xs: 0.79rem`, `sm: 0.889rem`, `base: 1rem`, `lg: 1.125rem`, `xl: 1.266rem` (new). Migration: old `md (0.9)` → `sm`; old `lg (0.95)` → `base`. Names `md`/`lg` are kept: `md` pins to `sm`'s value; `lg` re-values to `1.125rem` only at explicitly-audited heading call sites, all other `lg` call sites snap to `base` during S3's audit. Alias values pinned by test. Block-level call sites that move a step get a line-height check in the same slice [TYPE-02].

**Elevation [UI-08]**: `--acx-shadow-1` (card; `--acx-shadow-card` aliases it), `--acx-shadow-2` (popover/drawer), `--acx-shadow-3` (dialog; folds dialog-primary/secondary pair). The 13 raw `box-shadow` literals snap to these 3 levels.

**Font weight**: add `--acx-font-weight-medium: 500` (10 existing call sites). Snap: `400→normal`, `500→medium`, `600→semibold`, `700→bold`.

**Radius**: semantic names canonical; `--acx-radius-8`/`-10` become deprecated aliases, call sites migrated in S3 (finding 257). Snap table: `4px/0.25rem→sm` · `6px/0.375rem→md` (0.5rem; +2px deliberate ladder consolidation, part of the single re-baseline [UI-01]) · `8px/0.5rem→md` · `10px/0.625rem→lg` · `12px/0.75rem→` new `--acx-radius-xl: 0.75rem` (9 call sites; duty: large cards/drawers) · `999px/9999px→pill` · `50%→circle` · `inherit` stays.

**Alpha/tint literals (16 rgb/rgba call sites)**: black-alpha values inside `box-shadow` snap to the elevation scale; `rgba(37,99,235,.1)` and `rgba(0,115,170,.05)` (accent/WP-admin tints) snap to new `--acx-color-accent-soft: rgb(37 99 235 / 10%)` (duty: selection/focus tint, decorative); slate-alpha `rgba(15,23,42,x)` snaps to `--acx-color-overlay` at overlay duty or gray-ramp borders at border duty; remaining black-alpha non-shadow uses get case-by-case snap to gray ramp with disposition comment if kept.

Spacing out of scope except literals adjacent to a swap already covered by an existing token.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tokens | `js/admin/styles/tokens/_colors.scss` | grey ramp + roles + functional re-values |
| tokens | `js/admin/styles/tokens/_typography.scss` | modular ladder + alias pins |
| tests | `js/admin/styles/tokens/__tests__/design-tokens.test.ts` | dangling-var guard, contrast acceptance, alias pins |
| styles | `js/admin/styles/components/_identity-cluster-list.scss` | 67 hex → tokens |
| styles | `js/admin/styles/components/_combobox.scss` | 13 hex → tokens |
| styles | `js/admin/styles/components/_orientation-card.scss` | 2 hex → tokens |
| styles | `js/admin/styles/components/*.scss` (remaining) | font-size/weight/radius/shadow/rgba sweep |
| tests | `js/admin/styles/tokens/__tests__/workbench-tokenization.test.ts` (or successor) | extend no-raw-literal guard to all `components/` |
| tests | `tests/e2e/visual/workbench-visual.spec.ts` snapshots | single re-baseline |
| markup | status-indicator TSX where color-only (roster zero-state, pills, toast, retention) | add icon/label second channel |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/styles/tokens/_radius.scss`, `_spacing.scss` | radius alias deprecation; spacing untouched |
| `tests/e2e/a11y/*-axe.spec.ts` | must stay green (floor, not gate [A11Y-23]) |
| `js/admin/styles/main.scss` | token import order if a new partial is added |

## Verification Strategy

- Deterministic tests (per slice): `node_modules/.bin/vitest run js/admin/styles/tokens/__tests__/` (npx broken by EALLOWDIRECTORY — use direct bin path).
- Contrast acceptance: computed WCAG ratios from resolved hex for every duty pair in the tables above, in `design-tokens.test.ts`.
- Gate: `make check-remote` on committed HEAD (JS/TS targets; no PHP surface in this task). No full local suites.
- Manual: human review of every visual-snapshot diff in S4 (finding 258).

## Slice Delivery

### Slice 1: Token foundation + computed acceptance (orchestrator-owned)

**Goal**: Encode the design direction in token files with contrast acceptance computed in tests.

Changes:

- Rewrite `tokens/_colors.scss` per spec (ramp, roles, functional re-values); `tokens/_typography.scss` ladder + pins; elevation tokens.
- Extend `design-tokens.test.ts`: (a) every `var(--acx-*)` referenced in `styles/` is defined (findings 251/315), (b) contrast acceptance from resolved hex per duty table [A11Y-01], (c) alias-pin assertions.

Proof: tokens vitest scope green; contrast table in test output.

### Slice 2: Hex sweep — cluster-list, combobox, orientation-card (offload)

**Goal**: 82 raw hex → declared tokens under extended guard.

Changes:

- Snap each hex to its token per S1 tables; no new tokens without a duty row.
- Extend tokenization guard to the three files.

Proof: tokens vitest scope green; `grep -oE '#[0-9a-fA-F]{3,8}' components/_identity-cluster-list.scss | wc -l` = 0 (ditto combobox/orientation-card).

### Slice 3: Literal sweep — remaining components (offload)

**Goal**: raw font-size/weight/radius/shadow/rgba across `components/` → tokens.

Changes:

- Swap 54/30/53/13/16 literals per snap rules; migrate numeric-radius call sites; disposition comments for legitimate leftovers; audited `lg`→`1.125rem` heading list.
- Extend no-raw-literal guard to all of `components/`.

Proof: tokens vitest scope green; literal counts at 0 modulo disposition comments.

### Slice 4: sr-004 second-channel audit + single visual re-baseline (offload; orchestrator reviews diffs)

**Goal**: status indicators pair color with icon/label; snapshots re-baselined once.

Changes:

- Audit roster zero-state, cluster status pills, toast, retention states for color-only signals; add icon/label [A11Y-06][UI-02].
- Re-baseline `workbench-visual.spec.ts` snapshots.

Proof: axe specs green; visual spec green; every snapshot diff human-reviewed and enumerated in the slice decision.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded frontend guidelines, constitution sr-004, REFA-3 finding lineage before editing.
- [ ] Confirmed no contract boundary touched (frontend-local).

### Checklist for Slice 1: Token foundation

- [ ] `_colors.scss` ramp + roles + functional re-values match spec tables.
- [ ] `_typography.scss` ladder + `md`/`lg` pins.
- [ ] Elevation tokens + `--acx-shadow-card` alias.
- [ ] `design-tokens.test.ts`: dangling-var guard, computed contrast acceptance, alias pins.
- [ ] Tokens vitest scope green; committed.

### Checklist for Slice 2: Hex sweep

- [ ] `_identity-cluster-list.scss` 67 hex → tokens.
- [ ] `_combobox.scss` 13 hex, `_orientation-card.scss` 2 hex → tokens.
- [ ] Guard extended to the three files; vitest green; committed.

### Checklist for Slice 3: Literal sweep

- [ ] font-size/weight/radius/shadow/rgba swept across remaining `components/*.scss`.
- [ ] Numeric-radius aliases migrated; disposition comments placed.
- [ ] `lg` heading-audit list recorded in slice decision.
- [ ] Guard covers all `components/`; vitest green; committed.

### Checklist for Slice 4: Second channel + re-baseline

- [ ] Color-only status indicators paired with icon/label.
- [ ] Snapshots re-baselined once; diffs human-reviewed and enumerated.
- [ ] Axe + visual specs green; committed.

## Review Readiness

- [ ] No boundary-touching implementation (frontend-local) — token/test evidence in each slice.
- [ ] Runtime-parity: visual snapshots + axe specs cover render truth that unit guards can mask.
- [ ] Handoff decision per slice records change, verification, and re-baseline enumeration.

## Success Criteria

- [ ] Zero unguarded raw hex/rgb(a)/font-size/font-weight/border-radius/box-shadow literals in `components/*.scss` (disposition-commented exemptions only), enforced by test.
- [ ] All duty pairs pass computed floors (text 4.5:1, non-text 3:1) [A11Y-01].
- [ ] No dangling `var(--acx-*)` in `styles/`.
- [ ] One 1.125 modular ladder with pinned aliases [TYPE-05].
- [ ] Status indicators carry a second channel [A11Y-06]; axe specs green.
- [ ] Exactly one visual re-baseline commit, human-reviewed.
- [ ] `make check-remote` green on final HEAD.

## Heuristic IDs cited

[COL-02] [COL-03] [COL-04] [COL-05] [COL-06] [COL-09] [LAY-10] [TYPE-02] [TYPE-05] [A11Y-01] [A11Y-06] [A11Y-23] [UI-01] [UI-02] [UI-07] [UI-08] + repo sr-004. All verified present in heuristics-canon lexicons (design-aesthetics, accessibility, engineering) 2026-07-13.
