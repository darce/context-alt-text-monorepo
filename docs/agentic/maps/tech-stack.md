# Tech Stack by Role

When working in a role, use ctx7 to fetch current documentation
for the listed libraries before starting implementation.

```bash
# Fetch docs for a specific library (ctx7 CLI)
ctx7 docs <library-id> "<query>"

# Example: fetch FastAPI routing docs
ctx7 library fastapi "routing and dependency injection"
```

---

## Backend (Python)

- `fastapi`
- `sqlalchemy` (2.0+)
- `pgvector` — ctx7 ID: `/pgvector/pgvector-python`
- `pydantic` (v2)
- `pytest` / `pytest-asyncio`
- `httpx`
- `ruff`
- `alembic`

## Frontend (React/TS)

- `react` (18+)
- `@tanstack/react-query` (v5)
- `@radix-ui/react-*`
- `vitest`
- `@testing-library/react`
- `vite` (5+)
- `typescript` (5.3+)

## PHP Plugin

- `phpunit` (10.5+)
- `wp-mock` — **no ctx7 coverage**; use GitHub docs at [10up/wp_mock](https://github.com/10up/wp_mock) directly
- `phpstan` (level 8)
- `wordpress-rest-api`
- `phpcs` (PSR-12 + WordPress)

## Orchestration

- `sqlite3` (FTS5)
- `fastmcp` — ctx7 ID: `/prefecthq/fastmcp`

---

## Service Map

| Service             | Local address           | Port  |
| ------------------- | ----------------------- | ----- |
| FastAPI backend     | `http://localhost:8000` | 8000  |
| PostgreSQL (local)  | `localhost:5432`        | 5432  |
| PostgreSQL (Docker) | `localhost:55432`       | 55432 |
