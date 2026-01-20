---
description: Show database schema and table info
---

**Purpose**: Display database structure, table sizes, and row counts.

**When to use**:

- Understanding current schema
- Checking data distribution
- Debugging storage issues

**Prerequisites**: PostgreSQL running

// turbo-all

Show database schema information:

1. List all tables

```bash
cd apps/prototype-description-service && ./scripts/db_shell.sh --admin -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;" 2>&1
```

2. Show table sizes

```bash
cd apps/prototype-description-service && ./scripts/db_shell.sh --admin -c "SELECT relname AS table, pg_size_pretty(pg_total_relation_size(relid)) AS size FROM pg_catalog.pg_statio_user_tables ORDER BY pg_total_relation_size(relid) DESC LIMIT 10;" 2>&1
```

3. Show row counts for key tables

```bash
cd apps/prototype-description-service && ./scripts/db_shell.sh --admin -c "SELECT 'tenants' as tbl, COUNT(*) FROM tenants UNION ALL SELECT 'identity_clusters', COUNT(*) FROM identity_clusters UNION ALL SELECT 'face_embeddings', COUNT(*) FROM face_embeddings;" 2>&1
```
