# Development Instructions

> **Cold-start document for coding agents.** Read this first. It contains universal rules that apply to ALL tasks, then routes you to domain-specific guidelines.

**Epic**: `docs/epics/v0.1.0/wp-sovereign-cluster-epic.md` · **Roadmap vision**: `docs/roadmaps/roadmap-v3.hybrid.md`

---

## System Overview

```mermaid
flowchart TB
    subgraph WordPress["WordPress Plugin"]
        ReactUI["React Admin UI"] --> PHPLayer["PHP REST Layer"]
    end
    subgraph Backend["Recognition Service (FastAPI)"]
        API["FastAPI Routers"] --> Services["Domain Services"]
    end
    PHPLayer -->|"HTTP + API Key"| API
    Services --> Database["PostgreSQL + pgvector"]
```

**Full diagram:** [diagrams/system-overview.mmd](diagrams/system-overview.mmd)

---

## Role Selection

Choose your domain to load targeted context. **Always load the testing guide** alongside your role guidelines — we practice TDD.

| Role                          | Context Map                                | Guidelines                                                               | Testing Guide                                              | Key Entry Points                      |
| ----------------------------- | ------------------------------------------ | ------------------------------------------------------------------------ | ---------------------------------------------------------- | ------------------------------------- |
| **Backend (Python)**          | [maps/backend.md](maps/backend.md)         | [rules/backend-python-guidelines.md](rules/backend-python-guidelines.md) | [rules/testing-python.md](rules/testing-python.md)         | `apps/prototype-description-service/` |
| **Frontend (React/TS)**       | [maps/frontend.md](maps/frontend.md)       | [rules/frontend-guidelines.md](rules/frontend-guidelines.md)             | [rules/testing-typescript.md](rules/testing-typescript.md) | `apps/prototype-wp-alt-context/js/`   |
| **PHP Plugin**                | [maps/php-plugin.md](maps/php-plugin.md)   | [rules/backend-php-guidelines.md](rules/backend-php-guidelines.md)       | [rules/testing-php.md](rules/testing-php.md)               | `apps/prototype-wp-alt-context/src/`  |
| **Cross-Service Integration** | [maps/integration.md](maps/integration.md) | [contracts/](contracts/)                                                 | [rules/testing-principles.md](rules/testing-principles.md) | `docs/agentic/contracts/`             |

### Additional Routing

| Working on...                       | Load                                                                                 |
| ----------------------------------- | ------------------------------------------------------------------------------------ |
| Writing tests (any language)        | [rules/testing-principles.md](rules/testing-principles.md) + language-specific guide |
| React/TypeScript tests (Vitest)     | [rules/testing-typescript.md](rules/testing-typescript.md)                           |
| Python tests (pytest)               | [rules/testing-python.md](rules/testing-python.md)                                   |
| PHP tests (PHPUnit)                 | [rules/testing-php.md](rules/testing-php.md)                                         |
| Workflow, commits, scaffolding      | [rules/development-workflow.md](rules/development-workflow.md)                       |
| Branch review                       | [rules/branch-review-guide.md](rules/branch-review-guide.md)                         |
| Component architecture patterns     | [rules/component-architecture-patterns.md](rules/component-architecture-patterns.md) |
| Radix UI / accessibility primitives | [rules/RADIX_UI_COMPONENT_GUIDE.md](rules/RADIX_UI_COMPONENT_GUIDE.md)               |
| Roster auto-resolve vs pending      | [rules/roster_auto_resolve_behavior.md](rules/roster_auto_resolve_behavior.md)       |
| Embedding search evolution          | [rules/search_optimizations.md](rules/search_optimizations.md)                       |
| Why /identify endpoint exists       | [rules/why-identify-endpoint-exists.md](rules/why-identify-endpoint-exists.md)       |
| Face/Identity nomenclature (ADR)    | [ADR-001-face-identity-nomenclature.md](ADR-001-face-identity-nomenclature.md)       |
| MCP tooling / testing commands      | [BOOTSTRAP.md](BOOTSTRAP.md)                                                         |

---

## Monorepo Layout

```text
context-alt-text-monorepo/
    apps/
        prototype-wp-alt-context/     # WordPress plugin (frontend + PHP)
        prototype-description-service/ # FastAPI recognition service (backend)
    packages/
        shared-contracts/             # Shared API contracts and schemas
        wp-testing-helpers/           # Test utilities
    docs/
        agentic/                      # Agent-optimized documentation
            contracts/                # API schemas and fixtures
            diagrams/                 # Architecture diagrams (Mermaid)
            maps/                     # Context maps per domain
            rules/                    # Domain-specific guidelines
            templates/                # Reusable templates
        roadmaps/                     # Project roadmaps
        tasks/                        # Task breakdowns by version
    scripts/                          # Utility scripts
```

---

## Critical Rules

These rules are **universal** and apply to every task regardless of domain.

### Plugin Boundary Rule

> **You may ONLY modify files within this monorepo.**

**Allowed paths:**

- `apps/prototype-wp-alt-context/`
- `apps/prototype-description-service/`
- `packages/`
- `docs/`
- `scripts/`

**Never modify:**

- WordPress core files (`wp-config.php`, `.htaccess`, etc.)
- LocalWP configuration
- Files in `~/Local Sites/` or any WordPress installation directory
- System configuration files

If a task seems to require external changes, STOP and propose an alternative within plugin boundaries.

### Architecture Tooling Guardrail

Do not relax or edit compliance/lint scripts (e.g., `scripts/check-architecture-compliance.js`) to silence violations. Fix the offending code or update the documented rules instead.

### Greenfield Policy

> [!IMPORTANT]
> This is a **greenfield project** with NO production users and NO existing data that must be preserved.

- **No Data Migrations**: Storage surfaces (database tables, options, caches) are disposable.
- **Baseline Only**: All schema changes must be applied directly to the baseline migration file (`apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`).
- **Clean Rewrites**: Prefer clean rewrites of logic and schema over backward-compatibility shims.
- **No Feature Flags**: Full latitude to delete experimental features. Prefer removal over long-lived feature flags.

### Remove Over Flag

Delete-over-flag is the default. Re-introduce features behind tests only when truly needed.

### Quality Gates Must Be Invocable

Every `composer`/`npm` verification gate script must be tested for invocability -- not just defined. A script that fails on invocation (wrong arguments, missing targets) rather than on real violations is invisible rot.

### No Debug Artifacts in Version Control

Do not track debug output files (`test_output.txt`, log dumps, etc.) in Git. Add them to `.gitignore`.

### Consolidated Checklists in Task Documents

All task/planning documents MUST consolidate checklists at the **bottom** of the document.

- Prevents checklist sprawl across sections
- Single source of truth for progress tracking
- **Do NOT include time estimates** on phases
- **Enforcement:** Do not scatter `- [ ]` items throughout narrative sections

### Naming Convention: acx\_\* / ACX\_\* Prefix

| Surface                        | Prefix        | Example                             |
| ------------------------------ | ------------- | ----------------------------------- |
| WordPress options/meta         | `acx_*`       | `acx_roster_entries`, `acx_version` |
| PHP constants (plugin-defined) | `ACX_*`       | `ACX_PLUGIN_FILE`, `ACX_VERSION`    |
| PHP constants (deployment)     | `ACX_*`       | `ACX_RECOGNITION_URL`               |
| REST API namespace             | `acx/v1/`     |                                     |
| PHP namespace                  | `AltContext\` |                                     |
| Text domain / slug             | `alt-context` |                                     |
| Filter hooks                   | `acx_*`       | `acx_recognition_base_url`          |

> [!WARNING]
> The `cat_*` and `alt_context_*` prefixes are **legacy**. If encountered in code or documentation, update them to `acx_*`.

---

## Core Engineering Principles

Brief summaries of mandatory principles. Full details with code examples are in the linked domain guides.

### 1. Test-Driven Development

**Red -> Green -> Refactor** for every meaningful change. Do NOT write tests just to verify you wrote the code you wrote. Full details: [rules/testing-principles.md](rules/testing-principles.md) + your language-specific guide ([TypeScript](rules/testing-typescript.md), [Python](rules/testing-python.md), [PHP](rules/testing-php.md))

### 2. Scaffolding First (MANDATORY)

Before writing any implementation or tests, scaffold all interfaces and contracts. Full details: [rules/development-workflow.md](rules/development-workflow.md#scaffolding-first-mandatory)

### 3. Small Vertical Slices

Implement only the minimum needed to make the current test pass. Avoid speculative features.

### 4. Explicit Interfaces

Introduce abstractions (providers, services, interfaces) before integrating remote or hard-to-mock concerns.

### 5. Deterministic Tests

No network calls, randomness, or time-based logic without controlled seams/mocks. Tests must produce identical results on every run.

### 6. User Consent for Remote Operations

Never call remote recognition services or sync operations without explicit user action. Provide immediate feedback on success/failure.

### 7. No Fabricated Data

Never fabricate benchmark numbers, latency claims, or metrics. If data is unavailable, return an explicit empty state or error.

### 8. No False Claims of Bug Fixes

Never claim a bug is fixed without verifying in production/staging logs. A unit test passing does NOT prove a bug is fixed in production.

### 9. Curation-First Precedence

User curation decisions are ground truth. Never use time-based heuristics to override them. The correct gate is always a **data delta**: did the underlying evidence change since the user's decision? If yes, surface as a new proposal. If no, respect the decision indefinitely.

---

## Code Style

### Package Management

- **npm** for Node.js (not pnpm)
- **Composer** for PHP

### Formatting

- 4-space indentation (PHP, TypeScript, SCSS)
- 2-space indentation (JSON, YAML, Markdown)
- Prettier for auto-formatting (frontend)
- PHP_CodeSniffer for PHP
- `ruff format` for Python

### TypeScript

- `strict: true` in tsconfig
- Arrow functions for components and utilities
- No `any` types without documented justification

### Python

- Type hints on all functions
- Google-style docstrings
- 120 character line length
- Double quotes for strings

---

## Documentation Standards

### File Organization

- Architecture docs in `docs/agentic/`
- Task breakdowns in `docs/tasks/{version}/`
- Roadmaps in `docs/roadmaps/`
- Use descriptive filenames (avoid generic `implementation-plan.md`)

### Templates

| Template                                                                 | When to Use                                                              |
| ------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| [templates/TASK_PLAN.template.md](templates/TASK_PLAN.template.md)       | New implementation plan under `docs/tasks/`                              |
| [templates/EPIC.template.md](templates/EPIC.template.md)                 | Bounded multi-phase capability epic under `docs/epics/`                  |
| [templates/ROADMAP.template.md](templates/ROADMAP.template.md)           | Multi-phase architectural roadmap under `docs/roadmaps/`                 |
| [templates/CURRENT_TASK.template.md](templates/CURRENT_TASK.template.md) | Multi-session task tracking (copy to monorepo root as `CURRENT_TASK.md`) |

### Implementation Plan Requirements

All implementation plans in `docs/tasks/` MUST use [TASK_PLAN.template.md](templates/TASK_PLAN.template.md) and include:

1. **Problem Statement** -- What user-visible behavior needs to change
2. **Current State Analysis** -- What works, what's broken, what's missing
3. **Patterns to Follow** -- Code snippets showing the pattern to implement
4. **Functions to Change** -- Table with file paths, line numbers, and specific changes
5. **Related Files** -- Complete list of files that will be touched
6. **Consolidated Task Checklist** -- Phased checkboxes at the bottom

Epics under `docs/epics/` MUST use [EPIC.template.md](templates/EPIC.template.md). Epics are bounded capabilities with phased delivery, status tracking, and links to concrete task plans.

Roadmaps under `docs/roadmaps/` MUST use [ROADMAP.template.md](templates/ROADMAP.template.md). Roadmaps describe **what** and **why**; individual phases spawn task plans for **how**.

### Mermaid Diagrams

- **`.mmd` files: raw Mermaid syntax only -- NO code fences**
- `.md` files: use fenced code blocks
- Maximum 12 classes per diagram
- Use language-agnostic types: `string`, `int`, `bool`, `array<T>`

### ASCII Only

Use ASCII characters only in documentation. No emoji. Rationale: encoding issues across terminals and CI systems.

### Internationalization

All user-facing strings through `__()`, `_x()`, `_n()` with text domain `alt-context`.

---

## Quick Reference

### Key Files

| Purpose          | Location                                               |
| ---------------- | ------------------------------------------------------ |
| Roadmap (active) | `docs/roadmaps/v0.1.0/wp-sovereign-cluster-roadmap.md` |
| Roadmap (vision) | `docs/roadmaps/roadmap-v3.hybrid.md`                   |
| API Contracts    | `docs/agentic/contracts/`                              |
| Component Guide  | `docs/agentic/rules/RADIX_UI_COMPONENT_GUIDE.md`       |
| Backend UML      | `docs/agentic/diagrams/backend-uml/`                   |
| Frontend UML     | `docs/agentic/diagrams/frontend-uml/`                  |
| Active Tasks     | `docs/tasks/`                                          |

### Getting Help

1. Check the roadmap for context on current work
2. Review existing patterns in the codebase
3. Consult architecture docs for design decisions
4. Ask for clarification before making assumptions
