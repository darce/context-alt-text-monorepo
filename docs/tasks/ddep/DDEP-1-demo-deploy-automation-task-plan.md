# DDEP-1. Laptop-free demo deploy automation (CI-driven, tag:ci)

> **Metadata**
>
> - **Date**: 2026-07-14 EST
> - **Author**: claude-opus-4-8
> - **Project**: prototype-wp-alt-context + infra/oci/demo
> - **Task ID**: DDEP-1
> - **Target Branch**: `feature/ddep-1`
> - **Review Coverage Target**: 2

## Objective

Make the demo WordPress + ACX plugin deploy runnable entirely from CI — no operator laptop, no standing SSH grant — by mirroring the proven `deploy-recognition.yml` pattern (ephemeral `tag:ci` tailnet join + SSH deploy key) around the existing `sync-demo.sh`. Also fix the misleading vhost smoke that reports a benign root-`404` as a deploy failure.

## Intake (new-capability scope pass)

- **Key Q&A decisions**: `decision #2180` (`opus_scope_ddep_1_demo_deploy_automation`).
- **MVP cut**: deploy-CI + smoke fix only. **Trigger**: manual `workflow_dispatch` only. **Failure mode**: fail-loud + leave state (idempotent redeploy = recovery).
- **Not-Doing**: observability surface (deferred follow-up / `feature/ob-8`); auto-deploy-on-push; auto-rollback; blue/green; a second staging-demo environment; the backend recognition round-trip failure (needs observability first); any standing SSH grant to laptops or interactive agents.

## Problem Statement

The demo (`demo.altcontext.com`, a WordPress + MariaDB container stack on the OCI VM behind `acx-demo.service`) is deployed only via `make deploy-demo` → `scripts/deploy/sync-demo.sh`, which SSHes as `ubuntu@acx-backend.tail1a44b8.ts.net`. Public port 22 is closed; the tailnet SSH ACL authorizes **only** ephemeral CI (`tag:ci`) — interactive operator/agent identities are denied. Consequence: every demo deploy requires a specific authorized operator on a specific machine. There is **no** CI workflow for the demo (`deploy-recognition.yml` covers the backend service only). This blocked syncing RECOG-1 to the demo until an operator ran the deploy by hand. Separately, `sync-demo.sh`'s post-sync smoke curls `/` on the `api.*` vhosts, which have no root route → `404`, printed as `FAIL`, masking real outages and crying wolf on healthy deploys.

## Constraints

- **Security posture (non-negotiable)**: no standing SSH to laptops/agents. The only VM shell identity is ephemeral `tag:ci`. This task must not widen VM access; it moves the *existing* deploy onto that already-trusted identity.
- **Reuse, don't fork**: `sync-demo.sh` + `scripts/release/package-plugin.sh` stay the single source of truth for deploy + packaging logic. The workflow orchestrates them; it does not reimplement deploy steps.
- **Free-plan gate reality**: private repos have no GitHub required-reviewers on Environments; deliberate-action gating is a `CONFIRM=PROMOTE`-style string input, matching `deploy-recognition.yml`.
- **Public surface**: the demo is public; deploys must be deliberate (`workflow_dispatch` only) and serialized (one in-flight).
- **Smoke must not gate on out-of-scope failures**: the demo recognition round-trip is currently failing (backend); the post-deploy smoke must assert the *deploy* landed (admin surfaces render, RECOG-1 single-target contract live), not the recognition verdict.

## Workflow Principles

- Mirror the proven pipeline (`deploy-recognition.yml`) rather than invent a new shape; deviate only where the demo genuinely differs (plugin build + WP bootstrap vs REMOTE_BUILD service deploy).
- The deploy identity is ephemeral CI; humans/agents get automation (`gh workflow run`), never standing shell.
- Fail-loud over auto-heal: a failed smoke fails the job visibly; the idempotent redeploy is the recovery path.
- Deploy-success signal ≠ product-health signal: the smoke gates on surface-render/contract; recognition health is surfaced as information for the observability follow-up.

## Terminology

- **Demo stack**: the `acx-demo` compose stack (WordPress + MariaDB) + Caddy edge on the OCI VM, deployed by `sync-demo.sh`.
- **`tag:ci`**: the tailnet ACL tag granted SSH to the VM; assigned to ephemeral GitHub Actions runners via the Tailscale OAuth client.
- **Deploy smoke**: the post-deploy acceptance check that the deploy landed (distinct from the walkthrough's recognition verdict).

## Current State Analysis

- **Works**: `make deploy-demo` from an authorized operator identity; `sync-demo.sh` auto-picks the newest `dist/alt-context-*.zip`; `bootstrap-wp.sh` installs+activates the plugin with activation cycling for dbDelta; `package-plugin.sh` builds a `--no-dev` plugin zip; `deploy-recognition.yml` proves the ephemeral-`tag:ci` + SSH-deploy-key + Environment + concurrency pattern.
- **Broken/missing**: no CI path for the demo → laptop-bound deploys; interactive tailnet SSH ACL-denied for agents/operators-not-on-the-authorized-node.
- **Misleading**: `sync-demo.sh` vhost smoke curls `/` (→ `404` on `api.*`) and prints `FAIL`; a benign result reads as an outage (and a real outage on a routed path could read as pass). The demo `Version 7.0.1` string is unbumped, so version is not a reliable deploy-verification signal — the RECOG-1 single-target Settings contract is.

## Target Outcome

`gh workflow run deploy-demo.yml` (or the Actions UI) deploys the current-`main` demo plugin end-to-end from a disposable runner: build the plugin zip → join tailnet as `tag:ci` → `sync-demo.sh` with `PLUGIN_ZIP` → post-deploy deploy-smoke. No operator laptop, no new standing access. The workflow is `workflow_dispatch`-only, serialized by a concurrency group, and gated by the `CONFIRM=PROMOTE` string input — the **primary** deliberate-action control on this repo (free-plan private repos get no Environment required-reviewer enforcement). The `demo` GitHub Environment is used for **secrets isolation only**, not protection it cannot enforce. `sync-demo.sh`'s vhost smoke reports true health (`/health` for `api.*`).

## Context Loading

- Pattern: `.github/workflows/deploy-recognition.yml` (ephemeral tailnet, SSH key, Environment, concurrency, PROMOTE gate).
- Deploy logic: `scripts/deploy/sync-demo.sh`; `infra/oci/demo/bootstrap-wp.sh`; packaging `apps/prototype-wp-alt-context/scripts/release/package-plugin.sh`.
- One-time setup reference: `docs/runbooks/deploy-recognition-cicd.md` (secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `ACX_DEPLOY_SSH_KEY`).
- Smoke spec: `apps/prototype-wp-alt-context/tests/e2e/evidence/demo-walkthrough.spec.ts` (test-level assertions vs manifest verdict).
- Handoff: DDEP-1 `decision #2180`.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| CI → OCI VM deploy | infra/CI | `deploy-recognition.yml` deploys backend only; demo is laptop-only | Add `deploy-demo.yml` running `sync-demo.sh` under `tag:ci` | no (additive; new workflow) | `actionlint`; dispatch on the feature ref |
| `sync-demo.sh` vhost smoke | infra deploy script | curls `/` on all vhosts (api.* → 404 false-fail) | Probe `/health` for `api.*` (pre/post-promote baseline: FAIL only deploy-caused regressions); demo `/` follows redirects, final 2xx non-installer (contract updated by DDEP-2) | no (internal script) | run the smoke against live vhosts |
| Post-deploy acceptance | CI | none for demo | Run demo-walkthrough spec asserting surfaces render + RECOG-1 single-target contract; fail-loud | no | spec exit code on a healthy vs broken deploy |

## Proposed Solution

Add `.github/workflows/deploy-demo.yml`, a near-clone of `deploy-recognition.yml`: `workflow_dispatch` only; `runs-on: ubuntu-latest`; `CONFIRM=PROMOTE` string gate as the primary deliberate-action control; a `demo` GitHub Environment scoped to secrets isolation; `concurrency` group (`cancel-in-progress: false`). Steps: (1) checkout; (2) build the plugin zip on the runner — `setup-node` + `setup-php` (with composer), then `npm ci` in `apps/prototype-wp-alt-context` (build deps must exist first), then `package-plugin.sh` in **default build mode**: the packager itself runs `npm run build` and a staging-dir `composer install --no-dev`, and hard-errors if `public/assets/dist` is missing or empty (`ensure_runtime_inputs`), so `npm ci` MUST precede it and no separate workflow-level `npm run build`/`composer install` is needed; (3) join tailnet ephemerally as `tag:ci` + pin the VM tailnet IP and wait for `:22`; (4) configure the `ACX_DEPLOY_SSH_KEY` deploy key; (5) run `bash scripts/deploy/sync-demo.sh` from the repo root with `PLUGIN_ZIP` **unset** — `sync-demo.sh:36` auto-picks the newest `dist/alt-context-*.zip` (do NOT write `PLUGIN_ZIP=dist/alt-context-*.zip` as a command-prefix assignment: bash does no glob expansion there, and the literal string makes `scp "$PLUGIN_ZIP"` at `sync-demo.sh:71` fail mid-deploy; if an explicit pin is wanted, use `PLUGIN_ZIP="$(ls -t dist/alt-context-*.zip | head -1)"`); (6) post-deploy deploy-smoke. Harden `sync-demo.sh`'s vhost smoke to probe `/health` for `api.*`. The deploy-smoke runs the demo-walkthrough spec but treats its **test exit code** (surfaces render + single-target contract) as the gate, and its **manifest recognition verdict** as informational job output — so a backend recognition failure (out of scope) does not fail a successful deploy.

**Partial-failure recovery (fail-loud contract)**: the recovery path is a plain re-dispatch. `sync-demo.sh` re-copies the zip and re-runs `bootstrap-wp.sh`, whose `--force` reinstall + activation cycle re-runs dbDelta (idempotent by design), so an aborted scp or half-applied activation converges on the next run. Slice 1's proof includes one interrupted-then-redeployed run to verify convergence rather than asserting it.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| tooling/CI | `.github/workflows/deploy-demo.yml` | New `workflow_dispatch` demo deploy (mirror recognition pattern) |
| tooling/deploy | `scripts/deploy/sync-demo.sh` | Fix vhost smoke: `/health` for `api.*`; clear pass/fail; demo `/` final-2xx after redirects, installer-guarded (DDEP-2) |
| tests | `apps/prototype-wp-alt-context/tests/e2e/evidence/demo-walkthrough.spec.ts` | Add/confirm an assertion that the RECOG-1 single-target Settings contract is live (no local card / no `local_url` in GET) so the smoke proves the plugin landed, not just that WP renders |
| docs | `docs/runbooks/deploy-demo-cicd.md` (or extend `deploy-recognition-cicd.md`) | One-time secrets + Environment setup; how to dispatch; smoke semantics (deploy vs recognition) |

## Related Files

| File | Note |
| --- | --- |
| `infra/oci/demo/bootstrap-wp.sh` | Plugin install/activate cycle invoked by sync-demo (no change expected) |
| `apps/prototype-wp-alt-context/scripts/release/package-plugin.sh` | Runner-side zip build; verify it runs headless in CI |
| `infra/oci/demo/walkthrough-runbook.md` | Operator runbook that referenced `make deploy-demo`; cross-link the CI path |

## Verification Strategy

- Deterministic:
  - `actionlint .github/workflows/deploy-demo.yml` (workflow lint)
  - `bash -n scripts/deploy/sync-demo.sh` + shellcheck
  - `node_modules/.bin/vitest`/`tsc` unchanged; the new spec assertion runs under the `evidence` project only (its `testMatch` is `/evidence\/.*\.spec\.ts/`, `playwright.config.ts:49`; the `a11y` project does not match this spec) locally against the demo
- Runtime-parity:
  - `gh workflow run deploy-demo.yml --ref feature/ddep-1` (workflow_dispatch supports non-default refs) → observe an end-to-end deploy from CI; confirm demo serves the plugin. **Precondition**: the workflow file must be pushed to the remote feature branch first, and some GitHub setups only surface a `workflow_dispatch` workflow in the UI/API after it exists on the default branch. **Fallback** if dispatch on the feature ref is refused: `actionlint` + review pre-merge, then dispatch post-merge from `main` as the runtime proof (or `act` locally for a dry structural run).
  - Deploy-smoke: run demo-walkthrough spec against `demo.altcontext.com`; assert exit 0 (surfaces + single-target contract) on a healthy deploy
- Contract/fixture:
  - Smoke asserts `GET /acx/v1/settings` returns the trimmed RECOG-1 shape (no `local_url`) — proves current plugin is live
- Manual:
  - Confirm the vhost smoke prints `200`/health-true for `api.*` (no false `FAIL`)

## Slice Delivery

### Slice 1: `deploy-demo.yml` — laptop-free CI deploy

**Goal**: A `workflow_dispatch` run deploys the demo end-to-end from an ephemeral `tag:ci` runner, no operator machine.

Changes:
- New `.github/workflows/deploy-demo.yml`: dispatch-only trigger; `CONFIRM=PROMOTE` gate (primary control); `demo` Environment (secrets isolation); concurrency group (no cancel); ephemeral tailnet join + VM-IP pin + `:22` wait; `ACX_DEPLOY_SSH_KEY` config; runner-side plugin build (`setup-node` + `setup-php` with composer + `npm ci` in the plugin dir, then `package-plugin.sh` default build mode); `sync-demo.sh` from repo root with `PLUGIN_ZIP` unset (auto-pick, `sync-demo.sh:36`) — never a glob in a command-prefix assignment.
- Docs: one-time setup (secrets/Environment) + dispatch instructions.

Proof:
- `actionlint` clean; push the workflow to the remote feature branch, then `gh workflow run deploy-demo.yml --ref feature/ddep-1` deploys (fallback per Verification Strategy if the ref dispatch is refused); `demo.altcontext.com` serves the built plugin (single-target Settings), captured by the demo-walkthrough spec.
- One interrupted-then-redeployed run converges (partial-failure recovery verified, not assumed).

### Slice 2: Deploy-smoke hardening

**Goal**: The vhost smoke reports true health, and the workflow gates on deploy-success (not recognition health), fail-loud.

Changes:
- `sync-demo.sh`: probe `/health` for `api.*` vhosts; demo `/` gated on final 2xx after following redirects with a WP-installer guard (contract as revised by DDEP-2); explicit pass/fail lines.
- `demo-walkthrough.spec.ts`: assert the RECOG-1 single-target contract so the smoke proves the plugin landed; keep the recognition manifest verdict as informational.
- Wire the spec as the workflow's post-deploy acceptance step: gate on the spec's test exit code; publish the recognition verdict as a job annotation (informational).
- CI prerequisites for the spec (runner-side): `npm run e2e:install` (chromium) after `npm ci`; mint auth via `npm run e2e:auth` with `WP_BASE_URL=https://demo.altcontext.com`, `ACX_E2E_WP_ADMIN_USER`, `ACX_E2E_WP_ADMIN_PASS` supplied as `demo` Environment secrets. `e2e:auth` writes `tests/e2e/.auth/storageState.json` — on an ephemeral runner this is a fresh path each run, so the local-dev shared-storageState clobber concern does not apply; keep the path runner-local and never cache/upload it as an artifact.
- **Headed-browser reality (CI blocker if skipped)**: `playwright.config.ts` hard-codes `headless: false` for both `auth-setup` (`:41`) and `evidence` (`:52`, plus `slowMo`/video), and `e2e:auth` passes `--headed` (`package.json:12`); GitHub-hosted runners have no X server, so these fail immediately without a display. Wrap both CI invocations in `xvfb-run -a` (install first: `sudo apt-get update && sudo apt-get install -y xvfb`); `scripts/playwright-cli.sh` itself has no xvfb handling. Do not flip the config to headless — local evidence capture relies on the headed run.
- **Exact smoke invocation (file-scoped)**: run `xvfb-run -a bash scripts/playwright-cli.sh test --project=evidence evidence/demo-walkthrough.spec.ts` from `apps/prototype-wp-alt-context` (same file-scoped pattern as `e2e:runtime`, `package.json:15`). Do NOT use `npm run e2e:evidence` — the `evidence` project's `testMatch` (`playwright.config.ts:49`) sweeps all six evidence specs, including recognition-exercising `scan-runtime-evidence`, which would gate the deploy on recognition health and contradict the deploy-vs-recognition separation. Note `evidence` declares `dependencies: ['auth-setup']` (`playwright.config.ts:48`), so the admin-cred env vars must be present on the smoke invocation too, not only on the `e2e:auth` step.

Proof:
- Smoke passes on a healthy deploy, fails on a broken one; `api.*` no longer false-`FAIL`; a recognition round-trip failure does NOT fail the deploy job.

## Consolidated Checklist

## Context and Ownership
- [x] Loaded `deploy-recognition.yml`, `sync-demo.sh`, `package-plugin.sh`, and the CI-CD runbook before editing.
- [x] Confirmed no VM access is widened beyond the existing `tag:ci` identity.

### Checklist for Slice 1: CI deploy
- [x] `deploy-demo.yml` added: dispatch-only, PROMOTE gate (primary control), `demo` Environment (secrets isolation), concurrency (no cancel), ephemeral `tag:ci` join + VM-IP pin, deploy key, runner-side zip build (`npm ci` before `package-plugin.sh` default build mode), `sync-demo.sh` invocation.
- [x] One-time setup documented — secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `ACX_DEPLOY_SSH_KEY`, `WP_BASE_URL`, `ACX_E2E_WP_ADMIN_USER`, `ACX_E2E_WP_ADMIN_PASS`; `demo` Environment creation.
- [ ] Workflow pushed to the remote feature branch; dispatched on the feature ref (or documented fallback used); end-to-end deploy observed; demo serves the built plugin.
- [ ] Interrupted-then-redeployed run converges (recovery path verified).

### Checklist for Slice 2: Smoke hardening
- [x] `sync-demo.sh` vhost smoke probes `/health` for `api.*`; no false `FAIL`; clear pass/fail.
- [x] Walkthrough spec asserts the RECOG-1 single-target contract (deploy-landed signal).
- [x] Workflow gates on the spec's deploy-assertion exit code; recognition verdict is informational (does not fail the job).
- [x] Spec prerequisites wired in CI: `npm run e2e:install` (chromium) + `npm run e2e:auth` from Environment secrets; storageState stays runner-local (never cached/uploaded).
- [x] Both browser steps run under `xvfb-run -a` (xvfb installed); smoke invocation is file-scoped to `evidence/demo-walkthrough.spec.ts` (never bare `e2e:evidence`); admin-cred env present on the smoke invocation (auth-setup dependency).

## Review Readiness
- [x] The new workflow reuses `sync-demo.sh`/`package-plugin.sh` (no forked deploy logic).
- [x] Deploy vs recognition-health signals are clearly separated in the smoke.
- [x] Handoff decision records the CI addition, the smoke fix, and the deferred observability boundary.

## Stretch Goals
- [ ] Lighter alternative smoke: an authenticated `GET /acx/v1/settings` contract assertion (no browser) as a fast pre-check before the full walkthrough spec.
- [x] Emit the recognition manifest verdict as a GitHub job summary so the backend failure is visible to the observability follow-up.

## Success Criteria
- [ ] A demo deploy runs entirely from CI (`gh workflow run deploy-demo.yml`) with no operator laptop/SSH and no new standing VM access.
- [x] The deploy is dispatch-only, serialized (concurrency), and gated by the PROMOTE confirmation (primary control), with the `demo` Environment isolating secrets.
- [ ] `sync-demo.sh` vhost smoke reports true health for `api.*` (no benign-`404` false failure). *(implemented + characterization-tested at DDEP-2; runtime confirmation rides the first CI dispatch)*
- [ ] The post-deploy smoke fails a broken deploy but does not fail on the out-of-scope recognition round-trip failure. *(implemented + characterization-tested at DDEP-2; runtime confirmation rides the first CI dispatch)*
