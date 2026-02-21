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

1. Run root Makefile check-all (handles all languages: Python, TS, PHP)

```bash
make check-all
```
