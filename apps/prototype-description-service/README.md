# Prototype Description Service

This directory contains the experimental rewrite scaffolding for the description service.  
It uses a hexagonal-inspired layout with explicit application layers and HTTP interface adapters.

## Running the API

```bash
cd apps/prototype-description-service
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn api.main:app --reload
```

### Available health endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Aggregated status for every subsystem. |
| `GET /recognition/health` | Recognition subsystem health probe. |
| `GET /roster/health` | Roster subsystem health probe. |
| `GET /scene/health` | Scene analysis subsystem health probe. |

Each endpoint currently returns a static `"ok"` status. They are intended as integration points for future database, pgvector, or model checks.
