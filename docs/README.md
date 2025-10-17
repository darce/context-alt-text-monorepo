# Documentation Hub

Welcome to the Context Alt Text Monorepo documentation! This directory contains **monorepo-level documentation** covering architecture, system design, and cross-cutting concerns.

---

## 📚 Quick Navigation

### Getting Started

- **[Getting Started](getting-started.md)** - New contributor onboarding guide
- **[WordPress Plugin README](../apps/wp-context-alt-text/README.md)** - Plugin quick start
- **[Recognition Service README](../apps/recognition-service/README.md)** - Recognition service setup

### Architecture & Design

- **[Architecture Overview](architecture/)** - System design documents
  - [Backend UML](architecture/backend-uml/) - Recognition service diagrams
  - [Frontend UML](architecture/frontend-uml/) - WordPress plugin diagrams
  - [Contracts](architecture/contracts/) - API contracts between services
  - [Engineering Rules](architecture/rules/) - Principles, tasks, roadmaps

### WordPress Plugin Docs

- **[Configuration Guide](../apps/wp-context-alt-text/docs/configuration.md)** - Environment profiles, deployment
- **[Development Guide](../apps/wp-context-alt-text/docs/development.md)** - Contributing, testing, code standards
- **[API Reference](../apps/wp-context-alt-text/docs/api-reference.md)** - REST API endpoints
- **[Troubleshooting](../apps/wp-context-alt-text/docs/troubleshooting.md)** - Common issues

### Agentic Development

- **[Prompts Index](PROMPTS_INDEX.md)** - Quick links for AI agents
- **[Instructions](architecture/rules/instructions.md)** - Engineering principles
- **[Tasks](architecture/rules/tasks.md)** - Current sprint backlog

### Reference Materials

- **[Literature](literature/)** - Technical books and references
- **[WordPress Plugin Development Digest](wp-plugin-literature-digest.md)** - WP development guide

---

## 🎯 What Goes Where?

### Monorepo-Level Docs (Here)

- ✅ **System Architecture** - How services interact
- ✅ **API Contracts** - Shared contracts between services
- ✅ **Development Workflow** - Branching, commits, PRs
- ✅ **Cross-Cutting Concerns** - Security, performance patterns

### Project-Specific Docs

**WordPress Plugin** (`apps/wp-context-alt-text/docs/`):
- Configuration, development, API reference, troubleshooting

**Recognition Service** (`apps/recognition-service/`):
- Setup, usage, deployment (in README)

**Rule of Thumb:** If it's specific to one project, it goes in that project's docs. If it's architectural or cross-cutting, it belongs here.

---

## 🗺️ Directory Structure

```
docs/
├── README.md                      # This file - navigation hub
├── getting-started.md            # New contributor onboarding
├── PROMPTS_INDEX.md              # Agentic development index
├── wp-plugin-literature-digest.md # WordPress development references
│
├── architecture/                 # System design & architecture
│   ├── backend-uml/             # Recognition service diagrams
│   ├── frontend-uml/            # WordPress plugin diagrams
│   ├── contracts/               # API contracts
│   └── rules/                   # Engineering principles, tasks, roadmaps
│       ├── instructions.md      # Engineering principles
│       ├── tasks.md             # Current sprint backlog
│       ├── roadmap-v3.md        # MVP roadmap
│       └── ...
│
└── literature/                   # Reference materials
    ├── WordPress plugin Development.epub
    ├── WordPress Plugin Development Cookbook.epub
    └── extracted/               # Extracted book content
```

---

## 🚀 First Time Here?

1. **New to the project?** Start with [getting-started.md](getting-started.md)
2. **Working on WordPress plugin?** See [apps/wp-context-alt-text/README.md](../apps/wp-context-alt-text/README.md)
3. **Working on recognition service?** See [apps/recognition-service/README.md](../apps/recognition-service/README.md)
4. **Working with AI agent?** Check [PROMPTS_INDEX.md](PROMPTS_INDEX.md)
5. **Need architecture overview?** Browse [architecture/](architecture/)

---

## 🤝 Contributing to Docs

When updating documentation:

- **Monorepo concerns** → Update files in this directory
- **Plugin-specific** → Update `apps/wp-context-alt-text/docs/`
- **Service-specific** → Update `apps/recognition-service/README.md`
- **API changes** → Update both API reference and contracts
- **Architecture changes** → Update UML diagrams and design docs

---

Need help? Check [GitHub Discussions](https://github.com/darce/context-alt-text-monorepo/discussions) or open an issue!
