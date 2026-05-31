# AltContext Monorepo

AI-powered alternative text generation for WordPress media, with facial recognition and roster management.

![PHP](https://img.shields.io/badge/PHP-8.2%2B-777BB4) ![WordPress](https://img.shields.io/badge/WordPress-6.0%2B-21759B) ![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB) ![Node](https://img.shields.io/badge/Node-22%2B-339933)

---

## Monorepo Structure

```text
context-alt-text-monorepo/
    apps/
        prototype-wp-alt-context/       # WordPress plugin (PHP + TypeScript/React)
        prototype-description-service/  # Recognition service (Python FastAPI + InsightFace)
    packages/
        shared-contracts/               # JSON schemas for cross-service types
    docs/
        agentic/                        # Agent-optimized docs (instructions, rules, contracts, diagrams)
        roadmaps/                       # Project roadmaps (v0.1.0 active, v3 vision, v4 placeholder)
        tasks/                          # Task breakdowns by version
        literature/                     # Reference materials
    scripts/
        mcp/                            # MCP server for agentic development
```

---

## Quick Start

### WordPress Plugin

```bash
cd apps/prototype-wp-alt-context
npm ci && composer install
npm run dev
```

See [apps/prototype-wp-alt-context/README.md](apps/prototype-wp-alt-context/README.md)

### Recognition Service

```bash
cd apps/prototype-description-service
uv sync --locked --extra dev
make serve
```

See [apps/prototype-description-service/README.md](apps/prototype-description-service/README.md)

---

## Prerequisites

- Node.js >= 22.18.0
- npm 11.x
- PHP >= 8.2 + Composer
- Python >= 3.12
- uv
- WordPress >= 6.0 (LocalWP recommended)

---

## Testing

```bash
# WordPress plugin
cd apps/prototype-wp-alt-context
composer test          # PHPUnit
npm run test           # Vitest

# Recognition service
cd apps/prototype-description-service
make test              # pytest
```

---

## Development Workflow

- Branch from `main`: `feature/<description>`, `fix/<description>`, `docs/<description>`
- [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`
- AI agents start at [docs/agentic/instructions.md](docs/agentic/instructions.md)
- The canonical `workstate-handoff-mcp` and `workstate-orchestrator-mcp` packages now live outside this monorepo; this workspace consumes them as external dependencies during the extraction rollout.

---

## Documentation

| Purpose                 | Location                                                     |
| ----------------------- | ------------------------------------------------------------ |
| Agent cold-start        | [docs/agentic/instructions.md](docs/agentic/instructions.md) |
| Agent setup/MCP         | [docs/agentic/BOOTSTRAP.md](docs/agentic/BOOTSTRAP.md)       |
| API contracts           | [docs/agentic/contracts/](docs/agentic/contracts/)           |
| Architecture diagrams   | [docs/agentic/diagrams/](docs/agentic/diagrams/)             |
| Active roadmap (v0.1.0) | [docs/roadmaps/v0.1.0/](docs/roadmaps/v0.1.0/)               |
| Roadmap overview        | [docs/roadmaps/](docs/roadmaps/)                             |

---

## License

MIT -- see [LICENSE](LICENSE).
