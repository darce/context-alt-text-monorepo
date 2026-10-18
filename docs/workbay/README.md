# Agentic Documentation

Start here: [instructions.md](instructions.md)

## Doc Layer Ownership

Three distinct layers exist in this directory. Each has a different owner and audience.

| Layer | Path | Role | Agent-agnostic? |
| --- | --- | --- | --- |
| **Rules** | `rules/` | Mandatory invariants and gates. What must always happen. | Yes |
| **Playbooks** | `playbooks/` | Canonical operating procedures. How to operate within the rules. | Yes |
| **Skills** | `skills/` | Host-specific execution wrappers. How one agent runtime loads and applies a playbook. | No — agent-specific |

Canonical process truth lives in rules and playbooks. Skills are thin adapters: they decide when to trigger a procedure and how to execute it in a specific host runtime (e.g. Codex, VS Code Copilot). A skill must point to the canonical playbook or rule rather than duplicating process detail. If a skill becomes the only source of truth for a process, that is a maintenance risk.

Host-specific setup docs (e.g. Codex MCP attachment) are adapter guides, not canonical playbooks. They live in `playbooks/` with a clear host-specific classification rather than as shared procedures.

## Key Entry Points

- [instructions.md](instructions.md): cold-start guide for agents
- [BOOTSTRAP.md](BOOTSTRAP.md): MCP setup, install, and verification
- [contracts/](contracts/): boundary and tool contracts
- [maps/](maps/): current architecture and component maps
- [rules/](rules/): operating rules and review guidance
- [templates/](templates/): planning and handoff templates

## Supporting Reference

- [adrs/](adrs/README.md): architectural decision records
- [playbooks/](playbooks/README.md): operator workflows and orchestration guides
- [diagrams/](diagrams/README.md): Mermaid/UML diagrams
- [skills/](skills/): agent-specific execution wrappers (not canonical process docs)
