# APP-1 offline joined-validation evidence receipt

Date: 2026-09-22 UTC
Snapshot: `feature/app-1-offline-joined-validation`, `8ef8916cdcd990a89804116b96ee556593670d17`
Evidence owner: this file only

## Outcome

No browser-test, typecheck, or production-build result was collected. The required
offline dependency installation failed before the toolchain became runnable, and
the three follow-up commands were still invoked separately as required.

| Command | Observed result |
| --- | --- |
| `npm --prefix apps/app-portal ci --offline --no-audit --no-fund` | Exit 1. `esbuild/install.js` failed to spawn `apps/app-portal/node_modules/esbuild/bin/esbuild` with `EPERM`; Node reported `v22.23.1`. |
| Scoped Vitest command below | Exit 127 before Vitest startup: `apps/app-portal/node_modules/.bin/vitest` was absent. Collected: **0**; passed: **0**; failed: **0**. These are not test results. |
| `npm --prefix apps/app-portal run typecheck` | Exit 127: `tsc` was not found. |
| `npm --prefix apps/app-portal run build` | Exit 127: `vite` was not found. |

The exact scoped command was:

```text
apps/app-portal/node_modules/.bin/vitest run --root apps/app-portal src/__tests__/account-navigation.test.tsx src/__tests__/backend-authority.test.tsx src/__tests__/billing-journey.test.tsx src/__tests__/claim-journey.test.tsx src/__tests__/config-missing.test.tsx src/__tests__/csp-and-contracts.test.ts src/__tests__/identity-isolation.test.tsx src/__tests__/keys-api-fixwave.test.ts src/__tests__/keys-journey.test.tsx src/__tests__/keys-ui-fixwave.test.tsx src/__tests__/portal-me-fetch.test.ts src/__tests__/portal-request.test.ts src/__tests__/session-routes.test.tsx src/__tests__/signout-stale.test.tsx src/__tests__/usage-journey.test.tsx
```

## Provenance and limits

This receipt records only commands attempted on the current feature-ref snapshot
in the model sandbox. Earlier per-lane VM snapshots, prerequisites, and receipts
are context, not evidence for this joined run; their pass counts were not reused.
No native-VM collection, Clerk/Polar provider, live browser, WordPress, or
PostgreSQL evidence is claimed. The coordinator/native adapter must rerun the
scoped command where the dependency boundary is available.

The result therefore does not validate DDIA identity isolation, Release It
bounded waits, DATA-03 contract parity, or the GRPH-09/GRPH-31 joined-boundary
checks. Those rule IDs are used as verification scope only, with the stable
[heuristics canon](https://github.com/darce/heuristics-canon) as the cited source.

No product or test source was edited.
