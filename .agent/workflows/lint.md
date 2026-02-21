---
description: Run all linters across the monorepo
---

**Purpose**: Run all static analysis tools (ruff, mypy, eslint, phpstan) across the codebase.

**When to use**:

- Before committing changes
- After refactoring to catch issues
- Diagnosing type errors or style violations

**Prerequisites**: Node modules installed (`npm install`), Python venv active

// turbo-all

Run linters for all languages:

1. Run root Makefile lint-all (handles Python, TS, and PHP)

```bash
make lint-all
```
