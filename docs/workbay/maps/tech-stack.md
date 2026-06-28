# Tech Stack by Role

When working in a role, review current documentation for the listed
libraries before starting implementation.

---

## Backend (Python)

- `fastapi`
- `sqlalchemy` (2.0+)
- `pgvector`
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
- `wp-mock` — use GitHub docs at [10up/wp_mock](https://github.com/10up/wp_mock) directly
- `phpstan` (level 8)
- `wordpress-rest-api`
- `phpcs` (PSR-12 + WordPress)

## Orchestration

- `sqlite3` (FTS5)
- `fastmcp`

---

## Service Map

| Service             | Local address           | Port  |
| ------------------- | ----------------------- | ----- |
| FastAPI backend     | `http://localhost:8000` | 8000  |
| PostgreSQL (local)  | `localhost:5432`        | 5432  |
| PostgreSQL (Docker) | `localhost:55432`       | 55432 |
