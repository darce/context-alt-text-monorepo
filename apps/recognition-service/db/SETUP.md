# Database Setup Requirements

**Last Updated:** 2025-11-02

## Prerequisites

- **PostgreSQL 17+** (tested with 17.0)
- **pgvector extension 0.8.1+** (HNSW support required)

This service requires PostgreSQL with the pgvector extension for native vector similarity search. SQLite and other databases are not supported.

---

## Installation

### macOS (Homebrew)

```bash
# Install PostgreSQL 17 and pgvector
brew install postgresql@17 pgvector

# Add to PATH (add to ~/.zshrc for persistence)
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

# Start PostgreSQL service
brew services start postgresql@17

# Verify installation
psql --version  # Should show PostgreSQL 17.x
```

### Linux (Ubuntu/Debian)

```bash
# Add PostgreSQL APT repository
sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh

# Install PostgreSQL 17
sudo apt-get update
sudo apt-get install -y postgresql-17

# Install pgvector
sudo apt-get install -y postgresql-17-pgvector

# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Verify
psql --version
```

### Docker (Recommended for Development)

```bash
# Use official pgvector image with PostgreSQL 17
docker pull pgvector/pgvector:pg17

# Start container
docker run -d \
  --name recognition_db \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=recognition \
  -p 5432:5432 \
  pgvector/pgvector:pg17

# Verify
docker exec recognition_db psql -U postgres -d recognition -c "SELECT version();"
```

---

## Database Creation

### Create Database and Enable Extensions

```bash
# Create database
createdb recognition

# Enable required extensions
psql -d recognition << EOF
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOF
```

### Verify Extensions

```sql
-- Check pgvector version (should be 0.8.1+)
SELECT * FROM pg_extension WHERE extname = 'vector';

-- Verify vector operations work
SELECT '[1,2,3]'::vector <-> '[3,2,1]'::vector AS cosine_distance;
```

Expected output:

```
 extname | extversion
---------+------------
 vector  | 0.8.1
(1 row)

 cosine_distance
-----------------
        0.285714
(1 row)
```

---

## Apply Migrations

```bash
cd apps/recognition-service

# Set database URL
export DATABASE_URL="postgresql://localhost:5432/recognition"

# Apply all migrations
alembic upgrade head

# Verify tables created
psql -d recognition -c '\dt'
```

Expected tables:

- `tenants`
- `roster_entries`
- `reference_embeddings`
- `augmented_embeddings`
- `alembic_version`

---

## Configuration

### Environment Variables

Create `.env` file in `apps/recognition-service/`:

```bash
# Database (REQUIRED)
DATABASE_URL=postgresql://localhost:5432/recognition

# Connection pooling
DB_POOL_MIN=2
DB_POOL_MAX=10
DB_POOL_TIMEOUT=30

# pgvector tuning (adjust as corpus grows)
HNSW_M=16
HNSW_EF_CONSTRUCTION=64

# Tenant ID (optional, defaults to 'default')
TENANT_ID=default
```

### Database URL Formats

```bash
# Local (default user)
DATABASE_URL=postgresql://localhost:5432/recognition

# Local (specific user/password)
DATABASE_URL=postgresql://user:password@localhost:5432/recognition

# Docker container
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/recognition

# Remote with SSL (production)
DATABASE_URL=postgresql://user:password@host.com:5432/recognition?sslmode=require
```

---

## Verification

### Check Database Schema

```sql
-- List all tables
\dt

-- Verify HNSW index on roster_entries
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'roster_entries'
  AND indexname = 'idx_roster_embedding_hnsw';

-- Check vector column types
\d+ roster_entries
\d+ reference_embeddings
\d+ augmented_embeddings
```

### Test Vector Operations

```sql
-- Insert test data
INSERT INTO tenants (id, slug, name, plan_tier)
VALUES (gen_random_uuid(), 'test', 'Test Tenant', 'free');

-- Vector similarity search (should execute without errors)
SELECT id, label, aggregate_embedding <-> '[0.1,0.2,...]'::vector(512) AS distance
FROM roster_entries
ORDER BY distance
LIMIT 5;
```

---

## Performance Tuning

### HNSW Index Parameters

```sql
-- Adjust index parameters for larger datasets
-- m: number of connections per layer (16 = balanced, 32 = high recall)
-- ef_construction: build-time search depth (64 = default, 128 = high quality)

CREATE INDEX idx_roster_embedding_hnsw ON roster_entries
USING hnsw (aggregate_embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

### Connection Pooling

For production, use pgBouncer or adjust pool settings:

```bash
DB_POOL_MIN=5
DB_POOL_MAX=20
DB_POOL_TIMEOUT=30
```

---

## Troubleshooting

| Issue                                      | Solution                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------- |
| `CREATE EXTENSION vector` fails            | Install pgvector: `brew install pgvector` or `apt-get install postgresql-17-pgvector` |
| `relation "roster_entries" does not exist` | Run migrations: `alembic upgrade head`                                                |
| `HNSW index not used in queries`           | Check index exists: `\di+ idx_roster_embedding_hnsw`                                  |
| Slow vector searches                       | Increase `HNSW_M` or create HNSW index if missing                                     |
| Connection pool exhausted                  | Increase `DB_POOL_MAX` or add pgBouncer                                               |
| `DATABASE_URL not set`                     | Export in shell or add to `.env` file                                                 |

---

## Production Deployment

### Managed PostgreSQL Services

Recommended providers with pgvector support:

- **Supabase** - Built-in pgvector (PostgreSQL 15+)
- **Neon** - Serverless PostgreSQL with pgvector (16+)
- **AWS RDS** - Enable via parameter groups (15+)
- **Google Cloud SQL** - pgvector available (15+)
- **Azure Database** - Flexible Server with pgvector (16+)

### Setup Checklist

- [ ] Provision PostgreSQL 17+ instance
- [ ] Enable pgvector extension in database
- [ ] Create database user with appropriate permissions
- [ ] Configure SSL/TLS for connections
- [ ] Set up automated backups (PITR recommended)
- [ ] Configure connection pooling (pgBouncer)
- [ ] Set `DATABASE_URL` in deployment environment
- [ ] Run `alembic upgrade head` from CI/CD pipeline
- [ ] Monitor query performance (pg_stat_statements)
- [ ] Set up alerts for connection pool saturation

---

## References

- [pgvector Documentation](https://github.com/pgvector/pgvector)
- [PostgreSQL 17 Release Notes](https://www.postgresql.org/docs/17/release-17.html)
- [HNSW Algorithm Paper](https://arxiv.org/abs/1603.09320)
- Project Performance Targets: `docs/performance/targets.md`
