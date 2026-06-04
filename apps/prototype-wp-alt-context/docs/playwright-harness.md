# Playwright Harness Contract

This document defines the v1 Playwright harness shape for `apps/prototype-wp-alt-context` before the install and config land in Slice 2. It is the contract reviewers should use when checking the upcoming scaffolding work.

## Why One Toolchain

Use `@playwright/test` as the only Playwright dependency. Do not add the standalone `playwright-cli` package.

- `@playwright/test` already ships the `playwright` binary used for `test`, `install`, `codegen`, `open`, and `screenshot`.
- A second package would create a second browser/version pin and an avoidable drift source.
- Operators should only need to reason about one Chromium install, one config file, and one command family.

## Lane Responsibilities

- `Lane A` (`evidence`): headed operator-evidence runs that capture screenshots, transcripts, and traces for E15 manual gates.
- `Lane B` (`smoke`): headless durable smoke specs. This lane is part of the v2 envelope and is not shipped in v1 beyond the shared scaffolding.
- `Lane C` (`a11y`): headless route-level axe checks against the ACX admin routes, scoped to the plugin shell rather than the full WordPress admin chrome.
- `auth-setup`: one-time login bootstrap that writes shared storage state for the other projects.

## Planned Project Layout

Slice 2 will add the following layout under `apps/prototype-wp-alt-context`:

```text
playwright.config.ts
tests/
  e2e/
    auth-setup/
      auth.setup.ts
    smoke/
    a11y/
    evidence/
    fixtures/
      acx-routes.ts
    .auth/
local/
  playwright/
    <task-ref>/
```

The artifact root is task-scoped so operators can keep proof bundles separated by task (`E15-6`, `E15-22`, `E15-3a`) without renaming files by hand.

## Artifact Convention

- Task selector: `ACX_PLAYWRIGHT_TASK_REF`
- Artifact root: `apps/prototype-wp-alt-context/local/playwright/<task-ref>/`
- Shared auth state: `apps/prototype-wp-alt-context/tests/e2e/.auth/storageState.json`
- Secrets source: `apps/prototype-wp-alt-context/.env.local` (gitignored)

Nothing under `local/playwright/`, `tests/e2e/.auth/`, or `.env.local` is committed.

## Script Catalogue

These commands are wired in `apps/prototype-wp-alt-context/package.json` and the root `Makefile`.

- `npm run e2e:install`: install Chromium for the harness.
- `npm run e2e:auth`: run the one-time auth bootstrap.
- `npm run e2e:localwp`: run the smoke project against LocalWP.
- `npm run e2e:evidence`: run headed evidence capture.
- `npm run a11y:localwp`: run the route-level axe project.
- `make localwp-e2e-install`
- `make localwp-e2e-auth`
- `make localwp-e2e-smoke`
- `make localwp-evidence`
- `make localwp-a11y-smoke`

## Lane C Gate Shape

- The v1 gate scans the empty-state shell for Dashboard, Workbench, Roster, and Settings on a clean LocalWP install.
- Each spec is responsible for its own route-specific wait anchor before axe runs. Current anchors are the Dashboard `.acx-dashboard__shell` with `Alt Context Dashboard` heading, the Workbench `Your analysis queue is empty` empty-state card, the Roster empty-state message, and the Settings form shell.
- Only `serious` and `critical` axe violations fail the run by default. Lower-impact findings remain visible in the test output for triage, but they do not block the v1 gate.
- Each route spec also carries an `ACX_E2E_SEEDED`-guarded populated-state block. Those seeded assertions are opt-in and skipped by default until deterministic seed data exists.

## Auth Bootstrap Shape

- Primary path: copy `.env.local.example` to `.env.local` and set `ACX_E2E_WP_ADMIN_USER` plus `ACX_E2E_WP_ADMIN_PASS`.
- Runtime target: `http://localhost:10010/wp-admin/`.
- Fallback path: if either env var is missing, `auth.setup.ts` pauses a headed browser so the operator can log in interactively once.
- Success condition: shared storage state is written to `tests/e2e/.auth/storageState.json` for reuse by `evidence`, `smoke`, and `a11y`.

## When The Proof Selector Breaks

If the first proof spec stops finding its stable selector:

1. Confirm the route still renders manually in LocalWP before changing the test.
2. Update the selector in the affected spec and update `tests/e2e/fixtures/acx-routes.ts` too if the route slug changed.
3. Re-run the smoke project and mention the selector update in the slice-complete decision so future reviewers understand why the anchor moved.

## Boundaries

- No Playwright MCP surface is documented or wired here. That is explicitly out of v1 scope.
- No CI behavior is promised in this slice. CI belongs to the v2 envelope.
- Existing `vitest` and `vitest-axe` workflows remain unchanged.
