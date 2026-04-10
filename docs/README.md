# Documentation Hub

Monorepo-level documentation for the Alt Context project.

## Quick Navigation

| Audience | Start Here |
|----------|-----------|
| AI agents | [agentic/instructions.md](agentic/instructions.md) -- cold-start document |
| Agent setup/MCP | [agentic/BOOTSTRAP.md](agentic/BOOTSTRAP.md) |
| Humans planning work | [epics/README.md](epics/README.md) and [tasks/README.md](tasks/README.md) |
| Plugin developers | [../apps/prototype-wp-alt-context/docs](../apps/prototype-wp-alt-context/docs) |
| Backend developers | [../apps/prototype-description-service/README.md](../apps/prototype-description-service/README.md) |

## Directory Structure

```
docs/
    README.md                 # This file
    agentic/                  # Live agent/operator rules, contracts, maps, diagrams
    epics/                    # Multi-slice planning by release line
    tasks/                    # Task plans and investigations
    roadmaps/                 # Higher-level product/architecture direction
    deferred-features/        # Intentionally postponed scope
    research/                 # Research notes, evaluations, crosswalks
    archive/                  # Retrospectives and superseded operational material
    literature/               # Imported external reference material
```

## What Goes Where

- **Live operating guidance** -- `docs/agentic/`
- **Forward-looking planning** -- `docs/epics/`, `docs/tasks/`, `docs/roadmaps/`, `docs/deferred-features/`
- **Research and comparison notes** -- `docs/research/`
- **Historical retrospectives and superseded docs** -- `docs/archive/`
- **Assessments and investigations** -- `docs/assessments/`
- **Specs** -- `docs/specs/`
- **Architecture Decision Records** -- `docs/adrs/`
- **Imported external materials** -- `literature/` (top-level, gitignored)
- **Machine-readable schemas** -- `packages/shared-contracts/`
- **Plugin-specific docs** -- `apps/prototype-wp-alt-context/`
- **Service-specific docs** -- `apps/prototype-description-service/`
- **API contract changes** -- update both `docs/agentic/contracts/` and `packages/shared-contracts/`
