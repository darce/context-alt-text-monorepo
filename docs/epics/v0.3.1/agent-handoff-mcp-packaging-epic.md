# Agent Handoff MCP Packaging and Seam Separation (v0.3.1)

## Objective

Split `agent-handoff-mcp` into a portable, pip-installable core product and optional extension layers so 3rd-party repos can adopt handoff state management without inheriting ACE playbook logic, monorepo-specific lane manifests, or orchestration daemons they do not need.

## Problem Statement

Today all 53+ MCP tools ship in a single flat registration regardless of whether the consumer needs core handoff CRUD, multi-agent orchestration, or the ACE (Autonomous Coding Engine) reflection system. The `orchestration/` subpackage mixes three distinct concerns; generic multi-agent lane management, ACE-specific metrics/reflection, and this monorepo's hardcoded path assumptions (`REPO_ROOT = SCRIPT_DIR.parents[4]`, `config/lane-orchestration/` manifest dir, `docs/agentic/rules/` review rules dir, `apps/` boundary prefixes). A 3rd-party installer gets all of this or none of it, and the hardcoded paths would break immediately outside this monorepo.

## UX Vision

Portable adopters get a working MCP server with ~42 core tools for task state, decisions, findings, test results, artifacts, and CURRENT_TASK.md generation without pulling in repo-specific ACE logic. During the v0.x compatibility window, existing monorepo/full-install consumers keep the current orchestration surface; the portable core-only footprint is introduced as an explicit packaging mode or install target and only becomes the default in a clearly versioned breaking release. Repos that also want multi-agent worktree orchestration opt into the orchestration tier and get daemons, lane management, backend adapters, and review dispatch with configurable path conventions. ACE playbook logic (`ace_metrics`, `ace_reflect`) and project-specific lane manifests remain in this monorepo only. Planning/authoring templates (`EPIC.template.md`, `TASK_PLAN.template.md`, `ROADMAP.template.md`, decision-writing templates) remain repo-local guidance assets and are never a runtime dependency of the shipped package.

## Constraints

- The existing `[rg-013]` and `[rg-014]` guardrails (core.py stays pure CRUD; orchestration uses late-binding imports) are load-bearing and must be preserved, not relaxed.
- `fastmcp` remains the only required runtime dependency for the core package. Orchestration extras may add `textual` or similar TUI dependencies.
- No breaking changes to the MCP tool surface for existing consumers during the v0.x compatibility window. Shared tool signatures and behavior must remain stable, and existing monorepo/full-install consumers must keep the current orchestration surface, including today's `get_metrics_summary` availability, until a clearly versioned breaking release or an explicit alternate packaging mode is introduced.
- The `codex-subagent-bridge` package is a separate concern and stays out of `agent-handoff-mcp` core dependencies.
- Greenfield packaging policy applies; no backward-compat shims for import paths that move between tiers.
- Only operational templates that are actually rendered by shipped orchestration tooling may be treated as package-adjacent dependencies. Planning/authoring templates under `docs/agentic/templates/` stay repo-local and must not become required at package runtime.

## Terminology

- **Core Handoff**: The portable set of modules (`core.py`, `config.py`, `runtime.py`, `enums.py`, `artifact_index.py`, `cli.py`, core tool registrations in `api.py`) that provide task-state CRUD, review findings, artifacts, FTS5 search, export/import, and CURRENT_TASK.md generation. No subprocess calls, no orchestration imports.
- **Orchestration**: The generic multi-agent layer; daemons, backend adapters, lane exec/prompt/result, review dispatch/runner, slice review packets, dashboards. Reusable across any repo that uses worktree-based multi-agent workflows.
- **ACE**: Autonomous Coding Engine. The self-correcting playbook system that parses `[sr-NNN]`/`[rg-NNN]` strategy bullets from instruction files, tracks `helpful`/`harmful` evidence counters, and produces process metrics. Specific to this monorepo's `CLAUDE.md` format.
- **Project-specific**: Lane manifests, hardcoded `REPO_ROOT` derivations, boundary-prefix constants, and review-rules-dir paths that assume this monorepo's directory layout.
- **Operational templates**: Template files consumed by runtime/operator tooling, such as worktree lane brief/report renderers.
- **Authoring templates**: Repo-local planning/decision templates that guide humans/agents when drafting docs, but are not required for package runtime.

## Current State

- `core.py` is mostly portable; ~3300 lines of handoff CRUD with zero top-level imports from `orchestration/`, but it still owns `get_latest_slice_review_packet()` and performs a late import of `slice_review_packet` inside that wrapper.
- `api.py` mixes three registration styles today: most orchestration helpers come in via `_import_scripts_mcp_module()`, `get_latest_slice_review_packet` is still a direct alias to the core wrapper, and `get_metrics_summary` directly imports `orchestration.ace_metrics`. No feature flags or conditional registration exist; all tools are always registered.
- `orchestration/` mixes three concerns: (a) generic multi-agent management (daemons, adapters, lane exec), (b) ACE playbook evolution (`ace_metrics.py`, `ace_reflect.py`), (c) project-specific config readers and runtime assumptions (`lane_manifest.py`, `generate_lane_manifest.py`, `review_ready.py` with hardcoded boundary prefixes, `review_runner.py` with hardcoded rules dir, daemon/generator helpers with repo-root assumptions and ACE log handling).
- `pyproject.toml` declares only `fastmcp` as a runtime dependency and `hypothesis` as a test extra. No orchestration extra exists.
- `__init__.py` re-exports everything including orchestration symbols (`orchestrator_start`, `worker_start`, `SliceReviewPacket`) at the top level.

## Target Architecture

The package splits into three tiers with clean import boundaries:

```
agent-handoff-mcp (pip install)
  core.py, config.py, runtime.py, enums.py, artifact_index.py, cli.py
  api.py (core tools only when orchestration is absent)
  ~42 MCP tools

agent-handoff-mcp[orchestration] (pip install extra)
  orchestration/ subpackage (generic multi-agent)
  +10 MCP tools conditionally registered
  configurable paths (manifest_dir, rules_dir, boundary_prefixes)

repo-local (not shipped)
  ace_metrics.py, ace_reflect.py
  lane manifests (config/lane-orchestration/*.json)
  review_ready boundary prefixes
  review_runner rules_dir paths
  docs/agentic/templates/ (authoring templates and repo-owned operational templates)
```

`api.py` will eventually probe for `orchestration/` importability at registration time, but the rollout is staged for compatibility. During v0.x, the existing full-install path continues to expose the current orchestration surface for existing consumers, including the currently unconditionally registered `get_metrics_summary` tool, while a separate portable/core-only install target exercises the smaller registration set. `get_metrics_summary` only moves behind an explicit ACE extension when the caller has intentionally selected the portable/core-only mode or when the project takes a clearly versioned breaking release. The `__init__.py` public API becomes conditional only when the packaging mode is explicit or when the project takes a clearly versioned breaking release.

Template dependency policy:

- The shipped core package must not require any files under `docs/agentic/templates/`.
- Planning/authoring templates (`EPIC.template.md`, `TASK_PLAN.template.md`, `ROADMAP.template.md`, decision templates) remain repo-local guidance and are outside package dependency management.
- If shipped orchestration features keep rendering lane briefs/reports from disk templates, those templates need an explicit configurable seam such as `template_dir`, similar to `rules_dir`.
- Shipped orchestration must degrade cleanly when optional operational templates are absent: either use built-in defaults or disable the rendering feature with a clear diagnostic, never crash on a hardcoded monorepo path.

### Design Decisions

| Decision | Rationale |
| --- | --- |
| Three tiers, not two | ACE logic is deeply coupled to this repo's instruction-file format. A 3rd party gains nothing from it. Orchestration is genuinely reusable but optional for solo-agent setups. |
| Optional extra, not separate package | Orchestration shares the same DB schema, enums, and config surface. A separate package would need to re-declare those or add a cross-package dependency. An optional extra keeps the import tree simple. |
| Conditional tool registration in `api.py` | Avoid import errors for users who install core-only. Late imports already exist; adding an `_HAS_ORCHESTRATION` flag is minimal. |
| Staged compatibility rollout | The portable/core-only packaging target can land in v0.x, but the default install path for existing users should stay full-surface until a clearly versioned breaking release or explicit migration step. |
| Configurable paths instead of hardcoded `REPO_ROOT` | `lane_manifest.py` should accept `manifest_dir` as a parameter. `review_runner.py` should accept `rules_dir`. `review_ready.py` should accept `boundary_prefixes` and `contract_prefixes`. Defaults can match this monorepo's layout but must be overridable. |
| Move `slice_review_packet` late import out of `core.py` | Preserves `[rg-013]` cleanly. The tool wrapper moves to `api.py` where all other orchestration bridges already live. |
| ACE stays repo-local as an extension package | ACE should own metrics registration, reflection hooks, dashboard footer metrics, and advisory log processing from outside the shipped package. `agent-handoff-mcp` exposes only generic hook points or optional callback/config seams, not ACE-specific imports. |

### Data Model

- **Canonical source**: `handoff.db` SQLite schema, `artifacts.db` sidecar. Owned entirely by core; orchestration reads/writes via core's public functions.
- **Configuration flow**: `RuntimeConfig` (core) provides `workspace_root`, `state_dir`, `db_path`. Orchestration adds `manifest_dir`, `rules_dir`, `boundary_prefixes` as optional config extensions.
- **Template flow**: authoring templates remain repo-local and are discovered through repo instructions/rules, not package runtime. If orchestration keeps file-backed brief/report rendering, it must treat those as optional operational templates behind an explicit `template_dir`-style config seam rather than a hardcoded docs path.
- **Tool registration flow**: `build_handoff_mcp()` in `api.py` eventually registers core tools unconditionally and appends orchestration tools when `_HAS_ORCHESTRATION` is true, but the migration is staged. During v0.x, the default/full-install path keeps today's registration surface, including `get_metrics_summary`; the explicit portable/core-only mode is where orchestration and ACE tools become conditional first.
- **ACE integration flow**: the shipped package provides generic extension seams only, such as optional metrics providers, review-postprocessing hooks, and advisory hooks. This monorepo's ACE extension supplies the instruction-file paths, reflection log handling, and tool registration that sit on top of those seams.

## Phased Delivery

### Phase 1: Clean the Core Seam -- not-started

> **Status**: not-started
> **Task plans**: `not yet scoped`

**Goal**: Make `core.py` fully self-contained with zero orchestration imports.

Deliverables:

- Move `get_latest_slice_review_packet` tool wrapper from `core.py` to `api.py` (matches all other orchestration bridge tools).
- Verify `core.py` has no `from .orchestration` imports at any scope (top-level or late-binding).
- Update `[rg-013]` guard to explicitly include late-binding imports in the prohibition.

Exit criteria:

- `grep -rn 'orchestration' core.py` returns zero hits.
- All 732+ existing tests pass.
- `build_handoff_mcp()` still registers `get_latest_slice_review_packet` via `api.py` late import.

### Phase 2: Conditional Orchestration Registration -- not-started

> **Status**: not-started
> **Task plans**: `not yet scoped`

**Goal**: Make orchestration tool registration conditional on subpackage availability.

Deliverables:

- Add `_HAS_ORCHESTRATION` probe in `api.py`.
- Guard the portable/core-only registration path behind the orchestration probe while preserving the current full-install surface for existing consumers during v0.x.
- Keep `get_metrics_summary` on the current full-install/default surface during v0.x; only the explicit portable/core-only mode may omit it before a breaking release.
- Make `__init__.py` conditional only for the explicit portable packaging mode, or defer that change to the first clearly versioned breaking release.
- Add `[project.optional-dependencies] orchestration = [...]` to `pyproject.toml` if orchestration needs dependencies beyond `fastmcp`.
- Add a `doctor` check that reports which tiers are available.

Exit criteria:

- The explicit portable/core-only install target starts the MCP server with ~42 tools and no import errors.
- The existing full-install path, plus any explicit orchestration install target, still starts with all 53+ tools during the v0.x compatibility window, including `get_metrics_summary`.
- `run_doctor()` reports tier availability.
- All existing tests pass (orchestration tests may require the extra).

### Phase 3: Configurable Paths -- not-started

> **Status**: not-started
> **Task plans**: `not yet scoped`

**Goal**: Remove hardcoded monorepo paths from orchestration modules so they work in any repo.

Deliverables:

- `lane_manifest.py`: accept `manifest_dir` parameter instead of deriving from `SCRIPT_DIR.parents[4]`.
- `review_runner.py`: accept `rules_dir` parameter instead of hardcoding `docs/agentic/rules`.
- `review_ready.py`: accept `boundary_prefixes` and `contract_prefixes` instead of hardcoding `apps/`, `packages/agent-handoff-mcp/src/`, `docs/agentic/contracts/`.
- Audit shipped orchestration tooling for template-path assumptions (`scripts/worktree-lane` today; any future package-owned brief/report renderer) and either relocate that rendering outside the shipped package or parameterize it behind `template_dir`.
- Audit and parameterize the remaining repo-root/path-coupled helpers that currently assume this monorepo layout (`generate_lane_manifest.py`, `handoff_integrity_guard.py`, and any other `SCRIPT_DIR`/`REPO_ROOT`-derived orchestration helpers that are meant to ship).
- Add path configuration to `RuntimeConfig` or a new `OrchestrationConfig` dataclass, including `template_dir` only if template-backed orchestration rendering remains in scope.
- Default values match this monorepo's layout so nothing breaks without explicit config.

Exit criteria:

- Orchestration modules instantiated with custom paths work correctly in tests.
- This monorepo's existing workflow is unchanged (defaults match current hardcoded values).
- No remaining shipping-critical `SCRIPT_DIR.parents[N]`, monorepo-root path assumptions, or hardcoded template paths in the shipped orchestration modules.

### Phase 4: Extract ACE to Repo-Local Extension -- not-started

> **Status**: not-started
> **Task plans**: `not yet scoped`

**Goal**: Move ACE-specific modules out of the shipped package while keeping them functional in this monorepo.

Deliverables:

- Move `ace_metrics.py` and `ace_reflect.py` to a repo-local location (e.g., `scripts/ace/` or a separate `packages/ace-playbook/` package).
- Preserve `get_metrics_summary` on the default/full-install surface for the v0.x compatibility window, but make its implementation come from the same explicit ACE extension layer used by portable/core-only installs. After the compatibility window, remove it from the shipped default registration unless the ACE extension is installed.
- Move or gate the ACE-dependent runtime call sites in `worker_daemon.py`, `dashboard_live.py`, and `orchestrator_daemon.py` so the shipped package no longer imports ACE modules or writes ACE-specific log/advisory files.
- Move project-specific lane manifest generation (`generate_lane_manifest.py`, `generate_agent_config.py`) to repo-local scripts or the orchestration config layer.
- Add generic extension seams for metrics/footer providers, post-review finding processors, and dispatch advisory hooks so repo-local ACE behavior plugs in without hard imports from the shipped package.
- Remove top-level ACE-orchestration exports that force repo-local symbols into the shipped public package surface, or make them conditional in the same compatibility-managed packaging mode used for orchestration exports.
- Update `CLAUDE.md` and `BOOTSTRAP.md` references to reflect new import paths.

Exit criteria:

- `ace_metrics` and `ace_reflect` are importable and functional from this monorepo's `PYTHONPATH`.
- The published `agent-handoff-mcp` package contains no files that reference `[sr-NNN]`/`[rg-NNN]` bullet parsing, this repo's instruction-file format, `ace_reflect_log.jsonl`, `config/lane-orchestration/` paths, or unconditional top-level exports of repo-local orchestration/ACE symbols.
- `make ace-reflect` still works from the monorepo root.

### Phase 5: PyPI Readiness -- not-started

> **Status**: not-started
> **Task plans**: `not yet scoped`

**Goal**: Prepare the package for public distribution.

Deliverables:

- README.md rewrite for 3rd-party audience (quick start, tool reference, configuration).
- License file in package root.
- `pyproject.toml` metadata: author, URLs, classifiers, license.
- Version bump to `1.0.0` (or `0.2.0` if pre-release).
- CI workflow for package build and test (sdist + wheel).
- Smoke test: install from built wheel into a clean venv, start server, call 5 core tools.

Exit criteria:

- `pip install dist/agent_handoff_mcp-*.whl` in a clean venv starts a functional MCP server.
- README includes working quick-start example.
- Package metadata renders correctly on PyPI (test.pypi.org upload).

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| `fastmcp` stable release | External | Available | Core package runtime |
| PyPI account / namespace | @daniel | Not started | Phase 5 publication |
| `codex-subagent-bridge` packaging | Internal | Not started | Orchestration adapters (optional) |

## Code Anchors

| Layer | File | Note |
| --- | --- | --- |
| Core CRUD | `packages/agent-handoff-mcp/src/agent_handoff_mcp/core.py` | ~3300 lines; must stay orchestration-free per `[rg-013]` |
| Tool registration | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | `build_handoff_mcp()` registers all tools; conditional probe goes here |
| Public API | `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | Re-exports everything; needs conditional orchestration exports |
| Package metadata | `packages/agent-handoff-mcp/pyproject.toml` | Add `[project.optional-dependencies]` for orchestration extra |
| Orchestration entry | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/` | Subpackage to probe for availability |
| ACE metrics | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_metrics.py` | Moves to repo-local in Phase 4 |
| ACE reflect | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/ace_reflect.py` | Moves to repo-local in Phase 4 |
| Top-level exports | `packages/agent-handoff-mcp/src/agent_handoff_mcp/__init__.py` | Currently re-exports orchestration and slice-review symbols unconditionally |
| Hardcoded paths | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/lane_manifest.py` | `REPO_ROOT = SCRIPT_DIR.parents[4]`; parameterize in Phase 3 |
| Hardcoded prefixes | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_ready.py` | `BOUNDARY_PREFIXES`; parameterize in Phase 3 |
| Hardcoded rules dir | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/review_runner.py` | `REPO_ROOT / "docs" / "agentic" / "rules"`; parameterize in Phase 3 |
| Operational templates | `scripts/worktree-lane` | Reads `docs/agentic/templates/WORKTREE_LANE_{BRIEF,REPORT}.template.md`; decide whether this stays repo-local or moves behind `template_dir` |
| ACE log handling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/worker_daemon.py` | Appends to `ace_reflect_log.jsonl`; must move behind extension seam |
| ACE advisory handling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/orchestrator_daemon.py` | Reads pending `ace_reflect_log.jsonl` state; must move behind extension seam |
| Repo-root helpers | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/generate_lane_manifest.py` | Derives output from monorepo-root assumptions; likely repo-local |
| Repo-root guard | `packages/agent-handoff-mcp/src/agent_handoff_mcp/orchestration/handoff_integrity_guard.py` | Resolves package/src paths relative to repo root; audit for shipment |
| Lane manifests | `config/lane-orchestration/*.json` | Project-specific; stays repo-local |
| Authoring templates | `docs/agentic/templates/{EPIC,TASK_PLAN,ROADMAP,DECISION_*}.template.md` | Repo-local guidance only; not a runtime dependency of the shipped package |
| Guard rules | `docs/agentic/instructions.md` | `[rg-013]`, `[rg-014]` enforce core/orchestration boundary |

---

# Consolidated Checklist

## Phase 1: Clean the Core Seam -- not-started

- [ ] Move `get_latest_slice_review_packet` wrapper from `core.py` to `api.py`
- [ ] Verify zero orchestration references in `core.py`
- [ ] Update `[rg-013]` to cover late-binding imports
- [ ] All tests pass

## Phase 2: Conditional Orchestration Registration -- not-started

- [ ] Add `_HAS_ORCHESTRATION` probe to `api.py`
- [ ] Guard the portable/core-only registration path without breaking the existing full-install surface during v0.x
- [ ] Keep `get_metrics_summary` on the full-install/default surface during v0.x while moving portable/core-only installs to explicit ACE extension registration
- [ ] Conditional `__init__.py` exports only in explicit portable mode or a later breaking release
- [ ] Add optional-dependencies to `pyproject.toml`
- [ ] `doctor` reports tier availability
- [ ] Core-only install starts MCP server without errors

## Phase 3: Configurable Paths -- not-started

- [ ] Parameterize `lane_manifest.py` manifest_dir
- [ ] Parameterize `review_runner.py` rules_dir
- [ ] Parameterize `review_ready.py` boundary/contract prefixes
- [ ] Decide whether operational brief/report templates remain repo-local or gain an explicit `template_dir` seam for shipped orchestration
- [ ] Audit and parameterize or relocate remaining shipping repo-root helpers (`generate_lane_manifest.py`, `handoff_integrity_guard.py`, similar `SCRIPT_DIR`/`REPO_ROOT` consumers)
- [ ] Add path config to `RuntimeConfig` or `OrchestrationConfig` for every remaining shipped path dependency, including templates if needed
- [ ] Defaults match this monorepo; custom paths work in tests

## Phase 4: Extract ACE to Repo-Local Extension -- not-started

- [ ] Move `ace_metrics.py` and `ace_reflect.py` to repo-local location
- [ ] Route `get_metrics_summary` through the ACE extension while preserving v0.x full-install compatibility; remove it from default registration only after the compatibility window or in explicit portable mode
- [ ] Remove or gate ACE imports and `ace_reflect_log.jsonl` behavior from shipped orchestration runtimes
- [ ] Move project-specific manifest generators to repo-local
- [ ] Add generic extension hooks for repo-local ACE behavior
- [ ] Make top-level orchestration/ACE exports conditional or move them out of the shipped default package surface
- [ ] Update monorepo docs and import paths
- [ ] `make ace-reflect` still works

## Phase 5: PyPI Readiness -- not-started

- [ ] README rewrite for 3rd-party audience
- [ ] License and metadata in `pyproject.toml`
- [ ] Version bump
- [ ] CI build/test workflow
- [ ] Clean-venv smoke test
- [ ] test.pypi.org upload verification

## Deferred (Post-v0.3.1)

- [ ] Plugin/hook system for registering custom tool extensions (e.g., ACE tools) into the MCP server at startup
- [ ] `codex-subagent-bridge` as a separately published package
- [ ] Multi-DB backend support (Postgres, etc.) for core handoff state
