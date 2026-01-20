---
description: Run Alembic database migrations
---

**Purpose**: Apply pending database migrations using Alembic.

**When to use**:

- After pulling changes with new migrations
- Testing migration scripts
- Note: Greenfield project uses baseline-only approach

**Prerequisites**: PostgreSQL running, Python venv active

Run pending database migrations:

1. Check current migration status

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/alembic current 2>&1
```

// turbo 2. Run pending migrations

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/alembic upgrade head 2>&1 | tail -20
```

// turbo 3. Show migration history

```bash
cd apps/prototype-description-service && ~/.pyenv/versions/description-service/bin/alembic history --verbose 2>&1 | head -30
```
