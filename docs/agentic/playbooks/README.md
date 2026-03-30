# Playbooks

Operator and orchestration workflows. Playbooks are agent-agnostic by default: any agent runtime or human operator can follow them. Host-specific setup docs are classified separately below.

## Canonical Agent-Agnostic Playbooks

These documents are the portable operating procedure. Read them for shared process truth.

- [worktree-orchestration-playbook.md](worktree-orchestration-playbook.md): multi-lane worktree orchestration — task manifests, lane lifecycle, scope enforcement, health model, make commands
- [lane-scoped-context.md](lane-scoped-context.md): lane-local prompt and context rules for workers
- [ace-pruning-playbook.md](ace-pruning-playbook.md): ACE rule maintenance, evidence thresholds, pruning cadence

## Host-Specific Adapter Docs

These documents describe how to operate the above procedures on a specific host runtime. They are not canonical process truth — they are adapter/companion guides for one platform. Adapter docs live in `host-adapters/` to keep them separate from canonical playbooks and to make room for future non-Codex adapters.

- [host-adapters/worktree-codex-playbook.md](host-adapters/worktree-codex-playbook.md): **Codex adapter** — bootstrap, execution backends, model/reasoning-effort configuration, and Codex app-server session details; references `worktree-orchestration-playbook.md` for the portable procedure
- [host-adapters/codex-custom-mcp-playbook.md](host-adapters/codex-custom-mcp-playbook.md): **Codex adapter** — attach the MCP server to a Codex session over HTTP

## Ownership Rule

Skills (in `skills/`) are execution wrappers, not canonical process docs. A skill may describe how one agent runtime triggers a playbook procedure, but it must not become the only source of truth for that procedure. If a step belongs to all agents, it belongs here in a playbook.
