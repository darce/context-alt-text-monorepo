# Task Plan: REFA-3 — `_workbench.scss` Tokenization

> **Metadata**
>
> - **Date**: 2026-06-07
> - **Author**: Claude (claude-opus-4-8)
> - **Owning Epic**: `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
> - **Epic Short ID**: REFA
> - **Target Branch**: `feature/refa-3`
> - **Review Coverage Target**: 2
>
> Review counts/finding totals are DB-canonical — query via `list_review_runs(task_ref="REFA-3")`.

---

## REFA-3. Tokenize `js/admin/styles/components/_workbench.scss`

## Objective

Replace raw style literals in `_workbench.scss` with `--acx-*` design tokens across **all five sr-004-governed families** — color, radius, font-size, font-weight, shadow — **defining the missing families first**. End state: every sr-004-governed value is token-driven; non-governed values (1px hairline borders, component layout widths) are tokenized via an explicit new family or kept raw with documented rationale.

## Problem Statement

The epic frames REFA-3 as a "low-risk mechanical warm-up: 83 px + 11 hex → tokens." Direct inspection contradicts that framing in **three** material ways:

1. **The "83 px + 11 hex" count severely undercounts the sr-004 surface.** It omits, because they are not `px`: **35 raw `font-size` literals (in `rem`)**, **13 raw `font-weight` literals**, and **1 raw `box-shadow`**. sr-004 governs all of these (`--acx-text-*`, `--acx-font-weight-*`, `--acx-shadow-*`). The real surface is ~5 families and ~143 literals, and the **largest single family is font-size (35 sites)** — entirely absent from the epic deliverable.
2. **The token surface is incomplete.** `tokens/` defines only `_colors.scss`, `_spacing.scss` (8 steps), `_typography.scss` (base size + line-height). There are **no** `--acx-radius-*`, `--acx-text-*` scale, `--acx-font-weight-*`, `--acx-gray-*`, shadow-beyond-dialog, border-width, or size families.
3. **`--acx-radius-*` and `--acx-text-*` are referenced but defined nowhere** — 18 `var(--acx-radius-…)`/`var(--acx-text-…)` usages across `_workbench.scss` + `_media-selection.scss` resolve to *undefined custom properties today*, so those elements currently render with **0 border-radius (square corners)** and font-size fallback. Defining those families — required to tokenize the raw radii/sizes — changes rendering at all 18 sites. This is a **deliberate, reviewed visual correction**, not a behavior-preserving swap, and its blast radius extends beyond `_workbench.scss`.

So REFA-3 is not a literal-for-token substitution. It is: define five token families (design decisions, incl. consolidating a 9-value ad-hoc font scale into a clean ramp), accept/verify rendering corrections on currently-broken sites, then swap. The plan must be honest about this or the epic's "a11y/visual unchanged" exit criterion is unachievable.

## Constraints

- **sr-004 scope is the authority, not raw px count.** sr-004 governs color, font-size (`--acx-text-*`), font-weight (`--acx-font-weight-*`), shadow (`--acx-shadow-*`), radius (`--acx-radius-*`). It does **not** mandate tokens for border-width or arbitrary layout widths. The exit criterion is defined against sr-004 family coverage, not "zero raw px."
- **Behavior-preserving except deliberate, reviewed corrections.** No HTML/JS, class-rename, or layout-structure change. Two intentional rendered changes are allowed *only with explicit review + re-baseline*: (a) defining the referenced-but-undefined radius/text tokens; (b) snapping near-duplicate font-sizes onto a shared `--acx-text-*` step. Neither may be slipped in as "unchanged."
- **Cross-file blast radius.** Defining `--acx-radius-*`/`--acx-text-*` in `tokens/` affects every consumer (`_media-selection.scss` +6 radius refs, plus any `--acx-text-*` users). REFA-3 owns the family definitions, so it verifies those consumers too — not only `_workbench.scss`.
- **Reuse existing token names; semantic is canonical (decided, PR-02).** `--acx-radius-sm/md/lg`, `--acx-radius-8/10`, and `--acx-text-sm` are already *used*. Define the **semantic** scale (`sm/md/lg`) as canonical; define `--acx-radius-8`/`--acx-radius-10` as **aliases** (`var(--acx-radius-md)` etc.) so existing refs resolve without a parallel scale, and migrate the numeric refs to semantic where touched. Do not invent new numeric names.
- **Two Hats (Fowler Ch2).** No `acx/v1` or feature changes. Token swap only.
- **npm for Node tooling; Composer for PHP** (sr-003). Add to the shared token surface before consuming (sr-004).

## Workflow Principles

- One token *family* (or one cohesive pair) per slice, each independently reviewable with its own build + a11y + visual proof.
- Token-family definitions land before their first consumer; foundation slice owns all family definitions and the rendering corrections they trigger.
- A raw value with no sr-004-governed family stays raw *with a one-line rationale comment* rather than force-fit into an ill-suited family (no spacing-token-as-radius, no one-off `--acx-text-0.68`).
- Font-scale consolidation snaps are enumerated and reviewed, never silent.

## Terminology

- **sr-004-governed**: a literal whose role is color, font-size, font-weight, shadow, or border-radius. Border-width and component layout widths are explicitly *out of sr-004 scope*.
- **Undefined-token reference**: `var(--acx-foo)` where `--acx-foo` is declared nowhere in source → resolves to invalid → declaration dropped at render.
- **Consolidation snap**: mapping a near-duplicate ad-hoc size (e.g. `0.85rem` vs `0.875rem`) onto one shared `--acx-text-*` step — a small intentional visual change.
- **Re-baseline**: capturing a new visual/a11y reference *after* a reviewed intentional change, replacing the implicit (broken) prior state.

## Current State Analysis

Measured against `_workbench.scss` @ `feature/refa-3` HEAD (`0931284532d7`):

- **Color**: 11 hex. 8 map to *existing* `--acx-color-*` (e.g. `#92400e`→`warning-pill-text`, `#fef3c7`→`warning-pill-bg`, `#f59e0b`→`warning-border`); **3 have no exact token** — `#3b82f6`, `#f0f7ff`, `#ccdfff` → new color tokens. Plus an `rgba(0,0,0,0.1)` inside the raw shadow.
- **Radius**: raw `999px`×4 (pills), `50%`×3 (circles), `4/6/10px`; spacing-token-as-radius `border-radius: var(--acx-space-8)` (lines 80, 278, 377) and `var(--acx-space-4)` (461); and `var(--acx-radius-md/sm/lg)` (lines 631, 704, 726, 790, 904, 936, 973, 986, 1003, 1096) that are **undefined**.
- **Font-size**: **35 raw `font-size`** declarations across **9 distinct rem values** — `0.68 / 0.7 / 0.75 / 0.8 / 0.85 / 0.875 / 0.9 / 0.95 / 1rem`. Near-duplicates (`0.85`/`0.875`/`0.9`) make a clean scale impossible without consolidation snaps. `var(--acx-text-sm)` is already used once (line 961) but **undefined**.
- **Font-weight**: **13 raw `font-weight`** across 3 values — `400 / 600 / 700`. No `--acx-font-weight-*` family exists.
- **Shadow**: **1 raw `box-shadow: 0 4px 12px rgba(0,0,0,0.1)`** (line 568). Existing shadow tokens are dialog-only.
- **Spacing/size px**: 83 raw `px` — `1px`×27 (hairline borders), `999px`×4 (counted under radius), `2/4/6/8/10/12/24/26/32/40/48/68/80/96px` (spacing) and `144–480px` (≈11 component widths). **None occur inside `@media` conditions** (verified) — all tokenizable in principle.
- **Undefined families**: `--acx-radius-*` / `--acx-text-*` / `--acx-font-weight-*` / `--acx-gray-*` defined nowhere in source (grep across scss/css/php/ts, excl. `node_modules`/`public`): 18 dangling `var()` references repo-wide.
- **Verification baseline reality**: only **axe a11y** specs exist (`tests/e2e/a11y/workbench-axe.spec.ts`), requiring a live LocalWP `baseURL`. There is **no `toHaveScreenshot` visual baseline** anywhere in `tests/`. The epic's "visual snapshot unchanged" verification does not currently exist.

## Target Outcome

`tokens/` gains `_radius.scss` (`--acx-radius-sm/md/lg/8/10` + pill + circle), an extended `_typography.scss` (`--acx-text-*` ramp grounded in the existing sizes + `--acx-font-weight-*`), a card `--acx-shadow-*`, and 3 new colors. `_workbench.scss` uses only `--acx-*` for color, radius, font-size, font-weight, and shadow; spacing literals map to `--acx-space-*`; the spacing-token-as-radius misuse is corrected; `1px` borders and layout widths are tokenized via an explicit family or kept raw with rationale. Currently-square radius sites and font-scale snaps render as reviewed corrections captured in a new baseline. All consumers of newly-defined families (incl. `_media-selection.scss`) are verified.

## Context Loading

- Rules: `docs/workbay/rules/frontend-guidelines.md`, sr-004 (CLAUDE.md Short Rules)
- Token surface: `js/admin/styles/tokens/_colors.scss`, `_spacing.scss`, `_typography.scss`; `js/admin/styles/main.scss` (`@use` graph)
- Consumers of undefined families: `js/admin/styles/components/_media-selection.scss`
- Tests: `tests/e2e/a11y/workbench-axe.spec.ts`, `playwright.config.ts`
- Handoff/MCP: task `REFA-3`; epic `docs/epics/v0.4.1/wp-alt-context-structural-refactor-epic.md`
- `ctx7`: not required.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `--acx-*` token surface (`tokens/`) | frontend | implicit; radius/text families referenced-but-undefined | **add** `--acx-radius-*`, `--acx-text-*`, `--acx-font-weight-*`, card shadow, 3 colors | no — additive; greenfield, no external consumer | build green; all `var(--acx-…)` in workbench + media-selection resolve |
| `acx/v1` REST | backend | n/a | none | n/a | n/a |
| Rendered DOM/JS | frontend | n/a | none (CSS-only) | n/a | axe a11y + visual review |

## Proposed Solution

Five slices, foundation-first. Slice 1 defines all token families and owns the intentional radius + font-scale corrections with explicit visual review + new baseline. Slices 2–5 are family-scoped swaps within `_workbench.scss`, each green on build + axe + visual review. The authoritative disposition of every literal (tokenized vs intentionally raw) is a Slice-5 deliverable.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tokens | `js/admin/styles/tokens/_radius.scss` (new) | define `--acx-radius-sm/md/lg/8/10` + pill + circle |
| tokens | `js/admin/styles/tokens/_typography.scss` | add `--acx-text-*` ramp + `--acx-font-weight-*` |
| tokens | `js/admin/styles/tokens/_colors.scss` | add 3 colors (`#3b82f6`, `#f0f7ff`, `#ccdfff`) + card shadow token |
| tokens | `js/admin/styles/main.scss` | `@use './tokens/radius'` |
| styles | `js/admin/styles/components/_workbench.scss` | swap color/radius/font-size/font-weight/shadow/spacing; document kept-raw values |
| tests | `tests/e2e/` (new `toHaveScreenshot` workbench spec) + `tests/e2e/a11y/` | required visual baseline (Slice 1) + re-run axe |

## Related Files

| File | Note |
| --- | --- |
| `js/admin/styles/components/_media-selection.scss` | consumes 6 undefined `--acx-radius-*` — rendering changes when Slice 1 defines them; must be verified |
| `js/admin/styles/components/*.scss` | any other `--acx-text-*`/`--acx-radius-*` consumers inherit the new definitions |
| `playwright.config.ts` | a11y/visual project wiring; requires LocalWP `baseURL` |

## Verification Strategy

- Deterministic / build:
  - `npm run build` (Vite — SCSS must compile with new `@use`)
  - `npm run lint && npm run format` (no new violations)
  - `grep -nE 'font-size:\s*[0-9]|font-weight:\s*[0-9]|#[0-9a-fA-F]{3,8}\b|box-shadow:\s*[0-9]' …/_workbench.scss` → only documented exceptions remain
  - cross-check every `var(--acx-…)` repo-wide against defined names → **zero dangling references**
- Runtime-parity / a11y (requires LocalWP):
  - `npm run a11y:localwp` (workbench-axe — no serious/critical violations)
- Visual (durable — required, not optional):
  - Slice 1 adds a `toHaveScreenshot` workbench spec (none exists today): capture pre-change, accept the radius-correction baseline. Slices 2–5 run it as an automated guard. The only intended baseline refresh after Slice 1 is the font-snap delta in Slice 4 (reviewed against the snap map).
- Manual:
  - Operator opens workbench in LocalWP; confirms pills/cards/tabs/typography render as intended.

## Slice Delivery

### Slice 1: Token-surface foundation + visual guard + radius correction

**Goal**: Add every missing family to `tokens/`, establish the durable visual baseline, and review the radius correction that defining the dangling tokens triggers.

Changes:
- New `tokens/_radius.scss`: semantic `--acx-radius-sm/md/lg` (canonical) + `pill` + `circle`; `--acx-radius-8`/`--acx-radius-10` as aliases of the semantic steps (PR-02). Values grounded in the raw radii being replaced (4/6/8/10px, 999px, 50%).
- Extend `_typography.scss`: `--acx-text-*` ramp consolidating the 9 ad-hoc sizes into a documented step set + a recorded **snap map** (raw value → step); `--acx-font-weight-normal/semibold/bold` (400/600/700). This slice only *defines* the ramp — the 35 raw `font-size` swaps that make the snaps visible land in Slice 4.
- `_colors.scss`: add `#3b82f6`/`#f0f7ff`/`#ccdfff` + a card `--acx-shadow-*`.
- **Add a required `toHaveScreenshot` workbench spec** (empty + seeded) under `tests/e2e/` (PR-03) — capture the pre-change baseline *before* wiring `@use`, then accept the corrected baseline after, so Slices 2–5 inherit an automated visual guard.
- No `_workbench.scss` literal swaps yet — this slice is the token surface + the rendering correction it triggers at the existing `var()` sites.

Scope of this slice's rendered delta (PR-01): defining `--acx-radius-*` corrects 18 dangling-radius sites (workbench + `_media-selection.scss`, square→rounded); defining `--acx-text-sm` corrects the single existing `--acx-text-sm` ref (`_workbench.scss:961`). The 34 *raw* font-size snaps are **not** in this baseline — they render in Slice 4.

Proof:
- `npm run build` green; every `var(--acx-radius-…)`/`var(--acx-text-…)` in workbench + `_media-selection.scss` resolves (zero dangling refs repo-wide).
- `toHaveScreenshot` baseline established; the radius correction diff (workbench + media-selection) is reviewed and accepted as the new baseline. `npm run a11y:localwp` green.

### Slice 2: Color + shadow → tokens

**Goal**: Replace 11 hex and the raw `box-shadow` in `_workbench.scss`.

Changes:
- Each hex → `--acx-color-*` (8 existing + 3 added); `box-shadow` (line 568) → card `--acx-shadow-*`.

Proof:
- Zero raw hex/shadow in `_workbench.scss`; build + `a11y:localwp` green; visual unchanged vs Slice-1 baseline.

### Slice 3: Radius literals → radius tokens; fix spacing-as-radius

**Goal**: Replace raw `999px`/`50%`/`4-10px` radii and correct `border-radius: var(--acx-space-*)`.

Changes:
- `999px`→pill, `50%`→circle, `4/6/10px`→`--acx-radius-*`; lines 80/278/377/461 corrected from space-token to radius-token.

Proof:
- Zero raw radius literals and zero `border-radius: var(--acx-space-*)`; build + a11y green; visual unchanged vs baseline.

### Slice 4: Font-size + font-weight → tokens (owns the font-snap delta)

**Goal**: Replace 35 `font-size` and 13 `font-weight` literals, and review the consolidation-snap visual delta this slice produces.

Changes:
- Each `font-size` → `--acx-text-*` per the Slice-1 snap map.
- Each `font-weight` → `--acx-font-weight-normal/semibold/bold`.

Proof:
- Zero raw `font-size`/`font-weight` in `_workbench.scss`; build + `a11y:localwp` green.
- **This slice introduces the 34 font-snap pixel changes** (PR-01): review the `toHaveScreenshot` diff, confirm each snap matches the recorded snap map, and accept the refreshed baseline. Snaps must be intentional and enumerated — no unexplained size drift.

### Slice 5: Spacing/size sweep + literal disposition

**Goal**: Map spacing px to `--acx-space-*`, decide layout-width and `1px`-border policy, record disposition of every literal.

Changes:
- Spacing px → `--acx-space-*` (add 6/10/40/80px steps only where no acceptable nearest-step exists; never silently round).
- Layout widths (`144–480px`) and `1px` borders: tokenize via explicit `--acx-size-*`/border-width family **or** keep raw with a one-line rationale comment.
- Inline note recording which literal categories are tokenized vs intentionally raw.

Proof:
- Disposition documented; all 5 sr-004 families fully tokenized; build + lint + `a11y:localwp` green; final visual matches the refreshed baseline (radius correction from Slice 1, font snaps from Slice 4).

---

## Consolidated Checklist

## Context and Ownership

- [x] Loaded sr-004, frontend-guidelines, and the `tokens/` surface before editing.
- [x] Confirmed `ctx7` not required.
- [x] Recorded that REFA-3 owns the `--acx-radius-*`/`--acx-text-*`/`--acx-font-weight-*` family definitions (cross-file blast radius incl. `_media-selection.scss`).

### Checklist for Slice 1: Token-surface foundation + visual guard + radius correction

- [x] `tokens/_radius.scss` defines semantic `--acx-radius-sm/md/lg` + pill + circle; `--acx-radius-8/10` aliased to semantic (PR-02); `@use` wired.
- [x] `_typography.scss` defines `--acx-text-*` ramp + documented font-size snap map + `--acx-font-weight-*`.
- [x] 3 colors + card shadow added to `_colors.scss`.
- [x] Zero dangling `var(--acx-radius-…)`/`var(--acx-text-…)` repo-wide.
- [x] Required `toHaveScreenshot` workbench spec added (pre-change captured, corrected baseline accepted).
- [x] Radius correction (workbench + `_media-selection.scss`) reviewed + accepted as new baseline; build + `a11y:localwp` green. (Raw font-size snaps deferred to Slice 4 — PR-01.)

### Checklist for Slice 2: Color + shadow

- [x] 11 hex → `--acx-color-*`; raw `box-shadow` → card `--acx-shadow-*`.
- [x] Zero raw hex/shadow remain; build + a11y green; visual unchanged vs baseline.

### Checklist for Slice 3: Radius literals + spacing-as-radius fix

- [x] Raw `999px`/`50%`/`4-10px` radii → radius tokens.
- [x] `border-radius: var(--acx-space-*)` (80/278/377/461) corrected to radius tokens.
- [x] Zero raw radius literals; build + a11y green; visual unchanged vs baseline.

### Checklist for Slice 4: Font-size + font-weight (owns font-snap delta)

- [x] 35 `font-size` → `--acx-text-*` per snap map; 13 `font-weight` → `--acx-font-weight-*`.
- [x] Zero raw `font-size`/`font-weight` remain; build + `a11y:localwp` green.
- [x] `toHaveScreenshot` diff reviewed against the snap map; each delta intentional; baseline refreshed (PR-01).

### Checklist for Slice 5: Spacing/size sweep + disposition

- [x] Spacing px → `--acx-space-*`; new steps added only where no acceptable nearest mapping; no silent rounding.
- [x] Layout-width + `1px`-border policy decided and documented.
- [x] Disposition of every literal recorded; all 5 sr-004 families fully tokenized; build + lint + a11y green.

## Review Readiness

- [x] No boundary-touching change without matching evidence (token defs + resolving `var()` references verified).
- [x] The intentional radius + font-snap corrections are explicitly reviewed and re-baselined, not slipped in as "unchanged."
- [x] Handoff decision records the family additions, the corrections, and the cross-file blast radius.

## Stretch Goals

- [x] Clean the same undefined-radius references in `_media-selection.scss` in-task (swap its 6 `var(--acx-radius-*)` consumers to the now-canonical semantic names) if review wants the consumer cleaned here; else leave to its own task. (Verification of those sites is already required by Slice 1.)

## Success Criteria

- [x] Zero sr-004-governed raw literals (color, radius, font-size, font-weight, shadow) in `_workbench.scss`; spacing on `--acx-space-*`.
- [x] Zero dangling `--acx-radius-*`/`--acx-text-*`/`--acx-font-weight-*` references repo-wide.
- [x] `npm run build`, `npm run lint`, `npm run a11y:localwp` green.
- [x] `toHaveScreenshot` workbench guard exists and passes against the final baseline (radius correction in Slice 1, font snaps in Slice 4).
- [x] `_media-selection.scss` consumers of the newly-defined radius tokens verified.
- [x] Disposition of every literal (tokenized vs intentionally raw) documented; font-size snap map recorded.

## Resolved Planning Decisions

Decisions made during planning-review (findings `REFA-3-PA-01/02/04/05/06`, `PR-01/02/03`):

- [x] **Epic reconciliation (PA-01/02/04)**: epic Phase 2 (Problem Statement, deliverable, exit criterion, Current State row, checklist) updated to enumerate all 5 sr-004 families, reclassify the exit from "visual unchanged" to "matches a re-reviewed baseline incorporating the radius/font correction," and note the cross-file (`_media-selection.scss`) token-surface ownership. REFA-3 plan is the authoritative scope.
- [x] **Font-scale consolidation (PA-05)**: **snap** the 9 ad-hoc sizes onto a small documented `--acx-text-*` ramp; record the snap map in Slice 1; the resulting deltas are reviewed/re-baselined in Slice 4. (Per-value tokens rejected — defeats the design-token purpose.)
- [x] **Layout widths + 1px borders (PA-06)**: **kept raw with a one-line rationale comment** — out of sr-004 scope; no `--acx-size-*`/border-width family introduced (avoids scope creep). Exit criterion is sr-004 family coverage, not literal `px` count.
- [x] **Radius naming (PR-02)**: semantic `--acx-radius-sm/md/lg` canonical; numeric `8/10` defined as aliases; migrate numeric refs to semantic where touched.
- [x] **Slice ownership of visual delta (PR-01)**: Slice 1 owns the radius correction + visual baseline; Slice 4 owns the font-snap delta. Each slice reviews the change it introduces.
- [x] **Visual guard (PR-03)**: a `toHaveScreenshot` workbench baseline is a **required** Slice-1 deliverable, not a stretch goal.
