---
description: Run Python unit tests with coverage summary
---

**Purpose**: Run Python unit tests (fast, no database required).

**When to use**:

- After implementing new features
- Verifying test baseline before changes
- Quick feedback during TDD cycle

**Prerequisites**: Python venv active (`pyenv shell description-service`)

// turbo-all

Run backend unit tests with coverage:

1. Activate pyenv and run pytest

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/pytest recognition/tests/unit/ -v --tb=short 2>&1 | tail -50
```

2. Show test count summary

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/pytest recognition/tests/unit/ --collect-only -q 2>&1 | tail -10
```
