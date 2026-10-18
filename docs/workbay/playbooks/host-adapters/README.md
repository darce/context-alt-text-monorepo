# Host-Specific Adapter Docs

This directory contains adapter and setup guides for specific agent host runtimes. These docs are **not** canonical process truth — they explain how to operate the shared procedures documented in `../` (the parent `playbooks/` directory) on a particular platform.

## Separation from Canonical Playbooks

Canonical, agent-agnostic procedures belong in `docs/workbay/playbooks/` (the parent). When a procedure applies to all agents and human operators, it goes there. When a procedure is specific to one host runtime (e.g., Codex bootstrapping, Codex MCP attachment), it goes here.

This separation makes it possible to add adapters for future host runtimes (e.g., a non-Codex CLI runner) without polluting the shared operating procedures.

## Current Adapters

- [worktree-codex-playbook.md](worktree-codex-playbook.md): **Codex adapter** — bootstrap, execution backends, model/reasoning-effort configuration, and Codex app-server session setup. See [../worktree-orchestration-playbook.md](../worktree-orchestration-playbook.md) for the portable orchestration procedure this wraps.
- [codex-custom-mcp-playbook.md](codex-custom-mcp-playbook.md): **Codex adapter** — how to attach the `workbay-handoff-mcp` server to a Codex session over HTTP.
