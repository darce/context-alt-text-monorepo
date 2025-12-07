# Getting Started - Context Alt Text Monorepo

Welcome to the Context Alt Text Monorepo! This guide will help you get started contributing to the project.

## Table of Contents

- [Monorepo Overview](#monorepo-overview)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Development Workflow](#development-workflow)
- [Documentation Organization](#documentation-organization)
- [Contributing](#contributing)

---

## Monorepo Overview

The Context Alt Text project is a monorepo containing multiple packages and applications:

```
context-alt-text-monorepo/
├── apps/
│   ├── recognition-service/     # Python FastAPI service for face recognition
│   └── wp-context-alt-text/      # WordPress plugin (main application)
├── packages/
│   ├── shared-contracts/         # Shared TypeScript/JSON schemas
│   └── wp-testing-helpers/       # WordPress testing utilities
├── docs/                         # Monorepo-level documentation
│   ├── architecture/            # System design, UML diagrams, contracts
│   ├── literature/              # Reference materials
│   └── PROMPTS_INDEX.md         # Agentic development prompts
├── scripts/                      # Monorepo-level scripts
└── tools/                        # Development tools
```

---

## Quick Start

### Prerequisites

- **Node.js** >= 22.18.0
- **PHP** >= 8.2
- **Python** >= 3.10 (for recognition service)
- **Composer** >= 2.0
- **WordPress** >= 6.0 (LocalWP recommended)
- **Git**

### Clone & Setup

```bash
git clone https://github.com/darce/context-alt-text-monorepo.git
cd context-alt-text-monorepo
```

**Then choose your focus:**

- 📖 **WordPress Plugin:** [`apps/wp-context-alt-text/README.md`](../apps/wp-context-alt-text/README.md)
- 📖 **Recognition Service:** [`apps/recognition-service/README.md`](../apps/recognition-service/README.md)
- 📖 **Quick Start Commands:** See [monorepo README](../README.md#-quick-start)

---

## Project Structure

### Applications (`apps/`)

#### `recognition-service/`

Python FastAPI service providing face recognition using InsightFace models.

- **Technology:** Python 3.10+, FastAPI, InsightFace, w600k_r50 model
- **Purpose:** AI-powered face detection and recognition
- **Deployment:** Hugging Face Spaces, Docker, or local development
- **Documentation:** [`apps/recognition-service/README.md`](../apps/recognition-service/README.md)

**Architecture Note:** The recognition service uses a **Face → Identity nomenclature boundary**:

| Layer          | Nomenclature            | Purpose                              |
| -------------- | ----------------------- | ------------------------------------ |
| Infrastructure | `Face*`                 | InsightFace-specific detection code  |
| Domain         | `*Identity`             | Technology-agnostic clustering logic |
| Seam           | `to_media_identities()` | Transformation point                 |

This allows swapping detection providers (InsightFace → ArcFace, MediaPipe) without changing domain logic. See [ADR-001](architecture/ADR-001-face-identity-nomenclature.md) for details.

#### `wp-context-alt-text/`

WordPress plugin for managing alternative text with AI assistance.

- **Technology:** PHP 8.2+, TypeScript, React 19, Vite 7
- **Purpose:** WordPress plugin for alt text management
- **Deployment:** WordPress plugins directory or custom hosting
- **Documentation:** [`apps/wp-context-alt-text/README.md`](../apps/wp-context-alt-text/README.md)

---

### Packages (`packages/`)

#### `shared-contracts/`

Shared API contracts and types between services.

- **Purpose:** Type safety across service boundaries
- **Format:** TypeScript interfaces, JSON schemas
- **Usage:** Import into WordPress plugin and recognition service

#### `wp-testing-helpers/`

WordPress testing utilities and mocks.

- **Purpose:** Reusable test utilities for WordPress development
- **Usage:** Import into WordPress plugin tests

---

### Documentation (`docs/`)

#### Monorepo-Level Documentation

Located in `docs/` at the root:

- **Purpose:** Architecture, cross-cutting concerns, agentic development
- **Audience:** Contributors, architects, AI agents
- **Focus:** System design, contracts, development workflows

**Key Files:**

- [`docs/getting-started.md`](.) - This file! Monorepo onboarding
- [`docs/PROMPTS_INDEX.md`](PROMPTS_INDEX.md) - Agentic development prompts
- [`docs/architecture/`](architecture/) - System design documents, UML diagrams

#### Project-Specific Documentation

Located in each project:

- **WordPress Plugin:** `apps/wp-context-alt-text/docs/`
- **Recognition Service:** `apps/recognition-service/README.md`

---

## Development Workflow

### Branching Strategy

```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Create bugfix branch
git checkout -b fix/bug-description

# Create documentation branch
git checkout -b docs/documentation-update
```

### Commit Convention

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add roster import from CSV
fix: resolve recognition timeout issue
docs: update configuration guide
test: add tests for RecognitionSettings
refactor: simplify observation matching logic
chore: update dependencies
```

### Pull Request Process

1. **Create feature branch** from `main`
2. **Make changes** following code standards
3. **Add tests** for new functionality
4. **Update documentation** if needed
5. **Run tests** and ensure they pass
6. **Create pull request** with description
7. **Address review feedback**
8. **Merge** when approved

---

## Documentation Organization

The monorepo uses a **two-level documentation structure**:

### Level 1: Monorepo Documentation (`docs/`)

**Purpose:** Cross-cutting concerns, architecture, system design

**What belongs here:**

- ✅ System architecture (UML diagrams, component diagrams)
- ✅ API contracts between services
- ✅ Monorepo-level scripts and tools
- ✅ Agentic development prompts and rules
- ✅ Literature and reference materials
- ✅ Contributor onboarding (this file!)

**What doesn't belong here:**

- ❌ Project-specific how-to guides
- ❌ API endpoint documentation (belongs in project docs)
- ❌ Troubleshooting for specific projects

---

### Level 2: Project Documentation

**WordPress Plugin** (`apps/wp-context-alt-text/docs/`):

- [`README.md`](../apps/wp-context-alt-text/README.md) - Quick start, focused entry point (~400 lines)
- [`docs/configuration.md`](../apps/wp-context-alt-text/docs/configuration.md) - Environment profiles, settings
- [`docs/development.md`](../apps/wp-context-alt-text/docs/development.md) - Contributing, testing, code standards
- [`docs/api-reference.md`](../apps/wp-context-alt-text/docs/api-reference.md) - REST API documentation
- [`docs/troubleshooting.md`](../apps/wp-context-alt-text/docs/troubleshooting.md) - Common issues and solutions

**Recognition Service** (`apps/recognition-service/`):

- [`README.md`](../apps/recognition-service/README.md) - All documentation in main README

---

### Industry Standard Practices

This organization follows **industry-standard patterns**:

**Similar to:**

- **Express.js** - README (~300 lines) + detailed docs in /docs/
- **React Router** - README (~200 lines) + API docs, guides, examples
- **Vue.js** - README (quick start) + comprehensive /docs/ directory
- **Next.js** - README (overview) + /docs/ with deep-dive guides

**Best Practices:**

- ✅ README is a **doorway** (quick start, links to detailed docs)
- ✅ Detailed docs live in `/docs/` directory
- ✅ Related topics consolidated (configuration, development, API, troubleshooting)
- ✅ Monorepo docs separate from project docs
- ✅ Documentation scales as project grows

---

## Contributing

### First-Time Contributors

1. **Read this guide** (you're doing it!)
2. **Choose a project** (WordPress plugin or recognition service)
3. **Set up development environment** (see Quick Start above)
4. **Read project-specific docs** (README + docs/ directory)
5. **Find an issue** labeled [`good-first-issue`](https://github.com/darce/context-alt-text-monorepo/labels/good-first-issue)
6. **Ask questions** in GitHub Discussions

### Regular Contributors

1. **Check** [`docs/PROMPTS_INDEX.md`](PROMPTS_INDEX.md) for agentic development rules
2. **Review** architecture docs before making structural changes
3. **Update** documentation when changing public APIs
4. **Add** tests for all new functionality
5. **Follow** code standards (PSR-12 for PHP, TypeScript strict mode)

---

## Architecture Overview

### System Components

The Context Alt Text system consists of three main components that work together:

1. **WordPress Plugin** - Admin UI for managing alt text and roster entries
2. **REST API** - Bridges WordPress and the recognition service
3. **Recognition Service** - Python FastAPI service with InsightFace AI

**📖 Detailed architecture diagrams:** [`docs/architecture/`](architecture/)

**Key Interactions:**

- WordPress admin UI calls REST API endpoints
- REST API communicates with recognition service
- Recognition service analyzes images, returns observations
- WordPress stores observations and roster entries
- UI displays results and allows roster management

---

## Testing

All projects include comprehensive test suites. See project-specific documentation for detailed testing guides:

### WordPress Plugin

- **PHP Tests:** `composer test` (163 tests, 653 assertions)
- **TypeScript Tests:** `npm run test`
- **Documentation:** [`apps/wp-context-alt-text/docs/development.md#testing`](../apps/wp-context-alt-text/docs/development.md#testing)

### Recognition Service

- **Python Tests:** `pytest` with coverage
- **Documentation:** [`apps/recognition-service/README.md`](../apps/recognition-service/README.md)

---

## Common Tasks

### Adding a New Feature

1. **Design** - Sketch architecture, update UML if needed
2. **Implement** - Code in appropriate project
3. **Test** - Add unit and integration tests
4. **Document** - Update README and relevant docs
5. **Review** - Create PR, address feedback

### Updating API Contracts

1. **Update** `packages/shared-contracts/`
2. **Update** WordPress plugin to use new contract
3. **Update** recognition service to use new contract
4. **Update** API documentation
5. **Test** integration between services

### Deploying Changes

**WordPress Plugin:**

- Build assets: `npm run build`
- Deploy to WordPress hosting
- Update version number

**Recognition Service:**

- Deploy to Hugging Face Space
- Update environment variables
- Test health endpoint

---

## Support

- **Issues:** [GitHub Issues](https://github.com/darce/context-alt-text-monorepo/issues)
- **Discussions:** [GitHub Discussions](https://github.com/darce/context-alt-text-monorepo/discussions)
- **Documentation:** This guide and project-specific docs
- **Questions:** Open a discussion or ask in PR comments

---

## Next Steps

**For WordPress Plugin Development:**

- 📖 Read [`apps/wp-context-alt-text/README.md`](../apps/wp-context-alt-text/README.md)
- 📖 Review [`apps/wp-context-alt-text/docs/development.md`](../apps/wp-context-alt-text/docs/development.md)

**For Recognition Service Development:**

- 📖 Read [`apps/recognition-service/README.md`](../apps/recognition-service/README.md)

**For Architecture/Design:**

- 📖 Explore [`docs/architecture/`](architecture/)
- 📖 Review [`docs/PROMPTS_INDEX.md`](PROMPTS_INDEX.md) for agentic development

---

Welcome to the project! 🎉
