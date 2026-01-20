---
description: Run ad-hoc SQL query via db_shell.sh
---

**Purpose**: Execute SQL queries against the development database.

**When to use**:

- Debugging data issues
- Verifying database state
- Testing queries before adding to code

**Prerequisites**: PostgreSQL running

**Usage**: Replace `<query>` with your SQL statement.

Run a SQL query against the development database. Replace `<query>` with your SQL.

1. Run query as app user (RLS-enabled)

```bash
cd apps/prototype-description-service && ./scripts/db_shell.sh -c "<query>" 2>&1
```

Or run as admin (bypasses RLS):

```bash
cd apps/prototype-description-service && ./scripts/db_shell.sh --admin -c "<query>" 2>&1
```

**Common queries:**

```sql
-- List tables
SELECT tablename FROM pg_tables WHERE schemaname = 'public';

-- Count clusters
SELECT COUNT(*) FROM identity_clusters;

-- Show tenants
SELECT id, name FROM tenants;

-- Check embeddings count
SELECT COUNT(*) FROM face_embeddings;
```
