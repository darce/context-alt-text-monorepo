# Tech Debt Plan: E2E + Smoke Automation Path (WordPress Sovereign Flows)

## Problem Statement

Phase 3 closure required manual smoke checks that depended on LocalWP internals and ad-hoc service toggling.
This is slow, brittle, and difficult to reproduce across agents and CI.

## Goal

Define a stable, repeatable E2E/smoke testing path that validates WordPress plugin behavior through real user and API flows without relying on LocalWP private GraphQL APIs.

## Principles

- Playwright is the primary E2E driver (UI + API assertions).
- WP-CLI is the setup/reset mechanism (users, fixtures, plugin state).
- LocalWP-specific APIs are optional local convenience only, never required for CI.
- Outage/recovery scenarios must be first-class (backend up/down, sync reconciliation).

## Proposed Tooling

1. Playwright (`@playwright/test`) for browser automation and auth state reuse.
2. Playwright `APIRequestContext` for authenticated REST assertions during UI tests.
3. WP-CLI for deterministic seed/reset scripts.
4. Docker Compose or `wp-env` for reproducible WordPress+DB test runtime.
5. Toxiproxy (or equivalent) for controllable backend failure simulation.

## Test Scenarios (Minimum Gate)

1. Offline label persistence:
   - Backend down -> label cluster -> verify local persistence.
   - Backend up -> trigger sync/read -> verify label still present.
2. Full cycle local-read resilience:
   - Backend up -> clusters load + analysis trigger.
   - Backend down -> clusters still load from local projection.
3. Sync status integrity:
   - Verify `sync-status` transitions (`last_synced_at`, stale state) across restart/recovery.

## Implementation Path

### Phase 0: Scaffolding

- [ ] Add E2E directory and Playwright config for WP plugin flows (`apps/prototype-wp-alt-context/tests/e2e/`).
- [ ] Add reusable login/auth fixture (`storageState`) for WordPress admin.
- [ ] Add WP-CLI seed/reset helpers for deterministic fixtures and cleanup.
- [ ] Add backend control helper (start/stop or proxy toggles) for outage scenarios.

### Phase 1: Core Smoke Specs

- [ ] Implement spec: offline label persists across backend outage and reconciliation.
- [ ] Implement spec: full cycle (proxy load -> analyze -> backend down -> local projection render).
- [ ] Implement spec: sync-status transitions are observable and valid.

### Phase 2: CI Integration

- [ ] Add dedicated CI job for E2E smoke with reproducible environment.
- [ ] Persist Playwright traces/videos on failure.
- [ ] Fail PRs on smoke regression in sovereign read/write paths.

### Phase 3: Hardening

- [ ] Remove dependency on LocalWP GraphQL from required smoke flow docs.
- [ ] Document local-only fallback path separately (non-gating).
- [ ] Add flake budget and retry policy with explicit thresholds.

## Success Criteria

- [ ] Phase 3 manual smoke scenarios are covered by automated Playwright specs.
- [ ] CI can run smoke tests without LocalWP private APIs.
- [ ] Backend outage/recovery behavior is validated deterministically.
- [ ] New contributors can run the smoke suite with one documented setup path.
