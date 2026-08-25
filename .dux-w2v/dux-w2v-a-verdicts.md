# dux-w2v-a verdicts

FINDINGS_BEGIN
FINDING: DUX-W2D14-RV-08
VERDICT: sustained
EVIDENCE: `cd apps/prototype-wp-alt-context && npm run typecheck` exit 0; stdout is only `> prototype-wp-alt-context@0.0.4 typecheck` / `> tsc --noEmit --project tsconfig.type-check.json` (no TS2339). Local UxScreen at dashboard-uxmap-code-parity.test.ts:31-39 now declares `code_ref: string` (used at :333 `workbench?.code_ref`). Matches dashboard.uxmap.json screens (`code_ref` at :34,:130,:157,:187). tsconfig.type-check.json includes `js/**/*.ts`. No `any`, `as` on UxScreen, `@ts-expect-error`, `@ts-ignore`, or index signature; the only `as` is `JSON.parse(...) as UxMap` at :70. Truthful widen, not checker suppression.
FINDING: DUX-W2D14-RV-09
VERDICT: sustained
EVIDENCE: it('RV-03') at dashboard-uxmap-code-parity.test.ts:202-212 imports buildDashboardPriorityModel and asserts FIRST_NAMED -> HIDDEN and UNSCANNED -> BEFORE_GRID. Model at buildDashboardPriorityModel.ts:99-102 is `inputs.flowState === DASHBOARD_FLOW_STATE.FIRST_NAMED ? HIDDEN : BEFORE_GRID`. TEST-15 mutant `=== UNSCANNED` inverts both results so both expects go RED. Source-text regex at test.ts:213-216 is additional DashboardPage.tsx:85-86 wiring coverage, not the only pin; no tautological regex against the model source remains in this it() block.
FINDING: DUX-W2D14-RV-10
VERDICT: sustained
EVIDENCE: h1Literal at test.ts:94-104 slices from `/<h1\b[^>]*>/` to first `</h1>` then `/__\(\s*'([^']+)'/` on that slice only. DashboardPage.tsx:314-316 is `<h1 ...>{__('Overview', 'alt-context')}</h1>`. (a) Hoist `const dashboardTitle = __('Overview','alt-context')` outside h1: no `__()` in the slice, helper throws; cannot walk past `</h1>` (it('RV-10') at :167-180). Correct vs original walk-past FALSE RED. (b) `<h1><span className="acx-visually-hidden">{__('Overview',...)}</span>{__('Dashboard',...)}</h1>` still FALSE GREEN: first inner `__()` is Overview. Remaining gap, not the named walk-past defect; slice makes a post-`</h1>` match impossible.
FINDING: DUX-W2D14-RV-13
VERDICT: sustained
EVIDENCE: test.ts:267 still joins for the union check; load-bearing per-sketch loop is test.ts:294-319 `unconditionalControls`. Map: 'Open Review Queue' -> [default, first_time, degraded]; 'Fix missing descriptions' -> all five. DashboardSyncHealthSection.tsx:56-66 vs :129-133 renders Open Review Queue only in loaded-success (not isLoading/isError); sketches include it at dashboard.md:69,:142,:230 and omit it in loading :170-171 / error :199-200. DashboardPage.tsx:217-245 keeps progress + __('Fix missing descriptions') outside isStatsLoading; Loading sketch corrected at md:176-178, also md:79/:151/:207/:239. Controls were not made conditional; map does not exempt them. Degraded omitting Open Review Queue or Loading omitting the CTA would RED. vitest 8/8 passed.
FINDINGS_END
