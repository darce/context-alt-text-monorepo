# APP-1 offline joined-validation evidence receipt

Date: 2026-09-22 UTC
Assessment owner: this file only
Verification source commit: `30c299fe62ad372fc3aa519f61cf5ea65d808719`

## Outcome

The coordinator independently bootstrapped the exact existing VM sandbox with
`npm ci --offline --no-audit --no-fund` outside the inner model sandbox. The
successful direct-VM receipt below is separate from the failed historical
attempts and is limited to the checked-in portal fixtures and local build
artifacts.

## Historical failed attempts

These attempts are retained for provenance and are not successful verification:

| Attempt | Observed result |
| --- | --- |
| Original inner-model-sandbox `npm --prefix apps/app-portal ci --offline --no-audit --no-fund` | Exit 1. `esbuild/install.js` failed to spawn `apps/app-portal/node_modules/esbuild/bin/esbuild` with `EPERM`; Node reported `v22.23.1`. |
| Original native/adapter scoped Vitest attempt | Exit 127 before Vitest startup because `apps/app-portal/node_modules/.bin/vitest` was absent. Collected: **0**; passed: **0**; failed: **0**. This attempt did not pass. |
| Original native/adapter `npm --prefix apps/app-portal run typecheck` | Exit 127: `tsc` was not found. |
| Original native/adapter `npm --prefix apps/app-portal run build` | Exit 127: `vite` was not found. |

## Successful direct-VM verification

The coordinator-supplied receipt is from source commit
`30c299fe62ad372fc3aa519f61cf5ea65d808719`, not from the failed attempts above:

| Command | Observed result |
| --- | --- |
| `npm ci --offline --no-audit --no-fund` in the existing VM sandbox | Completed successfully outside the inner model sandbox. |
| Exact scoped Vitest command below | Exit 0; 15 test files passed, 105 tests passed, in 29.52s. |
| `npm run typecheck` from `apps/app-portal` | Exit 0. |
| `npm run build` from `apps/app-portal` | Exit 0; Vite `7.3.6`, 131 modules. |

Vitest emitted non-fatal React `act(...)` warnings in the supplied stderr; no
test failed. The exact scoped command was:

```text
apps/app-portal/node_modules/.bin/vitest run --root apps/app-portal src/__tests__/account-navigation.test.tsx src/__tests__/backend-authority.test.tsx src/__tests__/billing-journey.test.tsx src/__tests__/claim-journey.test.tsx src/__tests__/config-missing.test.tsx src/__tests__/csp-and-contracts.test.ts src/__tests__/identity-isolation.test.tsx src/__tests__/keys-api-fixwave.test.ts src/__tests__/keys-journey.test.tsx src/__tests__/keys-ui-fixwave.test.tsx src/__tests__/portal-me-fetch.test.ts src/__tests__/portal-request.test.ts src/__tests__/session-routes.test.tsx src/__tests__/signout-stale.test.tsx src/__tests__/usage-journey.test.tsx
```

## Provenance and limits

The historical failures were attempted in the inner model sandbox and by the
original native/adapter path. The successful direct-VM receipt is a separate
coordinator-supplied execution at source commit
`30c299fe62ad372fc3aa519f61cf5ea65d808719`; it is not evidence from the
failed attempts, and the current documentation checkout is not its source.
Earlier per-lane VM snapshots, prerequisites, and receipts are context, not
evidence for this joined run; their pass counts were not reused.

The successful run is fixture-only evidence for the named portal tests and
local type/build checks. No live Clerk authentication, Polar provider or
payment, WordPress connection, browser acceptance, PostgreSQL receipt, or
deployment acceptance is claimed. No adapter-native rerun was performed; if
one is later needed, it must use the existing VM npm installation.

The fixture receipt does not close separate durable/live DDIA identity-isolation,
Release It bounded-wait, DATA-03 contract-parity, or GRPH-09/GRPH-31
joined-boundary evidence requirements. Those rule IDs are used as verification
scope only, with the stable
[heuristics canon](https://github.com/darce/heuristics-canon) as the cited source.

No product or test source was edited.
