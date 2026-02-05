# Agentic Documentation

Context documentation for AI coding agents working in this monorepo. These documents are designed to be human-readable **and** optimized for agent consumption.

## Structure

```
docs/agentic/
├── BOOTSTRAP.md      # Quick start for agents (read first)
├── instructions.md   # Full development guidelines
├── contracts/        # API contracts between services
├── diagrams/         # Architecture diagrams (Mermaid)
├── maps/             # Context maps (5-10 key files per domain)
├── rules/            # Additional guidelines and patterns
└── templates/        # Reusable templates (CURRENT_TASK.md, etc.)
```

## Quick Start for Agents

1. Read [BOOTSTRAP.md](BOOTSTRAP.md) first for routing
2. Select your domain from the context maps in [maps/](maps/)
3. Follow the development rules in [instructions.md](instructions.md)

## Directory Purposes

| Directory | Contents |
|-----------|----------|
| `contracts/` | API schemas, endpoint documentation, security patterns |
| `diagrams/` | UML and architecture diagrams in Mermaid format |
| `maps/` | Context maps with key entry points per domain |
| `rules/` | Component patterns, UI guidelines |
| `templates/` | Reusable templates for task tracking and documentation |

## Related

- **Slash commands**: [.agent/workflows/](../../.agent/workflows/) — Executable workflows
- **MCP server**: [scripts/mcp/unified_server.py](../../scripts/mcp/unified_server.py) — Code intelligence tools
- **Active tasks**: [docs/tasks/](../tasks/) — Current implementation work
- **Session state**: Use [templates/CURRENT_TASK.template.md](templates/CURRENT_TASK.template.md) for multi-session tasks
