# Recognition Service Architecture Views

Backend-only architecture diagrams for the recognition service (prototype-description-service).

## Quick Navigation

**New to the codebase?** Start with `master.mmd` → `class-diagram.mmd` → relevant component.

| I want to understand...   | Start here                          |
| ------------------------- | ----------------------------------- |
| Overall backend structure | `master.mmd`                        |
| Class relationships       | `class-diagram.mmd`                 |
| Scan/analyze flow         | `components/scan-pipeline.mmd`      |
| Clustering/assignment     | `components/assignment-gate.mmd`    |
| Suggestions               | `components/suggestion-service.mmd` |
| Job lifecycle             | `components/job-service.mmd`        |
| Database schema           | `persistence.mmd`                   |

---

## Service → Diagram Map

Use this table to find the diagram for any service mentioned in code:

| Service Class                | Location in Code                                           | Diagram                                                 |
| ---------------------------- | ---------------------------------------------------------- | ------------------------------------------------------- |
| **ScanQueueService**         | `recognition/application/scan/scan_queue_service.py`       | `components/scan-pipeline.mmd`                          |
| **ScanService**              | `recognition/application/scan/service.py`                  | `components/scan-pipeline.mmd`                          |
| **ClusterService**           | `recognition/application/orchestration/cluster_service.py` | `class-diagram.mmd`, `workflows/unified-assignment.mmd` |
| **SuggestionService**        | `recognition/application/suggestions/service.py`           | `components/suggestion-service.mmd`                     |
| **SuggestionRefreshService** | `recognition/application/suggestions/refresh_service.py`   | `components/suggestion-service.mmd`                     |
| **MergeSuggestionService**   | `recognition/application/suggestions/merge_suggestions.py` | `components/suggestion-service.mmd`                     |
| **JobService**               | `recognition/application/orchestration/job_service.py`     | `components/job-service.mmd`                            |
| **MediaIdentityService**     | `recognition/interface_adapters/http/deps/stores.py`       | `components/media-identity-service.mmd`                 |
| **AssignmentGate**           | `recognition/application/assignment/gate.py`               | `components/assignment-gate.mmd`                        |
| **AssignmentWriter**         | `recognition/application/persistence/assignment_writer.py` | `components/assignment-gate.mmd`                        |
| **EventBroadcaster**         | `recognition/application/events/broadcaster.py`            | `components/realtime-events.mmd`                        |

---

## Master Diagram Subgraphs

| Master subgraph          | Detailed Diagrams                                                                                                                                          |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| HTTP Boundary            | `agent-quick-start.mmd`, `components/http-boundary.mmd`, `job-progress-flow.mmd`, `components/media-identity-service.mmd`                                  |
| Application Services     | `class-diagram.mmd`, `components/scan-pipeline.mmd`, `components/suggestion-service.mmd`, `components/job-service.mmd`, `workflows/unified-assignment.mmd` |
| Realtime + Observability | `components/realtime-events.mmd`, `components/observability_module.mmd`, `observability/metrics.mmd`                                                       |
| Worker                   | `components/worker-pipeline.mmd`, `components/scan-pipeline.mmd`, `workflows/recognize_faces.mmd`, `workflows/error_retry.mmd`                             |
| Infrastructure + Data    | `persistence.mmd`, `components/assignment-gate.mmd`, `domain/*.mmd`                                                                                        |
| Context                  | `context.mmd`, `container.mmd`, `hexagonal-map.mmd`                                                                                                        |

## Diagram Index

### System Overview

| File                    | Description                                                        |
| ----------------------- | ------------------------------------------------------------------ |
| `master.mmd`            | Backend signal flow (HTTP boundary, services, worker, infra, data) |
| `agent-quick-start.mmd` | Endpoints -> services -> repositories quick map                    |
| `container.mmd`         | Runtime components and dependencies                                |
| `context.mmd`           | Backend context (clients, data plane, worker)                      |
| `class-diagram.mmd`     | Key service + pipeline class overview                              |
| `job-progress-flow.mmd` | Backend SSE job progress flow                                      |
| `hexagonal-map.mmd`     | Hexagonal directory map (bounded contexts + layers)                |

### Domain

| File                                | Description                             |
| ----------------------------------- | --------------------------------------- |
| `domain/identity_domain.mmd`        | Core identity/cluster/suggestion models |
| `domain/job_domain.mmd`             | Job lifecycle models                    |
| `domain/constraints_domain.mmd`     | Constraint domain types                 |
| `domain/face-identity-boundary.mmd` | Face detection to identity seam         |

### Components

| File                                    | Description                                                        |
| --------------------------------------- | ------------------------------------------------------------------ |
| `components/scan-pipeline.mmd`          | ScanQueueService + ScanService → FaceDetector → EmbeddingGenerator |
| `components/suggestion-service.mmd`     | SuggestionService + RefreshService + MergeSuggestionService        |
| `components/job-service.mmd`            | JobService lifecycle + Job state machine                           |
| `components/media-identity-service.mmd` | MediaIdentityService query composition (HTTP layer)                |
| `components/assignment-gate.mmd`        | Assignment gate validation flow                                    |
| `components/http-boundary.mmd`          | HTTP boundary (routers, auth, SSE)                                 |
| `components/observability_module.mmd`   | Observability classes and persistence helpers                      |
| `components/realtime-events.mmd`        | Event broadcaster + SSE cluster events                             |
| `components/worker-pipeline.mmd`        | Worker handlers + scan pipeline                                    |

### Persistence & Observability

| File                        | Description                             |
| --------------------------- | --------------------------------------- |
| `persistence.mmd`           | Database entities and pgvector schema   |
| `observability/metrics.mmd` | Observability persistence + diagnostics |

### Workflows (`workflows/`)

| File                              | Description                          |
| --------------------------------- | ------------------------------------ |
| `recognize_faces.mmd`             | Analyze + scan queue processing      |
| `image-to-cluster-happy-path.mmd` | Happy path summary (image → cluster) |
| `unified-assignment.mmd`          | Discovery + assignment gate flow     |
| `error_retry.mmd`                 | Scan queue error handling            |

---

## Nomenclature Standards

Use these suffix conventions consistently across code and diagrams:

| Suffix        | Layer        | Purpose                       | Examples                                           |
| ------------- | ------------ | ----------------------------- | -------------------------------------------------- |
| `*Service`    | Application  | Orchestration, business logic | `ClusterService`, `ScanService`, `JobService`      |
| `*Repository` | Domain/Infra | Data access abstraction       | `ClusterRepository`, `FaceIdentityRepository`      |
| `*Writer`     | Application  | Persistence side-effects      | `AssignmentWriter`, `ClusterWriter`                |
| `*Check`      | Assignment   | Validation step               | `BlockCheck`, `ConstraintCheck`, `ConfidenceCheck` |
| `*Discovery`  | Assignment   | Cluster discovery algorithm   | `SingletonDiscovery`, `ExistingClusterDiscovery`   |
| `*Factory`    | Domain       | Object construction           | `ClusterFactory`                                   |
| `*Router`     | HTTP         | FastAPI endpoint group        | `IdentityRouter`, `ScanRouter`                     |
| `*Handler`    | Worker       | Async task handler            | `ScanHandler`                                      |

---

## Authoring Guidelines

1. **One concern per diagram** — Keep diagrams focused for readability
2. **Match code names** — Use exact class names from codebase (see Nomenclature Standards)
3. **Short labels, external notes** — Put details in README, not node text
4. **Use standard Mermaid** — `flowchart`, `erDiagram`, `sequenceDiagram`, `classDiagram`
5. **Link to code** — Include file paths in diagram titles or notes
6. **Avoid parentheses in labels** — Use dashes: `result - fatal` not `result (fatal)`
