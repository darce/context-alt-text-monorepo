# Recognition Privacy-Minimized Hybrid Roadmap (v0.1)

## Objective

Launch a proof-of-concept and MVP recognition product with a credible privacy story that does not require most customers to run a local vector store. The system should default to privacy-minimized remote processing now, while preserving a path to optional customer-controlled or WordPress-authoritative embedding storage later.

## Problem Statement

The current recognition service is optimized for server-side persistence of biometric vectors in PostgreSQL with pgvector. That is technically strong for clustering and similarity search, but it weakens the product's privacy positioning if the commercial promise is framed as "data sovereignty" or "your embeddings stay under your control."

Pure WordPress-DB-local embeddings are also not a good default answer. MySQL/MariaDB has no pgvector equivalent, WordPress cannot run clustering or vector search efficiently at scale, and multimodal expansion would make a local-only WP storage strategy even less practical. The product therefore needs a tighter privacy proposition than "everything local" and a more practical architecture than "store every embedding forever in the remote service."

## Constraints

- The proof of concept must be launchable without requiring customers to operate a local vector database or a self-hosted ML stack.
- The existing recognition pipeline depends on pgvector, server-side NumPy operations, materialized centroid state, and worker-driven clustering; MVP cannot rewrite all of that.
- Privacy claims must be narrower than full sovereignty unless images, embeddings, and retention are genuinely customer-controlled.
- The service already persists 512D embeddings and uses them across clustering, representatives, centroid refresh, and similarity search, so retention changes must not silently break current clustering behavior.
- MVP should optimize for credible privacy controls, deletion, and non-retention posture rather than a finished sovereign architecture.

## Terminology

- **Privacy-minimized retention**: Store only the biometric state needed to continue recognition behavior, and delete the rest on a defined policy.
- **Authoritative store**: The system of record for embeddings and related biometric templates.
- **Representative**: A durable cluster exemplar retained for matching and UI display.
- **Centroid**: Cluster-level aggregate vector used for cluster comparison and discovery.
- **Ephemeral compute mode**: The description service receives embeddings or media, computes outputs, returns results, and does not persist biometric vectors after processing.
- **Sovereignty tier**: An optional deployment mode where customers control the authoritative embedding store and, potentially, encryption keys or hosting.

## Current State

- The description service stores face embeddings in `media_identities.embedding` and representative embeddings in `identity_cluster_representatives.embedding`.
- PostgreSQL + pgvector is the active storage and query engine, with IVFFlat cosine indexes and centroid materialization.
- Scan and clustering workers assume persisted vectors and persisted job state.
- Tenant isolation, API keys, and service-side auth/rate limiting already exist.
- The current architecture is technically effective for clustering and search, but the privacy posture is closer to "remote biometric storage" than "minimal biometric retention."
- WordPress projection tables currently store metadata, labels, thumbnails, and assignments, but not vectors.
- A WordPress-DB-authoritative embedding model is feasible only as a hybrid for specific tiers; it is not a good default for MVP because WordPress cannot replace pgvector-backed search and clustering.

## Target Architecture

The target launch architecture is a hybrid privacy model with three layers:

1. WordPress remains the customer-facing control plane for media, labels, assignments, and privacy settings.
2. The description service remains the compute backend for detection, embedding generation, clustering, and similarity-heavy operations.
3. Biometric retention is minimized by default:
   - short-lived member-level embeddings are treated as operational working state
   - durable cluster representatives and centroids are retained only when needed for recognition continuity
   - raw face crops are never retained as a product feature
   - export, purge, and auditability become first-class capabilities

The long-term architecture keeps an optional sovereignty path open:

- a customer-controlled embedding store
- a push-based clustering API that can accept embeddings without persisting them
- optional WordPress-authoritative or customer-managed vector ownership for high-privacy tiers

That sovereignty path is explicitly post-MVP. The MVP product promise is not "all biometric data stays local." The MVP promise is:

- no model training on customer biometric data
- configurable biometric retention
- auditable purge and export
- minimal persistent biometric state by default

### Design Decisions

| Decision | Rationale |
| --- | --- |
| Default MVP keeps the description service as the active vector engine | pgvector, materialized centroids, batch similarity, and clustering already live there; replacing that with WordPress storage would delay launch and degrade quality. |
| MVP privacy promise is non-retention and minimization, not full sovereignty | This is operationally credible for a proof of concept and avoids over-claiming while remote compute still exists. |
| Member-level embeddings become purgeable state | This reduces long-term biometric retention while preserving cluster continuity through representatives and centroids. |
| Cluster representatives and centroids remain durable in MVP | They are the smallest practical retained vector surface that still supports recognition continuity. |
| Raw face crops are not a durable product artifact | This materially improves privacy posture without blocking current detection and embedding generation. |
| WordPress-authoritative embeddings are deferred to post-MVP | WordPress DB is not a viable default vector engine; this should be an optional tier, not the launch architecture. |
| Privacy controls are per-tenant and auditable | The business proposition improves only if retention behavior is configurable, inspectable, and enforceable. |

### Data Model

**MVP / Launch data model**

- `tenants`
  - add retention and privacy policy fields such as `biometric_retention_mode`, `embedding_ttl_days`, `allow_training_use` defaulting to false, and optional `data_region`
- `media_identities`
  - keep `embedding` for operational use during scan and clustering
  - add `embedding_model_version`
  - add `embedding_retained`
  - add `embedding_purged_at`
  - add optional retention classification fields if needed for purge logic
  - plan to make `embedding` purgeable after clustering or TTL expiry
- `identity_cluster_representatives`
  - remain the durable embedding surface in MVP
  - add `embedding_model_version` and retention/audit metadata
- `mv_identity_cluster_centroids`
  - remain the durable aggregate surface in MVP
- `recognition_runs` / `recognition_events`
  - add explicit privacy and purge events so retention behavior is inspectable

**Post-MVP optional sovereignty data model**

- WordPress or customer-managed store becomes authoritative for embeddings
- the description service accepts batch embedding payloads or signed media references
- the remote service persists assignments, clusters, or job metadata only when configured
- remote vector persistence becomes optional or disabled per tenant tier

## Phased Delivery

### Phase 1: Proof of Concept Privacy Hardening

**Goal**: Prove a launchable privacy posture without changing the core clustering engine.

Deliverables:

- Add tenant-level privacy and retention configuration to the description service.
- Document a clear product policy: no customer biometric data used to train shared models, no durable raw face-crop retention, explicit retention modes.
- Add internal classification for biometric records so the service can distinguish operational embeddings from durable representatives.
- Add audit events for embed, retain, purge, and export actions.
- Add manual tenant-scoped purge and export endpoints for biometric-derived records.
- Review and reduce over-retention of direct media references where possible.

Exit criteria:

- A demo tenant can inspect its configured retention mode.
- A demo tenant can trigger export and purge of biometric-derived data through service APIs.
- The product can truthfully claim privacy-minimized retention and no training reuse, even though clustering still runs remotely.

### Phase 2: MVP Launch with Minimized Retention

**Goal**: Make privacy-minimized retention the default production behavior while preserving recognition continuity.

Deliverables:

- Make member-level embeddings purgeable after clustering completion or after a configurable TTL.
- Preserve only the vector state required for continuity: cluster representatives and centroids.
- Update clustering, similarity, and repository flows so steady-state behavior does not assume every historical member embedding remains present.
- Add background purge jobs tied to clustering completion and retention policy.
- Add service-level health and diagnostics for retention state, purge lag, and model version coverage.
- Add administrative visibility into what biometric state is currently retained per tenant.

Exit criteria:

- In default mode, the service no longer retains all member embeddings indefinitely.
- Existing cluster review and assignment flows still function after purge because representatives and centroids remain available.
- Tenant deletion/export/purge flows are operational and test-covered.

### Phase 3: Post-MVP Optional Sovereignty Tier

**Goal**: Support customers who require customer-controlled embedding authority without making it the default deployment model.

Deliverables:

- Add a stateless or ephemeral compute API that accepts embeddings or signed media references and returns clustering/assignment outputs without persisting vectors.
- Add a push-based clustering contract so WordPress or another customer-controlled store can send embeddings on demand.
- Add optional customer-managed retention mode where remote vector persistence is disabled.
- Add encryption-at-rest and per-tenant key-management hooks for retained biometric templates.
- Add region-pinning and deployment-mode reporting for sales and compliance use.

Exit criteria:

- A tenant can run in a mode where the description service performs clustering and assignment without remaining the authoritative long-term embedding store.
- Product messaging can accurately distinguish standard privacy-minimized mode from sovereignty mode.

## External Dependencies

| Dependency | Owner | Status | Blocks |
| --- | --- | --- | --- |
| Product/privacy messaging for "non-retention" vs "sovereignty" | Product + Legal | Not started | Phase 1 exit criteria |
| Retention-mode UX in WordPress admin | Plugin | Not started | Phase 1 rollout quality |
| DB migration for purgeable embeddings and tenant policy fields | Backend | Not started | Phase 2 exit criteria |
| Background job scheduling for purge workflows | Backend | Not started | Phase 2 exit criteria |
| Push-based embedding/clustering contract for optional sovereignty tier | Plugin + Backend | Not started | Phase 3 exit criteria |

## Code Anchors

| Layer | File | Note |
| --- | --- | --- |
| Backend API | `apps/prototype-description-service/api/main.py` | App entrypoint; privacy/export/purge routers and service metadata surface here. |
| Backend config | `apps/prototype-description-service/recognition/config/security.py` | Current runtime security flags; extend for retention and privacy policy controls. |
| Backend config | `apps/prototype-description-service/recognition/config/settings.py` | Add privacy-minimized retention settings and defaults. |
| Backend HTTP | `apps/prototype-description-service/recognition/interface_adapters/http/router.py` | Mount new privacy/export/purge endpoints and later ephemeral compute routes. |
| Backend model | `apps/prototype-description-service/db/models/tenant.py` | Add per-tenant retention mode, TTL, and privacy policy fields. |
| Backend model | `apps/prototype-description-service/db/models/identity.py` | Current embedding storage for identities, representatives, and centroids; make member embeddings purgeable and add retention metadata. |
| Backend model | `apps/prototype-description-service/db/models/observability.py` | Add audit events and run metadata for retain/export/purge actions. |
| Backend migration | `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py` | Baseline schema currently makes embeddings durable and indexed; follow-up migration will relax and annotate retention behavior. |
| Worker | `apps/prototype-description-service/recognition/worker/handlers/scan.py` | Current scan pipeline persists identities and auto-queues clustering; add privacy metadata and avoid over-retention. |
| Worker | `apps/prototype-description-service/recognition/worker/handlers/clustering.py` | Add retention-aware purge triggers after clustering or curation completion. |
| Repository | `apps/prototype-description-service/recognition/infrastructure/repositories/cluster_repository.py` | Today assumes persisted vectors and centroid state; adapt for partially purged member embeddings. |
| Similarity | `apps/prototype-description-service/recognition/application/similarity/search.py` | Keep representative-based matching functional when member embeddings are no longer fully retained. |
| Domain | `apps/prototype-description-service/recognition/domain/identity.py` | Clarify operational vs durable embedding use in domain semantics. |
| README | `apps/prototype-description-service/README.md` | Document the privacy posture, retention modes, and launch limitations. |

## Risks and Mitigations

- **Risk**: Privacy claims drift ahead of actual runtime behavior.
  Mitigation: Ship explicit retention modes, export/purge APIs, and audit events before using strong privacy messaging.

- **Risk**: Purging member embeddings breaks clustering follow-up jobs or similarity behavior.
  Mitigation: Keep representatives and centroids durable first, then make member-vector purge conditional and phased.

- **Risk**: `media_url` and other operational metadata still reveal more than expected.
  Mitigation: Reduce durable media-reference persistence, prefer IDs over direct URLs, and treat URL retention as a separate audit target.

- **Risk**: WordPress-authoritative embeddings become a distraction from a launchable MVP.
  Mitigation: Keep customer-controlled embedding ownership explicitly post-MVP and optional.

- **Risk**: Export and purge semantics become hard to reason about across scans, clusters, and audit logs.
  Mitigation: Define tenant-scoped retention classes early and log every retain/purge transition through observability tables.

## Success Metrics

- A tenant can see and configure a retention mode without engineering intervention.
- A tenant can export or purge biometric-derived data through documented service APIs.
- Default retention mode no longer stores all member embeddings indefinitely after clustering.
- Recognition continuity remains acceptable after purge because representative and centroid matching still work.
- Product messaging can truthfully say that customer biometric data is not used for shared model training and is retained only under explicit policy.

---

# Consolidated Checklist

## Phase 1: Proof of Concept Privacy Hardening

- [ ] Add tenant privacy policy fields in the service data model.
- [ ] Add runtime retention settings and defaults.
- [ ] Add privacy/export/purge HTTP endpoints.
- [ ] Add observability events for retain/export/purge operations.
- [ ] Document the product privacy posture in the service README and launch docs.
- [ ] Reduce obvious over-retention of direct media references where feasible.

## Phase 2: MVP Launch with Minimized Retention

- [ ] Make member embeddings purgeable under policy.
- [ ] Keep representative and centroid vectors as the durable matching surface.
- [ ] Add background purge workflows after clustering completion or TTL expiry.
- [ ] Update cluster repository and similarity flows for partially purged identity state.
- [ ] Add diagnostics for retention status and purge lag.
- [ ] Add automated tests for retention, purge, export, and steady-state matching after purge.

## Phase 3: Post-MVP Optional Sovereignty Tier

- [ ] Add ephemeral compute endpoints for batch clustering without durable remote vector storage.
- [ ] Add push-based embedding payload contract for customer-controlled stores.
- [ ] Add optional remote-disabled vector persistence mode.
- [ ] Add per-tenant encryption and key-management hooks.
- [ ] Add region and deployment-mode reporting for compliance-sensitive tenants.

## Deferred (Post-v0.1)

- [ ] WordPress-DB-authoritative embeddings as a default mode.
- [ ] Full customer-managed local similarity search at scale inside MySQL/MariaDB.
- [ ] Full sovereignty positioning in product copy before the customer-controlled mode is actually available.

## Success Criteria

- [ ] The proof of concept can launch with a credible privacy-minimized story that does not overclaim sovereignty.
- [ ] The MVP defaults to minimized biometric retention rather than indefinite storage of all member embeddings.
- [ ] The architecture leaves a clean path to an optional customer-controlled embedding tier without forcing it on every customer.
