# Architecture Contracts Documentation

Human-readable documentation of contracts between frontend (TypeScript) and backend (PHP).

## Purpose

This directory contains **documentation for developers** explaining how shared logic works across the stack. These are narrative documents with code examples, behavior matrices, and testing guidelines.

## Contents

### Validation & Sanitization Contracts

- **`validation-logic-contract.md`** - Shared validation constants and rules

  - Timeout validation (1000-120000ms)
  - URL scheme validation (http/https)
  - Manual testing checklists
  - TypeScript/PHP implementation comparison

- **`sanitization-patterns-contract.md`** - Shared sanitization patterns
  - 7 primitive type sanitization functions
  - TypeScript/PHP behavior matrices
  - 70+ test case examples
  - Usage guidelines

### API Response Samples

- **`dashboard/coverage.json`** - Sample coverage statistics API response
- **`workbench/media.json`** - Sample media listing API response

These samples help developers understand the expected data shapes without running the full application.

## vs. `/packages/shared-contracts/`

| This Directory                   | packages/shared-contracts/                 |
| -------------------------------- | ------------------------------------------ |
| **Human-readable documentation** | **Machine-readable schemas**               |
| Markdown files with explanations | JSON Schema, OpenAPI specs                 |
| For developers to read           | For code generators to consume             |
| "Here's how validation works"    | "Here's the schema to generate types from" |

## Example

```markdown
# In this directory (docs/architecture/contracts/)

validation-logic-contract.md explains:

- Why we use these timeout values
- How TypeScript and PHP implementations differ
- Manual testing checklist for verification

# In packages/shared-contracts/

recognition.schema.json defines:

- Exact shape of recognition API payloads
- Used to generate TypeScript types and PHP DTOs
- Machine-readable, no prose
```

## Related Directories

- **`/packages/shared-contracts/`** - Machine-readable schemas for code generation
- **`/docs/architecture/rules/`** - Architecture rules and guidelines
- **`/docs/architecture/frontend-uml/`** - Component architecture diagrams

## Maintenance

When updating contracts:

1. **Update implementation** (TypeScript/PHP code)
2. **Update this documentation** (explain the change)
3. **Update schemas** in `/packages/shared-contracts/` (if applicable)
4. **Run tests** to verify alignment

## Change Log

- **2025-10-18**: Created validation-logic-contract.md and sanitization-patterns-contract.md
- **2024-Q2**: Added sample API responses (dashboard, workbench)
