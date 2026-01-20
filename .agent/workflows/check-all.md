---
description: Run full CI check (lint + types + tests)
---

**Purpose**: Run complete CI validation pipeline before committing.

**When to use**:

- Before creating a PR or pushing
- After major refactoring
- Verifying all checks pass

**Prerequisites**: All dependencies installed (Python venv, npm, composer)

Run complete CI validation before committing:

1. Python checks via Makefile (handles pyenv)

```bash
cd apps/prototype-description-service && make check 2>&1 | tail -30
```

// turbo 2. Frontend TypeScript check

```bash
cd apps/prototype-wp-alt-context && npm run typecheck 2>&1 | tail -20
```

// turbo 3. Frontend tests

```bash
cd apps/prototype-wp-alt-context && npm run test -- --run 2>&1 | tail -30
```

// turbo 4. PHP static analysis

```bash
cd apps/prototype-wp-alt-context && composer phpstan 2>&1 | tail -20
```
