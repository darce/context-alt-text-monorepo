# Recognition Service Architecture Views

Backend architecture diagrams for the recognition service (current implementation).

## Diagram Index

### System Overview
| File | Description |
|------|-------------|
| `master.mmd` | System overview (clients, API, worker, data plane) |
| `agent-quick-start.mmd` | Endpoints -> services -> repositories quick map |
| `container.mmd` | Runtime components and dependencies |
| `context.mmd` | External systems integration |
| `context_integration.mmd` | WordPress plugin touchpoints |
| `class-diagram.mmd` | Key service + pipeline class overview |

### Domain
| File | Description |
|------|-------------|
| `domain/identity_domain.mmd` | Core identity/cluster/suggestion models |
| `domain/job_domain.mmd` | Job lifecycle models |
| `domain/constraints_domain.mmd` | Constraint domain types |
| `domain/face-identity-boundary.mmd` | Face detection to identity seam |

### Components
| File | Description |
|------|-------------|
| `components/assignment-gate.mmd` | Assignment gate validation flow |
| `components/observability_module.mmd` | Observability classes and persistence helpers |

### Persistence & Observability
| File | Description |
|------|-------------|
| `persistence.mmd` | Database entities and pgvector schema |
| `observability/metrics.mmd` | Observability persistence + diagnostics |

### Workflows (`workflows/`)
| File | Description |
|------|-------------|
| `complete-workflow.mmd` | End-to-end workflow (high level) |
| `recognize_faces.mmd` | Analyze + scan queue processing |
| `unified-assignment.mmd` | Discovery + assignment gate flow |
| `batch_job_observability.mmd` | Observability logging + reporting |
| `error_retry.mmd` | Scan queue error handling |
| `startup_sequence.mmd` | Application startup |
| `service_info.mmd` | Health + diagnostics endpoints |

## Authoring Guidelines

1. **One concern per diagram** — Keep diagrams small for readability
2. **Short labels, external notes** — Put details in README, not node text
3. **Use standard Mermaid** — `flowchart`, `erDiagram`, `sequenceDiagram`, `classDiagram`
