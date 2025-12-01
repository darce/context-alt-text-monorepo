# Recognition Service Architecture Views

This folder breaks the recognition service diagrams into focused slices so developers and future agents can jump straight to the view they need:

- `context.mmd` — external actors and systems the prototype description service integrates with.
- `context_integration.mmd` — WordPress plugin touchpoints, tenant context, caches, and stores.
- `container.mmd` — key runtime components inside `apps/prototype-description-service`.
- `persistence.mmd` — database entities for identities, clusters, suggestions, jobs, and the pgvector centroid view.
- `components/recognition_pipeline.mmd` — how `IdentityScanService` and `IdentityClusteringService` orchestrate adapters and algorithms.
- `domain/identity_domain.mmd` — recognition domain entities (value objects + persistence models).
- `observability/metrics.mmd` — metrics/health routers and the clustering metrics dataclass.
- `workflows/` — sequence diagrams for core flows (analyze chunking, clustering status, suggestion review, centroid refresh, startup wiring, training stage insight). Add more detailed diagrams here when a roadmap slice introduces new behaviour, naming each file after the scenario it covers.

### Authoring Guidelines

1. **One concern per diagram.** Keep diagrams small enough to render legibly in GitHub/IDE previews. Add a new file instead of overloading an existing one.
2. **Annotate in Markdown, not in-node prose.** Prefer short node labels and capture expanded notes in the README or adjacent Markdown so the visual stays uncluttered.
3. **Tie commits to roadmap tasks.** Mention the touched diagram(s) in roadmap updates (`docs/tasks/backend-clustering-persitence-tasks.md`) so downstream teams know where to look.
4. **Use ASCII-friendly Mermaid.** Stay within Mermaid primitives (`flowchart`, `erDiagram`, `sequenceDiagram`) to keep diff noise low and previews reliable.

When introducing new capabilities, sketch the behaviour here first; only then update implementation and tests so both code and diagrams stay in sync.
