# WB_CONTROL remote brief

Read COMMON.md + UI-CONTRACTS.md.

## objective

Prioritize selected recognition evidence and one empty nextstep; remove redundant control hierarchy while preserving nonempty reviews/errors.

## finding

19860.

## anchors

WorkbenchPageContent87–237 composes FaceGroupScatter, RecognitionPolicyControl, ScanTabContent, sibling MediaSelection via ReviewSurfaceContext. Do not edit MediaSelection/globalstyles. If a needed behavior resides ScanTabContent, request named ownership; do not hide all usefulsubtrees.

## rules

LAY-01 Contrast engine/big-little and LAY-03 Unequal intervals (Asymmetric Typography §use-of-space); PERC-01 Proximity binds meaning (Designing with the Mind in Mind + Refactoring UI §avoid-ambiguous-spacing).

## accept

One actionable recognition emptystate; no enabled no-work reviewactions; nonempty failures visible; selected group/media scopes explicit. Headless desktop/narrow scroll/focus proof; no pane forced to the whole5440px media list. Description lifecycle has one libraryhome.

## owned paths

- apps/prototype-wp-alt-context/js/admin/pages/WorkbenchPage.tsx
- apps/prototype-wp-alt-context/js/admin/styles/components/_workbench.scss

## scoped verification on VM

From apps/prototype-wp-alt-context: npm test -- js/admin/pages/__tests__/WorkbenchPage.test.tsx js/admin/pages/__tests__/WorkbenchPage.scatter.test.tsx js/admin/pages/workbench/__tests__/WorkbenchTwoPaneLayout.test.tsx js/admin/pages/workbench/__tests__/RecognitionPolicyControl.test.tsx
Then npm run typecheck and narrowly added headless acceptance. Install locked dependencies only in assigned remote sandbox if absent. Never use test:agent because it masks failure. Root reconciles exact lane/counter/subject before dispatch.
