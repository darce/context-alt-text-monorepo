# E17-10. Hoist Agentic System MVP — Distribution, Overlay, and Daemon Opt-In

- **Date**: 2026-04-17
- **Author**: Claude Opus 4.7
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-10`
- **Review Coverage Target**: 2
- **Source Scope**: [docs/scopes/hoist-agentic-system-to-remote-scope.md](../../scopes/hoist-agentic-system-to-remote-scope.md)
- **Hard Prerequisites**: E17-6 merged (skills anatomy, `harness-protocol.yaml`, `check-skills`, `check-harness-sync`). E17-8 merged far enough that both harness guards read `harness-protocol.yaml` through a contract-resolved path rather than hardcoded roots; Slice 2 of this plan adds the overlay layer on top of that contract path in consumer repos, and this plan does not reopen the guard rewrite. `gh` CLI authenticated as account `darce` with `repo` + `delete_repo` scopes (verified 2026-04-17 via `gh auth status`); SSH key configured for `git@github.com:darce/*`; target repo names `darce/agentic-system`, `darce/mcp-agent-orchestrator`, and `darce/agentic-bootstrap` verified available. Historical assumption: `darce/mcp-agent-handoff` already existed from AHMCP-5. As of 2026-04-19, remote verification has disproved that assumption; Slice 0 must recreate `darce/mcp-agent-handoff` before Slice 1 can pin against it. [E17-11](./E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md) (multi-active-task-singleton-writes-hotfix — formerly scoped as E17-7 Slice 2) is a **soft** prerequisite — see Slice 5 for the ordering tradeoff.

---

## Prior Review Disposition

This plan has been re-reviewed several times as the distribution topology and portability contract sharpened. The durable milestones on file are:

- **Review run 226** (`planning-review-e17-10-2026-04-17-run-01`, 2026-04-17 04:45Z, codex) — verdict `pass_with_findings` on commit `5f3bb5ca`. Preceded by plan-analyze run 225 (tenancy-clarification decision).
- **Review run 234** (`planning-review-e17-10-portability-20260417T1855Z`, 2026-04-17 18:55Z, codex) — verdict `fail` on commit `b7397615` with decision `claude_planning_review_E17-10_fail_path_portability` (portability gaps in the packaged-consumer path surface).
- **Revision commit `c19619e7`** (`E17-10: docs(tasks): revise plan to close 8 planning findings`) — closed 8 findings from runs 226 + 234, primarily around path-contract portability, `run_doctor` monorepo-relative assumptions, `scripts/mcp/mcp-server.sh` non-hoisting, and tenancy wording.
- **Review runs 246 / 247 / 250 / 251** (2026-04-18 sequence) — the plan moved through `conditional_pass`, `fail`, `fail`, then `pass` as the topology stabilized around standalone repos plus the bootstrap overlay, replacing earlier mixed monorepo/subdirectory assumptions.
- **Review run 259** (`planning-review-e17-10-2026-04-18-run-06`, 2026-04-18 23:46Z, Claude Opus 4) — verdict `conditional_pass` on commit `4f2ee291`, leaving follow-up gaps around stale daemon anchors and consumer portability details.
- **Review run 266** (`planning-review-e17-10-2026-04-19-run-07`, 2026-04-19 02:54Z, codex) — verdict `conditional_pass` with decision `claude_opus_4_7_planning_review_E17-10_conditional_pass_run_07`, recording findings `E17-10-PR7-H-01`, `E17-10-PR7-M-01`, and `E17-10-PR7-L-01`.
- **Current working-tree revision on `feature/e17-10`** addresses the run-07 findings by (a) converting daemon anchors to function/pattern references, (b) adding explicit consumer `core.hooksPath` wiring + proof, and (c) documenting both `AmbiguousWorkspaceContextError` and `ConsumerRootResolutionError` in the planned consumer surface.

---

## Objective

Deliver an MVP that lets another local Daniel-owned project adopt the same handoff.db state, review findings, failed-test revisions, and parallel-agent implementation discipline without copying source trees. Scope:

1. **Distribute MCP servers** as pip packages (`git+ssh://...` URLs in the MVP) — `agent-handoff-mcp` and `agent-orchestrator-mcp` — with per-consumer `handoff.db` isolation.
2. **Symlink skills, hooks, contracts, and generated workflow adapters** into consumer repos via a new `agentic-bootstrap` CLI, including both `.github/hooks/` and `scripts/hooks/` because the VS Code and Claude harnesses do not currently share one hook directory.
3. **Resolve an overlay** where project-local `local/` surfaces take precedence over the symlinked shared surface; `check-skills` and `check-harness-sync` validate the effective overlay.
4. **Keep worker daemons shippable but opt-in**, with a deterministic token-consumption warning at daemon start and in `docs/agentic/consumer-setup.md`. Host-subagent primitives (Claude Agent tool, `codex exec`, `run_structured_turn`) remain the default parallel-implementation mechanism — consistent with [E17-9 Constraint 1](./E17-9-parallel-reviews-and-autonomous-bug-fix-loop-task-plan.md).
5. **Record an event-driven-daemon rework note** so the pull-vs-push architecture question is captured in a logical place for a follow-on epic, without implementing it here.

## Why This Is Separate

Neither E17-6, E17-7, E17-8, nor E17-9 owns cross-project distribution. Folding it into any of them would either delay their merge or scope-creep them into packaging and versioning concerns with zero overlap with their charters. This plan is the first surface that treats `harness-protocol.yaml` and generated command adapters as _external_ consumer-facing artifacts rather than internal repo plumbing — that reframing deserves its own plan. Tenancy and overlay are both load-bearing enough that they need explicit design here rather than a bolt-on to another in-flight epic.

## Problem Statement

The agentic system works inside this monorepo only. Five gaps block multi-project adoption:

1. **MCP servers are editable installs against local source trees.** `agent-handoff-mcp` and `agent-orchestrator-mcp` are consumed via `pip install -e packages/...` from this checkout. There is no versioned artifact a second project can pin, no documented MVP install URL, and no `CHANGELOG`-bump discipline tied to tagged releases.
2. **The existing handoff path contract is undocumented and too permissive for packaged consumers.** `RuntimeConfig.for_repo(Path("."))` already converges linked worktrees to the primary git worktree and `RuntimeConfig.from_args()` already honors `AGENT_HANDOFF_WORKSPACE_ROOT`, `AGENT_HANDOFF_STATE_DIR`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, `AGENT_HANDOFF_DASHBOARD_PATH`, and `AGENT_HANDOFF_EXPORTS_DIR`. The actual gaps are: no consumer-facing doc explains those surfaces, no packaged-consumer proof shows they isolate state under the consumer repo, and non-git callers still fall back silently to cwd-relative `.task-state/` paths instead of failing fast with a remediation message.
3. **Skills, hooks, contracts, and generated adapters live under this repo's paths.** A consumer project has no supported path to import them that preserves live editability or diff visibility when this repo ships updates. Copy-paste drifts silently; upstream changes never flow through.
4. **Validators assume one flat surface.** `scripts/check_skills.py` and `scripts/check_harness_sync.py` walk a single tree each. Overlay resolution (shared + local, with local precedence) does not exist, so a consumer cannot add a project-specific skill variant without forking upstream.
5. **Daemon token cost is invisible and polling is architecturally load-bearing, with no rework note in the repo.** `orchestrator_daemon.py` polls every 60s via the main-loop `time.sleep(poll_interval)` inside `orchestrator_loop()`, and `worker_daemon.py` polls every 30s via the `time.sleep(cfg.poll_interval)` sites inside `worker_loop()`. Each orchestrator cycle runs ≈10–15 MCP queries across `_worker_management_phase()`, `_poll_merge_ready_lanes()`, lane-inbox reads, `_dispatch_phase()`, and `_guidance_phase()`. Worker daemons spawn `lane_prompt.py --check` subprocesses per poll via `poll_lane_state()`. A consumer enabling daemons inherits that cost with no in-product warning. No `TODO`/`FIXME` in the daemon modules flags the pull-vs-push architecture question — the rework signal is load-bearing missing.

## Constraints

- **Install model is fixed (per scope decision).** MCP servers install as pip packages from `git+ssh://...` URLs in the MVP. Private PyPI or wheel mirrors are deferred to a later epic. Skills, hooks, contracts, and generated adapters install via the bootstrap CLI, which **symlinks** (not copies) from a consumer-local clone of the remote agentic repo.
- **Canonical standalone remote repos are fixed for MVP.** The remote family is:
  - `mcp-agent-handoff` (`darce/mcp-agent-handoff`)
  - `mcp-agent-orchestrator` (`darce/mcp-agent-orchestrator`)
  - `agentic-system` (`darce/agentic-system`)
  - `agentic-bootstrap` (`darce/agentic-bootstrap`)
- **Overlay model is fixed (per scope decision).** Shared symlinks + project-local `local/` counterparts with local precedence. Validators resolve the effective overlay, not the raw shared tree. YAML-valued surfaces (`harness-protocol.yaml`) merge with per-top-level-key local-override semantics; list values replace rather than concatenate. Slice 2 documents this contract.
- **MVP success signal is fixed (per scope decision).** One MCP minor-version bump **plus** one shared-skill change propagates end-to-end via the documented update workflow with zero manual copying. Slice 5 validates this.
- **No open-sourcing in MVP.** No LICENSE, no CONTRIBUTING, no badges, no public-PyPI upload, no social surfaces. Scope is private Daniel-owned repos only.
- **No substantive skill rewrites during the hoist.** Adapt skill path layouts to be overlay-aware if required; do not rewrite skill bodies.
- **Tenancy is by-DB-file, not by-schema.** Each consumer writes to its own `handoff.db` file under the existing state-dir contract: `AGENT_HANDOFF_STATE_DIR` → `RuntimeConfig.state_dir` → `<consumer-root>/.task-state/`, with `handoff.db` living at `<state-dir>/handoff.db`. `AGENT_HANDOFF_WORKSPACE_ROOT`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, `AGENT_HANDOFF_DASHBOARD_PATH`, and `AGENT_HANDOFF_EXPORTS_DIR` remain the only env-driven output/path surface in the MVP; this plan does not introduce parallel `*_DB_PATH` or `*_OUTPUT_ROOT` env vars. No `tenant_id` column is added to any `handoff.db` table in this plan. Schema-level tenancy is explicitly out of scope and, if ever needed, would be a new epic. Same-project active-task collisions are a separate concern owned by **[E17-11](./E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md)** (multi-active-task-singleton-writes-hotfix — formerly scoped as E17-7 Slice 2) and are a soft prerequisite to this plan.
- **Worker daemons ship, but are opt-in and noisy.** A `harness-protocol.yaml` flag `orchestrator.daemons.enabled` defaults `false`. `dispatch_lane_work(start_worker=True)`, `manage_worker(action in {"start","start_all"})`, and `manage_orchestrator(operation in {"start","single_cycle"})` all raise `DaemonsDisabledError` on `false` with an actionable message. The gated action sets are exactly the actions the existing tool dispatchers accept today (`manage_worker` valid set: `{start, stop, resume, status, event_history, start_all}`; `manage_orchestrator` valid set: `{pause, resume, single_cycle, start, status, stop}`) — no new action names are introduced. When `true`, daemon start emits a one-shot `logging.WARNING` naming poll intervals, approximate MCP-queries per cycle, a qualitative token-cost note (no invented tokens/hour figure), and the path to the event-driven design note. The MCP tool count does not change.
- **Host-subagent primitives remain the default parallel-implementation mechanism.** The MVP's parallel-review and auto-fix-loop user story flows through E17-9's `SubagentAdapter` protocol, not through daemons. Daemons are the long-running-operator-pipeline escape hatch.
- **Polling rework is noted, not implemented.** A design-note doc at `packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` + `TODO(E17-10-REWORK)` comments at every `time.sleep(poll_interval)` call site are the only deliverables for the event-driven question in this plan.
- **No new MCP tool names.** The bootstrap CLI is a separate pip console script. Configuration knobs land on existing `RuntimeConfig` and `harness-protocol.yaml` surfaces.
- **Branch-isolation and main-change guards must continue to function in a consumer repo.** `harness-protocol.yaml` must be resolvable through the overlay; `.github/hooks/` and `scripts/hooks/` must both be hoisted; and the consumer success signal assumes E17-8 has already landed contract-driven guard loading. This plan preserves and validates that behavior in the overlaid consumer tree; it does not own the guard rewrite itself.
- **`scripts/mcp/mcp-server.sh` is not a consumer surface.** Slice 3's harness-config writers emit MCP server commands directly. The monorepo-local launcher remains a repo-specific convenience and is neither hoisted nor relied on by consumer setup.
- **Constitution alignment preserved.** `rg-013` (handoff core stays pure CRUD) and `rg-014` (orchestrator uses late-binding imports for handoff symbols) continue to hold across package-boundary changes. Any slice that would violate them must stop and escalate.

## Current State Analysis

**Packaging and distribution**

- `packages/agent-handoff-mcp/pyproject.toml` and `packages/agent-orchestrator-mcp/pyproject.toml` declare versioned projects but are consumed via editable installs only.
- Neither package has a tag-based release script, a `CHANGELOG.md` update discipline tied to version bumps, nor a documented install URL for external consumers.
- `agent-orchestrator-mcp` currently depends on `agent-handoff-mcp` via a `git+ssh://git@github.com/darce/mcp-agent-handoff.git` URL pinned in its `pyproject.toml` — the dependency edge is cross-repo, not a sibling editable install. Post-Slice-0 the dep stays on the standalone handoff repo, pinned to a release tag rather than floating `main`.
- Per the [In-Monorepo Package Test Invocation Rule](../../agentic/rules/testing-python.md#in-monorepo-package-test-invocation-mandatory), an editable install pins all Python interpreters in the venv to one source path regardless of worktree — a consumer that also installs from source in an editable mode would inherit the same trap. The hoist must favor non-editable (`pip install git+ssh://...@tag`) resolution.

**Handoff DB path contract**

- `RuntimeConfig.for_repo(Path("."))` already resolves the primary git worktree and defaults state under `<workspace-root>/.task-state/`; `RuntimeConfig.from_args()` already honors `AGENT_HANDOFF_WORKSPACE_ROOT`, `AGENT_HANDOFF_STATE_DIR`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, `AGENT_HANDOFF_DASHBOARD_PATH`, and `AGENT_HANDOFF_EXPORTS_DIR`.
- What is missing is consumer-facing documentation, a packaged-consumer proof that those existing surfaces isolate state under the consumer repo, and a fail-fast branch for non-git/no-explicit-override callers instead of silently creating `.task-state/` under an arbitrary cwd.

**Skills, hooks, contracts, adapters**

- `.claude/skills/` holds the Claude surface; `.github/hooks/` holds the VS Code/Copilot hook surface; `scripts/hooks/` holds the Claude hook implementations referenced by `.claude/settings.json`; `docs/agentic/contracts/` holds the harness/protocol contracts; `.claude/commands/` and `.github/prompts/` hold generated adapters driven by `config/agent-workflows/portable_commands.json`.
- `scripts/check_skills.py` and `scripts/check_harness_sync.py` walk one flat tree each; overlay resolution does not exist.
- No bootstrap or install CLI exists.
- `scripts/mcp/mcp-server.sh` is monorepo-specific today: it probes `apps/prototype-description-service/.python-version`, which is not portable to consumers and therefore must not become part of the hoisted surface.

**Daemons and polling** (sourced from the plan-stage survey; symbolic anchors are intentional so this section survives routine line drift)

- `orchestrator_loop()` runs an infinite `while True` with default poll interval 60s; the load-bearing sites are the main-loop `time.sleep(poll_interval)` plus the additional backoff sleeps in the same module.
- Per-cycle reads dominate token cost: `_worker_management_phase()` invokes `manage_worker(action="status")` per lane, then `_poll_merge_ready_lanes()` iterates all lanes calling `worker_reports(operation="list", fields="merge_ready")`. `_dispatch_phase()` and `_guidance_phase()` read lane inbox + decisions per cycle. Total ≈10–15 MCP queries per 60s.
- `worker_loop()` runs at 30s per cycle; the load-bearing sites are each `time.sleep(cfg.poll_interval)` inside that loop. `_poll_phase()` calls `poll_lane_state()`, which spawns `lane_prompt.py --check` subprocesses per poll.
- No sqlite `update_hook`, filesystem watcher, or pub/sub mechanism exists as an alternative signal. Lock architecture is `OrchestratorLock` and `WorkerLock` — per-process flock with SIGTERM graceful shutdown, compatible with a future push-based refactor.
- No `TODO`/`FIXME` comments in either daemon module flag polling cost.

## Out of Scope

- **Public open-source distribution** (per scope decision): no PyPI, no LICENSE, no CONTRIBUTING, no badges.
- **Private PyPI or wheel mirror**: MVP install path is `pip install git+ssh://...`. Later epic decides PyPI topology.
- **Aggregator repo and PyPI mirror** — a future `darce/mcp-servers` aggregator repo or a private PyPI mirror remains out of scope and is revisit-post-MVP. Slice 0 itself commits to creating `darce/mcp-agent-orchestrator`, `darce/agentic-system`, and `darce/agentic-bootstrap` as standalone private repos (mirroring the existing `darce/mcp-agent-handoff`) so every consumer-facing install URL targets a standalone repo and none reference `context-alt-text-monorepo`.
- **MCP server schema or behavior changes beyond configuration.** The only behavior additions in this plan are (a) the `handoff.db` path override contract, (b) the daemon opt-in flag, (c) the first-use WARNING log. No new tools, no new endpoints, no schema migrations.
- **Schema-level multi-tenancy** (`tenant_id` column, shared-DB cross-project row partitioning). Tenancy is by-DB-file in this plan; schema tenancy is a new epic if it ever becomes load-bearing.
- **Event-driven daemon implementation.** Rework design note + in-code TODO anchors only. Picking between sqlite `update_hook`, filesystem watcher, unix-domain IPC, or hybrid push-with-fallback-poll is a follow-on epic.
- **Autonomous bug-fix loop or parallel-review consumer packaging.** E17-9 owns those workflows; the hoist ships the skill files through the overlay like any others but does not reopen design.
- **Branch-isolation edit-guard behavior changes.** E17-8 owns that surface; this plan consumes `permitted_main_surfaces` through the overlay but does not modify the guards.
- **Same-project multi-active-task concurrency.** Owned by [E17-11](./E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md) (formerly scoped as E17-7 Slice 2).

## Target Outcome

- A second Daniel-owned project can run:
  ```
  pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0"
  pip install "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.0"
  pip install "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.1.0"
  agentic-bootstrap install --target <project-root>
  ```
  (Each package installs from its own standalone `darce/*` repo — no install URL references `context-alt-text-monorepo`. Skills/hooks/contracts come from the separate `darce/agentic-system` remote cloned into `<project-root>/.agentic/remote/` by the bootstrap CLI — see Slice 0 for the topology decision.) End state: working `.claude/skills/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `docs/agentic/contracts/`, `.claude/commands/` symlinks plus a generated `<project-root>/.agentic-overlay.json` manifest and a per-consumer state dir at `<project-root>/.task-state/handoff.db`.
- `check-skills` and `check-harness-sync` run in the consumer project against the overlay-resolved surface, reporting shared-only, local-only, and overlapping cases correctly.
- A minor-version bump of `agent-handoff-mcp` plus a one-line change in a shared skill propagates to the consumer via `pip install --upgrade ... && agentic-bootstrap update` with zero manual file copying. This is the MVP success signal.
- `handoff.db` is per-consumer under the existing state-dir contract: `AGENT_HANDOFF_STATE_DIR` or `RuntimeConfig.state_dir` selects the state dir; default is `<consumer-root>/.task-state/handoff.db`. `AGENT_HANDOFF_WORKSPACE_ROOT`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, `AGENT_HANDOFF_DASHBOARD_PATH`, and `AGENT_HANDOFF_EXPORTS_DIR` remain the documented output/path overrides.
- `dispatch_lane_work(start_worker=True)`, `manage_worker(action in {"start","start_all"})`, and `manage_orchestrator(operation in {"start","single_cycle"})` raise `DaemonsDisabledError` when `orchestrator.daemons.enabled` is `false` (the default). When `true`, daemon start emits a one-shot `logging.WARNING` citing poll intervals, approximate MCP-query count per cycle, a qualitative token-cost warning, and the design-note path.
- The polling rework note exists at `packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` with four alternatives enumerated (sqlite `update_hook`, filesystem watcher, unix-domain-socket pub-sub, hybrid push-with-fallback-poll), trade-offs, and symbolic poll-site anchors (`orchestrator_loop()` main-loop sleep, `_worker_management_phase()`, `_poll_merge_ready_lanes()`, `_dispatch_phase()`, `_guidance_phase()`, `worker_loop()` sleep sites, `_poll_phase()`, `poll_lane_state()`, `OrchestratorLock`, `WorkerLock`). In-code `TODO(E17-10-REWORK)` comments reference the design note by path.
- One canonical `docs/agentic/consumer-setup.md` exists that a second project can follow without reading this task plan.

## Context Loading

- Source scope: [docs/scopes/hoist-agentic-system-to-remote-scope.md](../../scopes/hoist-agentic-system-to-remote-scope.md)
- E17-6 core (skills anatomy + contracts): [E17-6-phase3-retrofit-task-plan.md](./E17-6-phase3-retrofit-task-plan.md)
- E17-7 handoff evolution (informs DB-path contract + multi-active-task prerequisite): [E17-7-handoff-evolution-and-portable-workflow-task-plan.md](./E17-7-handoff-evolution-and-portable-workflow-task-plan.md)
- E17-8 branch-isolation edit-guard hardening (shares the `permitted_main_surfaces` contract the overlay must preserve): [E17-8-branch-isolation-edit-guard-hardening-task-plan.md](./E17-8-branch-isolation-edit-guard-hardening-task-plan.md)
- E17-9 parallel reviews + auto-fix loop (defines the host-subagent primitive the MVP relies on for parallel implementation): [E17-9-parallel-reviews-and-autonomous-bug-fix-loop-task-plan.md](./E17-9-parallel-reviews-and-autonomous-bug-fix-loop-task-plan.md)
- Portable workflow manifest + generator: `config/agent-workflows/portable_commands.json`, `scripts/generate_agent_workflows.py`
- Harness protocol contract: `docs/agentic/contracts/harness-protocol.yaml`
- Validators: `scripts/check_skills.py`, `scripts/check_harness_sync.py`
- Orchestrator daemon modules: `packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/orchestrator_daemon.py`, `.../worker_daemon.py`
- Handoff package entrypoint: `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py`
- Constitution guards: `docs/agentic/constitution.md` (rg-013 handoff-core purity, rg-014 late-binding imports)

## Proposed Solution

Six slices deliver the MVP. Slice 0 commits to the remote-repo topology and extracts the shared surface into a new private repo — without this the bootstrap CLI has no remote to clone. Slice 1 is foundation (per-consumer DB isolation + package release metadata). Slice 2 adds overlay resolution and validator integration. Slice 3 ships the bootstrap CLI plus the single consumer-setup doc. Slice 4 gates daemons behind opt-in and records the rework note. Slice 5 validates the full update pipeline against a scratch consumer — the MVP success signal.

### Slice 0 — Remote agentic repo extraction + topology commitment

**Goal**: create the canonical remote repository the bootstrap CLI clones, and commit to the umbrella-vs-split topology the MVP will ship. Resolves the PA-01 "remote doesn't exist" gap; without this slice, Slices 3 and 5 have nothing to point at.

**Decision (load-bearing for MVP)**:

- **New private repo `darce/agentic-system`** holds the canonical shared surface: `.claude/skills/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `docs/agentic/contracts/`, `.claude/commands/`, `config/agent-workflows/portable_commands.json`, `scripts/generate_agent_workflows.py`, and the validators (`scripts/check_skills.py`, `scripts/check_harness_sync.py`). The bootstrap CLI clones this repo into `<consumer-root>/.agentic/remote/` and symlinks surfaces out of it.
- **The standalone repo family uses a consistent `mcp-` prefix**, even where the repo ships shared surfaces or a bootstrap CLI rather than an MCP server binary. The intended package family is `darce/mcp-agent-handoff`, `darce/mcp-agent-orchestrator`, `darce/agentic-system`, and `darce/agentic-bootstrap`. E17-10 originally assumed the handoff repo already existed from AHMCP-5, but remote verification on 2026-04-19 showed that assumption was stale. Slice 0 must therefore create or recreate `darce/mcp-agent-handoff` alongside the three newly introduced repos. Consumers still install the bootstrap package as `agentic-bootstrap`; the repo name changes, not the CLI package name.
- **MCP packages and the bootstrap CLI ship from standalone repos**, not from `context-alt-text-monorepo`. Slice 0 must ensure all four standalone repos exist remotely: `darce/mcp-agent-handoff`, `darce/mcp-agent-orchestrator`, `darce/agentic-system`, and `darce/agentic-bootstrap`. The orchestrator repo is extracted from `packages/agent-orchestrator-mcp/`; the bootstrap repo is new and scaffolded for Slice 3 to populate. Consumers install via `pip install "git+ssh://git@github.com/darce/<repo>.git@<tag>"` — no `#subdirectory=` pattern and no install URL references `context-alt-text-monorepo`.
- **Rationale**: the stated MVP goal is external shippability to arbitrary Daniel-owned projects. Hardcoding `context-alt-text-monorepo.git` in every consumer's lockfile leaks the WordPress alt-text product identity into every downstream install, couples MCP server release cadence to this monorepo's release process, and contradicts the already-established standalone pattern used by `darce/mcp-agent-handoff`. The one-time cost of extracting `packages/agent-orchestrator-mcp/` to its own repo and re-pinning its `agent-handoff-mcp` dep at `git+ssh://.../mcp-agent-handoff.git@v0.1.0` is absorbed by Slice 1; the permanent cost of a misleading install URL would be borne by every consumer in perpetuity. Cross-package tests continue to work because the dependency edge between the two MCP packages is already a `git+ssh://` URL, not a path dep.

**Scope**

- Create the remote repo via `gh repo create darce/agentic-system --private --description "Shared agentic system surface (skills, hooks, contracts, commands) for Daniel's projects"`.
- Create or recreate `darce/mcp-agent-handoff` via `gh repo create darce/mcp-agent-handoff --private --description "Portable handoff MCP server for task state, findings, artifacts, and verified test history"` before any Slice 1 release-tagging work that pins orchestrator against the handoff repo.
- Populate it with a **single initial commit** that mirrors the current state of the shared directories above from this monorepo's `main` at the Slice 0 HEAD SHA. Recipe: `rsync --archive --delete <paths> <new-repo-clone>/`, then `cd <new-repo-clone> && git init && git add -A && git commit -m "Initial extraction from context-alt-text-monorepo@<sha>"`. `git subtree split` is explicitly rejected here — it preserves multi-commit history, which conflicts with the single-initial-commit constraint.
- Commit `README.md` naming the repo as an MVP-scope-private internal surface (no LICENSE, no CONTRIBUTING, per the plan-level no-open-sourcing constraint).
- Tag the initial SHA as `v0.1.0` on the new repo — the bootstrap CLI's `--remote-ref` default in Slice 3.
- Create `darce/mcp-agent-orchestrator` via `gh repo create darce/mcp-agent-orchestrator --private --description "agent-orchestrator-mcp MCP server — orchestrates lane workers on top of agent-handoff-mcp"`. Populate it with a single initial commit mirroring the current state of `packages/agent-orchestrator-mcp/` from monorepo `main` at Slice 0 HEAD SHA using the same `rsync --archive` + `git init` + commit recipe as `agentic-system`. Slice 1 updates its `pyproject.toml` to pin the `agent-handoff-mcp` dep at `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0`, adds release metadata, and tags `v0.1.0`.
- Create `darce/agentic-bootstrap` via `gh repo create darce/agentic-bootstrap --private --description "Bootstrap CLI repo for the agentic-bootstrap package; clones darce/agentic-system into consumer repos and manages MCP harness config"`. Seed with a README-only initial commit; Slice 3 implements the CLI package directly in this repo (not under `packages/` in `context-alt-text-monorepo`).
- Verify `gh auth status` on account `darce` carries `repo` + `delete_repo` scopes for all four required repos (`darce/mcp-agent-handoff`, `darce/agentic-system`, `darce/mcp-agent-orchestrator`, `darce/agentic-bootstrap`) before extraction begins.
- In THIS monorepo, document the extraction in `docs/agentic/rules/development-workflow.md § Shared Agentic Surface` with: the remote URL, the sync direction (initially one-way: extract from monorepo → `darce/agentic-system`), and an explicit `TODO(E17-10-POST-MVP-SYNC)` for the reverse sync workflow (how upstream changes made in the remote repo flow back to the monorepo). The reverse sync is out of scope for MVP — Slice 5 validates one-way flow only.
- **Do not delete the extracted directories from this monorepo in Slice 0.** Deletion lands as a post-MVP cleanup (tracked as `TODO(E17-10-POST-MVP-CLEANUP)` in `development-workflow.md`) AFTER Slice 5 proves the consumer workflow end-to-end. This preserves a rollback path if the scratch-consumer validation reveals topology issues.

**Proof**

- `gh repo view darce/mcp-agent-handoff --json url,isPrivate && gh repo view darce/agentic-system --json url,isPrivate && gh repo view darce/mcp-agent-orchestrator --json url,isPrivate && gh repo view darce/agentic-bootstrap --json url,isPrivate && grep -q E17-10-POST-MVP-SYNC docs/agentic/rules/development-workflow.md && grep -q E17-10-POST-MVP-CLEANUP docs/agentic/rules/development-workflow.md` proves the full Slice 0 repo family exists as private remotes and the Shared Agentic Surface anchors are documented in this monorepo.
- `git ls-remote git@github.com:darce/agentic-system.git refs/tags/v0.1.0` shows the tag.
- `git clone git@github.com:darce/agentic-system.git /tmp/agentic-system-smoke && ls /tmp/agentic-system-smoke/.claude/skills/` lists the expected skill directories.
- The MCP-package install URL documented in this plan matches the pattern `git+ssh://git@github.com/darce/<repo>.git@<tag>` in Slice 1's `[tool.hoisted]` table and Slice 3's `consumer-setup.md`, where `<repo>` is exactly `mcp-agent-handoff`, `mcp-agent-orchestrator`, or `agentic-bootstrap`. No install URL anywhere in the plan references `context-alt-text-monorepo`.

### Slice 1 — MCP package release metadata and packaged-runtime path hardening

**Goal**: both MCP packages are releasable from a git tag and their packaged runtime behavior is explicit, portable, and aligned with the existing `.task-state` contract.

**Scope**

- Keep the existing path surface: `RuntimeConfig.for_repo(...)` continues to converge linked worktrees to the primary git worktree and default state to `<consumer-root>/.task-state/handoff.db`; this plan does **not** migrate the state dir to `.agentic/` and does **not** add parallel `AGENT_HANDOFF_DB_PATH` / `AGENT_HANDOFF_OUTPUT_ROOT` env vars.
- **Define `<consumer-root>` as the project's main-worktree root**, not the caller cwd's worktree root. Existing `for_repo` behavior already does this for linked worktrees via the primary git worktree; Slice 1 hardens and documents that contract as the consumer surface.
- **Non-git-repo fail-fast (PA-04)**: if the upward walk from caller cwd reaches the filesystem root without finding a `.git` directory or file AND the caller did not pass explicit `workspace_root` / `state_dir` / path overrides, raise `ConsumerRootResolutionError("agent-handoff-mcp could not resolve <consumer-root> — caller cwd <path> is not inside a git repository. Set AGENT_HANDOFF_WORKSPACE_ROOT and, if needed, AGENT_HANDOFF_STATE_DIR / AGENT_HANDOFF_DASHBOARD_PATH / AGENT_HANDOFF_CURRENT_TASK_PATH explicitly, or call RuntimeConfig.for_workspace(...) for a non-git fixture.")`. No silent cwd-relative fallback for packaged consumer mode.
- **Existing ambiguous-workspace error remains authoritative for the overlapping-active-task case.** `AmbiguousWorkspaceContextError` already exists in `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_write_context.py` and is surfaced on read paths through `shared_primitives.py`. Slice 1 does not replace that behavior; `ConsumerRootResolutionError` is only for the non-git / unresolvable-root branch, while ambiguous candidate sets in a real repo continue to raise `AmbiguousWorkspaceContextError` with structured candidate details.
- Reuse the existing path env vars as the only documented consumer surface: `AGENT_HANDOFF_WORKSPACE_ROOT`, `AGENT_HANDOFF_STATE_DIR`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, `AGENT_HANDOFF_DASHBOARD_PATH`, and `AGENT_HANDOFF_EXPORTS_DIR`. Slice 1 documents and tests their precedence instead of adding new env names.
- Rework `run_doctor()` so pip-installed packages do not assume a monorepo checkout at `Path(__file__).resolve().parents[4]`. The stdio CLI probe must detect packaged installs and either skip the monorepo-only `PYTHONPATH` construction or degrade to a probe that works from site-packages without a sibling `packages/` tree.
- Update both `pyproject.toml` files (in their respective standalone repos after Slice 0) to pin MVP version `0.1.0`.
- **Retarget `agent-orchestrator-mcp`'s `agent-handoff-mcp` dep** inside the new `darce/mcp-agent-orchestrator` repo: change the current `git+ssh://git@github.com/darce/mcp-agent-handoff.git` (unpinned, tracks `main`) to the tagged form `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0`. Verify no path-based dep (`packages/agent-handoff-mcp`, `../agent-handoff-mcp`, or editable `-e` shim) remains in either standalone repo's `pyproject.toml`.
- Add a `[tool.hoisted]` table to each `pyproject.toml` documenting the canonical install URL using the standalone-repo pattern: `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v<tag>` and `git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v<tag>`. Placeholder tag — each repo's own `scripts/release_mcp_package.sh` (added below) injects the real one. Load-bearing: Slice 0 commits to both MCP packages being extracted to standalone repos, so the install URL carries no `context-alt-text-monorepo` reference.
- Create or extend `CHANGELOG.md` in each standalone MCP repo (`darce/mcp-agent-handoff`, `darce/mcp-agent-orchestrator`) with the hoist-MVP entry.
- Add `scripts/release_mcp_package.sh` to each standalone MCP repo that tags a release on THAT repo, updates its `CHANGELOG.md` heading, and prints the `git+ssh://git@github.com/darce/<repo>.git@v<tag>` install URL to paste into a consumer. The script is not hosted in `context-alt-text-monorepo`.

**Proof**

- Unit tests cover the precedence and current defaults for the existing path surface: explicit `state_dir`, env-driven `AGENT_HANDOFF_STATE_DIR`, consumer-root default `<consumer-root>/.task-state/`, linked-worktree convergence, the non-git-repo fail path (`ConsumerRootResolutionError` raised with expected message substrings naming the existing env vars), and the existing ambiguous-candidate path (`AmbiguousWorkspaceContextError` still surfaced with structured candidates).
- Unit tests cover current output-path behavior under the existing config surface: default `DASHBOARD.txt` / `CURRENT_TASK.json` placement at the consumer root, plus explicit `AGENT_HANDOFF_DASHBOARD_PATH`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, and `AGENT_HANDOFF_EXPORTS_DIR` overrides.
- Unit test covers the linked-worktree convergence case: three worktrees of one project all resolve to the same `<main-worktree-root>/.task-state/handoff.db` and the same consumer-root dashboard/current-task outputs unless explicitly overridden.
- A `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0"` against a scratch venv succeeds, and a script imports `agent_handoff_mcp`, calls `configure_runtime(RuntimeConfig(state_dir=Path("/tmp/e17-10-state")))`, writes a decision, asserts the DB was created at `/tmp/e17-10-state/handoff.db`, and confirms `run_doctor()` completes without a monorepo-relative stacktrace when no sibling `packages/` tree exists.
- A `pip install "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.0"` succeeds end-to-end: pip transitively resolves its `agent-handoff-mcp` dep from `darce/mcp-agent-handoff.git@v0.1.0` (the retargeted dep from this slice), no path dep falls back to `packages/`, and `import agent_orchestrator_mcp` succeeds in the scratch venv.
- `git ls-remote git@github.com:darce/mcp-agent-orchestrator.git refs/tags/v0.1.0` shows the tag once Slice 1 tags the extracted standalone repo.
- `pytest packages/agent-handoff-mcp/tests/test_runtime_config.py` green.

### Slice 2 — Overlay resolver and validator integration

**Goal**: `check-skills` and `check-harness-sync` walk the effective overlay and report shared/local/overlapping correctly.

**Scope**

- Add `scripts/overlay_resolver.py` exposing `resolve_surface(kind: Literal["skills","hooks","commands","prompts","contracts"], project_root: Path) -> list[ResolvedPath]` where each `ResolvedPath` carries `source in {"shared","local","overlapping"}`, `effective_path`, and `shared_path`/`local_path` when both exist. The `hooks` surface explicitly covers `.github/hooks/`, `scripts/hooks/`, and the client-side git-hook subtree at `scripts/hooks/git/`.
- Define the `.agentic-overlay.json` manifest schema: records the symlink roots, the remote clone path (`<project-root>/.agentic/remote/`), the current remote SHA, and per-surface overlap stats. The bootstrap CLI writes it; the resolver reads it.
- Extend `scripts/check_skills.py` to resolve via the overlay and validate each resolved skill against the canonical skill anatomy, distinguishing the three cases in the report.
- Extend `scripts/check_harness_sync.py` the same way. YAML-value merge semantics: top-level keys in local `harness-protocol.yaml` replace the corresponding shared keys in full (no deep-merge of list values); a stanza-level replace log line is emitted per overridden key.
- Add `scripts/lint_hoisted_paths.py` plus `make lint-hoisted-paths` to statically scan hoisted surfaces (`.claude/skills/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `.claude/commands/`, `docs/agentic/contracts/`, `config/agent-workflows/`) for monorepo-only path leakage such as `apps/prototype`, `context-alt-text-monorepo`, `/Users/daniel`, `.python-version` probes, and brittle `Path(__file__).resolve().parents[N]` assumptions.
- Unit tests: shared-only skill, local-only skill, overlapping skill (local wins), missing local dir (shared used), broken symlink (raises `BrokenOverlayError` — same named error used by `agentic-bootstrap doctor` / `repair`; error message names `agentic-bootstrap repair` as the recovery path), and the YAML replace-semantics for `harness-protocol.yaml`.

**Proof**

- `make check-skills`, `make check-harness-sync`, and `make lint-hoisted-paths` green for this monorepo (which has no `local/` layer yet — the resolver no-ops).
- New unit tests cover the three-cell matrix {shared-only, local-only, overlapping} for skills AND the YAML replace semantics for contracts.
- `ResolvedPath` return values include the expected `source` tags under each test scenario.
- The static lint fails on any reintroduced monorepo-only path literal in hoisted surfaces before a full consumer smoke run is needed.

### Slice 3 — Bootstrap CLI + consumer-setup doc

**Goal**: one pip console script installs and maintains the symlinked overlay; one canonical doc is all a consumer reads.

**Scope**

- New package `agentic-bootstrap` (developed in `darce/agentic-bootstrap` repo created in Slice 0; pip-installable, zero runtime deps beyond stdlib + `tomllib` (reader) + `tomlkit` (round-trip writer)) exposing:
  - `agentic-bootstrap install --target <path> [--remote-ref <tag>]`: clones (or `git worktree add`s) the remote agentic repo into `<target>/.agentic/remote/`, then symlinks `.claude/skills/`, `.github/hooks/`, `scripts/hooks/`, `.github/prompts/`, `docs/agentic/contracts/`, `.claude/commands/` from the clone into `<target>/`, writes `<target>/.agentic-overlay.json`, and invokes the four config writers below in sequence (three MCP-harness writers plus the git-hooks writer that sets `core.hooksPath`).
  - `agentic-bootstrap update`: runs `git fetch && git checkout <ref>` in the clone, re-validates symlinks (no move if already correct), runs `check-skills` + `check-harness-sync` in dry-run mode against the consumer repo, and updates `.agentic-overlay.json` with the new remote SHA.
  - `agentic-bootstrap status`: reports remote SHA, overlay layer counts, overlay-resolver shared/local/overlapping per surface, daemon-flag state, and current `git config core.hooksPath` status for the consumer repo.
  - `agentic-bootstrap doctor`: runs `status` + pip-package version resolution + `AGENT_HANDOFF_WORKSPACE_ROOT` / `AGENT_HANDOFF_STATE_DIR` discovery + a trial `import agent_handoff_mcp; configure_runtime(...)` call + an overlay integrity check (broken symlinks, missing `.agentic/remote/`, SHA drift between manifest and clone) + a git-hook wiring check that `core.hooksPath` points at the overlaid `scripts/hooks/git`. Fails fast with the same `BrokenOverlayError` that `check-skills` and `check-harness-sync` raise.
  - `agentic-bootstrap repair` (PA-07): detects a missing, corrupt, or SHA-mismatched `<target>/.agentic/remote/` and re-clones + relinks without the user re-running `install` from scratch. Idempotent: if nothing is broken, it exits zero with "overlay healthy." If the clone exists but is at the wrong ref, fast-forwards or checks out the ref from `.agentic-overlay.json`. Does NOT touch `local/` surfaces. It also repairs drifted git-hook wiring by resetting `core.hooksPath` to the overlaid `scripts/hooks/git` when the overlay itself is healthy. **Dirty-clone guard (rg-017)**: before any delete-and-re-clone path, `repair` runs `git -C <target>/.agentic/remote/ status --short --untracked-files=all`. If that returns any output, `repair` aborts non-zero with a message naming the dirty files and the `--force-dirty` opt-in flag; it does not destroy uncommitted work. `--force-dirty` is the documented opt-in for the case where the consumer knows the dirty state is recoverable (or empty).

- **Config writers (PA-02)**: the `install` command runs each writer unconditionally (they no-op if the format does not apply to the detected environment). Each writer is a separate sub-module with its own unit tests, its own merge semantics, and its own idempotency rules. The four writers:

  | Writer              | File                          | Format     | Fields touched                                                                                                                                                                                                                                                                             | Merge rule                                                                                                                                                                                                                             | Re-run semantics                                                                                                   |
  | ------------------- | ----------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
  | `claude_mcp_config` | `<target>/.mcp.json`          | JSON       | `mcpServers.agent-handoff-mcp`, `mcpServers.agent-orchestrator-mcp` (each with `command`, `args`, `env`)                                                                                                                                                                                   | Deep-merge on `mcpServers`: add our two keys, leave all other keys and their nested values untouched. If the two keys already exist, **replace** them (not deep-merge) so stale args/env from a prior install version get overwritten. | Idempotent — running twice produces the same file byte-for-byte.                                                   |
  | `vscode_mcp_config` | `<target>/.vscode/mcp.json`   | JSON       | Same two servers; command stays as the console-script entrypoint (`agent-handoff-mcp`, `agent-orchestrator-mcp`) and env uses `${workspaceFolder}`-style variables for `AGENT_HANDOFF_WORKSPACE_ROOT`.                                                                                     | Same as above. Also create `.vscode/` directory if absent.                                                                                                                                                                             | Idempotent. Existing unrelated VS Code config preserved (this file is MCP-specific; settings.json is not touched). |
  | `codex_mcp_config`  | `<target>/.codex/config.toml` | TOML       | `[mcp_servers.agent-handoff-mcp]` and `[mcp_servers.agent-orchestrator-mcp]` tables with `command`, `args`, `env`. Default command remains the console-script entrypoint resolved on PATH at invocation time; absolute command paths are an explicit opt-in escape hatch, not the default. | Replace the two named tables; leave any other `[mcp_servers.*]` tables alone. Preserve non-`mcp_servers` top-level tables verbatim.                                                                                                    | Idempotent. Requires a TOML writer that preserves comments and key order — use `tomlkit` (round-trip library). `tomli_w` is explicitly rejected because it cannot preserve comments (documented library design limitation).   |
  | `git_hook_config`   | `<target>/.git/config`        | git-config | `core.hooksPath`, set to the overlaid `scripts/hooks/git` subtree so the shipped client-side git hooks (`post-checkout`, `post-merge`, `post-rewrite`, `pre-push`) actually execute in the consumer repo.                                                                                | Replace only `core.hooksPath` via `git -C <target> config core.hooksPath scripts/hooks/git`; preserve all other git config untouched.                                                                                                   | Idempotent. Re-running with the expected value is a no-op; `doctor` and `repair` report or fix drifted values.    |

  Each writer preserves the symbolic launcher approach by default: `command` stays as the console-script entrypoint and env pins `AGENT_HANDOFF_WORKSPACE_ROOT` plus, when the caller explicitly passes `--state-dir`, `AGENT_HANDOFF_STATE_DIR`. Consumers who install into a project-specific venv activate that venv before launching the harness. Absolute command paths are available only as an explicit `agentic-bootstrap install --python <path>` escape hatch for environments that cannot rely on PATH resolution.

- `scripts/mcp/mcp-server.sh` remains monorepo-local and is **not** hoisted or referenced by the bootstrap writers. Consumer harness configs call the installed console scripts directly.

- Write `docs/agentic/consumer-setup.md` covering: prerequisites, `pip install` both MCP packages from their standalone `git+ssh://git@github.com/darce/<repo>.git@<tag>` URLs from Slice 0/1, `pip install agentic-bootstrap`, `agentic-bootstrap install`, the default `<consumer-root>/.task-state/` behavior plus the existing override env vars (`AGENT_HANDOFF_WORKSPACE_ROOT`, `AGENT_HANDOFF_STATE_DIR`, `AGENT_HANDOFF_DASHBOARD_PATH`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, `AGENT_HANDOFF_EXPORTS_DIR`), first `load_session` sanity check, update workflow, daemon opt-in pointer with the token-cost warning, `repair` / `doctor` for overlay corruption recovery, git-hook wiring (`core.hooksPath -> scripts/hooks/git`), a troubleshooting section for both `AmbiguousWorkspaceContextError` and `ConsumerRootResolutionError`, and tenancy expectations (per-DB-file isolation; see `## Tenancy` section).

**Proof**

- Unit tests per writer: `.mcp.json` deep-merge preserves unrelated `mcpServers` entries; `.vscode/mcp.json` creates the directory and writes the expected JSON; `.codex/config.toml` replaces the two named tables without mangling other `[mcp_servers.*]` tables or non-`mcp_servers` tables; `git_hook_config` sets `core.hooksPath` to `scripts/hooks/git` in a temp git repo without mutating unrelated git config. Each writer has an idempotency test asserting byte-for-byte identical output on the second run where the format permits byte-for-byte comparison, and a value-stability assertion for the git-config writer.
- Unit tests for bootstrap CLI core: symlink creation idempotency (re-running `install` does not duplicate), update reconciliation (skips unchanged symlinks), `.agentic-overlay.json` manifest round-trip.
- Unit tests for `agentic-bootstrap repair`: missing `.agentic/remote/` → re-cloned; corrupt clone (detected by `git fsck` or missing `.git/`) → removed and re-cloned; SHA mismatch → `git fetch && git checkout <manifest-sha>`; healthy state → exits zero with "overlay healthy" message; **dirty-clone without `--force-dirty` → aborts non-zero, names the dirty files, names the `--force-dirty` flag, and performs no destructive filesystem operation** (rg-017 regression guard); dirty-clone with `--force-dirty` → proceeds with the delete-and-re-clone path.
- Unit tests for `agentic-bootstrap doctor`: broken symlink in overlay → exits non-zero with `BrokenOverlayError` pointing to the broken path AND naming `agentic-bootstrap repair` as the fix; drifted `core.hooksPath` → exits non-zero with the expected remediation message. Same named error raised from `check-skills` and `check-harness-sync` when they encounter the same broken overlay state.
- Dry-run `install` against a scratch temp directory creates the expected symlinks, a valid `.agentic-overlay.json`, the three MCP-harness-config files (where the format detects as applicable), and the expected `core.hooksPath` wiring in the temp git repo. Slice 5 validates the full live run.
- Writer tests assert the default emitted `command` values are symbolic console scripts, not absolute interpreter paths, and that `scripts/mcp/mcp-server.sh` is never referenced in the generated consumer config.
- `git ls-remote git@github.com:darce/agentic-bootstrap.git refs/tags/v0.1.0` shows the first standalone bootstrap tag pushed from that repo.
- A `pip install "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.1.0"` succeeds in a scratch venv before the consumer walk-through begins.
- `docs/agentic/consumer-setup.md` exists and reviewer confirms it is standalone (no task-plan or epic references required to execute).

### Slice 4 — Daemon opt-in, token-cost warning, and polling-rework note

**Goal**: daemons ship, but a consumer cannot accidentally enable them without an informed signal, and the rework question is captured where a future engineer will find it.

**Scope**

- Add `orchestrator.daemons.enabled: false` to `harness-protocol.yaml` (shared default). The flag name is deliberately plural (`daemons`, not `worker_daemons`) because it governs every daemon-start surface, not just worker-side ones. Consumers opt in by placing a `local/harness-protocol.yaml` with `orchestrator.daemons.enabled: true` — overlay resolver Slice 2 defines the merge semantics that make this work.
- **Enforcement surface (PA-06) — all three entry points must check the flag and raise `DaemonsDisabledError` on `false`**:
  - `dispatch_lane_work(start_worker=True)` (worker-daemon start)
  - `manage_worker(action in {"start","start_all"})` (worker-daemon lifecycle — both the single-lane `start` and the multi-lane `start_all` dispatch paths)
  - `manage_orchestrator(operation in {"start","single_cycle"})` (orchestrator-daemon lifecycle — both the long-running `start` and the one-shot `single_cycle` paths, since `single_cycle` still executes the full per-cycle MCP-query load). Non-start operations (`stop`, `pause`, `resume`, `status`, `event_history`) are NOT gated — they operate on existing processes and are safe to invoke regardless of the flag.
    Message: `"Daemons are opt-in. Enable via \`orchestrator.daemons.enabled: true\` in your \`local/harness-protocol.yaml\`. See \`docs/agentic/consumer-setup.md § Daemons\` for token-cost implications."` Identical message at all three sites so consumers see a single surface.
- Emit a one-shot `logging.WARNING` per process when **any** daemon starts successfully (orchestrator or worker), using the format: `"agent-orchestrator-mcp: <daemon_kind> daemon enabled (poll_interval=<N>s, ~<K> MCP queries/cycle). Worker daemons also spawn lane_prompt.py --check subprocesses per poll. This may consume significant agent tokens over long runs. Rework candidate: see packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md"`. Query-count comes from the plan-stage polling survey (10–15 queries/cycle for orchestrator, ~3–5 for worker before subprocess spawn) and is filled from static config at startup. **No tokens/hour claim in the message (PA-05)**: a tokens/hour number requires either a prerequisite measurement run or runtime payload-size sampling, neither of which this slice ships; pinning an unmeasured number becomes folklore. The qualitative "may consume significant agent tokens over long runs" line carries the warning without inventing a figure. A future measurement-driven slice (out of scope here) can upgrade the message to quantified cost.
- Create `packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` with:
  - Problem statement: per-poll token cost, summary of measurements from the plan-stage survey.
  - Four enumerated alternatives with pros/cons: (a) sqlite `update_hook` in-MCP callbacks, (b) filesystem watcher on `handoff.db`/lane-inbox markers (`watchdog` / `inotify`), (c) unix-domain-socket pub-sub inside the orchestrator lock boundary, (d) hybrid push-with-fallback-poll (push primary signal, poll as watchdog at a much longer interval).
  - Anchors: the main-loop `time.sleep(poll_interval)` and additional backoff sleeps inside `orchestrator_loop()`, `_worker_management_phase()`, `_poll_merge_ready_lanes()`, `_dispatch_phase()`, `_guidance_phase()`, `_poll_phase()`, `poll_lane_state()`, `OrchestratorLock`, `WorkerLock`, and each `time.sleep(cfg.poll_interval)` inside `worker_loop()`.
  - Explicit non-goals: this note does NOT pick a solution. It enumerates. The follow-on epic owns selection.
- Insert `# TODO(E17-10-REWORK): Pull-based poll — see packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` comments at:
  - `orchestrator_daemon.py` immediately above the main-loop `time.sleep(poll_interval)` in `orchestrator_loop()`.
  - `worker_daemon.py` immediately above each `time.sleep(cfg.poll_interval)` inside `worker_loop()`.
- Document the daemon opt-in + token cost in `docs/agentic/consumer-setup.md § Daemons (opt-in)` and cross-link from the `docs/agentic/rules/development-workflow.md` rule that governs worker-daemon usage.
- No new MCP tools. No change to the polling architecture. No change to the default poll interval.

**Proof**

- Unit tests: (a) `DaemonsDisabledError` raised at **all three** enforcement sites (`dispatch_lane_work(start_worker=True)`, `manage_worker(action="start")`, `manage_worker(action="start_all")`, `manage_orchestrator(operation="start")`, `manage_orchestrator(operation="single_cycle")`) when the flag is false; negative-test that non-start operations (`manage_worker(action="status")`, `manage_orchestrator(operation="stop")`) are NOT blocked regardless of flag; (b) WARNING emitted exactly once per process when flag is true — both for worker-daemon start and for orchestrator-daemon start; (c) WARNING message does NOT contain a tokens/hour substring (regex-asserted negative); WARNING message DOES contain the qualitative "may consume significant agent tokens" phrase; (d) `event-driven-daemon-design-note.md` exists at the expected path and is linked from the WARNING message; (e) grep-based lint asserts `TODO(E17-10-REWORK)` is present at the main-loop sleep site in `orchestrator_loop()` and at every `time.sleep(cfg.poll_interval)` site in `worker_loop()` — pattern-based, not line-number-based.
- A fresh `ruff`/`mypy` / `make check-all` run touches none of the unrelated surfaces.

### Slice 5 — Update-pipeline validation against a scratch consumer

**Goal**: prove the MVP success signal against a real second project.

**Scope**

- Stand up a scratch consumer at `~/Development/hoist-mvp-consumer/` (a sibling directory rather than `/tmp` so survival across reboots is not an issue; `git init --initial-branch=main`, commit a stub `README.md`).
- From the scratch consumer, install from the **real standalone SSH remotes** created in Slice 0 (no monorepo-URL fallback):
  - `pip install "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0"`
  - `pip install "git+ssh://git@github.com/darce/mcp-agent-orchestrator.git@v0.1.0"`
  - `pip install "git+ssh://git@github.com/darce/agentic-bootstrap.git@v0.1.0"`
  - Then `agentic-bootstrap install --target .` (the CLI clones `git@github.com/darce/agentic-system.git@v0.1.0` into `.agentic/remote/`).
- Verify: overlay-resolver reports expected surfaces; `check-skills` + `check-harness-sync` + `lint-hoisted-paths` pass; `git -C ~/Development/hoist-mvp-consumer config --get core.hooksPath` returns `scripts/hooks/git`; a synthetic dirty-main push attempt proves the shipped `pre-push` hook fires in the consumer repo; and a `configure_runtime` + `set_handoff_state` + `record_event` cycle writes to `~/Development/hoist-mvp-consumer/.task-state/handoff.db` (assert path via SQL `PRAGMA database_list;` or Python `_get_active_db_path()`) and not the monorepo DB.
- Execute the update-propagation test (all three remotes are real `darce/*` GitHub repos — no local bare-clone fallback):
  - Bump `agent-handoff-mcp` to `0.1.1` via the `release_mcp_package.sh` script that lives in the `darce/mcp-agent-handoff` repo (no-op CHANGELOG line — the point is the tag and version wire-up); push the `v0.1.1` tag to `git@github.com/darce/mcp-agent-handoff.git`.
  - Edit one line in one shared skill (pick a skill whose SKILL.md has a safe place for a clarifying note, e.g. `.claude/skills/scope/SKILL.md`) in the `darce/agentic-system` repo; push to `git@github.com/darce/agentic-system.git` (default branch or the ref `.agentic-overlay.json` pins).
  - From `~/Development/hoist-mvp-consumer/`: `pip install --upgrade "git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.1" && agentic-bootstrap update`.
  - Assert: `pip show agent-handoff-mcp` reports `0.1.1`; `readlink .claude/skills/scope/SKILL.md` resolves to the updated `.agentic/remote/` clone head SHA; `grep` finds the new line in the resolved file; `handoff.db` state unchanged; `docs/agentic/consumer-setup.md § Update Workflow — Verified MVP Example` updated with the exact shell transcript.
- Add a portability-leak proof step: `grep -RE 'apps/prototype|context-alt-text-monorepo|/Users/daniel|packages/agent-(handoff\|orchestrator)-mcp|packages/agentic-bootstrap|\.python-version' ~/Development/hoist-mvp-consumer/.agentic/remote/ ~/Development/hoist-mvp-consumer/.claude/ ~/Development/hoist-mvp-consumer/.github/ ~/Development/hoist-mvp-consumer/scripts/ || true` must produce zero matches outside intentional test fixtures. (Grep explicitly includes `context-alt-text-monorepo` and the three `packages/*` subpaths so any leaked monorepo-URL install pattern is caught.)
- **E17-11 ordering tradeoff** (formerly E17-7 Slice 2): record in the proof doc whether this plan lands before or after [E17-11 multi-active-task-singleton-writes-hotfix](./E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md). If before: the consumer inherits the singleton active-task model, and `switch_task` still overwrites the active row — acceptable for MVP (consumers only have one active task at a time in practice) but flag explicitly. If after: cross-reference the registry docs in `docs/agentic/consumer-setup.md` and note the cross-project isolation is STILL by-DB-file; concurrent task rows only benefit same-project multi-task work.

**Proof**

- `docs/agentic/proofs/e17-10-consumer-update-walkthrough.md` committed containing: `pip show` output pre- and post-upgrade; `readlink` output pre- and post-update; `ls -la` of the symlinked dirs pre- and post-update; `git config --get core.hooksPath` output; synthetic dirty-main push / `pre-push` hook transcript; DB-path assertion transcript; zero-match portability-grep output; `lint-hoisted-paths` output; E17-7 Slice 2 ordering note.
- `agentic-bootstrap doctor` run from the consumer exits zero.
- `handoff_close_check(task_ref="E17-10", enforce=True)` on the feature branch returns green before merge.

## Consolidated Checklist

- [ ] Slice 0: `darce/mcp-agent-handoff` private repo exists remotely again via `gh`; if absent, it is recreated before Slice 1 release tagging and install-path proof.
- [ ] Slice 0: `darce/agentic-system` private repo created via `gh`; initial commit mirrors shared surface from monorepo `main` via the `rsync --archive --delete` + `git init` + commit recipe (no `git subtree split`); `v0.1.0` tag pushed.
- [ ] Slice 0: `darce/mcp-agent-orchestrator` private repo created via `gh`; initial commit mirrors `packages/agent-orchestrator-mcp/` from monorepo `main`; release metadata and `v0.1.0` tag land in Slice 1.
- [ ] Slice 0: `darce/agentic-bootstrap` private repo created via `gh`; README-only initial commit seeds the standalone repo; CLI implementation and first package tag `v0.1.0` land in Slice 3.
- [x] Slice 0: `docs/agentic/rules/development-workflow.md § Shared Agentic Surface` added with all three standalone remote URLs, one-way-sync-direction statement, and `TODO(E17-10-POST-MVP-SYNC)` anchor.
- [x] Slice 0: monorepo in-tree skills/hooks/contracts NOT deleted yet — rollback path preserved until Slice 5 proof.
- [x] Slice 1: existing path surface (`AGENT_HANDOFF_WORKSPACE_ROOT`, `AGENT_HANDOFF_STATE_DIR`, `AGENT_HANDOFF_CURRENT_TASK_PATH`, `AGENT_HANDOFF_DASHBOARD_PATH`, `AGENT_HANDOFF_EXPORTS_DIR`) is documented and tested; default state remains `<main-worktree-root>/.task-state/handoff.db`; linked-worktree convergence, non-git-repo `ConsumerRootResolutionError`, and existing ambiguous-candidate `AmbiguousWorkspaceContextError` paths are covered.
- [x] Slice 1: packaged `run_doctor()` no longer assumes a monorepo checkout at `Path(__file__).resolve().parents[4]`; tests cover site-packages-style execution with no sibling `packages/` tree.
- [ ] Slice 1: `agent-handoff-mcp` and `agent-orchestrator-mcp` version `0.1.0` tagged on their respective **standalone** `darce/mcp-agent-handoff` + `darce/mcp-agent-orchestrator` repos; `CHANGELOG.md` entries written in each repo.
- [ ] Slice 1: orchestrator `pyproject.toml` retargets its `agent-handoff-mcp` dependency from the editable sibling path to `git+ssh://git@github.com/darce/mcp-agent-handoff.git@v0.1.0`; transitive-install smoke test green.
- [ ] Slice 1: each standalone MCP repo hosts its own `scripts/release_mcp_package.sh` that emits `git+ssh://git@github.com/darce/<repo>.git@v<tag>` URLs (no `#subdirectory=` fragment, no `context-alt-text-monorepo` URL); `[tool.hoisted]` table in each `pyproject.toml` documents the standalone install URL.
- [ ] Slice 2: `scripts/overlay_resolver.py` returns tagged `ResolvedPath` entries across skills/hooks/commands/prompts/contracts, with the hook surface covering `.github/hooks/`, `scripts/hooks/`, and `scripts/hooks/git/`.
- [ ] Slice 2: `check-skills` and `check-harness-sync` consume the overlay; unit tests cover shared-only, local-only, overlapping, `BrokenOverlayError` on broken symlink, and YAML replace-semantics.
- [ ] Slice 2: `.agentic-overlay.json` schema documented in `docs/agentic/contracts/overlay-manifest.yaml` (or equivalent); round-trip test green.
- [ ] Slice 2: `scripts/lint_hoisted_paths.py` + `make lint-hoisted-paths` added to statically catch monorepo-only path leakage in hoisted surfaces.
- [ ] Slice 3: `agentic-bootstrap` (developed in the standalone `darce/agentic-bootstrap` repo created in Slice 0) with `install`, `update`, `status`, `doctor`, `repair` commands and the first standalone `v0.1.0` package tag pushed from that repo; zero runtime deps beyond stdlib + `tomllib` (reader) + `tomlkit` (round-trip writer). `tomli_w` is explicitly rejected because it cannot preserve comments.
- [ ] Slice 3: four config writers implemented (`claude_mcp_config`, `vscode_mcp_config`, `codex_mcp_config`, `git_hook_config`) with per-writer unit tests for merge semantics, idempotency/value stability, and default symbolic console-script commands. The `codex_mcp_config` writer uses `tomlkit` so comments and key order in existing `.codex/config.toml` files are preserved across re-runs.
- [ ] Slice 3: `agentic-bootstrap repair` unit tests cover missing-remote, corrupt-clone, SHA-mismatch, healthy-noop, **and dirty-clone guard (rg-017): abort-without-`--force-dirty`** (no destructive filesystem op; error names the dirty files and the `--force-dirty` flag) and **proceed-with-`--force-dirty`**.
- [ ] Slice 3: `BrokenOverlayError` raised consistently by `doctor`, `repair`, `check-skills`, and `check-harness-sync` when overlay is broken; error message names `agentic-bootstrap repair` as the fix.
- [ ] Slice 3: `docs/agentic/consumer-setup.md` written and self-contained.
- [ ] Slice 3: consumer overlay includes `.github/hooks/`, `scripts/hooks/`, and `scripts/hooks/git/`; generated config never references monorepo-local `scripts/mcp/mcp-server.sh`, and bootstrap wiring sets `core.hooksPath` to the overlaid git-hook subtree.
- [ ] Slice 4: `orchestrator.daemons.enabled` in `harness-protocol.yaml` defaults `false`; `DaemonsDisabledError` raised at **all three** entry points (`dispatch_lane_work(start_worker=True)`, `manage_worker(action in {start, start_all})`, `manage_orchestrator(operation in {start, single_cycle})`) on `false`; non-start operations remain unblocked.
- [ ] Slice 4: one-shot WARNING emitted per process when any daemon starts; cites poll interval, MCP-queries/cycle, qualitative token-cost note, and design-note path. WARNING does NOT contain a tokens/hour figure (regex-asserted).
- [ ] Slice 4: `packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` exists with four alternatives and all cited anchors.
- [ ] Slice 4: `TODO(E17-10-REWORK)` comment inserted immediately above the main-loop sleep in `orchestrator_loop()` and above each `time.sleep(cfg.poll_interval)` in `worker_loop()`; grep-based lint test green.
- [ ] Slice 5: scratch consumer at `~/Development/hoist-mvp-consumer/` installs MCP packages + `agentic-bootstrap`, runs overlay validators plus `lint-hoisted-paths`, writes to its own `.task-state/handoff.db`, and emits `DASHBOARD.txt` under the consumer root (not the monorepo root).
- [ ] Slice 5: minor-version + shared-skill update propagates via `pip install --upgrade` + `agentic-bootstrap update`; `docs/agentic/proofs/e17-10-consumer-update-walkthrough.md` committed.
- [ ] Slice 5: E17-11 (formerly E17-7 Slice 2) ordering tradeoff recorded in the proof doc.
- [ ] Slice 5: portability-leak grep over the consumer tree returns zero matches outside intentional fixtures.
- [ ] Pre-merge gate: `handoff_close_check(task_ref="E17-10", enforce=True)` passes with zero open findings.

## Tenancy (explicit note)

The MVP's tenancy model is **siloed by-DB-file per project** (user-confirmed 2026-04-17):

- Each consumer project has exactly one `handoff.db` at `<main-worktree-root>/.task-state/handoff.db` (or the existing explicit state-dir/current-task/dashboard overrides).
- **All linked worktrees under a project share that one DB.** A project with three active feature worktrees has three shells writing to one `handoff.db` — this is required for cross-worktree handoff visibility and is enforced by the Slice 1 `<consumer-root>` resolver that converges linked worktrees to the main worktree's root.
- No `tenant_id` column is added. No schema-level multi-tenancy.
- **Future**: a master aggregator `handoff.db` that merges per-project state across all of Daniel's projects is a **possible future follow-on** if cross-project visibility ever proves valuable. It is explicitly out of scope for this plan. The per-DB-file design is compatible with a future aggregator (the aggregator would read per-project DBs and render a union view) — no architectural retrofit required.
- Cross-project dashboards, centralized oncall visibility, and multi-tenant row-level filtering remain out of scope for this plan and would belong to that later aggregator epic.

Same-project active-task collisions (the singleton-keyed `handoff_state WHERE id = 1` that overwrites when `switch_task` runs) are a **separate problem** owned by [E17-11 multi-active-task-singleton-writes-hotfix](./E17-11-multi-active-task-singleton-writes-hotfix-task-plan.md) (formerly scoped as E17-7 Slice 2). If E17-11 lands before this plan, consumers benefit from concurrent task rows per-project for free; if not, the consumer experience inherits the current singleton behavior — noted but acceptable for MVP.

## Risk Register

- **Risk**: a consumer runs `pip install -e` instead of tag-install, inherits the monorepo testing-python rule failure mode (env-wide source-path pinning). **Mitigation**: `consumer-setup.md` explicitly tells consumers to use `git+ssh://...@v<tag>`, not editable installs. `doctor` command warns on detected editable installs.
- **Risk**: symlink-based overlay breaks on Windows. **Mitigation**: MVP scope is Unix/macOS only (Daniel-owned private projects). Document the limit in `consumer-setup.md § Platform Support`.
- **Risk**: a consumer enables daemons, misses the WARNING, and burns a token budget. **Mitigation**: one-shot WARNING is loud; `consumer-setup.md` frames daemons as "off by default, informed opt-in." Post-MVP: add a `doctor` check that reports "daemons enabled — token cost: ~X/hour."
- **Risk**: Slice 0 remote-repo extraction introduces divergence between `darce/agentic-system` and this monorepo's in-tree copies (skills/hooks/contracts are not deleted from the monorepo until a later Slice 7 cleanup). **Mitigation**: during MVP, the monorepo is the source of truth; Slice 0 pushes one-way to the remote. A `TODO(E17-10-POST-MVP-SYNC)` is committed in `development-workflow.md` so the reverse-sync workflow is visible. Slice 5 validates that one-way flow produces a working consumer; post-MVP work either deletes the monorepo copies (monorepo becomes consumer) or implements bidirectional sync.
- **Risk**: polling rework design note becomes a dead document if no one picks it up. **Mitigation**: in-code TODOs + the one-shot WARNING message both name the path; a future engineer touching the daemon will see both signals.
- **Risk**: per-format MCP-harness-config writers (Slice 3) could silently corrupt a consumer's existing `.mcp.json` or `.codex/config.toml` if merge semantics are wrong. **Mitigation**: each writer has dedicated unit tests asserting unrelated entries are preserved byte-for-byte; `agentic-bootstrap install` refuses to overwrite a config file when a non-writer-owned top-level section has been modified from its expected shape unless `--force` is passed. `doctor` diff-reports any drift.
