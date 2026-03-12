# Backend Context Map (Python/FastAPI)

> Quick reference for agents working on the Recognition Service.

## Critical Files (Read First)

| Priority | File                                                                              | Purpose                                             |
| -------- | --------------------------------------------------------------------------------- | --------------------------------------------------- |
| 1        | `apps/prototype-description-service/api/main.py`                                  | FastAPI app entry point                             |
| 2        | `apps/prototype-description-service/recognition/interface_adapters/http/routers/` | All API endpoints                                   |
| 3        | `apps/prototype-description-service/recognition/application/`                     | Service layer (business logic)                      |
| 4        | `apps/prototype-description-service/db/models.py`                                 | SQLAlchemy models                                   |
| 5        | `apps/prototype-description-service/roster/`                                      | Curation sync (person/cluster-person operations)    |
| 6        | `docs/agentic/contracts/recognition-clustering.md`                                | API contract specification                          |
| 7        | `docs/agentic/contracts/curation-sync-api.md`                                     | Outbox replay contract                              |
| 8        | `docs/agentic/ADR-001-face-identity-nomenclature.md`                              | Face* (infra) vs *Identity (domain) naming boundary |

## Architecture Layers

### API Routers (`recognition/interface_adapters/http/routers/`)

| Router          | Key Endpoints                                          | Purpose                            |
| --------------- | ------------------------------------------------------ | ---------------------------------- |
| `analyze.py`    | `POST /analyze`, `GET /jobs/{id}`                      | Scan/recognition job submission    |
| `clusters.py`   | `GET /clusters`, `PATCH /clusters/{id}`, merge/split   | Cluster CRUD and topology          |
| `suggestions.py`| `GET /suggestions`, accept/reject                      | Merge suggestions                  |
| `events.py`     | `GET /events`                                          | Observability events               |

### Curation Sync (`roster/`)

| File                | Key Endpoint                | Purpose                                      |
| ------------------- | --------------------------- | -------------------------------------------- |
| `roster/router.py`  | `POST /roster/curation/sync`| Idempotent replay of local curation mutations |

### Snapshot (`recognition/interface_adapters/http/routers/`)

| Endpoint                                          | Purpose                                     |
| ------------------------------------------------- | ------------------------------------------- |
| `GET /tenants/{tenant_uuid}/clusters/snapshot`    | Pull snapshot for sovereign projection      |
| `POST /tenants/{tenant_uuid}/acknowledge-projection` | Acknowledge snapshot projection          |

## Test Entry Points

| Scope       | Path                             | When to Use                                |
| ----------- | -------------------------------- | ------------------------------------------ |
| API         | `recognition/tests/api/`         | Endpoint behavior, request/response shapes |
| Integration | `recognition/tests/integration/` | Database, repository patterns              |
| Unit        | `recognition/tests/unit/`        | Domain logic, pure functions               |

## Key Diagrams

- [agent-quick-start.mmd](../diagrams/backend-uml/agent-quick-start.mmd) — Endpoint → Service → Repo routing
- [hexagonal-map.mmd](../diagrams/backend-uml/hexagonal-map.mmd) — Directory-to-layer map
- [workflows/recognize_faces.mmd](../diagrams/backend-uml/workflows/recognize_faces.mmd) — Analyze + scan queue processing
- [workflows/image-to-cluster-happy-path.mmd](../diagrams/backend-uml/workflows/image-to-cluster-happy-path.mmd) — Happy path summary (image -> cluster)
- [workflows/unified-assignment.mmd](../diagrams/backend-uml/workflows/unified-assignment.mmd) — Discovery + assignment gate flow
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
