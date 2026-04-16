# Hoist Agentic System (Skills + MCP Servers) to Remote Repo — Scope Note

- **Date**: 2026-04-16
- **Owning Epic**: TBD (E17 follow-on candidate: E17-9; plausibly its own epic E18 given breadth)
- **Status**: intake — awaiting task-plan drafting

## Objective

Make the agentic system — skills, hooks, contracts, `agent-handoff-mcp`, and `agent-orchestrator-mcp` — consumable by *other* projects via a versioned install path, so the same workflow discipline (skills, hooks, MCP state, review gates) can be propagated without copying source trees by hand.

## Install Model (decided)

**Hybrid**:

- MCP servers ship as **pip packages** with pinned versions (consumer gets code-loaded Python behind a version bound).
- Skills, hooks, and contracts ship via a **bootstrap CLI** that clones the remote repo and **symlinks** `.claude/skills/`, `.github/hooks/`, and `docs/agentic/contracts/` into the consumer repo. Keeps skill bodies live-editable and diff-visible in the consumer's git history when needed.

## Override Model (decided)

**Overlay with project-local precedence**:

- Shared skills/hooks come from the symlinked remote surface.
- The consumer project may add `local/` counterparts that take precedence over shared when both exist.
- Contract validators (`check-skills`, `check-harness-sync`) resolve the overlay and validate the effective surface, not the raw shared tree.

## MVP Success Signal (decided)

**Versioning + release cadence is demonstrated**: a minor version bump of one MCP package **plus** a change to one skill propagate cleanly through the documented update workflow into a consumer without manual file copying. Proves the *update pipeline* works, not just the first install.

## Open Questions for the Task Plan

(User chose "Decide in the plan" for topology; these are explicit planning-phase decisions, not intake-phase.)

- **Repo topology**: umbrella repo vs extending `darce/mcp-agent-handoff` + new orchestrator + new skills/hooks repo vs folding everything into `darce/mcp-agent-handoff`. Trade-offs to analyze in the plan.
- **Package index**: private PyPI? `git+ssh://...` direct installs? Local wheel mirror? Something else?
- **Version sync strategy**: do MCP packages and the skills/hooks bundle share a single version line, or do they version independently with compatibility constraints?
- **Overlay resolver home**: new utility module, or absorbed into `check-skills`/`check-harness-sync` directly?
- **Handoff DB scoping**: with MCP servers shared across projects, does each consumer get its own handoff DB file path, or is DB location per-project config?
- **Bootstrap CLI distribution**: is the CLI itself a pip package, a shell script vendored into the remote, or a one-liner `curl | bash`-style installer?

## Not-Doing (decided)

- **Open-sourcing / external publication** — first pass is private Daniel-owned repos only. Public packaging, licensing, CONTRIBUTING docs, badges, and social announcements are deferred to a later epic.

## Not Explicitly Excluded (but flagged)

The user did NOT mark the following as out-of-scope during intake — so they may be in-scope, but they are load-bearing enough that the task plan must make deliberate decisions:

- **Migrating / restructuring `darce/mcp-agent-handoff`**: in scope for the topology analysis. Repo surgery is a real possibility, not a side quest.
- **Changing MCP server behavior or schema**: distribution-infrastructure-only is the preferred stance, but if any MCP surface change is required to support multi-project consumption (e.g., configurable DB path, per-project namespacing), the plan must call it out explicitly and justify it relative to E17-7's handoff evolution work.
- **Changing skill bodies during the hoist**: minor edits may be needed to adapt skills to an overlay-aware path layout. Substantive skill rewrites should not happen as part of the hoist.

## Success Criteria

- MVP: one MCP package minor-version bump + one skill update propagate end-to-end via the documented update workflow to a consumer project with no manual file copying.
- Check gates: `check-skills` and `check-harness-sync` run against the overlay-resolved surface and report correctly on shared-only, local-only, and overlapping cases.
- Documentation: one canonical `consumer-setup.md` that another project can follow without reading the plan itself.

## Sequencing

- Independent of E17-8 (branch-isolation edit guard) — they touch different surfaces and can land in parallel.
- Requires E17-6 Phase 3 core (skills anatomy, harness-protocol.yaml, check-skills validator) as a prerequisite — the contract-driven validators are what make overlay resolution tractable.
- E17-7 handoff schema evolution (multi-active-task registry) is NOT a hard prerequisite but materially improves the consumer story; flag the dependency trade-off in the plan.

## Assumptions

- User intends this as a new epic *or* E17-9; plan drafting should confirm before claiming an id.
- `darce/mcp-agent-handoff` continues to be the canonical home for `agent_handoff_mcp`; its location vs a new umbrella repo is a topology question for the plan.
- Consumer projects will be in the same ownership/trust boundary as this monorepo (no open-source hardening required in the MVP).
