# E15-6. Playwright Operator-Evidence Harness (three lanes)

> **Status**: scope (intake recorded 2026-06-03)
> **Task ref**: `E15-6`
> **Parent epic**: [docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../epics/v0.4.0/public-demo-launch-readiness-epic.md) (E15)
> **Branch**: `feature/e15-6`
> **Worktree**: `context-alt-text-monorepo-e15-6`
> **Supersedes**: [docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md](../tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md) (un-deferred from E16 by this scope) and absorbs the former tech-debt plan now archived into [docs/tasks/15.0/E15-6-playwright-operator-evidence-harness-task-plan.md](../tasks/15.0/E15-6-playwright-operator-evidence-harness-task-plan.md).

## Problem

Operator evidence for E15 gates (E15-3a, E15-22, E15-5) is captured manually today: ad-hoc screenshots, terminal transcripts, and LocalWP clickthroughs that vary per agent and are not reproducible. Two adjacent problems compound this: (1) there is no committed browser harness for durable plugin E2E smoke (the tech-debt doc has stayed open since Phase 3), and (2) full-page a11y is only enforced at the component level via `vitest-axe` (`apps/prototype-wp-alt-context/package.json:52`), so route-level violations on Dashboard/Workbench/Roster/Settings can ship undetected.

E15-6 already exists as a stub in `docs/tasks/15.0/` and was deferred to E16 with explicit intent to "absorb" the tech-debt automation doc. Two stake holders, zero implementation. This scope pulls E15-6 forward into v0.4.0 and refocuses its v1 around the operator-evidence problem (the one blocking E15 demo gates) plus shared scaffolding, with durable smoke specs staying as Phase 2 inside E15-6.

## MVP scope

This scope note defines the outcome and boundaries for the task-plan stage; it does not lock the implementation contract.

- A single Playwright toolchain (`@playwright/test`) powers all three lanes. There is no separate `playwright-cli` package install; operator evidence runs as `playwright test --headed` (or `playwright codegen`/`playwright screenshot` against the same install).
- Three lanes are recognised, with v1 scope only on Lanes A and C plus shared scaffolding:
  - **Lane A — Operator evidence (v1).** Headed runs that capture screenshots, transcripts, and time-sequenced proof artifacts for E15 manual gates. Default target: LocalWP at `http://localhost:10010/wp-admin/`. Artifacts land under a gitignored task-scoped path.
  - **Lane B — Durable E2E smoke (Phase 2, deferred inside E15-6).** The three specs from the absorbed tech-debt doc — offline label persistence, full-cycle local-read resilience, sync-status integrity — plus CI wiring and backend-outage helpers (Toxiproxy/wp-env/Docker). Out of v1 scope; remains in E15-6 backlog or splits back to E16.
  - **Lane C — Axe a11y smoke (v1).** Route-level `@axe-core/playwright` checks on Dashboard, Workbench, Roster, Settings. Serious/critical violations are blockers; moderate findings are triaged unless the active task is explicitly a11y work. Stays separate from screenshot evidence — a screenshot proving avatars rendered is not an a11y pass.
- Auth bootstrap for v1 targets LocalWP only. A documented `auth.setup.ts` global-setup pattern (interactive one-time login, gitignored `storageState.json` output) is the only auth path that ships in v1. Public-demo storage-state waits until E15 hosting exists.
- MCP browser tooling is opt-in only. The task plan ships a documented snippet (using `@playwright/mcp` with `--isolated`, `--output-mode=file`, and a task-scoped `--user-data-dir`/output dir) but does not wire MCP into any committed workflow or default config. The snippet must explicitly call out that MCP's browser context cannot share state with `@playwright/test` runs.
- Repo-local docs live under `apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md` (LocalWP-specific operator playbook) and `apps/prototype-wp-alt-context/docs/playwright-harness.md` (config, scripts, conventions). Generic operator-evidence doctrine extracts to `agentic-protocol-monorepo` only after this repo proves the shape; nothing lands in `docs/workbay/playbooks/` in v1.
- All Playwright artifacts (storageState, traces, videos, screenshots, axe reports) live under a gitignored path scoped per task ref, e.g. `local/playwright/<task-ref>/`. The task plan picks the exact convention; `.gitignore` updates are part of Phase 0.
- First implementation slice (v1) is intentionally narrow: docs + ignore paths + Playwright config + npm/Make wrappers + one route-load smoke test. Axe and richer seeded proof flows follow only after login/storage-state and fixture setup are boring.

## Decisions (intake)

Recorded as MCP decisions on `E15-6`:

- `D1` -- **Three-lane harness with one toolchain.** Operator evidence, durable e2e, and a11y are recognised as distinct lanes with distinct lifecycles; they share `@playwright/test` as the only install. No `playwright-cli` package. Rationale: avoid two parallel toolchains; `--headed` runs and `codegen`/`screenshot` subcommands cover evidence capture from the same binary.
- `D2` -- **Placement is this monorepo, under `apps/prototype-wp-alt-context`.** Generic operator-evidence doctrine extracts to `agentic-protocol-monorepo` only after this repo proves the shape. No independent vendored repo. Rationale: most of the work is product-specific (WP admin storage state, LocalWP target, ACX routes, seeded media, E15 mappings); abstraction over a sample size of one is premature.
- `D3` -- **E15-6 pulled forward from E16; absorbs the tech-debt doc.** The deferred-in-stub status is overridden by this scope. v1 ships Phase 0 scaffolding + Lane A (operator evidence) + Lane C (axe smoke). Lane B (durable smoke specs from the tech-debt doc) becomes Phase 2 inside E15-6 or returns to E16; the task plan decides. The tech-debt doc is archived once Phase 0 lands so there is one source of truth.
- `D4` -- **LocalWP-only auth bootstrap for v1.** Document a single `auth.setup.ts` global-setup pattern with interactive one-time login against `http://localhost:10010/wp-admin/` and a gitignored `storageState.json`. Public-demo storage-state waits until E15 hosting exists; v1 does not ship an env-var-driven multi-target abstraction.
- `D5` -- **Not-doing v1: visual regression / pixel-diff, cross-browser + WP version matrix (Chromium-only on LocalWP default WP), CI integration + backend-outage helpers, Playwright MCP committed wiring.** MCP ships as an opt-in docs snippet only. Rationale: smallest first slice that proves the shape; each deferred item has a clean re-entry point under E15-6 Phase 2 or a follow-on epic.

## Success criteria

1. The follow-on task plan can describe one concrete first slice (Phase 0 + Lane A first proof test) that an operator can run end-to-end against LocalWP without inventing storage-state or artifact conventions on the fly.
2. The scaffolding (Playwright config, `auth.setup.ts`, artifact-dir convention, npm/Make wrappers) is reusable by Lane B (durable smoke) and Lane C (axe) without rework — Phase 2 work is additive, not a refactor.
3. The repo-local docs (`apps/prototype-wp-alt-context/docs/playwright-*.md`) are sufficient for a second agent to capture E15-22 (workbench avatar/progress) or E15-3a (LocalWP→OCI roundtrip) evidence without out-of-band guidance.
4. The MCP opt-in snippet documents the user-data-dir and output-mode separation explicitly enough that an exploratory MCP session cannot poison a `@playwright/test` storage state.

## Not-doing

- No durable e2e smoke specs in v1 (offline label persistence, full-cycle local-read resilience, sync-status integrity remain Phase 2 inside E15-6 or return to E16).
- No CI job, no Playwright traces/videos persisted to CI artifacts, no PR-blocking smoke gate.
- No backend-outage simulation (Toxiproxy, `wp-env`, Docker Compose, service stop/start helpers).
- No visual regression / pixel-diff infrastructure (Percy, Argos, etc.). Operator screenshots are artifacts, not gated diffs.
- No cross-browser matrix (no Firefox/WebKit projects in v1). No WordPress version matrix.
- No public-demo storage-state, no env-var-driven multi-target auth abstraction beyond what LocalWP needs.
- No Playwright MCP wiring in default config or any committed workflow; MCP ships as an opt-in docs snippet only.
- No `docs/workbay/playbooks/` entries; the v1 playbook is repo-local under `apps/prototype-wp-alt-context/docs/`.
- No file-by-file implementation inventory, exact npm script names, exact ignore-path conventions, or per-route axe rule allowlists in this scope note; those belong in the task plan.

## Assumptions

- LocalWP is installed and running at `http://localhost:10010/wp-admin/` for any operator who runs the v1 harness. Operators without LocalWP are out of scope for v1.
- The plugin is activated and seeded in the LocalWP install per existing operator docs (`apps/prototype-wp-alt-context/docs/localwp-development-runbook.md`); the harness does not (re-)seed WordPress in v1.
- `@playwright/test` and `@axe-core/playwright` are acceptable new dev dependencies under `apps/prototype-wp-alt-context/package.json`. No conflict with the existing `vitest-axe` component-level a11y setup.
- The existing `vitest-axe` component-level a11y enforcement stays as-is; route-level axe is additive, not a replacement.
- Operators capturing evidence will run `npm run e2e:localwp` / `npm run a11y:localwp` (or the make wrappers) from the worktree; one-off `npx playwright ...` invocations are an unsupported escape hatch in v1.

## Next step

Draft the E15-6 task plan on `feature/e15-6` at `docs/tasks/15.0/E15-6-playwright-operator-evidence-harness-task-plan.md`, using the intake decisions above to specify:

- exact `apps/prototype-wp-alt-context/playwright.config.ts` shape (projects: `evidence` headed, `smoke` headless, `a11y` headless),
- `auth.setup.ts` bootstrap and `storageState` location,
- `local/playwright/<task-ref>/` (or equivalent) artifact convention and `.gitignore` updates,
- npm scripts (`e2e:localwp`, `a11y:localwp`, evidence-capture wrapper) and root Make targets,
- the single Phase 0 + Lane A first proof test (route-load against `/wp-admin/admin.php?page=acx-dashboard` or equivalent stable ACX route),
- the repo-local docs (`apps/prototype-wp-alt-context/docs/playwright-localwp-evidence.md`, `playwright-harness.md`),
- the Playwright MCP opt-in snippet (separate `--user-data-dir`, `--output-mode=file`, task-scoped output dir; explicit non-shareability with `@playwright/test`),
- the archival path absorbed into `docs/tasks/15.0/E15-6-playwright-operator-evidence-harness-task-plan.md` and the update to the deferred E15-6 stub at `docs/tasks/15.0/E15-6-e2e-smoke-gate-automation-stub.md`,
- the E15 epic update that un-defers E15-6 from E16 and lists the v1 scope.

Phase 2 (Lane B durable smoke specs + CI + backend-outage helpers) gets its own slice inside E15-6 once v1 is verified, or splits back to E16 — the task plan picks.
