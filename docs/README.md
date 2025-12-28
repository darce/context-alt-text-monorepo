# Documentation Hub

Welcome to the Context Alt Text Monorepo documentation! This directory contains **monorepo-level documentation** covering architecture, system design, and cross-cutting concerns.

---

## 📚 Quick Navigation

### Getting Started

- **[Getting Started](getting-started.md)** - New contributor onboarding guide
- **[WordPress Plugin README](../apps/prototype-wp-alt-context/README.md)** - Plugin quick start
- **[Recognition Service README](../apps/prototype-description-service/README.md)** - Recognition service setup

### Agentic Development (AI Agents Start Here)

- **[BOOTSTRAP.md](agentic/BOOTSTRAP.md)** - 🚀 Single entry point for coding agents
- **[Instructions](agentic/instructions.md)** - Engineering principles & standards
- **[Context Maps](agentic/maps/)** - Domain-specific file references
- **[Contracts](agentic/contracts/)** - API contracts between services
- **[Diagrams](agentic/diagrams/)** - Architecture diagrams (Mermaid)

### Architecture & Design

- **[Architecture Overview](architecture/)** - System design documents
  - [ADR-001](architecture/ADR-001-face-identity-nomenclature.md) - Face identity nomenclature
  - [Roadmaps](roadmaps/) - Project roadmaps

### Reference Materials

- **[Literature](literature/)** - Technical books and references
- **[WordPress Plugin Development Digest](wp-plugin-literature-digest.md)** - WP development guide

---

## 🎯 What Goes Where?

### Agentic Docs (`docs/agentic/`)

- ✅ **BOOTSTRAP.md** — Agent entry point
- ✅ **instructions.md** — Engineering principles
- ✅ **contracts/** — API contracts (human-readable)
- ✅ **diagrams/** — Architecture diagrams (Mermaid)
- ✅ **maps/** — Context maps for each domain

### Machine-Readable Schemas (`packages/shared-contracts/`)

- ✅ **JSON Schemas** — For code generation (TS, PHP, Python)
- ✅ **Sample payloads** — Example request/response data

### Project-Specific Docs

**WordPress Plugin** (`apps/prototype-wp-alt-context/`):

- Plugin-specific README and inline docs

**Recognition Service** (`apps/prototype-description-service/`):

- Service-specific README and inline docs

---

## 🗺️ Directory Structure

```
docs/
├── README.md                     # This file - navigation hub
├── getting-started.md            # New contributor onboarding
├── wp-plugin-literature-digest.md # WordPress development references
│
├── agentic/                      # 🤖 AI agent documentation hub
│   ├── BOOTSTRAP.md              # Single entry point for agents
│   ├── instructions.md           # Engineering principles & standards
│   ├── contracts/                # API contracts (human-readable)
│   ├── diagrams/                 # Architecture diagrams
│   │   ├── system-overview.mmd
│   │   ├── backend-uml/
│   │   └── frontend-uml/
│   ├── maps/                     # Context maps per domain
│   │   ├── backend.md
│   │   ├── frontend.md
│   │   ├── php-plugin.md
│   │   └── integration.md
│   ├── rules/                    # Additional guidelines
│   └── blackboard/               # Agent working memory
│
├── architecture/                 # Architecture decisions
│   └── ADR-001-*.md              # Decision records
│
├── roadmaps/                     # Project roadmaps
│
└── literature/                   # Reference materials
```

---

## 🚀 First Time Here?

1. **New to the project?** Start with [getting-started.md](getting-started.md)
2. **AI Agent?** Go to [agentic/BOOTSTRAP.md](agentic/BOOTSTRAP.md)
3. **Working on WordPress plugin?** See [apps/prototype-wp-alt-context/README.md](../apps/prototype-wp-alt-context/README.md)
4. **Working on recognition service?** See [apps/prototype-description-service/README.md](../apps/prototype-description-service/README.md)
5. **Need architecture overview?** See [agentic/diagrams/system-overview.mmd](agentic/diagrams/system-overview.mmd)

---

## 🤝 Contributing to Docs

When updating documentation:

- **Agentic/architecture** → Update files in `docs/agentic/`
- **Plugin-specific** → Update `apps/prototype-wp-alt-context/`
- **Service-specific** → Update `apps/prototype-description-service/`
- **API changes** → Update `docs/agentic/contracts/` and `packages/shared-contracts/`
- **Diagram changes** → Update `docs/agentic/diagrams/`
