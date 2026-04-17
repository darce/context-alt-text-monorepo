# E17-10. Hoist Agentic System MVP — Distribution, Overlay, and Daemon Opt-In

- **Date**: 2026-04-17
- **Author**: Claude Opus 4.7
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-10`
- **Review Coverage Target**: 2
- **Source Scope**: [docs/scopes/hoist-agentic-system-to-remote-scope.md](../../scopes/hoist-agentic-system-to-remote-scope.md)
- **Hard Prerequisites**: E17-6 merged (skills anatomy, `harness-protocol.yaml`, `check-skills`, `check-harness-sync`). `gh` CLI authenticated as account `darce` with `repo` + `delete_repo` scopes (verified 2026-04-17 via `gh auth status`); SSH key configured for `git@github.com:darce/*`; target repo name `darce/agentic-system` verified available. E17-7 Slice 2 (multi-active-task registry) is a **soft** prerequisite — see Slice 5 for the ordering tradeoff.

---

## Objective

Deliver an MVP that lets another local Daniel-owned project adopt the same handoff.db state, review findings, failed-test revisions, and parallel-agent implementation discipline without copying source trees. Scope:

1. **Distribute MCP servers** as pip packages (`git+ssh://...` URLs in the MVP) — `agent-handoff-mcp` and `agent-orchestrator-mcp` — with per-consumer `handoff.db` isolation.
2. **Symlink skills, hooks, contracts, and generated workflow adapters** into consumer repos via a new `agentic-bootstrap` CLI.
3. **Resolve an overlay** where project-local `local/` surfaces take precedence over the symlinked shared surface; `check-skills` and `check-harness-sync` validate the effective overlay.
4. **Keep worker daemons shippable but opt-in**, with a deterministic token-consumption warning at daemon start and in `docs/agentic/consumer-setup.md`. Host-subagent primitives (Claude Agent tool, `codex exec`, `run_structured_turn`) remain the default parallel-implementation mechanism — consistent with [E17-9 Constraint 1](./E17-9-parallel-reviews-and-autonomous-bug-fix-loop-task-plan.md).
5. **Record an event-driven-daemon rework note** so the pull-vs-push architecture question is captured in a logical place for a follow-on epic, without implementing it here.

## Why This Is Separate

Neither E17-6, E17-7, E17-8, nor E17-9 owns cross-project distribution. Folding it into any of them would either delay their merge or scope-creep them into packaging and versioning concerns with zero overlap with their charters. This plan is the first surface that treats `harness-protocol.yaml` and generated command adapters as *external* consumer-facing artifacts rather than internal repo plumbing — that reframing deserves its own plan. Tenancy and overlay are both load-bearing enough that they need explicit design here rather than a bolt-on to another in-flight epic.

## Problem Statement

The agentic system works inside this monorepo only. Five gaps block multi-project adoption:

1. **MCP servers are editable installs against local source trees.** `agent-handoff-mcp` and `agent-orchestrator-mcp` are consumed via `pip install -e packages/...` from this checkout. There is no versioned artifact a second project can pin, no documented MVP install URL, and no `CHANGELOG`-bump discipline tied to tagged releases.
2. **`handoff.db` has no documented per-consumer path contract.** `RuntimeConfig.for_repo(Path("."))` resolves the DB relative to the caller cwd with no env-driven override documented as the consumer surface. Two projects on the same machine would collide on a single DB file unless the consumer knows to pass `RuntimeConfig(db_path=...)` — which is not covered in any consumer-facing doc because no such doc exists.
3. **Skills, hooks, contracts, and generated adapters live under this repo's paths.** A consumer project has no supported path to import them that preserves live editability or diff visibility when this repo ships updates. Copy-paste drifts silently; upstream changes never flow through.
4. **Validators assume one flat surface.** `scripts/check_skills.py` and `scripts/check_harness_sync.py` walk a single tree each. Overlay resolution (shared + local, with local precedence) does not exist, so a consumer cannot add a project-specific skill variant without forking upstream.
5. **Daemon token cost is invisible and polling is architecturally load-bearing, with no rework note in the repo.** `orchestrator_daemon.py` polls every 60s ([packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/orchestrator_daemon.py:1203](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/orchestrator_daemon.py)) and `worker_daemon.py` polls every 30s ([packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon.py:1786](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon.py)). Each orchestrator cycle runs ≈10–15 MCP queries across `_worker_management_phase()` (line 965), `_poll_merge_ready_lanes()` (line 991), lane-inbox reads, plan-dispatch phase (line 953), and guidance phase (line 908). Worker daemons spawn `lane_prompt.py --check` subprocesses per poll ([worker_daemon.py:143](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon.py)). A consumer enabling daemons inherits that cost with no in-product warning. No `TODO`/`FIXME` in the daemon modules flags the pull-vs-push architecture question — the rework signal is load-bearing missing.

## Constraints

- **Install model is fixed (per scope decision).** MCP servers install as pip packages from `git+ssh://...` URLs in the MVP. Private PyPI or wheel mirrors are deferred to a later epic. Skills, hooks, contracts, and generated adapters install via the bootstrap CLI, which **symlinks** (not copies) from a consumer-local clone of the remote agentic repo.
- **Overlay model is fixed (per scope decision).** Shared symlinks + project-local `local/` counterparts with local precedence. Validators resolve the effective overlay, not the raw shared tree. YAML-valued surfaces (`harness-protocol.yaml`) merge with per-top-level-key local-override semantics; list values replace rather than concatenate. Slice 2 documents this contract.
- **MVP success signal is fixed (per scope decision).** One MCP minor-version bump **plus** one shared-skill change propagates end-to-end via the documented update workflow with zero manual copying. Slice 5 validates this.
- **No open-sourcing in MVP.** No LICENSE, no CONTRIBUTING, no badges, no public-PyPI upload, no social surfaces. Scope is private Daniel-owned repos only.
- **No substantive skill rewrites during the hoist.** Adapt skill path layouts to be overlay-aware if required; do not rewrite skill bodies.
- **Tenancy is by-DB-file, not by-schema.** Each consumer writes to its own `handoff.db` file, resolved via `AGENT_HANDOFF_DB_PATH` → `RuntimeConfig.db_path` → `<consumer-root>/.agentic/handoff.db`. No `tenant_id` column is added to any `handoff.db` table in this plan. Schema-level tenancy is explicitly out of scope and, if ever needed, would be a new epic. Same-project active-task collisions are a separate concern owned by **E17-7 Slice 2** (multi-active-task registry) and are a soft prerequisite to this plan.
- **Worker daemons ship, but are opt-in and noisy.** A `harness-protocol.yaml` flag `orchestrator.daemons.enabled` defaults `false`. `dispatch_lane_work(start_worker=True)`, `manage_worker(action in {"start","restart"})`, and `manage_orchestrator(action in {"start","restart"})` all raise `DaemonsDisabledError` on `false` with an actionable message. When `true`, daemon start emits a one-shot `logging.WARNING` naming poll intervals, approximate MCP-queries per cycle, a qualitative token-cost note (no invented tokens/hour figure), and the path to the event-driven design note. The MCP tool count does not change.
- **Host-subagent primitives remain the default parallel-implementation mechanism.** The MVP's parallel-review and auto-fix-loop user story flows through E17-9's `SubagentAdapter` protocol, not through daemons. Daemons are the long-running-operator-pipeline escape hatch.
- **Polling rework is noted, not implemented.** A design-note doc at `packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` + `TODO(E17-10-REWORK)` comments at every `time.sleep(poll_interval)` call site are the only deliverables for the event-driven question in this plan.
- **No new MCP tool names.** The bootstrap CLI is a separate pip console script. Configuration knobs land on existing `RuntimeConfig` and `harness-protocol.yaml` surfaces.
- **Branch-isolation and main-change guards must continue to function in a consumer repo.** `harness-protocol.yaml` must be resolvable through the overlay; `guard-main-branch.{py,sh}` must read through the overlay-resolved contract. E17-8 owns the guard code; this plan only adjusts the resolution path.
- **Constitution alignment preserved.** `rg-013` (handoff core stays pure CRUD) and `rg-014` (orchestrator uses late-binding imports for handoff symbols) continue to hold across package-boundary changes. Any slice that would violate them must stop and escalate.

## Current State Analysis

**Packaging and distribution**

- `packages/agent-handoff-mcp/pyproject.toml` and `packages/agent-orchestrator-mcp/pyproject.toml` declare versioned projects but are consumed via editable installs only.
- Neither package has a tag-based release script, a `CHANGELOG.md` update discipline tied to version bumps, nor a documented install URL for external consumers.
- `agent-orchestrator-mcp` depends on `agent-handoff-mcp` as a sibling editable install; the dependency edge is implicit in this monorepo.
- Per the [In-Monorepo Package Test Invocation Rule](../../agentic/rules/testing-python.md#in-monorepo-package-test-invocation-mandatory), an editable install pins all Python interpreters in the venv to one source path regardless of worktree — a consumer that also installs from source in an editable mode would inherit the same trap. The hoist must favor non-editable (`pip install git+ssh://...@tag`) resolution.

**Handoff DB path contract**

- `RuntimeConfig.for_repo(Path("."))` resolves `handoff.db` relative to caller cwd; there is no environment-driven override documented as a consumer contract.
- The monorepo's dev ergonomics rely on the implicit `<repo>/handoff.db` path — the hoist must preserve that behavior for this repo while adding a supported per-consumer path surface for others.

**Skills, hooks, contracts, adapters**

- `.claude/skills/` holds the Claude surface; `.github/hooks/` holds the VS Code/Copilot hook surface; `docs/agentic/contracts/` holds the harness/protocol contracts; `.claude/commands/` and `.github/prompts/` hold generated adapters driven by `config/agent-workflows/portable_commands.json`.
- `scripts/check_skills.py` and `scripts/check_harness_sync.py` walk one flat tree each; overlay resolution does not exist.
- No bootstrap or install CLI exists.

**Daemons and polling** (sourced from the plan-stage survey)

- `orchestrator_daemon.py:1208` opens `orchestrator_loop()` with an infinite `while True` at line 1234; default poll interval 60s; sleep at [orchestrator_daemon.py:1203](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/orchestrator_daemon.py).
- Per-cycle reads dominate token cost: `_worker_management_phase()` (line 965) invokes `manage_worker(action="status")` per lane, then `_poll_merge_ready_lanes()` (line 991) iterates all lanes calling `worker_reports(operation="list", fields="merge_ready")`. Dispatch phase (line 887) reads lane inbox + decisions per cycle. Total ≈10–15 MCP queries per 60s.
- `worker_daemon.py:1762` runs `worker_loop()` at 30s per cycle; sleep call sites at lines 1783, 1790, 1796, 1806. `_poll_phase()` (line 1786) spawns `lane_prompt.py --check` subprocesses per poll via `poll_lane_state()` ([worker_daemon.py:143](../../../packages/agent-orchestrator-mcp/src/agent_orchestrator_mcp/orchestration/worker_daemon.py)).
- No sqlite `update_hook`, filesystem watcher, or pub/sub mechanism exists as an alternative signal. Lock architecture is `OrchestratorLock` (orchestrator_daemon.py:530) and `WorkerLock` (worker_daemon.py:98) — per-process flock with SIGTERM graceful shutdown, compatible with a future push-based refactor.
- No `TODO`/`FIXME` comments in either daemon module flag polling cost.

## Out of Scope

- **Public open-source distribution** (per scope decision): no PyPI, no LICENSE, no CONTRIBUTING, no badges.
- **Private PyPI or wheel mirror**: MVP install path is `pip install git+ssh://...`. Later epic decides PyPI topology.
- **Further repo topology changes** beyond Slice 0's extraction of `darce/agentic-system` and the decision to keep MCP packages in this monorepo. A future aggregator repo, a PyPI mirror, or a further split of `agent-orchestrator-mcp` from `agent-handoff-mcp` are all out of scope — revisit post-MVP if concrete need emerges.
- **MCP server schema or behavior changes beyond configuration.** The only behavior additions in this plan are (a) the `handoff.db` path override contract, (b) the daemon opt-in flag, (c) the first-use WARNING log. No new tools, no new endpoints, no schema migrations.
- **Schema-level multi-tenancy** (`tenant_id` column, shared-DB cross-project row partitioning). Tenancy is by-DB-file in this plan; schema tenancy is a new epic if it ever becomes load-bearing.
- **Event-driven daemon implementation.** Rework design note + in-code TODO anchors only. Picking between sqlite `update_hook`, filesystem watcher, unix-domain IPC, or hybrid push-with-fallback-poll is a follow-on epic.
- **Autonomous bug-fix loop or parallel-review consumer packaging.** E17-9 owns those workflows; the hoist ships the skill files through the overlay like any others but does not reopen design.
- **Branch-isolation edit-guard behavior changes.** E17-8 owns that surface; this plan consumes `permitted_main_surfaces` through the overlay but does not modify the guards.
- **Same-project multi-active-task concurrency.** Owned by E17-7 Slice 2.

## Target Outcome

- A second Daniel-owned project can run:
  ```
  pip install "git+ssh://git@github.com/darce/context-alt-text-monorepo.git@v0.1.0#subdirectory=packages/agent-handoff-mcp"
  pip install "git+ssh://git@github.com/darce/context-alt-text-monorepo.git@v0.1.0#subdirectory=packages/agent-orchestrator-mcp"
  pip install "git+ssh://git@github.com/darce/context-alt-text-monorepo.git@v0.1.0#subdirectory=packages/agentic-bootstrap"
  agentic-bootstrap install --target <project-root>
  ```
  (MCP packages install from this monorepo via `#subdirectory=`; skills/hooks/contracts come from the separate `darce/agentic-system` remote cloned into `<project-root>/.agentic/remote/` by the bootstrap CLI — see Slice 0 for the topology decision.) End state: working `.claude/skills/`, `.github/hooks/`, `.github/prompts/`, `docs/agentic/contracts/`, `.claude/commands/` symlinks plus a generated `<project-root>/.agentic-overlay.json` manifest and a `<project-root>/.agentic/handoff.db` per-consumer DB.
- `check-skills` and `check-harness-sync` run in the consumer project against the overlay-resolved surface, reporting shared-only, local-only, and overlapping cases correctly.
- A minor-version bump of `agent-handoff-mcp` plus a one-line change in a shared skill propagates to the consumer via `pip install --upgrade ... && agentic-bootstrap update` with zero manual file copying. This is the MVP success signal.
- `handoff.db` is per-consumer: `AGENT_HANDOFF_DB_PATH` env var or `RuntimeConfig.db_path` selects the path. Default is `<consumer-root>/.agentic/handoff.db`. Dev-monorepo fallback preserved for this repo.
- `dispatch_lane_work(start_worker=True)` and `manage_worker(action in {"start","restart"})` raise `DaemonsDisabledError` when `orchestrator.daemons.enabled` is `false` (the default). When `true`, daemon start emits a one-shot `logging.WARNING` citing poll intervals, approximate MCP-query count per hour, and the design-note path.
- The polling rework note exists at `packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` with four alternatives enumerated (sqlite `update_hook`, filesystem watcher, unix-domain-socket pub-sub, hybrid push-with-fallback-poll), trade-offs, and exact poll-site anchors (`orchestrator_daemon.py:1203`, `orchestrator_daemon.py:965`, `orchestrator_daemon.py:991`, `worker_daemon.py:1786`). In-code `TODO(E17-10-REWORK)` comments reference the design note by path.
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

- **New private repo `darce/agentic-system`** holds the canonical shared surface: `.claude/skills/`, `.github/hooks/`, `.github/prompts/`, `docs/agentic/contracts/`, `.claude/commands/`, `config/agent-workflows/portable_commands.json`, `scripts/generate_agent_workflows.py`, and the validators (`scripts/check_skills.py`, `scripts/check_harness_sync.py`). The bootstrap CLI clones this repo into `<consumer-root>/.agentic/remote/` and symlinks surfaces out of it.
- **MCP packages stay in this monorepo**, installed via `pip install "git+ssh://git@github.com/darce/context-alt-text-monorepo.git@<tag>#subdirectory=packages/<pkg>"`. This preserves the existing release workflow and avoids a two-repo split for state-carrying code. The install URL in `[tool.hoisted]` (Slice 1) and `consumer-setup.md` (Slice 3) uses this `#subdirectory=` pattern, not a standalone `darce/agent-handoff-mcp` repo.
- **Rationale**: extracting skills/hooks/contracts is a straight file move — no tests, no callers, no state. Extracting MCP servers would require splitting `packages/` into two repos, reconciling the monorepo-internal cross-package tests (e.g., `agent-orchestrator-mcp` depends on `agent-handoff-mcp`), and maintaining two release pipelines. Not worth the MVP bandwidth.

**Scope**

- Create the remote repo via `gh repo create darce/agentic-system --private --description "Shared agentic system surface (skills, hooks, contracts, commands) for Daniel's projects"`.
- Populate it with a **single initial commit** that mirrors the current state of the five directories above from this monorepo's `main` at the Slice 0 HEAD SHA. Use `git subtree split` or a manual `rsync --archive` + `git init` + commit (the choice is a runbook detail, not a plan-level concern).
- Commit `README.md` naming the repo as an MVP-scope-private internal surface (no LICENSE, no CONTRIBUTING, per the plan-level no-open-sourcing constraint).
- Tag the initial SHA as `v0.1.0` on the new repo — the bootstrap CLI's `--remote-ref` default in Slice 3.
- In THIS monorepo, document the extraction in `docs/agentic/rules/development-workflow.md § Shared Agentic Surface` with: the remote URL, the sync direction (initially one-way: extract from monorepo → `darce/agentic-system`), and an explicit `TODO(E17-10-POST-MVP-SYNC)` for the reverse sync workflow (how upstream changes made in the remote repo flow back to the monorepo). The reverse sync is out of scope for MVP — Slice 5 validates one-way flow only.
- **Do not delete the extracted directories from this monorepo in Slice 0.** Deletion lands as a post-MVP cleanup (tracked as `TODO(E17-10-POST-MVP-CLEANUP)` in `development-workflow.md`) AFTER Slice 5 proves the consumer workflow end-to-end. This preserves a rollback path if the scratch-consumer validation reveals topology issues.

**Proof**

- `gh repo view darce/agentic-system --json url,isPrivate` returns the created repo with `isPrivate: true`.
- `git ls-remote git@github.com:darce/agentic-system.git refs/tags/v0.1.0` shows the tag.
- `git clone git@github.com:darce/agentic-system.git /tmp/agentic-system-smoke && ls /tmp/agentic-system-smoke/.claude/skills/` lists the expected skill directories.
- `docs/agentic/rules/development-workflow.md` has the new § Shared Agentic Surface section with the TODO anchor.
- The MCP-package install URL documented in this plan matches the pattern `git+ssh://git@github.com/darce/context-alt-text-monorepo.git@<tag>#subdirectory=packages/<pkg>` in Slice 1's `[tool.hoisted]` table and Slice 3's `consumer-setup.md`.

### Slice 1 — MCP package release metadata and DB-path isolation

**Goal**: both MCP packages are releasable from a git tag and configurable per consumer.

**Scope**

- Add the DB-path resolution order to `agent_handoff_mcp.RuntimeConfig`: `AGENT_HANDOFF_DB_PATH` env > `RuntimeConfig.db_path` arg > `<consumer-root>/.agentic/handoff.db`.
- **Define `<consumer-root>` as the project's main-worktree root**, not the caller cwd's worktree root. Resolve it by walking upward from caller cwd until a `.git` directory **or** `.git` file (linked-worktree pointer) is found, then: if `.git` is a directory → that is the main worktree; if `.git` is a file → parse `gitdir:` pointer, walk back to `commondir`, and use `commondir`'s parent as the main worktree. All linked worktrees under the same project MUST resolve to the same `<consumer-root>` so they share one `handoff.db`. This is mandatory — splitting the DB per-worktree would break cross-worktree handoff visibility, which is the entire point of the system.
- **Non-git-repo fail-fast (PA-04)**: if the upward walk from caller cwd reaches the filesystem root without finding a `.git` directory or file AND no `AGENT_HANDOFF_DB_PATH` env var is set AND no `RuntimeConfig.db_path` was passed explicitly, raise `ConsumerRootResolutionError("agent-handoff-mcp could not resolve <consumer-root> — caller cwd <path> is not inside a git repository. Set AGENT_HANDOFF_DB_PATH to an explicit DB path or pass RuntimeConfig(db_path=...).")`. The error names the env var so the fix is mechanical. No silent cwd-relative fallback.
- **Parallel output-path contract (PA-03)**: add `AGENT_HANDOFF_OUTPUT_ROOT` env > `RuntimeConfig.output_root` arg > derived from resolved DB path's parent. `generate_dashboard_md()` and `generate_current_task_md()` write under `<output_root>/DASHBOARD.txt` and `<output_root>/CURRENT_TASK.md` respectively. Default derivation: if the resolved DB path is `<consumer-root>/.agentic/handoff.db`, `output_root` defaults to `<consumer-root>/` (so DASHBOARD.txt and CURRENT_TASK.md land at the repo root alongside the hidden `.agentic/` directory); if an explicit `AGENT_HANDOFF_DB_PATH` places the DB outside `<consumer-root>/.agentic/`, `output_root` defaults to the DB's parent directory. Dev-monorepo fallback preserves the existing `<repo>/` placement because the resolved DB is `<repo>/handoff.db` and the parent is `<repo>/`. Tenancy of outputs follows tenancy of inputs.
- Preserve the dev-monorepo fallback: if no env var is set AND the resolved main-worktree root contains `packages/agent-handoff-mcp/src/agent_handoff_mcp/`, use `<main-worktree-root>/handoff.db` (the monorepo's existing location) instead of `<main-worktree-root>/.agentic/handoff.db`. Document as dev ergonomics, not a consumer contract.
- Drop the silent cwd-relative fallback for non-monorepo callers — either the env or the consumer-root default applies.
- Update both `pyproject.toml` files to pin MVP version `0.1.0`.
- Add a `[tool.hoisted]` table to each `pyproject.toml` documenting the canonical install URL using the monorepo-subdirectory pattern: `git+ssh://git@github.com/darce/context-alt-text-monorepo.git@v<tag>#subdirectory=packages/agent-handoff-mcp` (and the equivalent for `agent-orchestrator-mcp`). Placeholder tag — `scripts/release_mcp_package.sh` injects the real one. This pattern is load-bearing because Slice 0 commits to MCP packages staying in this monorepo rather than being extracted to standalone repos.
- Create or extend `packages/agent-handoff-mcp/CHANGELOG.md` and add `packages/agent-orchestrator-mcp/CHANGELOG.md` with the hoist-MVP entry.
- Add `scripts/release_mcp_package.sh` that tags a release on the monorepo, updates the CHANGELOG heading, and prints the `git+ssh://...#subdirectory=packages/<pkg>` install URL to paste into a consumer.

**Proof**

- Unit tests cover the five-way DB-path resolution order: env, arg, consumer-root default, dev-monorepo fallback, AND the non-git-repo fail path (`ConsumerRootResolutionError` raised with expected message substrings naming the env var).
- Unit tests cover the four-way output-root resolution: env, arg, derived-from-consumer-root, derived-from-explicit-DB-parent. A matrix test asserts that for every DB-path arm, `generate_dashboard_md()` writes to the expected output directory.
- Unit test covers the linked-worktree convergence case: three worktrees of one project all resolve to the same `<main-worktree-root>/.agentic/handoff.db` and the same `<main-worktree-root>/` output root.
- A `pip install "git+ssh://git@github.com/darce/context-alt-text-monorepo.git@v0.1.0#subdirectory=packages/agent-handoff-mcp"` against a scratch venv succeeds, and a script imports `agent_handoff_mcp`, calls `configure_runtime(RuntimeConfig(db_path=Path("/tmp/e17-10-test.db")))`, writes a decision, asserts the DB was created at the supplied path, AND asserts `generate_dashboard_md()` wrote `DASHBOARD.txt` to `/tmp/` (the DB's parent).
- `pytest packages/agent-handoff-mcp/tests/test_runtime_config.py` green.

### Slice 2 — Overlay resolver and validator integration

**Goal**: `check-skills` and `check-harness-sync` walk the effective overlay and report shared/local/overlapping correctly.

**Scope**

- Add `scripts/overlay_resolver.py` exposing `resolve_surface(kind: Literal["skills","hooks","commands","prompts","contracts"], project_root: Path) -> list[ResolvedPath]` where each `ResolvedPath` carries `source in {"shared","local","overlapping"}`, `effective_path`, and `shared_path`/`local_path` when both exist.
- Define the `.agentic-overlay.json` manifest schema: records the symlink roots, the remote clone path (`<project-root>/.agentic/remote/`), the current remote SHA, and per-surface overlap stats. The bootstrap CLI writes it; the resolver reads it.
- Extend `scripts/check_skills.py` to resolve via the overlay and validate each resolved skill against the canonical skill anatomy, distinguishing the three cases in the report.
- Extend `scripts/check_harness_sync.py` the same way. YAML-value merge semantics: top-level keys in local `harness-protocol.yaml` replace the corresponding shared keys in full (no deep-merge of list values); a stanza-level replace log line is emitted per overridden key.
- Unit tests: shared-only skill, local-only skill, overlapping skill (local wins), missing local dir (shared used), broken symlink (raises `BrokenOverlayError` — same named error used by `agentic-bootstrap doctor` / `repair`; error message names `agentic-bootstrap repair` as the recovery path), and the YAML replace-semantics for `harness-protocol.yaml`.

**Proof**

- `make check-skills` and `make check-harness-sync` green for this monorepo (which has no `local/` layer yet — the resolver no-ops).
- New unit tests cover the three-cell matrix {shared-only, local-only, overlapping} for skills AND the YAML replace semantics for contracts.
- `ResolvedPath` return values include the expected `source` tags under each test scenario.

### Slice 3 — Bootstrap CLI + consumer-setup doc

**Goal**: one pip console script installs and maintains the symlinked overlay; one canonical doc is all a consumer reads.

**Scope**

- New package at `packages/agentic-bootstrap/` (pip-installable, zero runtime deps beyond stdlib + `tomli`/`tomllib`) exposing:
  - `agentic-bootstrap install --target <path> [--remote-ref <tag>]`: clones (or `git worktree add`s) the remote agentic repo into `<target>/.agentic/remote/`, then symlinks `.claude/skills/`, `.github/hooks/`, `.github/prompts/`, `docs/agentic/contracts/`, `.claude/commands/` from the clone into `<target>/`, writes `<target>/.agentic-overlay.json`, and invokes the three MCP-harness-config writers below in sequence.
  - `agentic-bootstrap update`: runs `git fetch && git checkout <ref>` in the clone, re-validates symlinks (no move if already correct), runs `check-skills` + `check-harness-sync` in dry-run mode against the consumer repo, and updates `.agentic-overlay.json` with the new remote SHA.
  - `agentic-bootstrap status`: reports remote SHA, overlay layer counts, overlay-resolver shared/local/overlapping per surface, daemon-flag state.
  - `agentic-bootstrap doctor`: runs `status` + pip-package version resolution + `AGENT_HANDOFF_DB_PATH` discovery + a trial `import agent_handoff_mcp; configure_runtime(...)` call + an overlay integrity check (broken symlinks, missing `.agentic/remote/`, SHA drift between manifest and clone). Fails fast with the same `BrokenOverlayError` that `check-skills` and `check-harness-sync` raise.
  - `agentic-bootstrap repair` (PA-07): detects a missing, corrupt, or SHA-mismatched `<target>/.agentic/remote/` and re-clones + relinks without the user re-running `install` from scratch. Idempotent: if nothing is broken, it exits zero with "overlay healthy." If the clone exists but is at the wrong ref, fast-forwards or checks out the ref from `.agentic-overlay.json`. Does NOT touch `local/` surfaces.

- **MCP-harness-config writers (PA-02)**: the `install` command runs each writer unconditionally (they no-op if the format does not apply to the detected environment). Each writer is a separate sub-module with its own unit tests, its own merge semantics, and its own idempotency rules. The three writers:

  | Writer | File | Format | Fields touched | Merge rule | Re-run semantics |
  |---|---|---|---|---|---|
  | `claude_mcp_config` | `<target>/.mcp.json` | JSON | `mcpServers.agent-handoff-mcp`, `mcpServers.agent-orchestrator-mcp` (each with `command`, `args`, `env`) | Deep-merge on `mcpServers`: add our two keys, leave all other keys and their nested values untouched. If the two keys already exist, **replace** them (not deep-merge) so stale args/env from a prior install version get overwritten. | Idempotent — running twice produces the same file byte-for-byte. |
  | `vscode_mcp_config` | `<target>/.vscode/mcp.json` | JSON | Same two servers; path convention is workspace-relative (`${workspaceFolder}` variable) per VS Code's MCP extension docs. | Same as above. Also create `.vscode/` directory if absent. | Idempotent. Existing unrelated VS Code config preserved (this file is MCP-specific; settings.json is not touched). |
  | `codex_mcp_config` | `<target>/.codex/config.toml` | TOML | `[mcp_servers.agent-handoff-mcp]` and `[mcp_servers.agent-orchestrator-mcp]` tables with `command`, `args`, `env`. Path convention is absolute (Codex runs with the `~/.codex/` config resolved first; project-local resolution uses absolute paths). | Replace the two named tables; leave any other `[mcp_servers.*]` tables alone. Preserve non-`mcp_servers` top-level tables verbatim. | Idempotent. Requires a TOML writer that preserves comments and key order — use `tomli_w` with `sort_keys=False`. |

  Each writer resolves the MCP-server `command` as the path to the `pyenv`-resolved Python that has both MCP packages pip-installed, so consumers who install into a project-specific venv get that venv's Python recorded. The `env` block pins `AGENT_HANDOFF_DB_PATH` if the caller passed `--db-path` to `install`; otherwise it is omitted and the DB-path resolver (Slice 1) picks up the consumer-root default.

- Write `docs/agentic/consumer-setup.md` covering: prerequisites, `pip install` both MCP packages using the `#subdirectory=packages/<pkg>` pattern from Slice 0/1, `pip install agentic-bootstrap`, `agentic-bootstrap install`, configure `AGENT_HANDOFF_DB_PATH` (or accept the default consumer-root path), first `load_session` sanity check, update workflow, daemon opt-in pointer with the token-cost warning, `repair` / `doctor` for overlay corruption recovery, tenancy expectations (per-DB-file isolation; see `## Tenancy` section).

**Proof**

- Unit tests per writer: `.mcp.json` deep-merge preserves unrelated `mcpServers` entries; `.vscode/mcp.json` creates the directory and writes the expected JSON; `.codex/config.toml` replaces the two named tables without mangling other `[mcp_servers.*]` tables or non-`mcp_servers` tables. Each writer has an idempotency test asserting byte-for-byte identical output on the second run.
- Unit tests for bootstrap CLI core: symlink creation idempotency (re-running `install` does not duplicate), update reconciliation (skips unchanged symlinks), `.agentic-overlay.json` manifest round-trip.
- Unit tests for `agentic-bootstrap repair`: missing `.agentic/remote/` → re-cloned; corrupt clone (detected by `git fsck` or missing `.git/`) → removed and re-cloned; SHA mismatch → `git fetch && git checkout <manifest-sha>`; healthy state → exits zero with "overlay healthy" message.
- Unit tests for `agentic-bootstrap doctor`: broken symlink in overlay → exits non-zero with `BrokenOverlayError` pointing to the broken path AND naming `agentic-bootstrap repair` as the fix. Same named error raised from `check-skills` and `check-harness-sync` when they encounter the same broken state.
- Dry-run `install` against a scratch temp directory creates the expected symlinks, a valid `.agentic-overlay.json`, and the three MCP-harness-config files (where the format detects as applicable). Slice 5 validates the full live run.
- `docs/agentic/consumer-setup.md` exists and reviewer confirms it is standalone (no task-plan or epic references required to execute).

### Slice 4 — Daemon opt-in, token-cost warning, and polling-rework note

**Goal**: daemons ship, but a consumer cannot accidentally enable them without an informed signal, and the rework question is captured where a future engineer will find it.

**Scope**

- Add `orchestrator.daemons.enabled: false` to `harness-protocol.yaml` (shared default). The flag name is deliberately plural (`daemons`, not `worker_daemons`) because it governs every daemon-start surface, not just worker-side ones. Consumers opt in by placing a `local/harness-protocol.yaml` with `orchestrator.daemons.enabled: true` — overlay resolver Slice 2 defines the merge semantics that make this work.
- **Enforcement surface (PA-06) — all three entry points must check the flag and raise `DaemonsDisabledError` on `false`**:
  - `dispatch_lane_work(start_worker=True)` (worker-daemon start)
  - `manage_worker(action in {"start","restart"})` (worker-daemon lifecycle)
  - `manage_orchestrator(action in {"start","restart"})` (orchestrator-daemon lifecycle)
  Message: `"Daemons are opt-in. Enable via \`orchestrator.daemons.enabled: true\` in your \`local/harness-protocol.yaml\`. See \`docs/agentic/consumer-setup.md § Daemons\` for token-cost implications."` Identical message at all three sites so consumers see a single surface.
- Emit a one-shot `logging.WARNING` per process when **any** daemon starts successfully (orchestrator or worker), using the format: `"agent-orchestrator-mcp: <daemon_kind> daemon enabled (poll_interval=<N>s, ~<K> MCP queries/cycle). Worker daemons also spawn lane_prompt.py --check subprocesses per poll. This may consume significant agent tokens over long runs. Rework candidate: see packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md"`. Query-count comes from the plan-stage polling survey (10–15 queries/cycle for orchestrator, ~3–5 for worker before subprocess spawn) and is filled from static config at startup. **No tokens/hour claim in the message (PA-05)**: a tokens/hour number requires either a prerequisite measurement run or runtime payload-size sampling, neither of which this slice ships; pinning an unmeasured number becomes folklore. The qualitative "may consume significant agent tokens over long runs" line carries the warning without inventing a figure. A future measurement-driven slice (out of scope here) can upgrade the message to quantified cost.
- Create `packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` with:
  - Problem statement: per-poll token cost, summary of measurements from the plan-stage survey.
  - Four enumerated alternatives with pros/cons: (a) sqlite `update_hook` in-MCP callbacks, (b) filesystem watcher on `handoff.db`/lane-inbox markers (`watchdog` / `inotify`), (c) unix-domain-socket pub-sub inside the orchestrator lock boundary, (d) hybrid push-with-fallback-poll (push primary signal, poll as watchdog at a much longer interval).
  - Anchors: `orchestrator_daemon.py:1203` (sleep), `orchestrator_daemon.py:965` (`_worker_management_phase`), `orchestrator_daemon.py:991` (`_poll_merge_ready_lanes`), `worker_daemon.py:1786` (`_poll_phase`), `worker_daemon.py:143` (`poll_lane_state`), `orchestrator_daemon.py:530` (lock), `worker_daemon.py:98` (lock).
  - Explicit non-goals: this note does NOT pick a solution. It enumerates. The follow-on epic owns selection.
- Insert `# TODO(E17-10-REWORK): Pull-based poll — see packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` comments at:
  - `orchestrator_daemon.py` above the `time.sleep(poll_interval)` call at line 1203.
  - `worker_daemon.py` above each `time.sleep(cfg.poll_interval)` call at lines 1783, 1790, 1796, 1806.
- Document the daemon opt-in + token cost in `docs/agentic/consumer-setup.md § Daemons (opt-in)` and cross-link from the `docs/agentic/rules/development-workflow.md` rule that governs worker-daemon usage.
- No new MCP tools. No change to the polling architecture. No change to the default poll interval.

**Proof**

- Unit tests: (a) `DaemonsDisabledError` raised at **all three** enforcement sites (`dispatch_lane_work(start_worker=True)`, `manage_worker(action="start")`, `manage_worker(action="restart")`, `manage_orchestrator(action="start")`, `manage_orchestrator(action="restart")`) when the flag is false; (b) WARNING emitted exactly once per process when flag is true — both for worker-daemon start and for orchestrator-daemon start; (c) WARNING message does NOT contain a tokens/hour substring (regex-asserted negative); WARNING message DOES contain the qualitative "may consume significant agent tokens" phrase; (d) `event-driven-daemon-design-note.md` exists at the expected path and is linked from the WARNING message; (e) grep-based lint asserts `TODO(E17-10-REWORK)` present at every cited line — same discipline as `scripts/check_task_plan_findings.py`.
- A fresh `ruff`/`mypy` / `make check-all` run touches none of the unrelated surfaces.

### Slice 5 — Update-pipeline validation against a scratch consumer

**Goal**: prove the MVP success signal against a real second project.

**Scope**

- Stand up a scratch consumer at `~/Development/hoist-mvp-consumer/` (a sibling directory rather than `/tmp` so survival across reboots is not an issue; `git init --initial-branch=main`, commit a stub `README.md`).
- From the scratch consumer: install both MCP packages from tag `v0.1.0`, install `agentic-bootstrap` from tag `v0.1.0`, run `agentic-bootstrap install --target .`.
- Verify: overlay-resolver reports expected surfaces; `check-skills` + `check-harness-sync` pass; a `configure_runtime` + `set_handoff_state` + `record_event` cycle writes to `~/Development/hoist-mvp-consumer/.agentic/handoff.db` (assert path via SQL `PRAGMA database_list;` or Python `_get_active_db_path()`) and not the monorepo DB.
- Execute the update-propagation test:
  - Bump `agent-handoff-mcp` to `0.1.1` via `scripts/release_mcp_package.sh` (no-op CHANGELOG line — the point is the tag and version wire-up).
  - Edit one line in one shared skill (pick a skill whose SKILL.md has a safe place for a clarifying note, e.g. `.claude/skills/scope/SKILL.md`).
  - For the MVP, `git push` to a local bare clone of the remote repo (set up once as the "remote" the bootstrap CLI resolves). Production remote setup is out of scope.
  - From `~/Development/hoist-mvp-consumer/`: `pip install --upgrade "agent-handoff-mcp==0.1.1" && agentic-bootstrap update`.
  - Assert: `pip show agent-handoff-mcp` reports `0.1.1`; `readlink .claude/skills/scope/SKILL.md` resolves to the updated remote SHA; `grep` finds the new line in the resolved file; `handoff.db` state unchanged; `docs/agentic/consumer-setup.md § Update Workflow — Verified MVP Example` updated with the exact shell transcript.
- **E17-7 Slice 2 ordering tradeoff**: record in the proof doc whether this plan lands before or after E17-7 Slice 2 (multi-active-task registry). If before: the consumer inherits the singleton active-task model, and `switch_task` still overwrites the active row — acceptable for MVP (consumers only have one active task at a time in practice) but flag explicitly. If after: cross-reference the registry docs in `docs/agentic/consumer-setup.md` and note the cross-project isolation is STILL by-DB-file; concurrent task rows only benefit same-project multi-task work.

**Proof**

- `docs/agentic/proofs/e17-10-consumer-update-walkthrough.md` committed containing: `pip show` output pre- and post-upgrade; `readlink` output pre- and post-update; `ls -la` of the symlinked dirs pre- and post-update; DB-path assertion transcript; E17-7 Slice 2 ordering note.
- `agentic-bootstrap doctor` run from the consumer exits zero.
- `handoff_close_check(task_ref="E17-10", enforce=True)` on the feature branch returns green before merge.

## Consolidated Checklist

- [ ] Slice 0: `darce/agentic-system` private repo created via `gh`; initial commit mirrors shared surface from monorepo `main`; `v0.1.0` tag pushed.
- [ ] Slice 0: `docs/agentic/rules/development-workflow.md § Shared Agentic Surface` added with remote URL, one-way-sync-direction statement, and `TODO(E17-10-POST-MVP-SYNC)` anchor.
- [ ] Slice 0: monorepo in-tree skills/hooks/contracts NOT deleted yet — rollback path preserved until Slice 5 proof.
- [ ] Slice 1: `AGENT_HANDOFF_DB_PATH` → `RuntimeConfig.db_path` → consumer-root default → dev-monorepo fallback resolution implemented; unit tests cover all four paths PLUS the linked-worktree convergence case (three worktrees of one project all resolve to the same `<main-worktree-root>/.agentic/handoff.db`) PLUS the non-git-repo `ConsumerRootResolutionError` fail path.
- [ ] Slice 1: `AGENT_HANDOFF_OUTPUT_ROOT` → `RuntimeConfig.output_root` → derived-from-DB-parent resolution implemented; unit-test matrix asserts `generate_dashboard_md()` + `generate_current_task_md()` write under the expected directory for every DB-path arm.
- [ ] Slice 1: `agent-handoff-mcp` and `agent-orchestrator-mcp` version `0.1.0` tagged on the monorepo; `CHANGELOG.md` entries written.
- [ ] Slice 1: `scripts/release_mcp_package.sh` exists and emits `git+ssh://git@github.com/darce/context-alt-text-monorepo.git@v<tag>#subdirectory=packages/<pkg>` URLs; `[tool.hoisted]` table in both `pyproject.toml` files documents the pattern.
- [ ] Slice 2: `scripts/overlay_resolver.py` returns tagged `ResolvedPath` entries across skills/hooks/commands/prompts/contracts.
- [ ] Slice 2: `check-skills` and `check-harness-sync` consume the overlay; unit tests cover shared-only, local-only, overlapping, `BrokenOverlayError` on broken symlink, and YAML replace-semantics.
- [ ] Slice 2: `.agentic-overlay.json` schema documented in `docs/agentic/contracts/overlay-manifest.yaml` (or equivalent); round-trip test green.
- [ ] Slice 3: `packages/agentic-bootstrap/` with `install`, `update`, `status`, `doctor`, `repair` commands; zero runtime deps beyond stdlib + `tomli`/`tomllib` + `tomli_w`.
- [ ] Slice 3: three MCP-harness-config writers implemented (`claude_mcp_config`, `vscode_mcp_config`, `codex_mcp_config`) with per-writer unit tests for merge semantics AND byte-for-byte idempotency.
- [ ] Slice 3: `agentic-bootstrap repair` unit tests cover missing-remote, corrupt-clone, SHA-mismatch, and healthy-noop paths.
- [ ] Slice 3: `BrokenOverlayError` raised consistently by `doctor`, `repair`, `check-skills`, and `check-harness-sync` when overlay is broken; error message names `agentic-bootstrap repair` as the fix.
- [ ] Slice 3: `docs/agentic/consumer-setup.md` written and self-contained.
- [ ] Slice 4: `orchestrator.daemons.enabled` in `harness-protocol.yaml` defaults `false`; `DaemonsDisabledError` raised at **all three** entry points (`dispatch_lane_work(start_worker=True)`, `manage_worker(action in start/restart)`, `manage_orchestrator(action in start/restart)`) on `false`.
- [ ] Slice 4: one-shot WARNING emitted per process when any daemon starts; cites poll interval, MCP-queries/cycle, qualitative token-cost note, and design-note path. WARNING does NOT contain a tokens/hour figure (regex-asserted).
- [ ] Slice 4: `packages/agent-orchestrator-mcp/docs/reworks/event-driven-daemon-design-note.md` exists with four alternatives and all cited anchors.
- [ ] Slice 4: `TODO(E17-10-REWORK)` comments present at `orchestrator_daemon.py:1203` and `worker_daemon.py:{1783,1790,1796,1806}`; grep-based lint test green.
- [ ] Slice 5: scratch consumer at `~/Development/hoist-mvp-consumer/` installs MCP packages + `agentic-bootstrap`, runs overlay validators, writes to its own `handoff.db`, emits `DASHBOARD.txt` under the consumer root (not the monorepo root).
- [ ] Slice 5: minor-version + shared-skill update propagates via `pip install --upgrade` + `agentic-bootstrap update`; `docs/agentic/proofs/e17-10-consumer-update-walkthrough.md` committed.
- [ ] Slice 5: E17-7 Slice 2 ordering tradeoff recorded in the proof doc.
- [ ] Pre-merge gate: `handoff_close_check(task_ref="E17-10", enforce=True)` passes with zero open findings.

## Tenancy (explicit note)

The MVP's tenancy model is **siloed by-DB-file per project** (user-confirmed 2026-04-17):

- Each consumer project has exactly one `handoff.db` at `<main-worktree-root>/.agentic/handoff.db` (or `AGENT_HANDOFF_DB_PATH` override).
- **All linked worktrees under a project share that one DB.** A project with three active feature worktrees has three shells writing to one `handoff.db` — this is required for cross-worktree handoff visibility and is enforced by the Slice 1 `<consumer-root>` resolver that converges linked worktrees to the main worktree's root.
- No `tenant_id` column is added. No schema-level multi-tenancy.
- **Future**: a master aggregator `handoff.db` that merges per-project state across all of Daniel's projects is a **possible future follow-on** if cross-project visibility ever proves valuable. It is explicitly out of scope for this plan. The per-DB-file design is compatible with a future aggregator (the aggregator would read per-project DBs and render a union view) — no architectural retrofit required.
- Cross-project dashboards, centralized oncall visibility, and multi-tenant row-level filtering remain out of scope for this plan and would belong to that later aggregator epic.

Same-project active-task collisions (the singleton-keyed `handoff_state WHERE id = 1` that overwrites when `switch_task` runs) are a **separate problem** owned by E17-7 Slice 2 (multi-active-task registry). If E17-7 Slice 2 lands before this plan, consumers benefit from concurrent task rows per-project for free; if not, the consumer experience inherits the current singleton behavior — noted but acceptable for MVP.

## Risk Register

- **Risk**: a consumer runs `pip install -e` instead of tag-install, inherits the monorepo testing-python rule failure mode (env-wide source-path pinning). **Mitigation**: `consumer-setup.md` explicitly tells consumers to use `git+ssh://...@v<tag>`, not editable installs. `doctor` command warns on detected editable installs.
- **Risk**: symlink-based overlay breaks on Windows. **Mitigation**: MVP scope is Unix/macOS only (Daniel-owned private projects). Document the limit in `consumer-setup.md § Platform Support`.
- **Risk**: a consumer enables daemons, misses the WARNING, and burns a token budget. **Mitigation**: one-shot WARNING is loud; `consumer-setup.md` frames daemons as "off by default, informed opt-in." Post-MVP: add a `doctor` check that reports "daemons enabled — token cost: ~X/hour."
- **Risk**: Slice 0 remote-repo extraction introduces divergence between `darce/agentic-system` and this monorepo's in-tree copies (skills/hooks/contracts are not deleted from the monorepo until a later Slice 7 cleanup). **Mitigation**: during MVP, the monorepo is the source of truth; Slice 0 pushes one-way to the remote. A `TODO(E17-10-POST-MVP-SYNC)` is committed in `development-workflow.md` so the reverse-sync workflow is visible. Slice 5 validates that one-way flow produces a working consumer; post-MVP work either deletes the monorepo copies (monorepo becomes consumer) or implements bidirectional sync.
- **Risk**: polling rework design note becomes a dead document if no one picks it up. **Mitigation**: in-code TODOs + the one-shot WARNING message both name the path; a future engineer touching the daemon will see both signals.
- **Risk**: per-format MCP-harness-config writers (Slice 3) could silently corrupt a consumer's existing `.mcp.json` or `.codex/config.toml` if merge semantics are wrong. **Mitigation**: each writer has dedicated unit tests asserting unrelated entries are preserved byte-for-byte; `agentic-bootstrap install` refuses to overwrite a config file when a non-writer-owned top-level section has been modified from its expected shape unless `--force` is passed. `doctor` diff-reports any drift.
