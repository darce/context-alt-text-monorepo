# Recognition Service Architecture Views

This folder breaks the recognition service diagrams into focused slices so developers and future agents can jump straight to the view they need:

- `context.mmd` — external actors and systems the service integrates with.
- `context_integration.mmd` — how the recognition service slots into the broader WordPress + documentation ecosystem (replaces the old unified view).
- `container.mmd` — key runtime components inside `apps/recognition-service`.
- `persistence.mmd` — database entities and the pgvector/HNSW index.
- `components/recognition_pipeline.mmd` — how `FaceRecognitionService` talks to adapters and infrastructure.
- `domain/roster_domain.mmd` — core roster entities, ports, and adapters.
- `observability/metrics.mmd` — how `shared/metrics.py` hooks FastAPI handlers and services into Prometheus gauges/counters.
- `workflows/` — sequence diagrams for high-signal flows (progressive learning, roster ETag caching, hybrid index cycle, error/retry handling, startup wiring, recognition requests, service info stats). Add more detailed diagrams here when a roadmap slice introduces new behaviour, naming each file after the scenario it covers.

### Authoring Guidelines

1. **One concern per diagram.** Keep diagrams small enough to render legibly in GitHub/IDE previews. Add a new file instead of overloading an existing one.
2. **Annotate in Markdown, not in-node prose.** Prefer short node labels and capture expanded notes in the README or adjacent Markdown so the visual stays uncluttered.
3. **Tie commits to roadmap tasks.** Mention the touched diagram(s) in roadmap updates (`docs/tasks/backend-clustering-persitence-tasks.md`) so downstream teams know where to look.
4. **Use ASCII-friendly Mermaid.** Stay within Mermaid primitives (`flowchart`, `erDiagram`, `sequenceDiagram`) to keep diff noise low and previews reliable.

When introducing new capabilities, sketch the behaviour here first; only then update implementation and tests so both code and diagrams stay in sync.
