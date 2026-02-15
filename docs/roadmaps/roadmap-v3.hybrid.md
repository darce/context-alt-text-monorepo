# Context Alt Text Roadmap v3.0 -- Core Vision

> **Status:** Superseded by active epics. Retained as the architectural vision document.
> Active work: [v0.1.0 Sovereign Cluster Roadmap](v0.1.0/wp-sovereign-cluster-roadmap.md)
> Next: v4 roadmap (placeholder at [roadmap-v4.md](roadmap-v4.md))

---

## Core Objective

Ship a WordPress plugin that lets admins batch-generate semantically rich, identity-aware alt text and confirm known people/brands by invoking:

- A **self-hostable remote recognition service** (FastAPI, faces/brands, side profiles and partial occlusions) that performs detection, recognition, and roster synchronization.
- A provider-agnostic LLM (captioning via PHP AI Client SDK).

### System Surfaces

| Area             | Directory                             | Notes                                       |
| ---------------- | ------------------------------------- | ------------------------------------------- |
| WordPress plugin | `apps/prototype-wp-alt-context/`      | React admin UI + PHP REST layer             |
| Backend service  | `apps/prototype-description-service/` | FastAPI recognition service                 |
| Shared contracts | `packages/shared-contracts/`          | JSON Schema definitions                     |
| Agent docs       | `docs/agentic/`                       | Contracts, diagrams, maps, rules, templates |

Recognition happens exclusively in the backend service. The WordPress UI consumes server-provided results. No in-browser detection, embeddings, or cosine matching.

---

## Architectural Principles

1. **Remote-only recognition** -- all detection, embedding, and clustering runs on the backend. Frontend bundle stays small.
2. **Sovereign local state** -- plugin owns a local projection of cluster/identity data. Backend is a compute/sync peer, not a runtime dependency.
3. **Curation-first** -- user curation decisions are ground truth and override backend suggestions unconditionally.
4. **Privacy by design** -- embeddings and model payloads stay on trusted servers. Only transient crops/URLs leave WordPress.
5. **Greenfield policy** -- no production users, no backward compatibility. Clean rewrites preferred.
6. **User consent for remote operations** -- all operations that use remote services require explicit user action.
7. **Keyboard accessibility** -- every interactive surface must be operable end-to-end via keyboard.

---

## Assisted Face Identification UX Vision

Deliver an Apple Photos-style assisted labeling flow:

- System forms clusters around visually similar, unknown faces.
- User confirms an identity label on a cluster, which cascades to every face inside it.
- Users can refine clusters by selecting/deselecting thumbnails or dragging misgrouped faces.
- High-confidence suggestions surface first; borderline matches are deferred for user review.

**Guiding UX principles:**

- Accuracy over volume -- never sacrifice user trust.
- Explicit user control -- no auto-labeling without confirmation; clear undo paths.
- Resource awareness -- throttled analysis of selected images before whole-library sweeps.
- Progressive disclosure -- basic grouping first; automation only after precision is validated.

---

## Epic Summary

### A -- Foundations and Safety

Plugin bootstrap, lifecycle hooks, security, API client with retries/backoff. Feature gates for post-MVP capabilities.

### B -- Data Model

Plugin-owned tables for clusters, identity members, and sync state. Sovereign local projection (see [v0.1.0 roadmap](v0.1.0/wp-sovereign-cluster-roadmap.md)).

### C -- Recognition Pipeline (WP <-> FastAPI)

RecognitionClient for analyze/embeddings. Backend exposes detection, clustering, suggestions. Round-trip: cluster computed on backend, projected locally, surfaced in UI.

### D -- Dashboard and Alt Text Generation

React admin dashboard (coverage, activity, recognition insights, automation pipeline). Alt-text generation via provider-agnostic LLM with draft review/approval workflow.

### E -- Propagation and Sync

Snapshot-based pull sync (v0.1.0). Outbox pattern with Action Scheduler (v0.2+). Conflict resolution: curation-first precedence.

### F -- Observability and Security

API key auth with tenant scoping, structured logging, metrics, audit logs. See [contracts/security.md](../agentic/contracts/security.md).

### G -- Backend Architecture (PostgreSQL + pgvector)

PostgreSQL as canonical storage layer. pgvector for embedding search. Alembic migrations. FAISS as optional derived in-memory index. Progressive learning pipeline (user confirmation -> augmented embeddings -> aggregate recomputation).

---

## Long-Term Backlog (Post-MVP)

- MCP tool enablement and agent documentation
- Advanced roster analytics (duplicate detection, tagging suggestions)
- Multi-tenant backend support with per-site API keys
- Offline processing queue using managed job runner
- Accessibility insights dashboard with trendlines and digests

---

## Key Design Decisions

| Decision                                          | Rationale                                                                  |
| ------------------------------------------------- | -------------------------------------------------------------------------- |
| No in-browser detection                           | Keeps bundle small, simplifies accessibility, centralizes recognition IP   |
| Plugin-owned tables (not post-meta or taxonomies) | Multiple faces per attachment; identity-level data requires its own schema |
| Remote-only embeddings                            | Privacy, consistency, model upgradeability                                 |
| Pull-first sync (v0.1.0)                          | Simplest viable sync; outbox pattern deferred to v0.2+                     |
| Curation-first conflict policy                    | User decisions override backend suggestions unconditionally                |
| Provider-agnostic LLM                             | PHP AI Client SDK supports GPT/Claude/Gemini; no vendor lock-in            |

---

## References

- Active epic: [v0.1.0 Sovereign Cluster Roadmap](v0.1.0/wp-sovereign-cluster-roadmap.md)
- API contracts: [docs/agentic/contracts/](../agentic/contracts/)
- Architecture diagrams: [docs/agentic/diagrams/](../agentic/diagrams/)
- Engineering rules: [docs/agentic/instructions.md](../agentic/instructions.md)
