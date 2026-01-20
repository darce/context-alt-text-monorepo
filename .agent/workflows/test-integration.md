---
description: Run integration tests requiring database
---

**Purpose**: Run integration tests that verify database interactions, RLS policies, and repository patterns.

**When to use**:

- After database schema changes
- Testing repository implementations
- Verifying RLS policy behavior

**Prerequisites**: PostgreSQL running with test database, Python venv active

Run backend integration tests (requires PostgreSQL):

1. Check database connection using db_shell.sh

```bash
cd apps/prototype-description-service && ./scripts/db_shell.sh --admin -c "SELECT 1 as db_ok;" 2>&1 || echo "❌ Database not available - start PostgreSQL first"
```

// turbo 2. Run integration tests with correct pyenv

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/pytest recognition/tests/integration/ -v --tb=short 2>&1 | tail -50
```
