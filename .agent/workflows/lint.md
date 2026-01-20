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

1. Python linting (ruff) with correct pyenv

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/ruff check . 2>&1 | head -30
```

2. Python type checking (mypy)

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/mypy . 2>&1 | head -30
```

3. TypeScript/ESLint

```bash
cd apps/prototype-wp-alt-context && npm run lint 2>&1 | head -30
```

4. PHP static analysis

```bash
cd apps/prototype-wp-alt-context && composer phpstan 2>&1 | head -30
```
