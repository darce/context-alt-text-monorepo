# Refactoring Evaluation: UI Design System

> Cross-referencing Adam Wathan and Steve Schoger's "Refactoring UI" (2018) against the Alt Context frontend to identify visual design system gaps and improvement opportunities.

**Date:** 2025-07-17
**Scope:** TypeScript frontend styles and components (`apps/prototype-wp-alt-context/js/admin/`)
**Method:** Systematic evaluation of CSS/SCSS tokens, component styling patterns, and UI implementation against each major section of the book.
**Cross-reference:** This document focuses exclusively on visual design patterns (CSS/SCSS tokens, layout, typography, color). No duplicate findings exist with [refactoring-evaluation.md](refactoring-evaluation.md) (Fowler/Beck; code structure across all stacks) or [refactoring-typescript-evaluation.md](refactoring-typescript-evaluation.md) (Hickey; TypeScript code health). The three evaluations are complementary and orthogonal.

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Methodology](#methodology)
- [What the Codebase Does Well](#what-the-codebase-does-well)
- [High-Impact Findings](#high-impact-findings)
  - [H1: Missing Type Scale; ad-hoc font sizes throughout](#h1-missing-type-scale-ad-hoc-font-sizes-throughout)
  - [H2: Incomplete Gray Scale; hardcoded hex values without tokens](#h2-incomplete-gray-scale-hardcoded-hex-values-without-tokens)
  - [H3: No Elevation System; ad-hoc box-shadow literals](#h3-no-elevation-system-ad-hoc-box-shadow-literals)
  - [H4: Color-Only Status Indicators](#h4-color-only-status-indicators)
- [Medium-Impact Findings](#medium-impact-findings)
  - [M1: Undefined Radius Tokens; referenced but not declared](#m1-undefined-radius-tokens-referenced-but-not-declared)
  - [M2: Inconsistent Focus Ring Styles](#m2-inconsistent-focus-ring-styles)
  - [M3: No Responsive Breakpoint System](#m3-no-responsive-breakpoint-system)
  - [M4: Missing Text Tertiary Color](#m4-missing-text-tertiary-color)
  - [M5: Font Weight Tokens Absent](#m5-font-weight-tokens-absent)
- [Low-Impact Findings](#low-impact-findings)
  - [L1: No Button Tertiary/Ghost Variant](#l1-no-button-tertiaryghost-variant)
  - [L2: Inconsistent Empty State Treatment](#l2-inconsistent-empty-state-treatment)
  - [L3: HSL Not Used Systematically](#l3-hsl-not-used-systematically)
- [Design System Maturity Assessment](#design-system-maturity-assessment)
- [Recommended Improvement Sequence](#recommended-improvement-sequence)

---

## Executive Summary

The frontend design system has a strong foundation in spacing tokens (`--acx-space-*`), semantic color naming (`--acx-color-*`), and user-uploaded content handling (`object-fit` discipline). The primary gaps are in typography, neutral colors, and elevation; areas where "Refactoring UI" prescribes systematic, token-based scales rather than ad-hoc values.

| Book Section          | Assessment                  | Key Gap                                                                                                       |
| --------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Starting from Scratch | N/A (project already built) | --                                                                                                            |
| Hierarchy             | Partial                     | Button hierarchy exists (primary/secondary/danger) but no tertiary variant; text hierarchy limited to 2 tiers |
| Layout and Spacing    | Excellent                   | 8px-based spacing scale with consistent token usage                                                           |
| Designing Text        | Weak                        | No type scale tokens; font sizes are ad-hoc literals; no font-weight tokens                                   |
| Working with Color    | Good                        | Semantic color tokens exist; gap is gray scale (no `--acx-gray-*` 100-900 scale)                              |
| Creating Depth        | Weak                        | Only 2 shadow tokens (dialog-only); all other shadows are hardcoded                                           |
| Working with Images   | Excellent                   | `object-fit: cover`, `aspect-ratio` discipline; avatar circle pattern                                         |
| Finishing Touches     | Good                        | Accent borders on toasts; dashed borders on empty states; but no systematic status icon pairing               |

**Top 3 improvements by payoff:**

1. **Define a type scale** (`--acx-text-xs` through `--acx-text-2xl`) with paired font-size + line-height values; replace all ad-hoc font-size literals. This addresses the book's core typography advice and creates a single source of truth.
2. **Define a gray scale** (`--acx-gray-50` through `--acx-gray-950`); replace hardcoded hex values like `#e2e8f0` and `#f1f5f9`. Maintains the Slate palette already used via comments but makes it official.
3. **Create an elevation scale** (4-5 shadow levels from subtle to floating); replace the 6+ ad-hoc `box-shadow` declarations scattered across components.

---

## Methodology

### Book Concepts Applied

Each section of "Refactoring UI" was evaluated against the actual SCSS tokens, component styles, and React rendering patterns:

| Section             | Key Prescriptions                                                                                                                                                |
| ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hierarchy           | 3 text colors (dark/grey/lighter); 2 font weights (normal/bold); button hierarchy (primary solid, secondary outline, tertiary link-style); labels as last resort |
| Layout and Spacing  | Spacing system with non-linear scale (base-16); don't fill whole screen; avoid ambiguous spacing between groups                                                  |
| Designing Text      | Hand-crafted type scale (5-7 sizes); avoid em units; line-height inversely proportional to font size; line length 45-75 chars; tighten headlines, widen all-caps |
| Working with Color  | HSL over hex; define shades up front (8-10 per color); separate greys, primary, and accent palettes; don't let lightness kill saturation                         |
| Creating Depth      | Simulate light source; small shadows for buttons, medium for dropdowns, large for modals; establish fixed elevation system (5 levels); two-part shadows          |
| Working with Images | Use good photos; consistent contrast for text over images; don't scale icons beyond intended size; control user-uploaded aspect ratios                           |
| Finishing Touches   | Supercharge defaults (custom bullets, checkboxes); accent borders; fewer borders (use shadows/spacing instead); design empty states                              |

### Evaluation Strategy

Token files (`tokens/_colors.scss`, `tokens/_spacing.scss`, `tokens/_typography.scss`) were compared against the book's prescribed token surfaces. Each component SCSS file was checked for ad-hoc values that should reference tokens. React components were checked for visual hierarchy patterns, empty state handling, and accessibility.

---

## What the Codebase Does Well

These patterns align well with "Refactoring UI" prescriptions and should be preserved:

### 1. Spacing System (Book: "Layout and Spacing")

[tokens/\_spacing.scss](../../../apps/prototype-wp-alt-context/js/admin/styles/tokens/_spacing.scss) defines a systematic 8px base scale: `--acx-space-2` (0.125rem) through `--acx-space-48` (3rem). Components consistently reference these tokens for gap, padding, and margin. This exactly matches the book's advice to use a non-linear spacing scale and avoid ambiguous spacing.

### 2. Semantic Color Naming (Book: "Working with Color")

[tokens/\_colors.scss](../../../apps/prototype-wp-alt-context/js/admin/styles/tokens/_colors.scss) uses intent-based naming:

- Surface: `--acx-color-surface`, `--acx-color-surface-alt`
- Text: `--acx-color-text`, `--acx-color-text-muted`
- Semantic: `--acx-color-danger`, `--acx-color-success`, `--acx-color-warning-*` with `-soft` and `-border` variants
- Accent: `--acx-color-accent`, `--acx-color-accent-contrast`

This follows the book's advice to separate primary, accent, and semantic color palettes.

### 3. User-Uploaded Content (Book: "Working with Images")

Components consistently use `aspect-ratio: 1` + `object-fit: cover` for thumbnails and grid items. Avatar images use `border-radius: 50%` for natural background bleed prevention. Media preview mode uses `object-fit: contain` where non-cropped display is appropriate. This matches the book's "control the shape and size" advice.

### 4. Empty State Pattern (Book: "Finishing Touches")

A dedicated `.acx-apply-panel--empty` class provides dashed border, centered layout, heading + description + CTA buttons. Used in `BatchTabContent.tsx`, `ScanTabContent.tsx`. This follows the book's advice to make empty states a priority.

### 5. Button Hierarchy (Book: "Hierarchy")

Primary (`--acx-color-accent` background, white text), secondary (surface background, border), and danger variants exist. This matches the book's primary/secondary/destructive button treatment.

### 6. Accent Border Pattern (Book: "Finishing Touches")

Toasts use `border-left: 4px solid var(--acx-color-success|error)` as a status indicator. This matches the book's "add color with accent borders" technique.

### 7. Responsive Grid Layouts (Book: "Layout and Spacing")

Dashboard and cluster grid use `grid-template-columns: repeat(auto-fit, minmax(240px, 1fr))` and `auto-fill` patterns. This avoids the fixed breakpoint grids the book warns against.

---

## High-Impact Findings

### H1: Missing Type Scale; ad-hoc font sizes throughout

**Book reference:** "Designing Text"; "Define a hand-crafted type scale with 5-7 sizes."

**Token surface:** [tokens/\_typography.scss](../../../apps/prototype-wp-alt-context/js/admin/styles/tokens/_typography.scss) defines only 3 tokens:

- `--acx-font-sans`: Inter + system fallbacks
- `--acx-font-size-base`: 16px
- `--acx-line-height-base`: 1.5

**Evidence of ad-hoc sizes across component files:**

| File                          | Value                           | Purpose                    |
| ----------------------------- | ------------------------------- | -------------------------- |
| `_dashboard.scss`             | `0.75rem`                       | Eyebrow text               |
| `_dashboard.scss`             | `1.75rem`                       | Page title                 |
| `_dashboard.scss`             | `1.5rem`                        | Stat value                 |
| `_dashboard.scss`             | `0.85rem`                       | Combobox text              |
| `_identity-cluster-list.scss` | `10px`                          | Count badge                |
| `_cluster-panels.scss`        | `1.25rem`, `0.875rem`, `1.5rem` | Various heading/body roles |

No `--acx-text-*` scale exists. Font sizes are repeated across files with slight variations (`0.85rem` vs `0.875rem`) that may be unintentional.

**Impact:** Without a type scale, there is no single source of truth for "what size should a label be?" Designers and developers independently pick sizes, leading to inconsistent visual rhythm. The book prescribes 5-7 defined sizes with paired line-height values.

**Remedy:** Define `--acx-text-xs` through `--acx-text-2xl` in `_typography.scss`:

```scss
:root {
  --acx-text-xs: 0.75rem; // 12px; line-height: 1rem
  --acx-text-sm: 0.875rem; // 14px; line-height: 1.25rem
  --acx-text-base: 1rem; // 16px; line-height: 1.5rem
  --acx-text-lg: 1.125rem; // 18px; line-height: 1.75rem
  --acx-text-xl: 1.25rem; // 20px; line-height: 1.75rem
  --acx-text-2xl: 1.5rem; // 24px; line-height: 2rem
  --acx-text-3xl: 1.75rem; // 28px; line-height: 2.25rem
}
```

---

### H2: Incomplete Gray Scale; hardcoded hex values without tokens

**Book reference:** "Working with Color"; "You'll need 8-10 shades of grey."

**Evidence:** Component files reference Tailwind Slate colors by hex with comments:

- `_identity-cluster-list.scss:9`: `#e2e8f0 // slate-200`
- `_identity-cluster-list.scss:25`: `#f1f5f9 // slate-100`
- Multiple references to `#0f172a` (slate-900), `#475569` (slate-600) via tokens

No `--acx-gray-*` token scale exists. The semantic tokens (`--acx-color-text`, `--acx-color-surface`) use specific gray shades but intermediate values are hardcoded. When a component needs "slightly darker than the surface but lighter than the border," there is no token to reach for.

**Impact:** The book warns that 3-4 gray shades quickly feel constraining. Without a full scale, developers pick arbitrary hex codes, creating visual drift between components.

**Remedy:** Define `--acx-gray-50` through `--acx-gray-950` using the Slate palette already in use, then reference these tokens from both semantic tokens and component styles:

```scss
:root {
  --acx-gray-50: #f8fafc;
  --acx-gray-100: #f1f5f9;
  --acx-gray-200: #e2e8f0;
  --acx-gray-300: #cbd5e1;
  --acx-gray-400: #94a3b8;
  --acx-gray-500: #64748b;
  --acx-gray-600: #475569;
  --acx-gray-700: #334155;
  --acx-gray-800: #1e293b;
  --acx-gray-900: #0f172a;
  --acx-gray-950: #020617;

  // Semantic tokens reference the scale:
  --acx-color-text: var(--acx-gray-900);
  --acx-color-text-muted: var(--acx-gray-600);
  --acx-color-surface: var(--acx-gray-50);
  --acx-color-border: var(--acx-gray-200);
}
```

---

### H3: No Elevation System; ad-hoc box-shadow literals

**Book reference:** "Creating Depth"; "Define a fixed set of shadows; five options is usually plenty."

**Token surface:** Only 2 shadow tokens exist, both for dialogs:

- `--acx-shadow-dialog-primary`: `0 20px 25px -5px rgb(15 23 42 / 20%)`
- `--acx-shadow-dialog-secondary`: `0 10px 10px -5px rgb(15 23 42 / 10%)`

**Evidence of ad-hoc shadows scattered across files:**

| File                 | Value                            | Purpose                  |
| -------------------- | -------------------------------- | ------------------------ |
| `_toast.scss`        | `0 4px 12px rgba(0,0,0,0.15)`    | Toast notifications      |
| `_dashboard.scss`    | `0 1px 3px rgba(0,0,0,0.05)`     | Dashboard cards (subtle) |
| `_cluster-grid.scss` | `0 4px 12px rgba(0,0,0,0.1)`     | Card hover effect        |
| `_cluster-grid.scss` | `0 8px 32px rgba(0,0,0,0.15)`    | Zoom overlay / lightbox  |
| `_roster.scss`       | `0 4px 6px -1px rgba(0,0,0,0.1)` | Combobox dropdown        |

**Impact:** The book prescribes a 5-level elevation system (raised, dropdown, sticky, overlay, modal) so that shadow choice communicates depth hierarchy semantically. Currently, a toast and a card hover use near-identical shadows despite representing different elevation levels.

**Remedy:** Define 5 elevation tokens:

```scss
:root {
  --acx-shadow-xs: 0 1px 2px 0 rgb(0 0 0 / 0.05); // Cards, subtle raise
  --acx-shadow-sm:
    0 1px 3px 0 rgb(0 0 0 / 0.1), 0 1px 2px -1px rgb(0 0 0 / 0.1); // Buttons, interactive elements
  --acx-shadow-md:
    0 4px 6px -1px rgb(0 0 0 / 0.1), 0 2px 4px -2px rgb(0 0 0 / 0.1); // Dropdowns, combobox
  --acx-shadow-lg:
    0 10px 15px -3px rgb(0 0 0 / 0.1), 0 4px 6px -4px rgb(0 0 0 / 0.1); // Toasts, sticky panels
  --acx-shadow-xl:
    0 20px 25px -5px rgb(0 0 0 / 0.1), 0 8px 10px -6px rgb(0 0 0 / 0.1); // Modals, dialogs, overlays
}
```

Note: The book recommends two-part shadows for most levels (ambient + direct light simulation).

---

### H4: Color-Only Status Indicators

**Book reference:** "Don't rely on color alone"; "Always use color to support something that your design is already saying."

**Evidence:**

- `_toast.scss` (lines 27-43): Toasts use `border-left: 4px solid` with color variants (success green, error red, info blue) as the primary visual signal. While the toast message text may clarify intent, the color border alone differentiates success from error for quick visual scanning.
- `_dashboard.scss` (lines 118-127): Status pill badges use background color for semantics.

**Impact:** The book specifically warns: "be careful not to rely on [color], or users with color blindness will have a hard time interpreting your UI." A red-green colorblind user cannot distinguish success from error toasts by border color alone.

**Remedy:** Pair each status color with an icon:

- Success: checkmark icon + green border
- Error: X or exclamation icon + red border
- Warning: triangle icon + yellow border
- Info: info-circle icon + blue border

Check whether the React implementation already renders icons in toast bodies; if so, ensure they are always present (not optional) and that icon + text provide sufficient differentiation without color.

---

## Medium-Impact Findings

### M1: Undefined Radius Tokens; referenced but not declared

**Book reference:** Implied in "Personality" section; border-radius is part of a design's visual identity.

**Evidence:** Component styles reference `var(--acx-radius-lg)` and `var(--acx-radius-md)` (e.g., `_workbench.scss` lines 478-479) but these are **not declared** in any token file. Actual border-radius values are hardcoded literals: `0.75rem`, `12px`, `8px`, `6px`, `4px`, `50%`.

**Impact:** Undefined CSS custom properties resolve to their fallback value or the `initial` value, which for `border-radius` is `0`. This may cause visual inconsistencies depending on fallback declarations.

**Remedy:** Declare radius tokens in `_typography.scss` or a new `_borders.scss`:

```scss
:root {
  --acx-radius-sm: 4px;
  --acx-radius-md: 6px;
  --acx-radius-lg: 8px;
  --acx-radius-xl: 12px;
  --acx-radius-full: 50%;
}
```

---

### M2: Inconsistent Focus Ring Styles

**Book reference:** Accessibility is a thread throughout the book; "Accessible doesn't have to mean ugly."

**Evidence:**

- `_combobox.scss` (lines 22-24): `outline: 2px solid #0f172a; outline-offset: 2px` (hardcoded color)
- `_checkbox.scss` (lines 20-22): `outline: 2px solid var(--acx-color-accent); outline-offset: 2px` (token-based)
- `_dialog.scss` (lines 25-26): `outline: none` on dialog content (removes focus ring entirely)

Three different approaches to focus rings across three components. Users navigating by keyboard see inconsistent visual feedback.

**Remedy:** Define a single focus token and apply consistently:

```scss
:root {
  --acx-focus-ring: 2px solid var(--acx-color-accent);
  --acx-focus-offset: 2px;
}
```

---

### M3: No Responsive Breakpoint System

**Book reference:** "Layout and Spacing"; while the book says "grids are overrated," it still prescribes deliberate layout decisions at different viewport sizes.

**Evidence:** Only one `@media` query found across all component styles:

- `_orientation-card.scss` (lines 45, 91): `@media (max-width: 768px)` for stack layout

No breakpoint tokens or SCSS mixins exist. Being a WordPress admin panel, the primary viewport is desktop, but the single breakpoint suggests responsive behavior is largely untested.

**Impact:** Low for current use (WordPress admin is desktop-oriented), but any future mobile/tablet support would require auditing every component for hardcoded widths.

**Remedy:** If responsive support is needed, define breakpoint tokens as SCSS variables (CSS custom properties don't work in `@media`):

```scss
$acx-bp-sm: 640px;
$acx-bp-md: 768px;
$acx-bp-lg: 1024px;
```

---

### M4: Missing Text Tertiary Color

**Book reference:** "Hierarchy"; "Use three text colors; dark for primary, grey for secondary, lighter grey for tertiary."

**Evidence:** Only two text color tokens exist:

- `--acx-color-text` (#0f172a; slate-900) for primary text
- `--acx-color-text-muted` (#475569; slate-600) for secondary text

No `--acx-color-text-tertiary` for hint text, timestamps, captions, or disabled labels. Components needing a lighter text color must pick an ad-hoc gray.

**Remedy:** Add `--acx-color-text-tertiary: var(--acx-gray-400);` (slate-400, #94a3b8).

---

### M5: Font Weight Tokens Absent

**Book reference:** "Hierarchy"; "Stick to two font weights: a normal weight (400 or 500) and a heavier weight (600 or 700)."

**Evidence:** Font weights `500`, `600`, `700` appear in various component files without semantic naming. No `--acx-font-weight-normal` or `--acx-font-weight-bold` tokens exist.

**Remedy:**

```scss
:root {
  --acx-font-weight-normal: 500;
  --acx-font-weight-semibold: 600;
  --acx-font-weight-bold: 700;
}
```

---

## Low-Impact Findings

### L1: No Button Tertiary/Ghost Variant

**Book reference:** "Hierarchy"; "Most pages only have one true primary action, a couple of less important secondary actions, and a few seldom-used tertiary actions." Tertiary buttons should look like styled links.

**Evidence:** Only primary (`--primary`), secondary (`--secondary`), and danger button variants exist. No ghost/tertiary variant for low-emphasis actions like "Cancel" or "Skip."

**Impact:** Low; the current UI has few tertiary actions. Future feature growth may need this.

---

### L2: Inconsistent Empty State Treatment

**Book reference:** "Don't overlook empty states"; "Use them as an opportunity to be interesting and exciting."

**Evidence:** The `.acx-apply-panel--empty` pattern is well-designed (dashed border, centered content, CTA), but not all empty states use it:

- `IdentityClusterList.tsx` (line 35): "No identities detected yet" is plain text
- `AnchorSelectionModal.tsx` (line 67): "No faces available to select" is plain text

**Remedy:** Apply the `.acx-apply-panel--empty` pattern (or a new `.acx-empty-state` utility) to all zero-content states.

---

### L3: HSL Not Used Systematically

**Book reference:** "Working with Color"; "HSL should be your weapon of choice" for web design.

**Evidence:** Colors are defined in hex (`#2563eb`, `#0f172a`, etc.) and RGB (`rgb(15 23 42 / 45%)`). HSL is not used anywhere. The book advocates HSL because adjusting saturation and lightness is more intuitive when creating shade variations.

**Impact:** Low for current token count. Would become more relevant if the design system needs to generate palette variations programmatically or if dark mode support is planned.

---

## Design System Maturity Assessment

Based on "Refactoring UI" prescriptions, the current design system maturity by token surface:

| Token Surface        | Maturity | Book Target                                      |
| -------------------- | -------- | ------------------------------------------------ |
| **Spacing**          | 5/5      | Systematic 8px scale, consistently used          |
| **Semantic Colors**  | 4/5      | Good naming; gap is underlying shade scale       |
| **User Content**     | 5/5      | Excellent object-fit/aspect-ratio discipline     |
| **Empty States**     | 4/5      | Good pattern; inconsistent application           |
| **Button Hierarchy** | 3/5      | Primary/secondary/danger; missing tertiary       |
| **Text Hierarchy**   | 2/5      | 2-tier only; needs tertiary + font-weight tokens |
| **Typography**       | 1/5      | No type scale; ad-hoc sizes everywhere           |
| **Gray Scale**       | 1/5      | Hardcoded hex; no token scale                    |
| **Elevation**        | 1/5      | 2 dialog-only tokens; rest hardcoded             |
| **Radius**           | 0/5      | Referenced but not declared                      |
| **Focus Rings**      | 1/5      | Inconsistent across components                   |

**Overall: 27/55 (49%)** of "Refactoring UI" token surfaces are adequately implemented.

---

## Recommended Improvement Sequence

Ordered by payoff and inter-dependency. Earlier phases provide tokens that later phases consume.

### Phase 1: Foundation Tokens

**Effort:** Small
**Targets:** H2, M1, M5

Define gray scale (`--acx-gray-*`), radius tokens (`--acx-radius-*`), and font weight tokens (`--acx-font-weight-*`). These are the primitives other improvements depend on. Replace hardcoded hex grays and radius literals across all component SCSS files.

### Phase 2: Type Scale

**Effort:** Small-Medium
**Targets:** H1

Define `--acx-text-xs` through `--acx-text-3xl` with paired line-height values. Audit all component SCSS files and replace ad-hoc `font-size` literals. This single change addresses the largest gap in the design system.

### Phase 3: Elevation System

**Effort:** Small
**Targets:** H3

Define 5-level shadow scale (`--acx-shadow-xs` through `--acx-shadow-xl`) using two-part shadow syntax. Replace all hardcoded `box-shadow` declarations. Map each component's purpose to an elevation level (cards = xs, dropdowns = md, toasts = lg, dialogs = xl).

### Phase 4: Text Hierarchy and Focus

**Effort:** Small
**Targets:** M2, M4

Add `--acx-color-text-tertiary` token. Consolidate focus ring styles into `--acx-focus-ring` / `--acx-focus-offset` tokens. Update all component focus styles to reference the token.

### Phase 5: Accessibility and Polish

**Effort:** Medium
**Targets:** H4, L1, L2

Add status icons alongside color borders in toasts and badges. Add a button tertiary variant. Apply `.acx-empty-state` pattern consistently to all zero-content states. Conduct a WCAG contrast audit against the finalized token palette.
