# Backend Context Map (Python/FastAPI)

> Quick reference for agents working on the Recognition Service.

## Critical Files (Read First)

| Priority | File                                                                              | Purpose                        |
| -------- | --------------------------------------------------------------------------------- | ------------------------------ |
| 🔥 1     | `apps/prototype-description-service/api/main.py`                                  | FastAPI app entry point        |
| 🔥 2     | `apps/prototype-description-service/recognition/interface_adapters/http/routers/` | All API endpoints              |
| 🔥 3     | `apps/prototype-description-service/recognition/application/`                     | Service layer (business logic) |
| 🔥 4     | `apps/prototype-description-service/db/models.py`                                 | SQLAlchemy models              |
| 🔥 5     | `docs/agentic/contracts/recognition-clustering.md`                                | API contract specification     |

## Architecture Layers

```
recognition/
├── interface_adapters/http/     # FastAPI routers (HTTP boundary)
│   ├── routers/
│   │   ├── analyze.py           # POST /analyze, GET /jobs/{id}
│   │   ├── clusters.py          # CRUD for clusters
│   │   ├── suggestions.py       # Accept/reject suggestions
│   │   ├── media.py             # Media identity queries
│   │   ├── jobs.py              # SSE progress streaming
│   │   └── diagnostics.py       # Health & observability
│   └── dependencies.py          # Dependency injection
├── application/                 # Use cases / orchestration
│   ├── scan/                    # Scan queue service
│   ├── orchestration/           # Cluster service, incremental clustering
│   ├── assignment/              # Assignment gate + checks (WELL-STRUCTURED)
│   ├── discovery/               # Representative, centroid, graph discovery
│   ├── clustering/              # HAC, representative-only clustering
│   └── suggestions/             # Suggestion service
├── domain/                      # Core business entities
│   ├── entities/                # Identity, Cluster, Member
│   └── repositories.py          # Repository protocols
├── infrastructure/              # External adapters
│   ├── repositories/            # SQLAlchemy repos
│   └── embedding/               # InsightFace wrapper
└── worker/                      # Background job processing
    └── scan_worker.py           # Scan + clustering job handler
```

## Test Entry Points

| Scope       | Path                             | When to Use                                |
| ----------- | -------------------------------- | ------------------------------------------ |
| API         | `recognition/tests/api/`         | Endpoint behavior, request/response shapes |
| Integration | `recognition/tests/integration/` | Database, repository patterns              |
| Unit        | `recognition/tests/unit/`        | Domain logic, pure functions               |

## Key Diagrams

- [agent-quick-start.mmd](../diagrams/backend-uml/agent-quick-start.mmd) — Endpoint → Service → Repo routing
- [workflows/complete-workflow.mmd](../diagrams/backend-uml/workflows/complete-workflow.mmd) — End-to-end flow
- [domain/identity_domain.mmd](../diagrams/backend-uml/domain/identity_domain.mmd) — Core entity relationships

## Common Tasks

### Add a new endpoint

1. Create router in `recognition/interface_adapters/http/routers/`
2. Register in `api/main.py`
3. Add service method in `recognition/application/`
4. Write API test in `recognition/tests/api/`

### Modify clustering logic

1. Entry: `recognition/application/orchestration/cluster_service.py`
2. Discovery: `recognition/application/discovery/`
3. Assignment: `recognition/application/assignment/` (gate + checks)
4. Clustering: `recognition/application/clustering/`

### Modify assignment validation

The assignment module is **well-structured** with Strategy pattern:

1. `assignment/gate.py` — Orchestrates checks
2. `assignment/checks/` — Individual validation rules (confidence, constraint, block)
3. `assignment/candidate.py` — Input dataclass
4. `assignment/decision.py` — Output dataclass (ACCEPT/SUGGEST/REJECT)

### Database changes

1. Modify `db/models.py`
2. Update baseline migration `db/migrations/versions/001_identity_schema.py`
3. Run `alembic upgrade head`
