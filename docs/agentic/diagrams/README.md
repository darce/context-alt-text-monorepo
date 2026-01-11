# Architecture Diagrams

Mermaid diagrams documenting the Context Alt Text system architecture.

## Quick Reference

| Diagram                                                                | Purpose                    | When to Use                        |
| ---------------------------------------------------------------------- | -------------------------- | ---------------------------------- |
| [system-overview.mmd](system-overview.mmd)                             | High-level system map      | Understanding overall architecture |
| [backend-uml/agent-quick-start.mmd](backend-uml/agent-quick-start.mmd) | API routing                | Finding code for endpoints         |
| [backend-uml/job-progress-flow.mmd](backend-uml/job-progress-flow.mmd) | SSE + multi-tab sync       | Job progress streaming (v4.10.3+)  |

## Directory Structure

```
diagrams/
├── system-overview.mmd          # Top-level architecture
├── backend-uml/                 # Recognition Service (Python/FastAPI)
│   ├── agent-quick-start.mmd   # Endpoint → Service → Repo mapping
│   ├── master.mmd              # System overview (clients, API, worker)
│   ├── class-diagram.mmd       # Key service + pipeline classes
│   ├── container.mmd           # Runtime components
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
| `master.mmd`            | System overview (clients, API, worker, data plane) |
| `agent-quick-start.mmd` | Endpoints → services → repositories quick map      |
| `container.mmd`         | Runtime components and dependencies                |
| `context.mmd`           | External systems integration                       |
| `class-diagram.mmd`     | Key service + pipeline class overview              |

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
| `components/observability_module.mmd` | Observability classes           |

### Persistence & Observability

| File                        | Description                             |
| --------------------------- | --------------------------------------- |
| `persistence.mmd`           | Database entities and pgvector schema   |
| `observability/metrics.mmd` | Observability persistence + diagnostics |

### Workflows

| File                                    | Description                         |
| --------------------------------------- | ----------------------------------- |
| `workflows/complete-workflow.mmd`       | End-to-end workflow (high level)    |
| `workflows/recognize_faces.mmd`         | Analyze + scan queue processing     |
| `workflows/unified-assignment.mmd`      | Discovery + assignment gate flow    |
| `workflows/batch_job_observability.mmd` | Observability logging               |
| `workflows/error_retry.mmd`             | Scan queue error handling           |
| `workflows/startup_sequence.mmd`        | Application startup                 |
| `job-progress-flow.mmd`                 | SSE progress + multi-tab (v4.10.3+) |

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
4. **Update when architecture changes** — Diagrams must match implementation
