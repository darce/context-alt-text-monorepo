# Architecture Diagrams

Mermaid diagrams documenting the Context Alt Text system architecture.

## Quick Reference

| Diagram                                                                | Purpose                    | When to Use                        |
| ---------------------------------------------------------------------- | -------------------------- | ---------------------------------- |
| [system-overview.mmd](system-overview.mmd)                             | High-level system map      | Understanding overall architecture |
| [sovereign-data-flow.mmd](sovereign-data-flow.mmd)                     | Sovereign synchronization flow | Understanding v0.1.0 sync mechanics |
| [backend-uml/agent-quick-start.mmd](backend-uml/agent-quick-start.mmd) | API routing                | Finding code for endpoints         |
| [backend-uml/job-progress-flow.mmd](backend-uml/job-progress-flow.mmd) | SSE job progress flow      | Debugging backend progress streams |

## Directory Structure

```
diagrams/
├── system-overview.mmd          # Top-level architecture
├── backend-uml/                 # Recognition Service (Python/FastAPI)
│   ├── agent-quick-start.mmd   # Endpoint → Service → Repo mapping
│   ├── master.mmd              # Backend signal flow
│   ├── class-diagram.mmd       # Key service + pipeline classes
│   ├── container.mmd           # Runtime components
│   ├── job-progress-flow.mmd   # Backend SSE job progress stream
│   ├── hexagonal-map.mmd       # Hexagonal directory map
│   ├── persistence.mmd         # Database schema
│   ├── domain/                 # Core domain models
│   ├── components/             # Component details
│   ├── workflows/              # Sequence diagrams
│   └── observability/          # Metrics and diagnostics
└── frontend-uml/               # WordPress Plugin (PHP/React)
    ├── master.mmd              # Frontend overview
    ├── class-diagram.mmd       # Plugin class relationships
    ├── proxy-boundary.mmd      # WP → Backend proxy
    ├── workbench-flow-v2.mmd   # Workbench user flow
    └── sequence-*.mmd          # Various sequence diagrams
```

## Backend Diagrams Index

### System Overview

| File                    | Description                                        |
| ----------------------- | -------------------------------------------------- |
| `master.mmd`            | Backend signal flow (HTTP boundary, services, worker, data) |
| `agent-quick-start.mmd` | Endpoints → services → repositories quick map      |
| `container.mmd`         | Runtime components and dependencies                |
| `context.mmd`           | Backend context (clients + data plane)             |
| `class-diagram.mmd`     | Key service + pipeline class overview              |
| `hexagonal-map.mmd`     | Hexagonal directory map (bounded contexts + layers) |

### Domain

| File                                | Description                             |
| ----------------------------------- | --------------------------------------- |
| `domain/identity_domain.mmd`        | Core identity/cluster/suggestion models |
| `domain/job_domain.mmd`             | Job lifecycle models                    |
| `domain/constraints_domain.mmd`     | Constraint domain types                 |
| `domain/face-identity-boundary.mmd` | Face detection to identity seam         |

### Components

| File                                  | Description                     |
| ------------------------------------- | ------------------------------- |
| `components/assignment-gate.mmd`      | Assignment gate validation flow |
| `components/http-boundary.mmd`        | HTTP boundary (routers, auth, SSE) |
| `components/observability_module.mmd` | Observability classes           |
| `components/realtime-events.mmd`      | Event broadcaster + SSE cluster events |
| `components/worker-pipeline.mmd`      | Worker handlers + scan pipeline |

### Persistence & Observability

| File                        | Description                             |
| --------------------------- | --------------------------------------- |
| `persistence.mmd`           | Database entities and pgvector schema   |
| `observability/metrics.mmd` | Observability persistence + diagnostics |

### Workflows

| File                                    | Description                         |
| --------------------------------------- | ----------------------------------- |
| `workflows/recognize_faces.mmd`         | Analyze + scan queue processing     |
| `workflows/image-to-cluster-happy-path.mmd` | Happy path (image → cluster)     |
| `workflows/unified-assignment.mmd`      | Discovery + assignment gate flow    |
| `workflows/batch_job_observability.mmd` | Observability logging               |
| `workflows/error_retry.mmd`             | Scan queue error handling           |
| `workflows/startup_sequence.mmd`        | Application startup                 |
| `job-progress-flow.mmd`                 | SSE job progress stream (backend)   |

## Frontend Diagrams Index

| File                                 | Description                |
| ------------------------------------ | -------------------------- |
| `master.mmd`                         | Frontend overview          |
| `class-diagram.mmd`                  | Plugin class relationships |
| `plugin-core-classes.mmd`            | Core plugin PHP classes    |
| `proxy-boundary.mmd`                 | WP → Backend proxy layer   |
| `workbench-flow-v2.mmd`              | Workbench user flow        |
| `media-selection-workflow.mmd`       | Media selection UX         |
| `roster-domain-classes.mmd`          | Roster management classes  |
| `sequence-complete-workflow.mmd`     | Full workflow sequence     |
| `sequence-generate-alt-text.mmd`     | Alt text generation        |
| `sequence-interactive-detection.mmd` | Interactive detection flow |
| `sequence-reference-upload.mmd`      | Reference photo upload     |
| `sequence-regenerate.mmd`            | Regenerate alt text flow   |

## Authoring Guidelines

1. **One concern per diagram** — Keep diagrams small for readability
2. **Use consistent styling** — Follow WCAG AA color contrast
3. **Include code anchors** — Reference source file locations
4. **Update when architecture changes** — Follow [../rules/uml-change-checklist.md](../rules/uml-change-checklist.md) and keep diagrams in the same slice as the code change
