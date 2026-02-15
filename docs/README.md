# Documentation Hub

Monorepo-level documentation for the Alt Context project.

## Quick Navigation

| Audience | Start Here |
|----------|-----------|
| AI agents | [agentic/instructions.md](agentic/instructions.md) -- cold-start document |
| Agent setup/MCP | [agentic/BOOTSTRAP.md](agentic/BOOTSTRAP.md) |
| Plugin developers | [../apps/prototype-wp-alt-context/README.md](../apps/prototype-wp-alt-context/README.md) |
| Backend developers | [../apps/prototype-description-service/README.md](../apps/prototype-description-service/README.md) |

## Directory Structure

```
docs/
    README.md                 # This file
    agentic/                  # Agent-optimized documentation hub
        instructions.md       # Cold-start document (rules + routing)
        BOOTSTRAP.md          # MCP tooling, testing commands
        ADR-001-*.md          # Architecture decision records
        contracts/            # API contracts (human-readable)
        diagrams/             # Architecture diagrams (Mermaid)
            backend-uml/
            frontend-uml/
        maps/                 # Context maps per domain
        rules/                # Domain-specific guidelines
        templates/            # Reusable templates (TASK_PLAN, ROADMAP, CURRENT_TASK)
    roadmaps/                 # Project roadmaps
    tasks/                    # Task breakdowns by version
    literature/               # Reference materials
```

## What Goes Where

- **Agent/architecture docs** -- `docs/agentic/`
- **Machine-readable schemas** -- `packages/shared-contracts/`
- **Plugin-specific docs** -- `apps/prototype-wp-alt-context/`
- **Service-specific docs** -- `apps/prototype-description-service/`
- **API contract changes** -- update both `docs/agentic/contracts/` and `packages/shared-contracts/`

