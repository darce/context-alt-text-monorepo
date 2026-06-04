# E15-6. Playwright Operator-Evidence Harness (two lanes)

> **Task Short ID**: E15-6
> **Status**: active v2.2 -- v1 harness files are present in the repo; 2026-06-04 refresh updates the durable checklist and consolidates the remaining operator proof backlog after the Playwright CLI work. Absorbs `docs/tasks/tech-debt/e2e-smoke-automation-path.md` and supersedes the deferred stub at `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md`. v2 drops the Playwright MCP slice entirely (user direction during plan-analyze: clear operator backlog first).
> **Target Branch**: `feature/e15-6`
> **Worktree**: `context-alt-text-monorepo-e15-6`
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) (un-defers E15-6 from [E16](../../epics/v0.4.1/public-demo-followons-epic.md) for the v1 scope).
> **Predecessors**: none for v1 Slices 1–4 (scaffolding + Lane A + Lane C). v2 envelope Slice 8 (offline label persistence spec) consumes the backend-outage helper from Slice 7; Slices 9–10 build on Slice 6 (WP-CLI seed/reset).
> **Blocks**: E15 manual-gate evidence work currently captured ad-hoc (`E15-3a` LocalWP→OCI roundtrip checklist, `E15-22` workbench avatar/progress proof, `E15-5` live-demo round-trip) gets a reproducible capture path once v1 lands.
> **Source intake**: scope note [`docs/scopes/e15-6-playwright-operator-evidence-harness.md`](../../scopes/e15-6-playwright-operator-evidence-harness.md); MCP decisions `#3186`–`#3191`; plan-analyze findings `E15-6-PA-01..08` (session `plan-analyze-e15-6-20260603`).

---

## Objective

Ship a single Playwright toolchain (`@playwright/test`) that powers two v1 lanes — operator-evidence capture and route-level axe a11y — under `apps/prototype-wp-alt-context`. v1 lands scaffolding plus Lane A (operator evidence) plus Lane C (axe smoke) against LocalWP at `http://localhost:10010/wp-admin/`. Lane B (durable smoke specs from the absorbed tech-debt doc) is specified in-plan as the v2 envelope so the tech-debt doc can be archived without losing context, but v2 slices do not ship in v1. Playwright MCP is wholly out of scope for this plan.

## Problem Statement

Operator evidence for E15 manual gates (`E15-3a`, `E15-22`, `E15-5`) is captured ad-hoc today: agents take their own screenshots, run different terminal transcripts, click through LocalWP differently, and produce artifacts of inconsistent shape. Two adjacent problems compound this:

- There is no committed browser harness for durable plugin E2E smoke. `docs/tasks/tech-debt/e2e-smoke-automation-path.md` has been open since v0.3.x Phase 3 with three named scenarios (offline label persistence, full-cycle local-read resilience, sync-status integrity) and Phase 0 scaffolding that has never landed.
- Full-page accessibility is only enforced at the component level via `vitest-axe` (`apps/prototype-wp-alt-context/package.json:52`). Route-level a11y violations on Dashboard, Workbench, Roster, and Settings can ship undetected.

E15-6 already exists as a stub in `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md`, deferred to E16, with explicit intent to "absorb" the tech-debt doc. Two stakes, zero implementation. The scope note pulls E15-6 forward and refocuses v1 around the operator-evidence problem that is currently blocking E15 demo gates, plus the scaffolding that Lane B and Lane C will reuse.

## Constraints

- **Single Playwright toolchain only.** `@playwright/test` is the only Playwright install. The standalone `playwright-cli` npm package is *not* added. Rationale: `@playwright/test` ships `npx playwright` exposing every subcommand the standalone CLI ever provided (`codegen`, `screenshot`, `pdf`, `open`, `install`, `show-trace`, `test --headed`). Adding `playwright-cli` would mean a second devDependency, a parallel browser-binary footprint that can drift from `@playwright/test`'s pin, two competing `npx playwright*` invocations operators must reason about, and a second version-skew vector. One install = one binary = one Chromium pin = one source of truth. Evidence-capture runs use `playwright test --headed` (project `evidence`) or the `codegen`/`screenshot` subcommands from the same binary.
- v1 ships scaffolding + Lane A + Lane C only (Slices 1–4). The three Lane B smoke specs (offline label persistence, full-cycle local-read resilience, sync-status integrity) are specified in-plan as v2 envelope slices but do not ship in v1. They land in a follow-on slice of E15-6 or split back to E16, owner decided when v2 is scheduled.
- Auth bootstrap for v1 targets LocalWP only. No public-demo storage-state, no env-var-driven multi-target abstraction. Public-demo auth waits until E15 hosting exists.
- **No Playwright MCP work in v1 — not even docs.** This overrides intake decision D5's "MCP as opt-in docs snippet only" allowance. v1 goal is to clear operator backlog; MCP enablement returns as a separate task once the harness is in operator hands. Decision `claude_e15-6_drop_mcp_from_v1_clear_operator_backlog_first` records this amendment.
- Repo-local docs only. v1 docs live under `apps/prototype-wp-alt-context/docs/`. No `docs/workstate/playbooks/` entries; generic operator-evidence doctrine extracts to `agentic-protocol-monorepo` only after this repo proves the shape.
- Artifacts (storageState, traces, videos, screenshots, axe reports) are gitignored under a task-scoped path: `apps/prototype-wp-alt-context/local/playwright/<task-ref>/`. The `.gitignore` update lands in Slice 1.
- Operator credentials never land in committed files or shell history. Convention: env vars `ACX_E2E_WP_ADMIN_USER` / `ACX_E2E_WP_ADMIN_PASS` sourced from a gitignored `apps/prototype-wp-alt-context/.env.local`; `auth.setup.ts` reads env first and only falls back to interactive `page.pause()` when env is missing.
- v1 does not add visual regression / pixel-diff infrastructure, a cross-browser matrix beyond Chromium, a WordPress version matrix, CI integration, backend-outage helpers, or any Playwright MCP surface (scope-note Decision D5 amended by this plan).
- v1 does not modify production plugin code. All edits land under `apps/prototype-wp-alt-context/tests/e2e/`, `apps/prototype-wp-alt-context/docs/`, `apps/prototype-wp-alt-context/package.json`, `apps/prototype-wp-alt-context/playwright.config.ts`, root `Makefile`, root `.gitignore`, the absorbed tech-debt doc, the deferred stub, and the v0.4.0 epic.

## Workflow Principles

- One toolchain, three project profiles in the same `playwright.config.ts`: `evidence` (headed, slowMo, traces always on), `smoke` (headless, traces on failure), `a11y` (headless, axe-injected). Plus an `auth-setup` setup-project that produces the shared `storageState.json`.
- Why one toolchain (see Constraints bullet 1 for the full rationale): `playwright-cli` is superseded; `@playwright/test`'s `npx playwright` covers every subcommand. Two installs only buys browser-binary drift and operator confusion.
- Evidence is a capture concern. Smoke and a11y are gating concerns. Their failure modes and artifact lifecycles differ; the config separates them so a flaky evidence run cannot block a gating run and vice versa.
- Auth state is a one-time interactive bootstrap, not a credential in config. Operators set `ACX_E2E_WP_ADMIN_USER` / `ACX_E2E_WP_ADMIN_PASS` in a gitignored `.env.local` (preferred) or accept the interactive `page.pause()` prompt; subsequent runs reuse the gitignored `storageState.json`.
- Storage-state is the load-bearing detail. Document the bootstrap path so it is boring and reproducible — this is one of the three improvements from the prior evaluation.
- v2 envelope (Slices 6–12) reuses Slice 2 scaffolding without modification. If v2 needs to refactor the config or `auth.setup.ts`, treat that as a v1 design escape and capture a finding.

## Terminology

- **Lane A (operator evidence)**: headed `@playwright/test` runs whose primary output is screenshots, transcripts, and trace files for E15 manual gates. Pass/fail of the test step is secondary to artifact capture.
- **Lane B (durable smoke)**: headless `@playwright/test` specs that gate behavior. Pass/fail of each step is primary; artifact capture is on-failure only. The three v2-envelope specs from the absorbed tech-debt doc live here.
- **Lane C (axe a11y)**: headless `@playwright/test` specs that inject `@axe-core/playwright` at route load and fail on serious/critical violations. v1 gates on the *empty-state* a11y of each route — i.e. the route's shell on a clean LocalWP install with no scan data; expanded populated-state a11y is opt-in via `ACX_E2E_SEEDED` and is not part of the v1 gate.
- **`auth.setup.ts`**: a Playwright project-level setup file (per [Playwright authentication docs](https://playwright.dev/docs/auth)) that runs once to produce a `storageState.json` and is reused by all subsequent tests via project `dependencies` and `storageState`. Canonical location: `apps/prototype-wp-alt-context/tests/e2e/auth-setup/auth.setup.ts`.
- **Task-scoped artifact dir**: `apps/prototype-wp-alt-context/local/playwright/<task-ref>/` where `<task-ref>` is the active MCP task ref (e.g. `E15-6`, `E15-22`). Operator runs export `ACX_PLAYWRIGHT_TASK_REF` to set this.
- **Absorbed-source Phase**: when this plan quotes the absorbed tech-debt doc's "Phase 0/1/2/3" numbering directly, the reference is marked "(absorbed tech-debt Phase N)" to distinguish it from this plan's v1/v2 slice numbering.

## Current State Analysis

- `apps/prototype-wp-alt-context/package.json` now declares `@playwright/test`, `@axe-core/playwright`, `dotenv`, and the v1 scripts `e2e:install`, `e2e:list`, `e2e:auth`, `e2e:localwp`, `e2e:evidence`, and `a11y:localwp`. Existing Vitest and `vitest-axe` workflows remain unchanged.
- `apps/prototype-wp-alt-context/playwright.config.ts` now defines `auth-setup`, `evidence`, `smoke`, and `a11y` projects with task-scoped output under `local/playwright/<task-ref>/`.
- `apps/prototype-wp-alt-context/tests/e2e/` now contains auth setup, route fixtures, one dashboard smoke spec, one dashboard evidence spec, and four route-level axe specs with `ACX_E2E_SEEDED` guarded populated-state blocks.
- `apps/prototype-wp-alt-context/docs/localwp-development-runbook.md` documents `http://localhost:10010/wp-admin/` as the LocalWP target; `apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md` is now the operator browser-evidence runbook.
- `docs/tasks/tech-debt/e2e-smoke-automation-path.md` has been archived into this plan: absorbed-tech-debt Phase 0 is represented by the shipped scaffolding, and absorbed-tech-debt Phase 1+ remains the v2 envelope Slices 8–12.
- `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md` now points at this plan, and the v0.4.0/v0.4.1 epics describe E15-6 as active v1 with a deferred durable smoke envelope.
- Runtime proof is partially closed: the 2026-06-04 no-secret proof attempt confirmed Corepack npm `11.14.1`, local `npm install` still fails under workstation policy (`EALLOWREMOTE`), and the new shared-worktree launcher successfully listed the `E15-6` smoke/auth specs from the linked worktree by reusing the common git worktree install. Browser-install and auth-backed runtime checks remain open.

## Target Outcome

After v1 Slices 1–4 land:

1. An operator with LocalWP running can clone the repo, run `npm install` under `apps/prototype-wp-alt-context`, run `npm run e2e:install` (one-time browser binary), populate a gitignored `.env.local` with admin credentials, run the one-time auth bootstrap, then run `npm run e2e:localwp` and see a passing headless smoke test plus a gitignored trace artifact. The same operator can run `npm run e2e:evidence -- --grep <gate-name>` to capture screenshots for an E15 manual gate.
2. An operator can run `npm run a11y:localwp` and see passing route-level axe smoke against the four ACX admin routes' empty-state shells. Adding new routes (or expanding to seeded-state assertions via `ACX_E2E_SEEDED`) is additive.
3. A second agent capturing evidence for a different E15 task (e.g. `E15-22` workbench avatar/progress) can read `apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md` and produce a proof bundle without out-of-band guidance.
4. `docs/tasks/tech-debt/e2e-smoke-automation-path.md` is archived; the deferred stub at `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md` is replaced by a pointer to this task plan; the v0.4.0 epic reflects E15-6 un-deferred.

v2 envelope (Slices 6–12) is not part of v1 sign-off but each slice has a written re-entry point.

## 2026-06-04 Operator Backlog Consolidation

E15-6 is now the durable source of truth for Playwright-backed operator evidence. The old `feature/e15-live-demo-plan` worktree at `75d63bdf` is not canonical for this list: `make context` reports `task_ref=E15`, `plan_path=null`, and dirty changes limited to `Makefile`, `docs/operations/public-demo-oci-cohost-launch-plan.md`, and `packages/codex-subagent-bridge/uv.lock`. Treat that worktree as possible input for E15-5/E15-5a live-demo operations only, not as the Playwright operator-evidence backlog.

| Gate / task | Playwright can reduce now | Operator or shell work still required | Durable home |
| --- | --- | --- | --- |
| E15-6 harness proof | `@playwright/test` config, auth setup, dashboard smoke/evidence spec, and four route-level axe specs are committed; safe no-secret checks are `corepack npm install`, `corepack npm run e2e:install`, and `ACX_PLAYWRIGHT_TASK_REF=E15-6 corepack npm run e2e:list`. | Local `npm install` is still blocked on this workstation by `EALLOWREMOTE`, but linked worktrees can now reuse the common git worktree install via `scripts/playwright-cli.sh`; re-run browser-install and auth-backed checks once Chromium and credentials are available. | This checklist plus `apps/prototype-wp-alt-context/docs/playwright-harness.md`. |
| E15-3a LocalWP to OCI roundtrip | After auth bootstrap, Playwright can capture dashboard/admin evidence, screenshots, videos, and traces under `local/playwright/E15-3a/`; CLI `playwright screenshot` can capture unauthenticated wp-admin reachability without storing secrets. | OCI backend deploy/key wiring, LocalWP packaged plugin install, gate key placement, seeded media scan, backend-side correlation IDs, CORS/rate-limit checks, fallback timeout proof, and redacted run-log entries remain operator/shell-owned. | `docs/tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md` and `docs/tasks/15.0/E15-3a-localwp-oci-run-log.md`. |
| E15-22 Workbench avatar/progress | Playwright provides the browser harness and artifact directory for screenshots/traces; it can replace manual screenshot capture once a Workbench-specific evidence spec or headed operator flow is used. | The accepted seeded-media scenario, scan start, backend `thumb_url`/fallback interpretation, progress timing, and final proof-bundle curation remain operator-owned until deterministic seed/reset helpers land. | `docs/tasks/15.0/E15-22-workbench-avatar-and-progress-readiness-task-plan.md` plus the E15-3a/E15-3 run-log proof bundle. |
| E15-5 live-demo roundtrip | LocalWP rehearsal can use the same `ACX_PLAYWRIGHT_TASK_REF=E15-5` artifact convention now; public-demo browser proof can reuse the harness once public-demo auth/storage state exists. | Public host provisioning, DNS/URL, ARM/OCI evidence, public-demo credentials/storage-state bootstrap, live backend logs, and final run-log acceptance remain operator-owned. | `docs/tasks/15.0/E15-5-manual-remote-e2e-task-plan.md` and `docs/tasks/15.0/E15-5-mvp-round-trip-log.md`. |
| E15-5a OCI operational hygiene | No meaningful browser proof. | Budgets, Tailscale/SSH, OCI service hygiene, secret rotation, and fallback operations remain shell/operator work. | `docs/tasks/15.0/E15-5a-oci-operational-hygiene-task-plan.md`. |
| E15-3 public demo provisioning | After the site exists, Playwright can capture admin/plugin route evidence using the same screenshot/trace conventions. | WordPress host creation, plugin packaging/activation, public service wiring, demo URL readiness, and production-scoped secrets remain operator-owned. | `docs/tasks/15.0/E15-3-wordpress-demo-provisioning-task-plan.md`. |

## Context Loading

- Scope: `docs/scopes/e15-6-playwright-operator-evidence-harness.md`
- Rules: `docs/workstate/rules/development-workflow.md`, `docs/workstate/rules/frontend-guidelines.md`, `docs/workstate/rules/testing-typescript.md`, `docs/workstate/rules/testing-principles.md`
- LocalWP: `apps/prototype-wp-alt-context/docs/localwp-development-runbook.md` (LocalWP target + admin URL)
- Absorbed source: `docs/tasks/tech-debt/e2e-smoke-automation-path.md` (entire file folded into Slices 2 + 6–12 below; archived after Slice 3 lands)
- Stub to update: `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md`
- Epic to update: `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` (un-defer E15-6 from E16 for v1 scope)
- Handoff/MCP state: task ref `E15-6`; intake decisions `#3186`–`#3191`; plan-analyze findings `E15-6-PA-01..08` (session `plan-analyze-e15-6-20260603`)
- Existing a11y baseline: `apps/prototype-wp-alt-context/package.json:52` (`vitest-axe` component-level — kept as-is, not replaced)
- Existing menu: `apps/prototype-wp-alt-context/src/admin/class-menu.php` (slug source for `tests/e2e/fixtures/acx-routes.ts` in Slice 2)

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| WP plugin dev tooling | `apps/prototype-wp-alt-context` | Vitest-only frontend test surface; no E2E install | Add `@playwright/test` and `@axe-core/playwright` devDependencies; add `playwright.config.ts`, `tests/e2e/`, `tests/e2e/auth-setup/auth.setup.ts`; add npm scripts (`e2e:install`, `e2e:auth`, `e2e:localwp`, `e2e:evidence`, `a11y:localwp`) | Yes — existing Vitest path unchanged | `npm run e2e:localwp` on operator workstation; CI not in v1 |
| Repo-root operator wrappers | root `Makefile` | No `localwp-*-smoke` targets today | Add `localwp-e2e-install`, `localwp-e2e-auth`, `localwp-e2e-smoke`, `localwp-evidence`, `localwp-a11y-smoke` wrappers that delegate to the app-local npm scripts | N/A — additive | Wrapper invocation produces same exit code as the underlying npm script |
| Repo-root ignore | root `.gitignore` | No Playwright artifact ignore today | Add `apps/prototype-wp-alt-context/local/playwright/`, `apps/prototype-wp-alt-context/tests/e2e/.auth/`, and `apps/prototype-wp-alt-context/.env.local` to ignore rules | N/A — additive | `git status` clean after a run with traces/screenshots written and `.env.local` populated |
| Operator credentials | `apps/prototype-wp-alt-context/.env.local` (gitignored) + `.env.local.example` (committed) | No documented credential surface today | Add a committed `.env.local.example` template with `ACX_E2E_WP_ADMIN_USER=` and `ACX_E2E_WP_ADMIN_PASS=` placeholders; document the copy-and-edit step in `playwright-localwp-evidence.md` | N/A — additive | Operator can complete auth bootstrap non-interactively when env is set; falls back to interactive prompt otherwise |
| Operator docs | `apps/prototype-wp-alt-context/docs/` | No Playwright docs today | Add `playwright-localwp-evidence.md` (operator playbook) and `playwright-harness.md` (config + scripts reference, including "when the proof selector breaks" subsection) | N/A — additive | Manual: second agent can run the harness from docs alone |
| E15 epic + stub | `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md`, `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md` | E15-6 stub status "deferred -- owned by E16" | Un-defer for v1 scope; stub replaced by pointer to this plan; epic E15-6 entry updated | N/A — planning-only | Visible in dashboard regeneration after merge |
| Absorbed tech-debt doc | `docs/tasks/tech-debt/e2e-smoke-automation-path.md` | Open absorbed-tech-debt Phase 0–3 plan | Archived once Slice 3 lands; its Phase 0 absorbed into Slice 2, Phase 1 into Slices 8–10, Phase 2 into Slice 11, Phase 3 into Slice 12 | N/A — planning-only | File removed from `docs/tasks/tech-debt/`; archival noted in slice-complete decision |

## Proposed Solution

Land scaffolding and the two v1 lanes (operator evidence + axe a11y) under `apps/prototype-wp-alt-context` in four slices, then defer the absorbed Lane B work (WP-CLI seed/reset, backend-outage helpers, three smoke specs, CI, hardening) as v2 envelope slices specified in this plan but not shipped in v1. Each v1 slice is small enough to merge independently and the slice order minimises rework: docs first (so the contract is visible and reviewable before any install), then scaffolding (so subsequent test slices have something to plug into), then one proof test per lane.

## Files and Surfaces to Change

| Surface | File | Slice | Change |
| --- | --- | --- | --- |
| docs | `apps/prototype-wp-alt-context/docs/playwright-harness.md` | 1 | New — config, scripts, conventions, lane responsibilities, why-no-playwright-cli rationale, "when the proof selector breaks" subsection |
| docs | `apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md` | 1 | New — LocalWP operator playbook (browser install, `.env.local` copy-and-edit, storage-state bootstrap, evidence capture recipes for E15-3a/E15-22/E15-5) |
| credentials template | `apps/prototype-wp-alt-context/.env.local.example` | 1 | New — committed template with `ACX_E2E_WP_ADMIN_USER=` and `ACX_E2E_WP_ADMIN_PASS=` placeholder lines and a comment block pointing at `playwright-localwp-evidence.md` |
| ignore | root `.gitignore` | 1 | Add `apps/prototype-wp-alt-context/local/playwright/`, `apps/prototype-wp-alt-context/tests/e2e/.auth/`, `apps/prototype-wp-alt-context/.env.local` |
| stub | `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md` | 1 | Replace contents with a pointer to this task plan; preserve task short ID and historical reference to E16 deferral |
| epic | `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` | 1 | Un-defer E15-6 entry; note v1 scope (scaffolding + Lane A + Lane C) and v2 envelope boundary |
| deps | `apps/prototype-wp-alt-context/package.json` | 2 | Add `@playwright/test` and `@axe-core/playwright` to `devDependencies`; add `e2e:install`, `e2e:auth`, `e2e:localwp`, `e2e:evidence`, `a11y:localwp` to `scripts` |
| config | `apps/prototype-wp-alt-context/playwright.config.ts` | 2 | New — four projects (`auth-setup`, `evidence`, `smoke`, `a11y`), task-scoped `outputDir`, gitignored `storageState` path |
| test | `apps/prototype-wp-alt-context/tests/e2e/auth-setup/auth.setup.ts` | 2 | New — reads `ACX_E2E_WP_ADMIN_USER`/`ACX_E2E_WP_ADMIN_PASS` env (loaded from gitignored `.env.local`); falls back to interactive `page.pause()` when env missing; performs WP admin login; writes `tests/e2e/.auth/storageState.json` |
| test fixtures | `apps/prototype-wp-alt-context/tests/e2e/fixtures/acx-routes.ts` | 2 | New — central registry of ACX admin slugs resolved at Slice 2 write time from `src/admin/class-menu.php` (Dashboard, Workbench, Roster, Settings) so Slices 3 and 4 do not duplicate selectors |
| wrappers | root `Makefile` | 2 | Add `localwp-e2e-install`, `localwp-e2e-auth`, `localwp-e2e-smoke`, `localwp-evidence` (passing through `ACX_PLAYWRIGHT_TASK_REF` from a Make variable), `localwp-a11y-smoke` targets that delegate to the app-local npm scripts |
| test | `apps/prototype-wp-alt-context/tests/e2e/smoke/dashboard-loads.spec.ts` | 3 | New — Lane A first proof test: load the ACX dashboard with stored auth, assert one stable selector renders, capture a screenshot |
| absorbed source | `docs/tasks/tech-debt/e2e-smoke-automation-path.md` | 3 | Delete (archive via git history) once Slice 3 verification passes; preserved via Slices 6–12 of this plan |
| test | `apps/prototype-wp-alt-context/tests/e2e/a11y/dashboard-axe.spec.ts` | 4 | New — Lane C empty-state axe smoke: load Dashboard, inject `@axe-core/playwright`, fail on serious/critical violations |
| test | `apps/prototype-wp-alt-context/tests/e2e/a11y/workbench-axe.spec.ts` | 4 | New — Workbench empty-state axe smoke (no seeded data needed for v1 gate); a populated-state block guarded by `ACX_E2E_SEEDED` is opt-in and not part of v1 gate |
| test | `apps/prototype-wp-alt-context/tests/e2e/a11y/roster-axe.spec.ts` | 4 | New — Roster empty-state axe smoke |
| test | `apps/prototype-wp-alt-context/tests/e2e/a11y/settings-axe.spec.ts` | 4 | New — Settings empty-state axe smoke |

## Related Files

| File | Note |
| --- | --- |
| `docs/scopes/e15-6-playwright-operator-evidence-harness.md` | Intake scope; this task plan is its downstream artifact. Intake decision D5 is amended by this plan: MCP wholly out of v1, not just opt-in docs |
| `docs/tasks/15.0/E15-22-workbench-avatar-and-progress-readiness-task-plan.md` | First consumer of Lane A evidence capture (workbench avatar/progress proof) |
| `docs/tasks/15.0/E15-3a-localwp-oci-roundtrip-task-plan.md` | Consumer of Lane A evidence capture (LocalWP→OCI roundtrip proof bundle) |
| `docs/tasks/15.0/E15-5-manual-remote-e2e-task-plan.md` | Consumer of Lane A evidence capture (live-demo round-trip; public-demo storage-state arrives later) |
| `docs/epics/v0.4.1/public-demo-followons-epic.md` | E16; receives v2 envelope Slices 6–12 if they do not ship inside E15-6 |
| `apps/prototype-wp-alt-context/package.json` | Existing Vitest + `vitest-axe` setup remains unchanged |
| `apps/prototype-wp-alt-context/src/admin/class-menu.php` | Slug source for `tests/e2e/fixtures/acx-routes.ts` |

## Verification Strategy

- Deterministic checks (v1):
  - `cd apps/prototype-wp-alt-context && npm install` — `@playwright/test` and `@axe-core/playwright` resolved.
  - `cd apps/prototype-wp-alt-context && npm run e2e:install` — Chromium browser binary installed locally; idempotent.
  - `cd apps/prototype-wp-alt-context && npm run e2e:auth` — runs the one-time auth bootstrap. With `.env.local` populated, the run is non-interactive; without, it falls back to `page.pause()`. Operator confirms `tests/e2e/.auth/storageState.json` lands and is gitignored.
  - `cd apps/prototype-wp-alt-context && ACX_PLAYWRIGHT_TASK_REF=E15-6 npm run e2e:localwp` — Slice 3 proof test passes against running LocalWP.
  - `cd apps/prototype-wp-alt-context && ACX_PLAYWRIGHT_TASK_REF=E15-6 npm run a11y:localwp` — Slice 4 empty-state axe smoke passes on all four routes; serious/critical violations fail the run.
  - `make localwp-e2e-smoke` and `make localwp-a11y-smoke` at repo root — wrappers produce the same exit code as the npm scripts.
- Runtime-parity / environment checks:
  - LocalWP running at `http://localhost:10010/wp-admin/` with the plugin activated per `apps/prototype-wp-alt-context/docs/localwp-development-runbook.md`.
- Manual verification:
  - A second agent reads `apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md` and captures an E15-22 workbench screenshot without further guidance.
- Pre-merge:
  - `handoff_close_check(enforce=True)` passes on `E15-6` with zero open findings (planning findings `E15-6-PA-01..08` resolved); v1 slice-complete decisions for Slices 1–4 recorded; test_result evidence for the verifications above tied to current HEAD SHA.

## Slice Delivery

### Slice 1: Repo-local docs + ignore paths + credentials template + stub + epic update

**Goal**: Land the v1 contract in docs before any install, so reviewers can confirm placement, conventions, credential handling, and the v2-envelope boundary before any code changes.

Changes:

- New `apps/prototype-wp-alt-context/docs/playwright-harness.md`: documents the three lane responsibilities, the one-toolchain principle (with the why-no-`playwright-cli` rationale from Constraints bullet 1 inlined), the project layout (`tests/e2e/{auth-setup/auth.setup.ts,smoke/,a11y/,evidence/,fixtures/}`), the artifact dir convention, the npm script catalogue (referencing Slice 2 for the actual install), and a "when the proof selector breaks" subsection covering (a) confirm the route still renders manually, (b) update the selector in the spec file plus `fixtures/acx-routes.ts` if the slug also changed, (c) re-run the smoke and record the change in the slice-complete decision.
- New `apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md`: operator playbook covering (a) prerequisites (LocalWP at `http://localhost:10010/wp-admin/`, plugin activated, `npm run e2e:install` one-time browser bootstrap, `cp .env.local.example .env.local && edit` for admin credentials), (b) the `auth.setup.ts` bootstrap walkthrough (non-interactive with env, interactive fallback), (c) evidence capture recipes for E15-3a (LocalWP→OCI roundtrip), E15-22 (workbench avatar/progress), and E15-5 (live-demo round-trip placeholder until public-demo auth lands), (d) artifact redaction rules before copying anything out of `local/playwright/<task-ref>/`.
- New `apps/prototype-wp-alt-context/.env.local.example`: committed template with `ACX_E2E_WP_ADMIN_USER=` and `ACX_E2E_WP_ADMIN_PASS=` placeholders and a comment block pointing at `playwright-localwp-evidence.md`. Never populated with real credentials in this file.
- Root `.gitignore`: add `apps/prototype-wp-alt-context/local/playwright/`, `apps/prototype-wp-alt-context/tests/e2e/.auth/`, and `apps/prototype-wp-alt-context/.env.local`.
- Replace `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md` contents with a pointer to this task plan; preserve the historical "deferred to E16" note as a one-line "v1 un-deferred 2026-06-03; v2 envelope owns the original E16 scope" line.
- Update `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` E15-6 entry: change status to active v0.4.0 for the v1 scope, link this task plan, note that v2 envelope may still split back to E16.

Verification:

- Manual review of the docs by the user; no executable check.
- `git status` after edits shows only the surfaces enumerated above.

Slice-complete decision: `claude_slice_complete_e15-6_docs_credentials_ignore_stub_epic`.

### Slice 2: Scaffolding (deps + config + auth setup + scripts + wrappers)

**Goal**: A bare scaffolding that subsequent test slices can plug into. No tests in this slice — only the infrastructure that makes Slices 3 and 4 small.

Changes:

- `apps/prototype-wp-alt-context/package.json`:
  - Add `@playwright/test` and `@axe-core/playwright` to `devDependencies` at versions pinned at slice-write time.
  - Add scripts: `e2e:install` → `bash scripts/playwright-cli.sh install chromium`; `e2e:list` → `bash scripts/playwright-cli.sh test --list`; `e2e:auth` → `bash scripts/playwright-cli.sh test --project=auth-setup --headed`; `e2e:localwp` → `bash scripts/playwright-cli.sh test --project=smoke`; `e2e:evidence` → `bash scripts/playwright-cli.sh test --project=evidence --headed`; `a11y:localwp` → `bash scripts/playwright-cli.sh test --project=a11y`.
  - New `apps/prototype-wp-alt-context/scripts/playwright-cli.sh`: resolves Playwright from the local app install first, then falls back to the common git worktree's `apps/prototype-wp-alt-context/node_modules` so linked worktrees can reuse an existing install without weakening npm policy.
- New `apps/prototype-wp-alt-context/playwright.config.ts` with four projects:
  - `auth-setup`: testDir `tests/e2e/auth-setup`, no `storageState`, headed, produces `tests/e2e/.auth/storageState.json`.
  - `evidence`: testDir `tests/e2e/evidence`, depends on `auth-setup`, headed, `slowMo: 200`, `trace: 'on'`, `video: 'on'`, `outputDir: local/playwright/${ACX_PLAYWRIGHT_TASK_REF ?? 'adhoc'}/evidence/`.
  - `smoke`: testDir `tests/e2e/smoke`, depends on `auth-setup`, headless, `trace: 'retain-on-failure'`, `outputDir: local/playwright/${ACX_PLAYWRIGHT_TASK_REF ?? 'adhoc'}/smoke/`.
  - `a11y`: testDir `tests/e2e/a11y`, depends on `auth-setup`, headless, `outputDir: local/playwright/${ACX_PLAYWRIGHT_TASK_REF ?? 'adhoc'}/a11y/`.
  - `use.baseURL` reads `WP_BASE_URL` env var with `http://localhost:10010` default.
  - Loads `.env.local` via `dotenv/config` (or equivalent) so env-driven credential reading works without a separate operator step.
- New `apps/prototype-wp-alt-context/tests/e2e/auth-setup/auth.setup.ts`:
  - Reads `ACX_E2E_WP_ADMIN_USER` / `ACX_E2E_WP_ADMIN_PASS` from `process.env`.
  - If both env vars present, performs login non-interactively against `WP_BASE_URL/wp-admin/`.
  - If either env var missing, opens the login page headed and calls `page.pause()` so the operator can type credentials interactively (one-shot UX).
  - Asserts admin bar visible, then `page.context().storageState({ path: 'tests/e2e/.auth/storageState.json' })`.
- New `apps/prototype-wp-alt-context/tests/e2e/fixtures/acx-routes.ts`: exports the ACX admin slugs as a typed const (per [sr-007] in CLAUDE.md), resolved at slice-write time from `src/admin/class-menu.php` (the four submenu slugs plus the top-level menu).
- Root `Makefile`: add five targets that `cd apps/prototype-wp-alt-context && npm run <script>` for `e2e:install`, `e2e:auth`, `e2e:localwp`, `e2e:evidence` (passing through `ACX_PLAYWRIGHT_TASK_REF` from a Make variable), `a11y:localwp`.

Verification:

- `cd apps/prototype-wp-alt-context && npm install` — `@playwright/test` and `@axe-core/playwright` resolved.
- `cd apps/prototype-wp-alt-context && npm run e2e:install` — Chromium installed.
- `cd apps/prototype-wp-alt-context && npm run e2e:list` — config loads through `scripts/playwright-cli.sh`; linked worktrees reuse the common git worktree install when local `node_modules` are absent.
- Wrapper verification (`make localwp-e2e-smoke`) is deferred to Slice 3 because `@playwright/test` defaults to exit code 1 when no tests match the project filter; the cleanly-exit-on-no-tests behavior requires `--pass-with-no-tests`, which is not the right shape for a gating wrapper.

Slice-complete decision: `claude_slice_complete_e15-6_scaffolding_deps_config_auth_scripts_wrappers`.

### Slice 3: Lane A first proof test + tech-debt doc archival

**Goal**: One concrete passing smoke test that exercises the full path (auth setup → smoke spec → trace artifact). Archive the absorbed tech-debt doc once the test is green.

Changes:

- New `apps/prototype-wp-alt-context/tests/e2e/smoke/dashboard-loads.spec.ts`: loads the ACX dashboard route from `fixtures/acx-routes.ts`, asserts one stable selector (pinned at slice-write time — either a heading containing "Alt Context" or a dashboard-card `data-testid`; spec narrative records which), captures a screenshot to the task-scoped artifact dir. No backend assertions, no clustering, no media — just route-load + render.
- Delete `docs/tasks/tech-debt/e2e-smoke-automation-path.md` (archived via git history; its content is preserved in Slices 2 + 6–12 of this plan).
- Cross-references in Slice 1's docs updated to point at this plan instead of the deleted tech-debt doc.

Verification:

- Operator runs `npm run e2e:auth` once (interactive or env-driven per Slice 2); `tests/e2e/.auth/storageState.json` exists and is gitignored.
- `cd apps/prototype-wp-alt-context && ACX_PLAYWRIGHT_TASK_REF=E15-6 npm run e2e:localwp` — Slice 3 spec passes; screenshot lands at `local/playwright/E15-6/smoke/dashboard-loads/`; trace not retained (passed).
- `make localwp-e2e-smoke` from repo root produces the same exit code.
- `git status` shows the tech-debt doc deleted; nothing else surprising.

Slice-complete decision: `claude_slice_complete_e15-6_lane_a_first_proof_test_and_tech_debt_archival`.

### Slice 4: Lane C empty-state axe smoke on four routes (closes v1)

**Goal**: Route-level a11y gating on the four ACX admin surfaces. Each spec asserts the route's *empty-state* a11y on a clean LocalWP install (no scan data needed). Serious/critical violations fail the run; moderate findings are reported but do not fail by default. A populated-state assertion block guarded by `ACX_E2E_SEEDED` is included in each spec but skipped by default — it is opt-in for richer a11y coverage after seed data exists, and is not part of the v1 gate.

Changes:

- New `apps/prototype-wp-alt-context/tests/e2e/a11y/dashboard-axe.spec.ts`: loads Dashboard, waits for the empty-state shell, injects `@axe-core/playwright`, asserts no serious/critical violations. Optional `ACX_E2E_SEEDED` block: skipped by default; when set, asserts the populated dashboard.
- New `apps/prototype-wp-alt-context/tests/e2e/a11y/workbench-axe.spec.ts`: same shape against Workbench's empty-state shell (the v1 gate). `ACX_E2E_SEEDED` block adds populated-cluster assertions, skipped by default.
- New `apps/prototype-wp-alt-context/tests/e2e/a11y/roster-axe.spec.ts`: same against Roster.
- New `apps/prototype-wp-alt-context/tests/e2e/a11y/settings-axe.spec.ts`: same against Settings.
- Update `apps/prototype-wp-alt-context/docs/playwright-harness.md` to document the serious/critical-only default, the empty-state-vs-`ACX_E2E_SEEDED` distinction, and the per-route empty-state pattern (each spec is responsible for the route-specific `waitFor` selector that confirms the empty-state shell is rendered before axe injection).

Verification:

- `cd apps/prototype-wp-alt-context && ACX_PLAYWRIGHT_TASK_REF=E15-6 npm run a11y:localwp` — all four empty-state specs pass against a clean LocalWP install with the plugin activated; the `ACX_E2E_SEEDED` blocks are skipped (`test.skip`) and reported as such.
- `make localwp-a11y-smoke` — same exit code.
- Per-violation triage: any serious/critical finding caught during this slice is recorded as an MCP review finding tied to E15-6, not silenced. Moderate findings are reported in the slice-complete decision rationale.

Slice-complete decision: `claude_slice_complete_e15-6_lane_c_axe_empty_state_smoke_closes_v1`. **This decision closes v1.**

---

## v2 envelope (absorbed from tech-debt doc; not part of v1)

The following slices are specified here so the absorbed tech-debt doc can be archived in Slice 3 without losing the work. They do not ship in v1. v2 is scheduled separately and may split back to E16 — that decision is made when v2 is picked up, not now.

### Slice 6 (v2): WP-CLI seed/reset helpers

Deterministic WP-CLI scripts for plugin options, projection tables, and seeded media fixtures. Reuses existing `acx xmp-backfill` and `acx reset-projection` per the absorbed-tech-debt doc's triage checklist. Lands under `apps/prototype-wp-alt-context/tests/e2e/fixtures/wp-cli/`. Enables the `ACX_E2E_SEEDED` populated-state axe assertions introduced in Slice 4 to actually run with data.

### Slice 7 (v2): Backend outage control helper

Service stop/start or Toxiproxy/wp-env/Docker Compose helper for outage scenarios. Choice of implementation deferred to the v2 scheduling decision (the absorbed-tech-debt doc lists all four as candidates). Lands under `apps/prototype-wp-alt-context/tests/e2e/fixtures/backend-control/`.

### Slice 8 (v2): Offline label persistence spec

Lane B durable smoke spec from the absorbed tech-debt doc, Test Scenarios §1: backend down → label cluster → verify local persistence; backend up → trigger sync/read → verify label still present. Consumes Slice 7 helper.

### Slice 9 (v2): Full-cycle local-read resilience spec

Lane B durable smoke spec, Test Scenarios §2: backend up → clusters load + analysis trigger; backend down → clusters still load from local projection. Consumes Slices 6 and 7.

### Slice 10 (v2): Sync-status integrity spec

Lane B durable smoke spec, Test Scenarios §3: verify `sync-status` transitions (`last_synced_at`, stale state) across restart/recovery. Consumes Slices 6 and 7.

### Slice 11 (v2): CI integration

Absorbed-tech-debt Phase 2: dedicated CI job for E2E smoke with reproducible environment; persist Playwright traces/videos on failure; fail PRs on smoke regression in sovereign read/write paths. Requires a CI WordPress runtime path (likely `wp-env` or Docker Compose) chosen during Slice 7.

### Slice 12 (v2): Hardening

Absorbed-tech-debt Phase 3: remove dependency on LocalWP private GraphQL from required smoke flow docs; document local-only fallback path separately (non-gating); add flake budget and retry policy with explicit thresholds. Targets the absorbed-tech-debt doc's Phase 3 success criteria.

---

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(PA-04 closed)`, `(fixed in MCP)`, or "resolve E15-6-PR-02"; finding status is queried from the handoff DB via `review_findings(review={"operation":"list","status":"open","task_ref":"E15-6"})` or read from `DASHBOARD.txt`. See [`branch-review-guide.md` § Review Findings Placement](../../workstate/rules/branch-review-guide.md#review-findings-placement-mandatory).

### Checklist for Slice 1: Repo-local docs + ignore paths + credentials template + stub + epic update

- [x] New `apps/prototype-wp-alt-context/docs/playwright-harness.md` with one-toolchain rationale, lane responsibilities, project layout, and "when the proof selector breaks" subsection.
- [x] New `apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md` with prerequisites, auth bootstrap walkthrough, evidence capture recipes (E15-3a/E15-22/E15-5), and artifact redaction rules.
- [x] New `apps/prototype-wp-alt-context/.env.local.example` committed template (placeholders only, no credentials).
- [x] Root `.gitignore` adds `apps/prototype-wp-alt-context/local/playwright/`, `apps/prototype-wp-alt-context/tests/e2e/.auth/`, `apps/prototype-wp-alt-context/.env.local`.
- [x] `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md` replaced with pointer to this task plan; historical E16-deferral note preserved as one line.
- [x] `docs/epics/v0.4.0/public-demo-launch-readiness-epic.md` E15-6 entry un-deferred; v1 scope and v2-envelope boundary noted.
- [x] Slice-complete bookkeeping is covered by current structured handoff decisions on HEAD: `copilot_slice_complete_E15-6_operator_playwright_backlog_refresh`, `copilot_slice_complete_E15-6_shared_playwright_launcher`, and `copilot_slice_complete_E15-6_runtime_proof_lanes_a_c`.

### Checklist for Slice 2: Scaffolding (deps + config + auth setup + scripts + wrappers)

- [x] `apps/prototype-wp-alt-context/package.json` adds `@playwright/test` + `@axe-core/playwright` devDependencies and scripts `e2e:install`, `e2e:list`, `e2e:auth`, `e2e:localwp`, `e2e:evidence`, `a11y:localwp`.
- [x] New `apps/prototype-wp-alt-context/scripts/playwright-cli.sh` resolves Playwright from the local app install first, then the common git worktree install for linked-worktree runs.
- [x] New `apps/prototype-wp-alt-context/playwright.config.ts` lists four projects (`auth-setup`, `evidence`, `smoke`, `a11y`); reads `WP_BASE_URL`; loads `.env.local`; `outputDir` interpolates `ACX_PLAYWRIGHT_TASK_REF`.
- [x] New `apps/prototype-wp-alt-context/tests/e2e/auth-setup/auth.setup.ts` reads `ACX_E2E_WP_ADMIN_USER`/`_PASS` env-first with `page.pause()` fallback; writes `tests/e2e/.auth/storageState.json`.
- [x] New `apps/prototype-wp-alt-context/tests/e2e/fixtures/acx-routes.ts` exports ACX admin slugs as typed const, resolved from `src/admin/class-menu.php`.
- [x] Root `Makefile` adds wrappers `localwp-e2e-install`, `localwp-e2e-auth`, `localwp-e2e-smoke`, `localwp-evidence`, `localwp-a11y-smoke`.
- [ ] Verification: `corepack npm install`, `corepack npm run e2e:install`, `ACX_PLAYWRIGHT_TASK_REF=E15-6 corepack npm run e2e:list` succeed. 2026-06-04 attempt confirmed Corepack npm `11.14.1`; local `npm install` still stops at workstation `EALLOWREMOTE`, but `corepack npm run e2e:localwp -- --list` now succeeds from the linked `E15-6` worktree via the shared-worktree launcher. Browser-install and auth-backed runtime checks remain deferred to Slice 3 runtime verification.
- [x] Slice-complete bookkeeping is covered by `copilot_slice_complete_E15-6_shared_playwright_launcher` plus `copilot_slice_complete_E15-6_runtime_proof_lanes_a_c`; the strict fresh-clone install proof remains the only Slice 2 verification gap.

### Checklist for Slice 3: Lane A first proof test + tech-debt doc archival

- [x] New `apps/prototype-wp-alt-context/tests/e2e/smoke/dashboard-loads.spec.ts` loads ACX dashboard, asserts stable selector, captures screenshot to task-scoped artifact dir.
- [x] New `apps/prototype-wp-alt-context/tests/e2e/evidence/dashboard-evidence.spec.ts` gives the headed evidence lane one committed dashboard proof capture.
- [x] `docs/tasks/tech-debt/e2e-smoke-automation-path.md` deleted (archived via git history); cross-references in Slice 1 docs updated to point at this plan.
- [x] Verification: operator ran `corepack npm run e2e:auth` (one-time); `ACX_PLAYWRIGHT_TASK_REF=E15-6 corepack npm run e2e:evidence` and `ACX_PLAYWRIGHT_TASK_REF=E15-6 corepack npm run e2e:localwp` passed; task-scoped artifacts landed under `local/playwright/E15-6/`; `ACX_PLAYWRIGHT_TASK_REF=E15-6 make localwp-e2e-smoke` exited 0 on 2026-06-04.
- [x] Slice-complete decision `copilot_slice_complete_E15-6_runtime_proof_lanes_a_c` recorded for the Lane A runtime proof closure on 2026-06-04.

### Checklist for Slice 4: Lane C empty-state axe smoke on four routes (closes v1)

- [x] New `apps/prototype-wp-alt-context/tests/e2e/a11y/dashboard-axe.spec.ts` asserts empty-state Dashboard axe; optional `ACX_E2E_SEEDED` block skipped by default.
- [x] New `apps/prototype-wp-alt-context/tests/e2e/a11y/workbench-axe.spec.ts` asserts empty-state Workbench axe (no seeded data needed for v1 gate).
- [x] New `apps/prototype-wp-alt-context/tests/e2e/a11y/roster-axe.spec.ts` asserts empty-state Roster axe.
- [x] New `apps/prototype-wp-alt-context/tests/e2e/a11y/settings-axe.spec.ts` asserts empty-state Settings axe.
- [x] `apps/prototype-wp-alt-context/docs/playwright-harness.md` updated to document serious/critical-only default + empty-state-vs-`ACX_E2E_SEEDED` distinction + per-route empty-state pattern.
- [x] Verification: `corepack npm run a11y:localwp` passed all four empty-state specs against clean LocalWP on 2026-06-04; the four `ACX_E2E_SEEDED` blocks reported as skipped by design; `make localwp-a11y-smoke` matched the passing exit code.
- [x] Slice-complete decision `copilot_slice_complete_E15-6_runtime_proof_lanes_a_c` recorded for the Lane C empty-state a11y runtime proof on 2026-06-04; seeded-state checks remain deferred behind `ACX_E2E_SEEDED`.

## Context and Ownership

- [x] Loaded the minimum authoritative rules, contracts, and handoff state before editing (`CLAUDE.md`, `docs/workstate/rules/development-workflow.md`, scope note, and current E15-6 MCP handoff state).
- [x] Confirmed external dependency context for `@playwright/test` and `@axe-core/playwright` does not require `ctx7` for this close-out pass; no upstream API behavior changed.
- [x] Recorded boundary ownership and compatibility expectations: WP plugin dev tooling, root Makefile wrappers, root `.gitignore`, repo-local docs surface, E15 epic + stub — all owned by this task; existing Vitest + `vitest-axe` path unchanged.

## Review Readiness

- [x] No boundary-touching implementation is left without matching contract/doc/fixture evidence: every npm script and Make wrapper added in Slice 2 is documented in Slice 1's `playwright-harness.md`; every artifact path is named in `.gitignore` and the operator playbook.
- [x] Runtime-parity checks are included where tests can mask real behavior: Slice 3's `make localwp-e2e-smoke` exercised the real LocalWP admin on 2026-06-04; Slice 4 exercised the real route empty-state markup through both direct npm and root Make wrappers. No mocked WP admin surface.
- [x] Handoff decisions record the change, verification, and contract implications for the current close-out evidence: `copilot_slice_complete_E15-6_operator_playwright_backlog_refresh`, `copilot_slice_complete_E15-6_shared_playwright_launcher`, and `copilot_slice_complete_E15-6_runtime_proof_lanes_a_c`.

## Success Criteria

- [ ] An operator with LocalWP running can, from a fresh clone, complete `npm install → npm run e2e:install → cp .env.local.example .env.local && edit → npm run e2e:auth → npm run e2e:localwp` and see a passing smoke test with a gitignored trace artifact. Current workstation proof remains blocked at `corepack npm install` by `EALLOWREMOTE`; linked-worktree execution is proven through the shared launcher, but it does not satisfy the strict fresh-clone criterion.
- [x] An operator can run `npm run a11y:localwp` and see four passing empty-state axe smoke specs against a clean LocalWP install with the plugin activated; the seeded-state checks remain intentionally skipped until `ACX_E2E_SEEDED` is set, and serious/critical violations still fail the run.
- [x] A second agent capturing evidence for a different E15 task (e.g. E15-22 workbench avatar/progress) can read `apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md` and produce a proof bundle without out-of-band guidance.
- [x] `docs/tasks/tech-debt/e2e-smoke-automation-path.md` archived; `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md` replaced by pointer to this plan; v0.4.0 epic reflects E15-6 un-deferred.
- [ ] `handoff_close_check(enforce=True)` passes on `E15-6` with zero open findings after the remaining fresh-clone install proof is resolved and the active MCP row is marked `done`.

## Risks

- **Operator credential handling.** `.env.local` lives on operator workstations only; never committed (Slice 1 `.gitignore` rule). If an operator skips the env-var setup, the auth bootstrap falls back to `page.pause()` and credentials are typed interactively (not persisted in shell history). If an operator misconfigures `.env.local` so it lands in a different gitignored path, the env-var read fails silently and bootstrap falls back to interactive — annoying but not insecure.
- **Slug drift.** `fixtures/acx-routes.ts` is resolved from `src/admin/class-menu.php` at Slice 2 write time. If the slugs change between slices, Slices 3 and 4 break. Mitigation: the "when the proof selector breaks" subsection in `playwright-harness.md` (Slice 1) covers the recovery path.
- **Proof-test selector drift.** Dashboard markup can change during E15-22 workbench work or any future refactor. Slice 3's stable-selector assertion would break. Mitigation: same `playwright-harness.md` subsection — confirm route renders, update spec + fixtures, re-run, record the change in the slice-complete decision.
- **Axe rule churn.** `@axe-core/playwright` rule set evolves with the package version. Pinning the dependency at Slice 2 write time and documenting the rule baseline in Slice 4 makes a future bump a deliberate decision instead of a silent regression source.
- **v2 envelope owner ambiguity.** Slices 6–12 are specified here but the scope note explicitly says they may split back to E16. v1 must not introduce dependencies on v2 envelope slices landing inside E15-6 specifically.

## Out of Scope (v1)

- Lane B durable smoke specs (offline label persistence, full-cycle local-read resilience, sync-status integrity) — specified as v2 envelope Slices 8–10.
- CI integration (dedicated job, PR-blocking smoke gate, trace/video persistence in CI) — v2 envelope Slice 11.
- Backend-outage helpers (Toxiproxy, `wp-env`, Docker Compose) — v2 envelope Slice 7.
- WP-CLI seed/reset helpers — v2 envelope Slice 6.
- Populated-state axe assertions (`ACX_E2E_SEEDED` blocks land in Slice 4 specs but are opt-in / skipped by default; they require Slice 6 seed helpers to be meaningful).
- Visual regression / pixel-diff (Percy, Argos, etc.).
- Cross-browser matrix beyond Chromium; WordPress version matrix.
- Public-demo storage-state and any env-var-driven multi-target auth abstraction.
- **Playwright MCP — not even docs.** Intake decision D5's "MCP as opt-in docs snippet" allowance is amended by this plan. MCP enablement returns as a separate task once operator backlog is cleared.
- `docs/workstate/playbooks/` entries — v1 docs are repo-local under `apps/prototype-wp-alt-context/docs/`.
- Extraction of generic operator-evidence doctrine to `agentic-protocol-monorepo` — happens after this repo proves the shape, not in v1.
- Modifications to production plugin code — v1 is additive test infrastructure only.
