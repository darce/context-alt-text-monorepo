---
description: Rollback last database migration
---

**Purpose**: Undo the most recent Alembic migration.

**When to use**:

- Migration caused issues
- Need to modify a migration before reapplying
- Testing rollback behavior

**Prerequisites**: PostgreSQL running, Python venv active

⚠️ WARNING: This will rollback the most recent migration. Data may be lost.

1. Show current migration

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/alembic current 2>&1
```

2. Rollback one migration (requires approval)

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/alembic downgrade -1 2>&1
```

// turbo 3. Verify new state

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/alembic current 2>&1
```
