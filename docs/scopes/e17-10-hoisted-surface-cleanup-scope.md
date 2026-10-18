# E17-10 Hoisted Surface Cleanup — Scope Note

- **Date**: 2026-04-23
- **Status**: intake complete; ready for task-plan drafting
- **Source TODO**: `TODO(E17-10-POST-MVP-CLEANUP)` in `docs/agentic/rules/development-workflow.md`
- **Intake decision**: this cleanup is intentionally pulled forward into its own task **before** E17-10 MVP closure so publication/validation concerns and monorepo-cleanup concerns stay separate

## Objective

Make the root monorepo consume the extracted standalone repos as the canonical implementation surfaces, then incrementally remove duplicated monorepo-owned copies once equivalent functionality from the external repos has been confirmed.

This is not an audit-only task. The MVP of this cleanup task is **both**:

1. switch monorepo consumption to the external `darce/*` hoisted-family repos where those repos are now canonical, and
2. clean duplicated root-repo surfaces out of the monorepo once parity is confirmed.

## External Repo Family

The hoisted family has four canonical external repos:

- `darce/mcp-agent-handoff` — canonical extracted repo for the handoff MCP package
- `darce/mcp-agent-orchestrator` — canonical extracted repo for the orchestrator MCP package
- `darce/agentic-system` — canonical shared surface repo for skills, hooks, prompts, commands, workflow generators, and agentic-only contracts
- `darce/agentic-bootstrap` — canonical bootstrap CLI repo for installing/updating the shared surface and MCP harness config in consumers

The `mcp-` prefix belongs to the MCP server repos. `agentic-system` and `agentic-bootstrap` are part of the same hoisted external family but are not MCP servers.

## Hard Prerequisites

- All four external repos must be reachable over SSH before deletion slices begin.
- `darce/agentic-bootstrap` must contain a publishable bootstrap package at the tag/ref the monorepo will consume. If the current GitHub repo only contains a README or the expected `v0.2.0` package tag is missing, the task plan must first recover, republish, or otherwise make bootstrap consumable before any slice depends on it.
- Any external repo consumed by the monorepo must have a concrete install or clone ref recorded in the task plan before local duplicates are removed.

## Scope

All root-repo surfaces that belong in the external hoisted repos are in scope.

Target families include:

- duplicated MCP package surfaces under `packages/`
- root scripts that only exist to support extracted MCP/runtime behavior
- shared agentic surfaces in the root repo that now belong with `darce/agentic-system`
- local harness/runtime wiring, CI, docs, and config that still resolve against monorepo-owned copies instead of the external repos

The core cleanup rule is:

- **externalize first, then delete**
- no monorepo surface is removed until the replacement behavior from the external repo has been confirmed working

## Current-State Inventory

Candidate removal or migration surfaces include:

- `packages/agent-handoff-mcp/` — duplicated handoff MCP implementation now owned by `darce/mcp-agent-handoff`; remove only after monorepo tests/runtime use the external install path.
- `packages/agent-orchestrator-mcp/` — duplicated orchestrator MCP implementation now owned by `darce/mcp-agent-orchestrator`; remove only after lane/review/orchestrator flows use the external install path.
- `scripts/mcp/mcp-server.sh` — monorepo-local compatibility shim for the installed handoff entrypoint; remove or justify once local tests/config no longer need it.
- `.claude/skills/` — shared skills that should come from `darce/agentic-system` unless they are monorepo-local overrides.
- `.github/hooks/` and `scripts/hooks/` — shared harness hooks that should come from `darce/agentic-system` unless they are monorepo-local overrides.
- `.github/prompts/`, `.claude/commands/`, and `config/agent-workflows/` — shared prompt/command/workflow surfaces that should come from `darce/agentic-system`.
- `docs/agentic/contracts/` — split surface: agentic-only contracts should be consumed from `darce/agentic-system`; alt-context-specific contracts remain in this monorepo.
- `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`, CI workflows, Makefiles, and package tests — wiring/proof surfaces that must stop depending on local duplicated package source before deletion.

This inventory is a candidate list, not permission to delete everything at once. The task plan must give each deletion a verification gate.

## Consumption Mechanism

Default consumption mechanism:

- MCP packages install from the `mcp-*` external repos using pinned `git+ssh://` refs or another explicitly documented package ref.
- Shared skills/hooks/contracts/prompts/commands/workflows are installed through `agentic-bootstrap`, which clones `darce/agentic-system` and manages the overlay/manifest.

Fallback if `agentic-bootstrap` is not publishable at plan-execution time:

- bootstrap publication/recovery becomes the first blocking slice; or
- the task plan may use a temporary direct clone/symlink proof for `darce/agentic-system`, but only as a transitional bridge with an explicit removal condition once bootstrap is publishable.

## Verification Contract

Each deletion slice must prove equivalent behavior from the external repo before deleting the local copy:

1. Install or clone the external repo into a scratch environment from the exact ref the monorepo will consume.
2. Run an external-repo-owned smoke or test command against the installed package/surface.
3. Run the monorepo consumer flow against the external install/overlay with the local duplicate absent or ignored.
4. Confirm local harness configs, tests, and runtime commands no longer import or execute through the deleted monorepo source path.

Blocking failures:

- external package install/import failure
- missing console script or bootstrap command required by monorepo runtime
- monorepo test/runtime failures that are caused by the externalization
- any fallback to the deleted local package or script path

Allowed deferred cleanup:

- historical docs that reference old paths but are clearly archived
- monorepo-specific wrappers that remain intentionally transitional and have a follow-up removal condition
- unrelated test failures already tracked outside the cleanup slice

## Contract Split Decision

The E17-10 follow-on contract split remains binding:

- agentic-only contracts move to or are consumed from `darce/agentic-system`
- alt-context-specific contracts stay in this monorepo

This cleanup task should remove local duplication for the agentic-only contracts once bootstrap/overlay consumption is proven. It must not delete alt-context-specific contracts just because they live under `docs/agentic/contracts/`.

## Constitution and Rule Migration

The cleanup task must include a workstream for constitution/rule migration before deleting package paths referenced by active rules.

At minimum, the task plan must audit and update references in:

- `docs/agentic/instructions.md`
- `docs/agentic/rules/development-workflow.md`
- `docs/agentic/contracts/harness-protocol.yaml`
- rule/contract references to package-local paths such as `packages/agent-handoff-mcp/` and `packages/agent-orchestrator-mcp/`

Rules such as `rg-013` and `rg-014` must keep their architectural intent while pointing at the external package boundary or a validated consumer-facing path.

## Relationship to E17-10 Follow-On

This scope builds on the E17-10 follow-on publication/validation work, especially:

- external repo publication and tag reconciliation for `darce/mcp-agent-handoff`, `darce/mcp-agent-orchestrator`, and `darce/agentic-system`
- Slice 4 cross-repo cleanup that removed monorepo-internal files from the standalone repos
- real-consumer validation proving the install path works outside this monorepo

Ordering:

- this cleanup must not duplicate Slice 4's external-repo cleanup work
- this cleanup may begin before E17-10 MVP closure, but only after the external repo refs it consumes are reachable and validated
- if any follow-on publication evidence is missing or contradicted by current remote state, the cleanup plan must pause at a prerequisite slice rather than deleting local monorepo surfaces

## Completion Signals

All of the following must be true for the task to close:

1. The monorepo consumes the external repos as the canonical runtime/source boundary rather than relying on duplicated local implementation surfaces.
2. No root-repo scripts remain that are only compatibility shims for extracted MCP behavior unless they are still required and explicitly justified.
3. Tests, harness configs, and runtime flows pass without local package-source coupling to the duplicated monorepo copies.

## Migration Strategy

Cleanup should be aggressive in direction but incremental in execution:

- aim for **full removal** of duplicated monorepo surfaces
- remove them slice by slice, not in one risky sweep
- confirm preserved functionality at each boundary before deleting the local copy
- prefer thin temporary wrappers only when they materially reduce migration risk; wrappers are transitional, not the target state

## Not-Doing

- No deletion of a monorepo surface before external-repo functionality has been confirmed.
- No assumption that MVP must close before this cleanup starts; this task is intentionally separate and earlier.
- No "audit only" outcome as the final deliverable; the task must drive real cleanup, not just inventory drift.
- No consumer-repo cleanup as part of this task unless a monorepo-side proof requires bounded validation there.
- No retagging or republishing external repos unless the cleanup uncovers a real missing capability that must be fixed upstream first.
- No deletion of alt-context-specific contracts as part of agentic-system cleanup.

## Assumptions

- The external standalone repos are already intended to be the canonical homes for the hoisted family, subject to current-state verification before deletion.
- The monorepo may still temporarily act as the source of truth for some shared surfaces during migration, but the goal of this task is to shrink that responsibility.
- Some root-repo files may survive the cleanup if they are still genuinely monorepo-specific rather than duplicated extracted functionality.

## Success Criteria

- Monorepo runtime/config/test paths resolve against the external repos wherever those repos are the intended canonical home.
- Duplicated monorepo surfaces are removed incrementally with explicit proof that functionality is preserved after each removal.
- Remaining root-repo surfaces have a clear ownership boundary: either monorepo-specific, or intentionally transitional with follow-up removal tracked.
- The old `TODO(E17-10-POST-MVP-CLEANUP)` can be replaced by concrete task-plan slices with explicit deletion gates and verification steps.