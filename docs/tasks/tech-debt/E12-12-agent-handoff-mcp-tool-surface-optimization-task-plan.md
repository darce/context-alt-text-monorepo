# Task Plan

> **Metadata**
>
> - **Date**: 2026-03-30 23:45 EDT
> - **Author**: GitHub Copilot (GPT-5.4)
> - **Owning Epic**: [docs/epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md](../../../epics/v0.3.1/epic-task-reference-prefixing-and-handoff-enforcement-epic.md)
> - **Epic Short ID**: E12
> - **Review Coverage Target**: 2

---

# E12-12. Agent Handoff MCP Tool Surface Optimization

## Objective

Reduce the cognitive load of `agent-handoff-mcp` tool discovery and improve tool-selection accuracy without weakening the canonical ledger workflows. When complete, the handoff package should expose a smaller default client-facing tool profile, keep the full 27-tool surface available for explicit use, and describe tools with shorter, less repetitive definitions.

## Problem Statement

`agent-handoff-mcp` currently exposes 27 tools through a single always-on MCP surface. Claude Code's deferred-tool mechanism already mitigates raw token cost — all 27 tools appear as name-only entries in context (~280 tokens), with full JSON schemas (~3,768 tokens total) loaded on demand via `ToolSearch`. The always-loaded cost is therefore the tool-name list, not the full schema surface.

However, cognitive load remains: the model must evaluate 27 tool names on every invocation decision, and low-frequency admin tools (import/export, artifact CRUD, audit) clutter the discovery surface alongside daily-use ledger tools. The tool descriptions in `api.py` are also verbose enough that they consume more context than necessary when schemas are fetched.

The codebase already has the right structural primitives for consolidation: a single `ToolEntry` registry in `api.py`, a registry-driven CLI in `cli.py`, and transport smoke tests that enumerate the exposed tools. The gap is optimization and separation of concerns: there is no notion of a default vs extended tool profile, description text is longer than necessary for MCP discovery, and the docs are partially stale about the actual CLI surface.

## Constraints

- The canonical full handoff surface remains 27 tools; optimization must not silently delete required ledger capabilities.
- The compatibility path must remain explicit: existing operators can still opt into the full surface even if checked-in adapters move to a smaller default profile.
- `core.py` remains a pure handoff-state CRUD/re-export surface per `rg-013`; registry and profile logic belong in `api.py`, `cli.py`, `config.py`, and related docs/tests.
- The MCP contract, README, BOOTSTRAP, and checked-in client adapters must stay synchronized in the same slice when profile behavior changes.
- Greenfield policy still applies: prefer deleting stale aliases/examples over preserving misleading compatibility text.

## Workflow Principles

- Optimize for cognitive-load reduction and tool-selection accuracy, not raw token count. Claude Code's deferred-tool mechanism already provides progressive disclosure; the primary value of profiles is a cleaner discovery surface.
- Preserve one canonical registry as the source of truth; do not create a second hand-maintained list of core tools in docs or adapters.
- Keep default tool profiles aligned with actual daily workflows (`state`, findings, decisions, blockers, tests, close checks, `CURRENT_TASK.md`) and move low-frequency admin/archive surfaces behind an explicit full profile.
- Treat stale documentation as a correctness bug; the plan should leave no lane/switch/orchestration references on the handoff side.

## Terminology

- **Full profile**: The existing 27-tool `agent-handoff-mcp` MCP surface.
- **Core profile**: A smaller default subset intended for normal coding sessions and cold starts.
- **Extended/admin tools**: Lower-frequency surfaces such as import/export/archive, artifact maintenance, and audit helpers.
- **Tool definition overhead**: The token cost of tool names, descriptions, and parameter schemas injected into the client model.
- **Deferred-tool mechanism**: Claude Code's built-in progressive disclosure — tool names are always in context (~10 tokens each) but full JSON schemas are loaded on demand via `ToolSearch`.

## Current State Analysis

### Deferred-Tool Behavior (Claude Code)

Claude Code implements progressive disclosure through its deferred-tool mechanism. All `agent-handoff-mcp` tools appear as name-only entries in the context; their full JSON schemas are loaded on demand when the model calls `ToolSearch`. This means the 27-tool surface costs ~280 tokens (name list) per prompt turn, not ~3,768 tokens (full schemas). A typical session fetches 5–8 tool schemas, adding ~900 tokens on demand.

### Token Cost Measurements (This Repo)

| Metric | Full (27 tools) | Core (16 tools) | Savings |
| --- | --- | --- | --- |
| Deferred tool-name list (always in context) | ~280 tokens | ~168 tokens | ~112 tokens |
| Tool schemas (loaded on demand via ToolSearch) | ~3,768 tokens | ~2,407 tokens | ~1,360 tokens |
| Typical session cost (5–8 tools fetched) | ~280 + ~900 | ~168 + ~900 | ~112 tokens |

The profile optimization therefore provides modest token savings (~112 tokens/turn) but meaningful cognitive-load reduction: 16 names to evaluate vs 27 improves tool-selection accuracy and separates daily-use tools from admin surfaces.

### Registry and Infrastructure

- `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` already has a single lazy `ToolEntry` registry and a single `TOOL_DESCRIPTIONS` dict; this is the correct optimization seam.
- `build_handoff_mcp()` currently registers every tool returned by `_build_tool_registry()` with no profile filter, so every default client session loads the full 27-tool surface.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` already derives CLI subcommands from the same registry, which means profile metadata can be introduced without inventing a separate CLI source of truth.
- `packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py` does not currently expose a `tool_profile` setting, so client adapters cannot request a smaller MCP surface through supported configuration.
- The checked-in adapters in `.mcp.json` and `.codex/config.toml` always launch `serve-stdio` with the full surface.
- `README.md` is stale about the post-separation CLI surface: it still references removed commands such as `lane-list` and `switch`, which makes the package look broader and noisier than it is.
- The contract doc claims 27 tools in prose but the MCP Tool Surface table omits `audit_decision_ids` (exposed in both `api.py` registry and CLI). This existing contract drift must be repaired explicitly in Slice 3, not assumed correct.
- The contract does not yet define a reduced default profile or explain how clients should choose between profiles.
- `shared_tool_adapters.py` already centralizes generic tool invocation behavior; this task is about reducing tool exposure and description verbosity, not changing the transport-level call adapter.

### Alternative Paradigms Evaluated

Three alternative approaches were evaluated against the profile-based optimization:

1. **Pi-agent skill-based approach** (no MCP): 4 built-in tools + markdown skill stubs. Near-zero registration overhead but loses structured input validation, actor metadata tracking, and mandatory workflow enforcement via CLAUDE.md tool-name references. Not recommended — the deferred-tool mechanism already achieves comparable progressive disclosure.

2. **Hybrid MCP + CLI skill**: Keep 5–8 highest-frequency tools as MCP-registered, expose the remaining 19 as a CLI skill document. Comparable always-loaded cost (~268 tokens) but splits validation guarantees. Worth prototyping only if tool-selection accuracy degrades with 16+ deferred tools.

3. **MCP spec evolution**: Draft proposals for Groups (#2084), Lazy Registration (#2376), Capability Tiers (#2470), and Skills (#2167) — none merged. The profile approach is forward-compatible with Groups and Capability Tiers if adopted.

The profile-based approach (Slices 1–3) is the right near-term optimization. See "Potential Slice 4" below for conditions under which a hybrid approach would be revisited.

## Target Outcome

`agent-handoff-mcp` keeps one canonical full registry at 27 tools, but default client adapters use a smaller core profile (~16 tools, ~168 tokens in the deferred name list) that covers normal ledger workflows and omits low-frequency admin/archive surfaces unless explicitly requested. The primary benefit is cognitive-load reduction — fewer tools for the model to evaluate on each invocation — with modest token savings as a secondary effect. Tool descriptions become concise enough for MCP discovery while the richer behavioral guidance moves to the contract and README. CLI, contract, BOOTSTRAP, README, and checked-in adapters all describe the same profile-aware surface.

## Context Loading

- Rules: `docs/agentic/instructions.md`, `docs/agentic/rules/planning-review-guide.md`, `docs/agentic/rules/contract-change-checklist.md`
- Contracts: `docs/agentic/contracts/agent-handoff-mcp.md`, `docs/agentic/BOOTSTRAP.md`
- Handoff/MCP state: `E12-9` decisions for the registry-based ledger-only boundary; active task `E12-12`
- External docs via `ctx7` only if: FastMCP profile/filter behavior or tool-registration semantics require upstream verification

## Contract and Boundary Impact

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| MCP handoff tool discovery | agentic-tooling | `docs/agentic/contracts/agent-handoff-mcp.md` | Add profile-aware surface semantics and concise default-tool guidance | yes; full 27-tool profile remains available explicitly | stdio/http tool-list tests + doctor output |
| CLI/runtime configuration | agentic-tooling | `packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py` + `cli.py` | Add optional `tool_profile` config/flag/env and keep `full` behavior reachable | yes; existing launches must keep working when no profile is specified | config tests + CLI parser tests |
| Checked-in client adapters | agentic-tooling | `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`, `docs/agentic/BOOTSTRAP.md` | Point default adapters at the core profile and document full-profile opt-in | yes; adapters must stay valid for local VS Code/Codex use | adapter config review + `test_adapters.py` assertions + manual tool-list check |
| Operator/package docs | agentic-tooling | `packages/agent-handoff-mcp/README.md` | Remove stale commands and describe profile-aware usage | yes; docs must match actual CLI and tool surface | doc sync + smoke tests |

## Core Profile Baseline

The following classification is the required floor for Slice 2 acceptance. Deviations require explicit justification in the slice decision.

| Tool | Profile | Rationale |
| --- | --- | --- |
| `get_handoff_state` | core | Every session start |
| `load_session` | core | Compound session start (state + findings) |
| `set_handoff_state` | core | Task initialization and focus updates |
| `record_decision` | core | Mandatory after every code change |
| `generate_current_task_md` | core | Mandatory after every slice |
| `close_slice` | core | Compound slice completion |
| `handoff_close_check` | core | Pre-review/pre-close readiness gate |
| `record_review_finding` | core | Single finding during review |
| `batch_record_review_findings` | core | Batch findings during review |
| `list_review_findings` | core | Check open findings |
| `update_review_finding` | core | Resolve/defer findings |
| `update_next_actions` | core | Track work items |
| `report_blocker` | core | Record blockers |
| `record_test_result` | core | Verification evidence |
| `record_review_run` | core | Review pass ledger entry |
| `list_review_runs` | core | Required at review-pass start (Phase 1 of review skill) |
| `get_review_coverage` | extended | Low-frequency review meta |
| `list_next_actions` | extended | Usually covered by `get_handoff_state` |
| `audit_decision_ids` | extended | Compliance audit; not daily use |
| `export_handoff_state` | extended | Admin / inter-workspace transfer |
| `import_handoff_state` | extended | Admin / inter-workspace transfer |
| `archive_task_state` | extended | Post-completion cleanup |
| `record_artifact` | extended | Sidecar artifact indexing |
| `search_artifacts` | extended | Sidecar artifact search |
| `get_artifact` | extended | Sidecar artifact read |
| `purge_artifacts` | extended | Sidecar artifact maintenance |
| `search_handoff` | extended | Ad hoc keyword search |

Core profile count: **16**. Extended: **11**. Full: **27**.

## Proposed Solution

Introduce explicit tool-profile metadata into the existing handoff registry, shorten MCP descriptions to compact discovery text, and route checked-in adapters to a smaller core profile while preserving a full-profile escape hatch. Keep the registry as the only source of truth: MCP registration, CLI exposure, doctor reporting, docs, and tests should all derive from the same metadata so the optimization does not create new drift.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/api.py` | Add profile metadata to `ToolEntry`, shorten MCP descriptions, filter tool registration by profile, and teach doctor to report profile-aware counts |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/config.py` | Add `tool_profile` runtime configuration with env/arg support |
| backend | `packages/agent-handoff-mcp/src/agent_handoff_mcp/cli.py` | Expose profile-aware serve/doctor behavior while preserving registry-driven CLI derivation |
| tests | `packages/agent-handoff-mcp/tests/test_config.py` | Add runtime-config coverage for tool-profile selection |
| tests | `packages/agent-handoff-mcp/tests/test_cli.py` | Add parser/CLI-profile coverage |
| tests | `packages/agent-handoff-mcp/tests/test_stdio.py` | Assert core-profile tool listing is reduced and full profile remains 27 tools |
| tests | `packages/agent-handoff-mcp/tests/test_http.py` | Mirror profile-aware tool-list verification over HTTP |
| docs | `docs/agentic/contracts/agent-handoff-mcp.md` | Document profile semantics, default adapter behavior, and concise tool-surface guidance |
| docs | `docs/agentic/BOOTSTRAP.md` | Update adapter examples and operator guidance for core vs full profile |
| docs | `packages/agent-handoff-mcp/README.md` | Remove stale commands and describe the optimized calling surface accurately |
| tooling | `.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml` | Point default adapters at the core profile |
| tests | `packages/agent-handoff-mcp/tests/test_adapters.py` | Update serve-stdio argv assertions for profile-aware adapter launches |

## Related Files

| File | Note |
| --- | --- |
| `packages/agent-handoff-mcp/src/agent_handoff_mcp/shared_tool_adapters.py` | Generic call adapter already exists; verify this task does not duplicate invocation logic here |
| `packages/agent-handoff-mcp/tests/test_stdio.py` | Existing source of truth for exposed MCP tool names |
| `packages/agent-handoff-mcp/tests/test_http.py` | Existing source of truth for HTTP transport tool enumeration |
| `packages/agent-handoff-mcp/tests/test_cli.py` | Existing source of truth for serve-http and parser behavior |
| `docs/tasks/12.0/12.1/E12-9-orchestration-physical-separation-task-plan.md` | Confirms handoff CLI is ledger-only and must stay that way |

## Verification Strategy

- Deterministic tests:
  - `cd /Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp && pyenv exec python -m pytest tests/test_config.py tests/test_cli.py tests/test_stdio.py tests/test_http.py -q`
- Runtime-parity / environment checks:
  - `cd /Users/daniel/Development/context-alt-text-monorepo/packages/agent-handoff-mcp && pyenv exec python -m pytest tests/test_cli.py -q`
  - `cd /Users/daniel/Development/context-alt-text-monorepo && pyenv exec python -m agent_handoff_mcp --workspace-root "$PWD" doctor`
- Contract/fixture verification:
  - Full profile still reports 27 tools
  - Core profile reports a reduced surface and includes the required daily-use ledger tools
  - Stale README command examples are removed or replaced with valid ledger-only commands
- Manual verification:
  - Validate that the checked-in `altcontext-mcp` adapter loads the core profile by default and that a full-profile launch remains possible with an explicit flag/env override

## Slice Delivery

### Slice 1: Registry Compression and Tool Taxonomy

**Goal**: Make the canonical registry small enough and structured enough to support profile-aware exposure.

Changes:

- Replace long MCP discovery descriptions with shorter, non-redundant text while preserving richer operator guidance in docs.
- Extend `ToolEntry` with explicit surface metadata (`core` vs `extended`/`admin`) and, if useful, a lightweight tool-kind classification for docs/doctor output.
- Keep `_build_tool_registry()` as the single source of truth for MCP tool exposure. Note: `_build_cli_registry()` appends two intentional CLI-only extras (`artifact-list`, `artifact-terms`) that have custom arg shapes and are not part of the MCP registry. These are exempt from profile metadata but must be documented in the CLI surface table.

Proof:

- Registry tests/assertions show every tool has a declared profile and full-profile count remains 27.

### Slice 2: Profile-Aware MCP Exposure and Adapter Wiring

**Goal**: Let clients load a smaller default handoff surface without losing access to the full registry.

Changes:

- Add `tool_profile` to `RuntimeConfig`, CLI flags, and any supported env var path.
- Teach `build_handoff_mcp()` and doctor/tool-list probes to respect the selected profile.
- Update `.mcp.json`, `.vscode/mcp.json`, and `.codex/config.toml` so the checked-in default adapters use the core profile.
- Update `tests/test_adapters.py` serve-stdio argv assertions for profile-aware adapter launches.

Proof:

- stdio/http smoke tests verify the core profile exposes a reduced tool set and full profile remains available at 27 tools.

### Slice 3: Doc and Calling-Surface Synchronization

**Goal**: Make the optimized tool surface understandable and drift-free for operators and agents.

Changes:

- Update `agent-handoff-mcp` contract, BOOTSTRAP, and README to describe the new profile semantics and the actual ledger-only CLI surface.
- Remove or replace the entire **Multi-Worktree Workflow** section and **Tool Surface** list from README: these sections reference `lane-upsert`, `lane-report`, `lane-report-list`, `lane-activity`, `lane-message`, `lane-message-update`, `lane-message-list`, `lane-list`, and `switch` — none of which exist in the current `_build_tool_registry()` after the E12-9 orchestration split. Replace them with accurate ledger-only CLI examples derived from the registry `cli_name` fields, plus the two CLI-only extras (`artifact-list`, `artifact-terms`) which are intentionally outside the MCP registry.
- Add tests or doctor assertions where needed so profile counts and docs do not drift again.
- Resolve **E12-12-REV-01**: `generate_current_task_md`'s `related_task_refs` parameter was removed (always-global behavior adopted in E12-11). Confirm the MCP contract and docstring reflect the new always-global cross-task findings behavior and the parameter is no longer advertised.
- Repair existing contract drift: add `audit_decision_ids` to the MCP Tool Surface table in `docs/agentic/contracts/agent-handoff-mcp.md` and verify the table row count matches the actual 27-tool registry.

Proof:

- Contract/README/BOOTSTRAP examples match the actual CLI and transport behavior; targeted docs/tests pass.
- README Multi-Worktree Workflow and Tool Surface sections are removed or replaced with ledger-only equivalents.
- E12-12-REV-01 is closed as fixed.

### Slice 4: Hybrid CLI Skill for Extended Tools (Deferred)

**Status**: Deferred pending evidence. Only proceed if Slices 1–3 prove insufficient.

**Goal**: Replace MCP registration for the 11 extended tools with a CLI skill document, achieving full 27-tool access with a smaller MCP footprint.

**Trigger criteria** (all must apply):
- Session-level profiling shows tool-selection accuracy degrades with 16+ deferred tools.
- The MCP spec does not adopt Groups or Capability Tiers within the next 2–3 months.
- New tools are added that would push the core profile beyond 20 tools.

**Scope if adopted**:

1. Create `packages/agent-handoff-mcp/SKILL-handoff-extended.md` documenting CLI invocations for the 11 extended tools.
2. Add a Claude Code skill stub (in `.claude/skills/`) that references the skill file.
3. Remove the 11 extended tools from the MCP registry entirely (not just profile-gated).
4. Update CLAUDE.md to reference CLI commands for extended operations.
5. Verify that actor metadata propagation works for CLI-invoked tools.

**Estimated cost**: ~168 tokens (core MCP names) + ~100 tokens (skill stub) = ~268 tokens always-loaded, with access to all 27 capabilities via bash.

**Tradeoffs vs profile-only approach**:

| Factor | Profile approach (Slices 1–3) | Hybrid approach (Slice 4) |
| --- | --- | --- |
| Implementation complexity | Low | Medium (new skill file, CLI docs, testing) |
| Token overhead (deferred list) | ~168 tokens | ~268 tokens |
| Access to extended tools | Requires `--tool-profile full` restart | Available via bash in any session |
| Structured validation | All tools have schemas | Only core tools have schemas |
| Actor metadata tracking | Automatic for all tools | Only core; CLI calls need manual `--actor` flags |
| Mandatory workflow enforcement | CLAUDE.md rules reference MCP tool names | Harder to enforce for CLI-invoked tools |

---

# Consolidated Checklist

## Context and Ownership

- [ ] Loaded the minimum authoritative rules, contracts, and handoff state before editing.
- [ ] Confirmed whether external dependency context requires `ctx7`.
- [ ] Recorded boundary ownership and compatibility expectations for MCP discovery, CLI/config, and checked-in client adapters.

## Slice 1: Registry Compression and Tool Taxonomy

- [ ] Add profile metadata to the canonical `ToolEntry` registry.
- [ ] Shorten MCP discovery descriptions without losing correctness.
- [ ] Capture proof that the full profile remains 27 tools.

## Slice 2: Profile-Aware MCP Exposure and Adapter Wiring

- [ ] Add runtime/CLI support for selecting a tool profile.
- [ ] Filter MCP registration and doctor/tool-list reporting by profile.
- [ ] Update checked-in adapters (`.mcp.json`, `.vscode/mcp.json`, `.codex/config.toml`) to use the core profile by default.
- [ ] Update `test_adapters.py` serve-stdio argv assertions for profile-aware launches.
- [ ] Capture profile-aware stdio/http verification evidence.

## Slice 3: Doc and Calling-Surface Synchronization

- [ ] Update the handoff contract, BOOTSTRAP, and README for the profile-aware surface.
- [ ] Remove or replace the Multi-Worktree Workflow section and Tool Surface list in README (9 stale commands: lane-upsert, lane-report, lane-report-list, lane-activity, lane-message, lane-message-update, lane-message-list, lane-list, switch).
- [ ] Keep CLI/runtime examples and doctor expectations aligned with the selected profile behavior.
- [ ] Resolve E12-12-REV-01: confirm `generate_current_task_md` docstring and contract reflect always-global cross-task findings; `related_task_refs` is removed from signature and docs.
- [ ] Repair contract drift: add `audit_decision_ids` to the MCP Tool Surface table and verify 27-row parity with the live registry.

## Review Readiness

- [ ] No boundary-touching implementation is left without matching contract/doc/fixture evidence.
- [ ] Runtime-parity checks are included where tests can mask real behavior.
- [ ] Handoff decision records the change, verification, and any contract implications.

## Stretch Goals

- [ ] Add per-profile doctor output that groups tools by action/query/generator to make future surface audits cheaper.

## Success Criteria

- [ ] The checked-in default `altcontext-mcp` adapter exposes a reduced core tool profile while the full 27-tool profile remains explicitly available.
- [ ] Tool descriptions and docs are concise, accurate, and free of stale CLI references.
- [ ] MCP tool discovery, doctor output, and docs all derive from the same registry/profile metadata without drift. CLI behavior derives from the same registry plus two documented CLI-only extras (`artifact-list`, `artifact-terms`).