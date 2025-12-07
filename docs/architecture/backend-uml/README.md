# Recognition Service Architecture Views (v4.2.4)

Backend architecture diagrams for the recognition service. Updated December 2025.

## Diagram Index

| File | Description |
|------|-------------|
| `master.mmd` | Full system overview with all layers |
| `class-diagram.mmd` | Complete class diagram with domain, assignment, discovery layers |
| `container.mmd` | Runtime components and dependencies |
| `context.mmd` | External systems integration |
| `context_integration.mmd` | WordPress plugin touchpoints |
| `persistence.mmd` | Database entities and pgvector schema |

### Components (`components/`)
| File | Description |
|------|-------------|
| `assignment-gate.mmd` | AssignmentGate validation flow |
| `observability_module.mmd` | Metrics and logging |

### Domain (`domain/`)
| File | Description |
|------|-------------|
| `identity_domain.mmd` | Core domain entities |
| `face-identity-boundary.mmd` | Face↔Identity nomenclature seam |

### Workflows (`workflows/`)
| File | Description |
|------|-------------|
| `complete-workflow.mmd` | Full clustering sequence |
| `unified-assignment.mmd` | Assignment gate sequence |
| `batch_job_observability.mmd` | Batch job logging flow |
| `recognize_faces.mmd` | Face detection flow |
| `startup_sequence.mmd` | Application startup |
| `error_retry.mmd` | Error handling |
| `service_info.mmd` | Health check endpoints |

## Authoring Guidelines

1. **One concern per diagram** — Keep diagrams small for readability
2. **Short labels, external notes** — Put details in README, not node text
3. **Use standard Mermaid** — `flowchart`, `erDiagram`, `sequenceDiagram`, `classDiagram`
