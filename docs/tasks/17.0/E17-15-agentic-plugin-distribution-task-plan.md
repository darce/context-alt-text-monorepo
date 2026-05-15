# E17-15. Agentic Plugin Distribution and Remote Implementation Handoff

- **Date**: 2026-05-15
- **Author**: GitHub Copilot
- **Owning Epic**: [docs/epics/v0.4.0/skill-formalization-and-process-automation-epic.md](../../epics/v0.4.0/skill-formalization-and-process-automation-epic.md)
- **Epic Short ID**: E17
- **Target Branch**: `feature/e17-15`
- **Review Coverage Target**: 2
- **Source Spec**: [docs/specs/agentic-plugin-distribution-spec.md](../../specs/agentic-plugin-distribution-spec.md)

## Objective

Convert the reviewed plugin-distribution spec into an implementation-ready package that can be landed in this monorepo, then ported to `agentic-protocol-monorepo` as the executable work plan for the shared plugin system. The task finishes when this repo has durable planning/ADR surfaces on `main`, the remote implementation scope is explicit, and the monorepo consumer-cleanup slice is ready to run after the remote plugin tree exists.

## Intake

- **Scope one-pager**: [docs/scopes/hoist-agentic-system-to-remote-scope.md](../../scopes/hoist-agentic-system-to-remote-scope.md), [docs/scopes/e17-10-hoisted-surface-cleanup-scope.md](../../scopes/e17-10-hoisted-surface-cleanup-scope.md), [docs/scopes/e17-12-codex-skill-discoverability-scope.md](../../scopes/e17-12-codex-skill-discoverability-scope.md)
- **Key Q&A decisions**: captured in the E17-15 spec review and plan-analyze handoff decisions.
- **Not-Doing**: no VS Code Copilot plugin distribution; no new public marketplace or package publication work; no MCP server repo code changes unless remote plugin implementation proves the existing entrypoints cannot launch.

## Problem Statement

The shared agentic workflow surface is still split across repo-local skill bodies, command adapters, Codex prompts, and harness instructions. The E17-15 spec selects a plugin-native distribution model, but implementation cannot begin safely until the repo has a reviewed task plan and ADR that separate three ownership boundaries: this monorepo's planning/review surfaces, `agentic-protocol-monorepo` implementation work, and remote MCP server registration references.

## Constraints

- Planning artifacts are authored and reviewed in this monorepo first because E17 handoff, review findings, and branch lifecycle state live here.
- Code changes for the shared plugin generator, manifest schema, emitted plugin trees, and canonical skill-body layout belong in `agentic-protocol-monorepo`, not this monorepo.
- Remote MCP server repos remain private source owners and are referenced from plugin `mcpServers` definitions via the current `uvx` package pins: `mcp-agent-handoff==0.11.2` and `mcp-agent-orchestrator==0.4.6`.
- This monorepo cleanup is limited to Tier 3 consumer migration after a working plugin tree exists.
- The root worktree must remain on `main`; all edits for this task happen on `feature/e17-15` until merge.

## Workflow Principles

- Land the planning contract before remote implementation starts.
- Port by immutable evidence: when copying this plan to `agentic-protocol-monorepo`, record the monorepo commit SHA and reviewed spec/ADR paths.
- Keep implementation ownership singular: plugin generator and canonical skill bodies live in `agentic-protocol-monorepo`; consumer cleanup lives here; MCP server behavior stays in the MCP repos.
- Preserve current MCP runtime package pins unless a later reviewed task explicitly changes the packaging model.

## Terminology

- **Plugin distribution package**: the spec, ADR, and task plan that define the shared plugin system before remote implementation.
- **Remote implementation repo**: `agentic-protocol-monorepo`, the target repo for canonical skill bodies, plugin manifest schema, deterministic generator, emitted plugin trees, and distribution docs.
- **Consumer cleanup**: this monorepo's removal of cross-harness skill/command/prompt copies after the remote plugin tree is installable.
- **MCP runtime registration**: plugin `mcpServers` entries that launch existing MCP server packages through `uvx` package pins.

## Current State Analysis

- The E17-15 spec exists in this feature worktree and has passed plan-analyze precheck after the APD-005 install-form correction.
- The spec-review finding for stale `git+ssh` MCP install language is fixed in handoff.
- `make context` can currently report active-task ambiguity when a root-scoped maintenance task is live beside this linked feature worktree; E17-15 writes and verification must pass `TASK=E17-15` explicitly until the root MAINT row is closed by its owner.
- No E17-15 task plan or ADR has landed yet, so remote implementation should not start from memory or chat-only instructions.

## Target Outcome

This branch lands a complete, reviewed planning bundle for E17-15 on `main`: spec, ADR, and task plan. That bundle becomes the source packet for creating equivalent implementation work in `agentic-protocol-monorepo`, where the plugin generator and emitted plugin manifests are built. Once the remote plugin tree is reviewed and installable, a later slice migrates this monorepo to consume it and removes duplicated cross-harness skill surfaces.

## Context Loading

- Rules: [docs/agentic/instructions.md](../../agentic/instructions.md), [docs/agentic/rules/development-workflow.md](../../agentic/rules/development-workflow.md), [docs/agentic/rules/planning-review-guide.md](../../agentic/rules/planning-review-guide.md)
- Constitution: [docs/agentic/constitution.md](../../agentic/constitution.md)
- Spec: [docs/specs/agentic-plugin-distribution-spec.md](../../specs/agentic-plugin-distribution-spec.md)
- Related plans: [E17-12 Codex skill discoverability](./E17-12-codex-skill-discoverability-task-plan.md), [E17-13 hoisted surface cleanup](./E17-13-hoisted-surface-cleanup-task-plan.md), [E17-14 root-visible task plans](./E17-14-root-visible-task-plans-and-current-task-demotion-task-plan.md)
- Handoff/MCP state: task ref `E17-15`, planning findings, plan-analyze run, formal planning-review runs.
- External docs via `ctx7` only if live Claude/Codex plugin schema behavior is unclear during ADR or remote implementation.

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| Planning bundle | this monorepo | E17 planning artifacts live under `docs/specs/`, `docs/adrs/`, and `docs/tasks/` | add reviewed E17-15 spec, ADR, and task plan | yes; planning pipeline gates must pass | plan-analyze, planning-review, review-ready |
| Plugin manifest schema | `agentic-protocol-monorepo` | no canonical plugin manifest/generator package exists in this repo | add manifest schema and deterministic Claude/Codex plugin generator remotely | no consumer compatibility until install path is selected | remote generator tests + deterministic diff check |
| Skill body ownership | `agentic-protocol-monorepo` | cross-harness skill bodies are present in this monorepo's harness dirs | canonical bodies move remote; consumer repo stops authoring shared copies | yes; local-only overrides remain allowed | byte-identical emitted skill-body checks + harness discovery smoke |
| MCP runtime registration | existing MCP package releases and plugin manifests | this monorepo uses `uvx` package pins in `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml` | emitted plugin manifests preserve the package-pin launch form | yes; current server startup must not regress | manifest checks + MCP startup/doctor smoke |
| Consumer migration | this monorepo | shared skill/command/prompt copies are repo-local | replace with plugin pin/cache install after remote plugin tree exists | yes; branch/review/planning skills stay discoverable | `claude /skills`, Codex skill discovery, `make check-agent-workflows` |

## Proposed Solution

Deliver E17-15 in three implementation layers. First, complete the monorepo planning bundle by adding the task plan and ADR, then run the planning gates and merge it to `main`. Second, port the reviewed bundle to `agentic-protocol-monorepo` and implement the canonical plugin system there. Third, return to this monorepo for consumer migration once the remote plugin tree is available at an immutable ref.

## Files and Surfaces to Change

| Surface | File / Path | Change |
| --- | --- | --- |
| Spec | `docs/specs/agentic-plugin-distribution-spec.md` | reviewed source contract for plugin distribution |
| Task plan | `docs/tasks/17.0/E17-15-agentic-plugin-distribution-task-plan.md` | this implementation and porting plan |
| ADR | `docs/adrs/ADR-NNN-agentic-plugin-distribution.md` | decide plugin-native distribution over symlink/bootstrap model |
| Remote implementation | `agentic-protocol-monorepo/packages/agentic-system/**` | canonical skills, manifest schema, generator, emitted plugin trees, docs |
| Consumer cleanup | `.claude/skills/`, `.claude/commands/`, `.codex/prompts/`, `.claude/plugins.json` or equivalent | remove shared copies and add plugin pin after remote plugin tree exists |
| Validation docs/tests | `scripts/test_*`, `docs/agentic/**` as needed | update only when consumer migration changes local behavior |

## Related Files

| File | Note |
| --- | --- |
| `config/agent-workflows/portable_commands.json` | current shared workflow registry that remote plugin manifests must replace or consume |
| `scripts/generate_agent_workflows.py` | current generated adapter pipeline; ownership is superseded or bridged by the remote plugin generator |
| `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml` | current MCP runtime package-pin source of truth for emitted plugin `mcpServers` examples |
| `docs/agentic/instructions.md`, `CLAUDE.md`, `.github/copilot-instructions.md` | current generated/handoff instruction surfaces; Copilot remains out of plugin scope |
| `.claude/skills/`, `.claude/commands/`, `.codex/skills/`, `.codex/prompts/` | current duplicated shared skill and prompt surfaces |

## Verification Strategy

- Deterministic tests:
  - `make plan-analyze DOC=docs/specs/agentic-plugin-distribution-spec.md TASK=E17-15`
  - `make plan-review DOC=docs/specs/agentic-plugin-distribution-spec.md TASK=E17-15`
  - `make plan-analyze DOC=docs/tasks/17.0/E17-15-agentic-plugin-distribution-task-plan.md TASK=E17-15`
  - `make plan-review DOC=docs/tasks/17.0/E17-15-agentic-plugin-distribution-task-plan.md TASK=E17-15`
- Runtime-parity / environment checks:
  - remote `make plugins-build` in `agentic-protocol-monorepo` once the plan is ported
  - `claude /skills` and Codex skill discovery after this monorepo consumes the plugin tree
- Contract/fixture verification:
  - emitted manifests contain `uvx` package pins for both MCP servers
  - Claude and Codex emitted skill bodies are byte-identical
  - plugin install/uninstall leaves no orphan shared skill copies in this monorepo
- Manual verification:
  - operator can install/update the private plugin from the selected remote ref and still run `make context`, planning review, and branch review flows.

## Slice Delivery

### Slice 1: Monorepo Planning Bundle and ADR

**Goal**: Land the reviewed source packet on this repo's `main` branch so remote implementation has a durable source of truth.

Changes:

- Add this task plan and keep it linked to the E17-15 spec.
- Add ADR for the plugin-native distribution model and explicitly supersede the hoist scope's symlink + bootstrap-CLI decision.
- Run plan-analyze and planning-review for the spec, ADR, and task plan; resolve findings in MCP.
- Record task-plan path in E17-15 handoff state so the plan is root-visible.

Proof:

- Plan-analyze and planning-review runs exist for the spec and task plan with zero open planning findings.
- ADR review passes with no open planning findings.
- `make review-ready TASK=E17-15` reports ready or only code-review steps that are intentionally deferred until remote implementation.

### Slice 2: Port Reviewed Work Package to agentic-protocol-monorepo

**Goal**: Create the remote implementation task from the reviewed monorepo packet.

Changes:

- Copy or translate the reviewed spec, ADR decision, and task plan into `agentic-protocol-monorepo` planning surfaces.
- Record the source monorepo commit SHA and paths in the remote repo's task plan.
- Create the remote branch/worktree and handoff task for the plugin generator implementation.
- Re-run the remote repo's plan-analyze/planning-review equivalents if available; otherwise record a manual planning-review decision against the remote handoff state.

Proof:

- Remote task plan exists and references the monorepo source commit and E17-15 planning bundle.
- Remote handoff state identifies the plugin implementation task, branch, and worktree.
- No remote MCP server repo change is queued unless the remote plugin implementation records a concrete launch incompatibility.

### Slice 3: Remote Plugin Generator and Manifests

**Goal**: Implement the canonical plugin distribution system in `agentic-protocol-monorepo`.

Changes:

- Move or copy canonical cross-harness skill bodies to `packages/agentic-system/skills/<name>/SKILL.md`.
- Add `plugins.yaml` or equivalent registration manifest.
- Add deterministic `make plugins-build` generator for Claude and Codex plugin trees.
- Emit `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, copied skill bodies, slash-command/command mappings, and `mcpServers` entries using current package pins.
- Add docs for adding skills, adding MCP server entries, bumping plugin refs, and install/uninstall workflows.

Proof:

- Remote generator tests pass.
- `make plugins-build && git diff --exit-code dist/` is clean after a second run.
- Claude and Codex emitted skill bodies are byte-identical.
- Emitted `mcpServers` entries launch `mcp-agent-handoff==0.11.2` and `mcp-agent-orchestrator==0.4.6` through `uvx`.

### Slice 4: This Monorepo Consumer Migration

**Goal**: Replace in-repo shared skill/command/prompt copies with the private plugin install once the remote plugin tree is ready.

Changes:

- Add the minimal plugin pin/reference file required by Claude and Codex.
- Remove cross-harness shared skill bodies and generated command/prompt adapters from this monorepo, preserving project-local-only overrides if any exist.
- Update generated routing/instruction surfaces so they describe plugin consumption accurately while keeping VS Code Copilot's current non-plugin instruction path.
- Run cleanup checks for stale shared-surface duplicates.

Proof:

- `claude /skills` lists each shared skill once from the plugin cache.
- Codex skill discovery lists each shared skill once from the plugin install path.
- `make check-agent-workflows` and targeted shared-surface duplicate checks pass.
- `make context`, planning review, and branch review workflows still work after plugin installation.

## Cross-Repo Work Decomposition

This task spans more than one repository, so do not initialize all work as lanes under this monorepo task. Use this monorepo branch only for the `planning-bundle` work. After the planning bundle lands on `main`, create a separate task/branch/worktree in `agentic-protocol-monorepo` for `remote-plugin-generator`. Return to this monorepo for `consumer-migration` only after the remote plugin tree is installable from an immutable ref.

### Workstreams

| Workstream | Owning Repo | Owned Paths | Upstream Dependencies | Required Tests |
| --- | --- | --- | --- | --- |
| `planning-bundle` | this monorepo | `docs/specs/**`, `docs/adrs/**`, `docs/tasks/17.0/E17-15-*` | none | `make plan-analyze ...`, `make plan-review ...` |
| `remote-plugin-generator` | `agentic-protocol-monorepo` | `packages/agentic-system/**` | `planning-bundle` landed on main | remote `make plugins-build`, generator tests |
| `consumer-migration` | this monorepo | `.claude/**`, `.codex/**`, `.github/**`, `config/agent-workflows/**`, `docs/agentic/**` | remote plugin tree installable | `make check-agent-workflows`, harness discovery smoke |

### Merge Order

1. `planning-bundle`
2. `remote-plugin-generator`
3. `consumer-migration`

### Task Registration

- Register only `planning-bundle` under this monorepo's E17-15 task state.
- Register `remote-plugin-generator` in `agentic-protocol-monorepo` with that repo's branch/worktree and handoff state after this planning bundle lands.
- Register `consumer-migration` back in this monorepo after the remote plugin tree is available at an immutable ref.

### Orchestration Mode

- **Codex subagent**: use only inside the owning repo/worktree for each workstream.
- **Shell fallback**: create explicit linked worktrees per repo, never editing remote MCP server repos from this monorepo workspace.

---

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, spec, and handoff state before editing.
- [ ] Confirmed plugin generator work belongs in `agentic-protocol-monorepo`.
- [ ] Confirmed this monorepo owns only planning/ADR staging and later consumer cleanup.
- [ ] Confirmed remote MCP server repos do not require code changes for this task as written.

### Checklist for Slice 1: Monorepo Planning Bundle and ADR

- [ ] E17-15 spec is reviewed and has zero open planning findings.
- [ ] E17-15 task plan is reviewed and has zero open planning findings.
- [ ] ADR is authored, reviewed, and explicitly supersedes the symlink/bootstrap model.
- [ ] E17-15 handoff state records the task-plan path.
- [ ] Planning bundle lands on this repo's `main` with the source commit recorded for porting.

### Checklist for Slice 2: Port Reviewed Work Package to agentic-protocol-monorepo

- [ ] Remote planning artifact references the source monorepo commit and E17-15 paths.
- [ ] Remote task branch/worktree and handoff state are created.
- [ ] Remote planning review records any repo-specific findings before implementation starts.
- [ ] MCP server repos remain untouched unless a concrete incompatibility is recorded.

### Checklist for Slice 3: Remote Plugin Generator and Manifests

- [ ] Canonical skill bodies live under `agentic-protocol-monorepo/packages/agentic-system/skills/`.
- [ ] Plugin registration manifest is validated at load/build time.
- [ ] Claude and Codex plugin trees are emitted deterministically.
- [ ] MCP server entries preserve current `uvx` package pins.
- [ ] Plugin distribution docs cover add-skill, add-MCP-entry, version bump, install, and uninstall workflows.

### Checklist for Slice 4: This Monorepo Consumer Migration

- [ ] Plugin pin/reference is present for Claude and Codex consumption.
- [ ] Cross-harness shared skill bodies and generated adapters are removed or gitignored emitted artifacts.
- [ ] VS Code Copilot non-plugin instruction path remains intact.
- [ ] Harness discovery and workflow checks pass after plugin install.

## Review Readiness

- [ ] No remote implementation starts before the monorepo planning bundle and ADR are reviewed.
- [ ] Boundary ownership is explicit for this monorepo, `agentic-protocol-monorepo`, and remote MCP server repos.
- [ ] Verification commands prove the current `uvx` package-pin runtime path and plugin install path separately.
- [ ] Handoff decision records the planning bundle, verification, and porting target.

## Stretch Goals

- [ ] Add a small porting checklist template for future work that starts in this monorepo and moves to another repo.

## Success Criteria

- [ ] This monorepo has a reviewed E17-15 spec, ADR, and task plan on `main`.
- [ ] `agentic-protocol-monorepo` has a remote implementation task that cites the landed monorepo planning bundle.
- [ ] Remote plugin generator emits deterministic Claude and Codex plugin trees from one canonical skill body source.
- [ ] This monorepo consumes the private plugin tree and no longer authors duplicated cross-harness shared skill bodies.