---
description: Reset dev database to clean state (DESTRUCTIVE)
---

**Purpose**: Drop and recreate the development database with fresh schema.

**When to use**:

- After schema changes to baseline migration
- Database is in inconsistent state
- Starting fresh test cycle

**Prerequisites**: PostgreSQL running, no active connections to dev DB

⚠️ WARNING: This will DROP and recreate the development database. All data will be lost.

1. Confirm database reset (requires user approval)

```bash
echo "This will DROP and recreate the development database."
echo "Press Ctrl+C to cancel, or wait 3 seconds to continue..."
sleep 3
```

// turbo 2. Run the reset script

```bash
cd apps/prototype-description-service && ./scripts/reset_dev_db.sh 2>&1 | tail -30
```

// turbo 3. Verify database connection

```bash
cd apps/prototype-description-service && ./scripts/db_shell.sh --admin -c "SELECT COUNT(*) FROM tenants;" 2>&1
```
