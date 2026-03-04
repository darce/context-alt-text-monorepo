---
description: Run all linters across the monorepo
---

**Purpose**: Run all static analysis tools (ruff, mypy, eslint, phpcs) across the codebase.

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

2. Optional: auto-fix PHP style violations (mutating)

```bash
make fix-php-style
```
