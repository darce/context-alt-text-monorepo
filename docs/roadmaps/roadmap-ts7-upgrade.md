# TypeScript 5.9 → 7 Upgrade Evaluation (v0.1)

## Objective

Evaluate the upgrade from TypeScript 5.9.3 to the TypeScript 7 native compiler (Go port, GA July 2026), quantify the lift for this monorepo's single TS surface, and decide whether/when the juice is worth the squeeze.

Source ingest: [ts7-announcement-ingest.md](../reference/ts7-announcement-ingest.md) (fetched 2026-07-12).
Sibling evaluation: [roadmap-pg18-upgrade.md](roadmap-pg18-upgrade.md).

## Verdict (TL;DR)

**Not yet for the compiler swap; yes now for the free steps.** The full-build speedup TS7 sells (8–12x) compresses a **4.4s** typecheck — our entire `tsc` surface — to well under a second: real but tiny absolute juice. The blocking cost is that **TS 7.0 ships no programmatic API**, and this repo's ESLint gate is type-aware (`recommendedTypeChecked` + `project`), so typescript-eslint must keep a TS 6 API package side-by-side via npm aliases — dual-package complexity for seconds of CI time. Recommended: do the cheap, required-anyway **TS 6.0 bridge upgrade** and the zero-risk **editor-only TS7 LSP** now; swap `tsc` to 7.x only once typescript-eslint runs natively on the TS 7.1+ API.

## Problem Statement

The frontend (`apps/prototype-wp-alt-context/js/`) is 299 TS/TSX files, ~45k LOC, on TypeScript 5.9.3. `tsc` is used **only** for type-checking (`npm run typecheck`, part of `npm run check` and CI); Vite 7/esbuild does all transpilation, Vitest 4 transforms tests, Playwright transforms e2e specs — none of them invoke `tsc` for emit. TypeScript 7 replaces the JS compiler with a native Go port promising 8–12x full builds, ~half-second editor first-error latency, and a multithreaded LSP server. The 6.x JS line becomes the API-compat bridge; feature releases continue on the 7.x native line every ~3–4 months. Staying on 5.9 indefinitely means drifting from the supported line; upgrading blindly breaks the type-aware lint gate.

## Constraints

- TS 7.0 has **no programmatic API**; TS 7.1 is expected to ship a new (different) one. typescript-eslint and any TS-API consumer must run against the TS 6.0 API (`@typescript/typescript6` alias) until then.
- TS 7 adopts TS 6.0 defaults; constructs deprecated in 6.0 are **hard errors** in 7.0. The published migration path is 5.9 → 6.0 → 7.x.
- `baseUrl` is unsupported in TS 7 (`paths` must be project-root-relative). This repo's `tsconfig.json` uses `baseUrl: "."` + `paths: {"~/*": ["js/*"]}`.
- Node ≥22.18 / npm 11 already required — no runtime constraint from TS7 (native binary ships via the normal `typescript` npm package).
- PHP plugin and Python service have no TS dependency; only `apps/prototype-wp-alt-context/` is affected.

## Current State (evidence, 2026-07-12)

| Surface | Fact |
|---|---|
| TS version | `typescript` 5.9.3 (devDependency; single package.json owns all TS) |
| Codebase | 299 `.ts`/`.tsx` files, ~45,371 LOC under `js/` (+ e2e specs, configs) |
| tsc role | Typecheck only: `tsc --noEmit --project tsconfig.type-check.json` |
| Typecheck baseline | **4.4s wall / 8.8s CPU** (measured on dev machine, cold) |
| Transpile | Vite 7 (esbuild) — never touches `tsc` |
| Tests | Vitest 4 (own transform), Playwright 1.56 (own transform) |
| Lint | typescript-eslint 8.x with `recommendedTypeChecked` + `stylisticTypeChecked`, `parserOptions.project: tsconfig.type-check.json` → **hard TS-API dependency** |
| Codegen | `json-schema-to-typescript` (json2ts) pins its own `typescript@^5.4.5` internally — unaffected by repo TS version |
| tsconfig | `strict: true`, `target: ES2022`, `module: ESNext`, `moduleResolution: bundler`, `esModuleInterop: true`, explicit `types` array, `baseUrl: "."` + `~/*` paths |
| tsgo-hostile features | None: zero namespaces, zero `const enum`, zero decorators, zero direct `import 'typescript'` in app/scripts code |
| Side-effect imports | Exactly 1 (`import './styles/main.scss'` in `js/admin/main.tsx`) — relevant to `noUncheckedSideEffectImports: true` default |

## Benefit Analysis (the juice)

1. **Typecheck speed**: 4.4s → ~0.4–0.6s expected (8–12x published band). Saves ~4s per `npm run check` and CI run. Real, but this is the whole prize on the CLI side — our build/test pipeline gets nothing else because nothing else uses tsc.
2. **Editor experience**: multithreaded LSP; published first-error latency 13x faster, 80% fewer failing LS commands, 60% fewer crashes. On a 45k-LOC project the current experience is already acceptable; the gain is comfort, not unblocking. **Available today with zero package changes** via the VS Code `TypeScriptTeam.native-preview` extension.
3. **Future-proofing**: feature releases land on the 7.x native line every ~3–4 months; 6.x is a compatibility bridge. Staying on 5.9 accrues drift debt (typescript-eslint, @types, lib updates will eventually assume ≥6).
4. **Memory**: 6–26% published reductions — irrelevant at our scale.

## Lift Analysis (the squeeze)

| Item | Lift | Notes |
|---|---|---|
| 5.9 → 6.0 bridge upgrade | **Small** | Adopt 6.0 deprecation cleanup now: drop `baseUrl` (make `paths` `./js/*`-relative), keep explicit `types`, fix 1 side-effect scss import if `noUncheckedSideEffectImports` flags it (ambient `*.scss` declaration). `strict`/`module`/`esModuleInterop` already at 6.0 defaults. typescript-eslint 8.x supports TS 6. |
| 6.0 → 7.x tsc swap (now) | **Moderate, awkward** | Dual-package alias layout: `"typescript": "npm:@typescript/typescript6@^6"` (for typescript-eslint/API consumers) + `"@typescript/native": "npm:typescript@^7"` (for `tsc`). Two TS versions to keep semantically aligned; every dev + CI must understand the split. |
| 6.0 → 7.x tsc swap (after typescript-eslint supports TS 7.1+ API) | **Small** | Single `typescript@^7` devDependency; `typecheck` script unchanged (`npx tsc`); optionally tune `--checkers` for CI. |
| Editor-only TS7 LSP | **Trivial** | VS Code extension; per-dev opt-in; flip back with one command. No repo change beyond optionally recommending the extension. |

Type-system behavior deltas (Unicode template-literal inference, JSDoc analysis rework) are low-risk here: no type-level string-unit utilities found, JS files are not type-checked via JSDoc conventions.

## Is the juice worth the squeeze?

- **Full swap today: No.** ~4 seconds of CI per run against a dual-TS-package maintenance burden and a lint gate riding an aliased legacy API. The repo's TS surface is too small for the headline numbers to matter operationally.
- **Bridge + editor now: Yes.** TS 6.0 is mandatory prep for any future on the supported line, costs roughly an hour, and removes every deprecation cliff at leisure instead of under pressure. The LSP extension is free comfort.
- **Re-evaluate trigger**: typescript-eslint announces native TS 7 (7.1+ API) support — then Phase 2 is a one-line dependency bump.

## Phased Delivery

### Phase 0: Zero-risk adoption (editor + hygiene)

**Goal**: capture the TS7 editor benefit and remove TS7-hard-error constructs without changing the toolchain.

Deliverables:

- Remove `baseUrl` from `tsconfig.json`; rewrite `paths` as `{"~/*": ["./js/*"]}` (TS 5.9 already supports baseUrl-less paths).
- Verify Vite `resolve.alias` for `~/` is independent of tsconfig `baseUrl` (it is — vite.config.ts owns its own alias).
- Add ambient declaration for side-effect `*.scss` import if not already covered by `vite/client` types.
- Recommend `TypeScriptTeam.native-preview` in `.vscode/extensions.json` (opt-in, per-dev).

Exit criteria:

- `npm run check` green with no `baseUrl` in any tsconfig.
- Editor resolves `~/` imports and scss side-effect import with TS7 LSP enabled.

### Phase 1: TypeScript 6.0 bridge upgrade

**Goal**: land on the supported compatibility line; absorb all 6.0 deprecations so a later 7.x swap is a dependency bump.

Deliverables:

- Bump `typescript` to `^6.0` (verify typescript-eslint 8.x peer range; bump typescript-eslint if needed).
- Run typecheck without `ignoreDeprecations`; fix every deprecation diagnostic (expected: none beyond Phase 0's `baseUrl`, given current config).
- Confirm `stableTypeOrdering` behavior (default on in 6.x-era flags) produces no diagnostic-order churn in CI snapshots.
- Explicitly set any `types` entries that previously leaked in via auto-include (already explicit — verify only).
- Full gate: `npm run check:all`, Playwright smoke, `composer test` untouched.

Exit criteria:

- CI green on TS 6.0 with zero `ignoreDeprecations` usage.
- `tsc --noEmit` clean — this is the published precondition for identical TS 7 compile results.

### Phase 2: TypeScript 7 compiler swap (gated)

**Gate**: typescript-eslint (and any other TS-API devDependency) supports the TS 7.1+ native API. Until then, do not adopt the dual-alias layout — the cost/benefit is negative at this repo's scale.

Deliverables:

- Bump `typescript` to `^7`; `typecheck` script unchanged.
- Remove any 6.x compat packaging if the interim alias layout was ever introduced (it should not be).
- Benchmark typecheck before/after; record in this doc.
- Evaluate `--checkers` for CI runner size (default 4; likely irrelevant at 45k LOC).

Exit criteria:

- `npm run check` green on TS 7 with a single `typescript` devDependency.
- Typecheck wall time ≤1s recorded.

## Deferred / Not Applicable

- **Dual-package alias layout (`@typescript/typescript6` + native)** — the published interim path for API consumers. Deferred deliberately: only worth it for repos where tsc dominates CI time. Revisit only if Phase 2's gate slips >2 quarters AND typecheck time grows past ~30s.
- **`--builders` / project references** — repo has a single TS project (`references: []`); nothing to parallelize.
- **`--watch` improvements** — dev loop is Vite HMR, not `tsc --watch`; no consumer.
- **Embedded-language concerns (Vue/Svelte/Volar/Angular)** — none in use; React JSX via `react-jsx` is fully supported.

## Risks and Mitigations

- **Risk**: typescript-eslint 8.x peer-rejects `typescript@6`.
  Mitigation: typescript-eslint tracks new TS majors closely; bump to the 8.x minor that widens the range, or pin with overrides for the bridge window.
- **Risk**: `noUncheckedSideEffectImports` default flags the scss import under 6.0/7.0.
  Mitigation: single ambient `declare module '*.scss'` file; one-line fix identified up front.
- **Risk**: TS 7 checker produces order-dependent diagnostics with `--checkers > 1` (published caveat).
  Mitigation: leave default checkers; CI does not diff diagnostic order.
- **Risk**: json2ts-generated contract types drift under a new TS version's emit conventions.
  Mitigation: json2ts pins its own internal TS; regenerate contracts (`npm run generate:contracts`) and diff as part of Phase 1/2 verification.
- **Risk**: 6.x line goes maintenance-only while Phase 2 gate is blocked, delaying security/lib updates.
  Mitigation: acceptable — 6.x is the officially supported API bridge line precisely for this window.

## Success Metrics

- Phase 0/1 land with **zero** behavioral diffs in CI (same lint findings, same type errors: none).
- `baseUrl` removed — **1 fewer TS7 hard-error construct** in the codebase.
- TS 6.0 adopted with no `ignoreDeprecations` — published precondition for byte-identical TS7 checking satisfied.
- On Phase 2: typecheck **4.4s → ≤1s**; single `typescript` devDependency retained (no alias split ever merged).

---

# Consolidated Checklist

## Phase 0: Zero-risk adoption

- [ ] Remove `baseUrl`; make `paths` project-root-relative in `tsconfig.json`
- [ ] Verify Vite alias + typecheck + eslint green after paths change
- [ ] Ambient `*.scss` declaration (or confirm `vite/client` covers it)
- [ ] Recommend TS7 LSP extension in `.vscode/extensions.json`

## Phase 1: TS 6.0 bridge

- [ ] Bump `typescript` to `^6.0` (+ typescript-eslint minor if peer range requires)
- [ ] Fix all 6.0 deprecation diagnostics; zero `ignoreDeprecations`
- [ ] Verify explicit `types` array still complete (no auto-include reliance)
- [ ] Regenerate contracts (`npm run generate:contracts`) and diff
- [ ] `npm run check:all` + Playwright smoke green

## Phase 2: TS 7 swap (gated on typescript-eslint TS7-API support)

- [ ] Confirm typescript-eslint native TS 7.1+ API support released
- [ ] Bump `typescript` to `^7`; no alias packages
- [ ] Benchmark typecheck before/after; record here
- [ ] `npm run check` green; CI green

## Re-evaluation triggers

- [ ] typescript-eslint announces TS 7 API support → schedule Phase 2
- [ ] Frontend typecheck exceeds ~30s → reconsider interim dual-alias layout
- [ ] TS 6.x line announces end of maintenance → Phase 2 becomes forced
