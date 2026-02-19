# Agentic Documentation

Context documentation for AI coding agents working in this monorepo. These documents are designed to be human-readable **and** optimized for agent consumption.

## Structure

```
docs/agentic/
├── instructions.md                    # Cold-start document (universal rules + routing table)
├── BOOTSTRAP.md                       # Setup reference (MCP, testing commands)
├── ADR-001-face-identity-nomenclature.md  # Architecture decision record
├── contracts/                         # API contracts between services
├── diagrams/                          # Architecture diagrams (Mermaid)
├── maps/                              # Context maps (5-10 key files per domain)
├── rules/                             # Domain-specific guidelines
│   ├── frontend-guidelines.md
│   ├── backend-python-guidelines.md
│   ├── backend-php-guidelines.md
│   ├── testing-standards.md
│   ├── development-workflow.md
│   ├── branch-review-guide.md
│   ├── component-architecture-patterns.md
│   ├── RADIX_UI_COMPONENT_GUIDE.md
│   ├── roster_auto_resolve_behavior.md
│   ├── search_optimizations.md
│   └── why-identify-endpoint-exists.md
└── templates/                         # Reusable templates (CURRENT_TASK.md, etc.)
```

## Quick Start for Agents

1. Read [instructions.md](instructions.md) first -- universal rules, system overview, and role selection
2. Follow the routing table to load only the domain-specific guidelines you need
3. Use [BOOTSTRAP.md](BOOTSTRAP.md) for MCP setup and testing commands

## Directory Purposes

| Directory    | Contents                                                            |
| ------------ | ------------------------------------------------------------------- |
| `contracts/` | API schemas, endpoint documentation, security patterns              |
| `diagrams/`  | UML and architecture diagrams in Mermaid format                     |
| `maps/`      | Context maps with key entry points per domain                       |
| `rules/`     | Domain-specific guidelines, architecture rules, and workflow guides |
| `templates/` | Reusable templates for task tracking and documentation              |

## Related

- **MCP server**: [scripts/mcp/unified_server.py](../../scripts/mcp/unified_server.py) -- Code intelligence tools
- **Active tasks**: [docs/tasks/](../tasks/) -- Current implementation work
- **Templates**: [templates/](templates/) -- TASK_PLAN, EPIC, ROADMAP, and CURRENT_TASK templates
- **Epics**: [docs/epics/](../epics/) -- Bounded multi-phase capability plans with status tracking
