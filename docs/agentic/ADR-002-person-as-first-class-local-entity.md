# ADR-002: Person as First-Class Local Entity

**Date**: March 3, 2026
**Status**: Accepted
**Context**: Recognition UX roadmap (v4), roster architecture reconciliation

---

## Context

During planning for the Recognition UX epic, a fundamental architectural question emerged: "what exactly do we mean by `acx_roster_entries`?" Investigation revealed a dual-naming tension:

1. **Backend (PG)**: `identity_clusters` table has a `label` column (varchar 255, nullable) and a `roster_id` column (UUID, nullable, no FK constraint). There is **no `roster_entries` table** in any migration -- `roster/` is an empty stub module. A raw SQL query in `cluster_repository.py` silently fails against the nonexistent table.

2. **Plugin (WP)**: `acx_roster_entries` WP option stores a flat JSON list of names. `acx_roster_assignments` WP option maps cluster IDs to `{roster_entry_id, new_entry_name}`. These are disconnected from each other and from the backend.

3. **Local projection**: `wp_acx_clusters` has a `label` column (synced from backend) but no person/roster FK. Cluster label and "roster entry name" are two independent naming systems with no reconciliation path.

The question: if we are adding a `wp_acx_roster_entries` table, what is its relationship to cluster labels? Are they the same data? Redundant? Complementary?

## Decision

**Person is a first-class local entity, stored in `wp_acx_persons`, that provides identity stability across the inherently volatile cluster lifecycle.**

### Architecture

```text
wp_acx_persons (canonical local write model)
  id BIGINT PK
  person_uuid CHAR(36) UNIQUE NOT NULL        -- stable sync identifier (UUID v4)
  name VARCHAR(255) UNIQUE
  tags TEXT (JSON)
  reference_thumb_path VARCHAR(512)
  created_at, updated_at

wp_acx_clusters (modified)
  + person_id BIGINT UNSIGNED DEFAULT NULL   -- logical FK to wp_acx_persons.id
  label text NULL                            -- derived: when person_id IS NOT NULL, label = person.name
```

### Key Rules

1. **Person CRUD is 100% local.** No backend proxy. Create/rename/delete happens in plugin tables only.
2. **Label derivation rule.** When `person_id IS NOT NULL`, the cluster's display label is the person's name. When `person_id IS NULL`, the cluster shows its own `label` column (the auto-generated "Person N" from the backend).
3. **`acx_roster_assignments` option is retired.** The assignment IS the `person_id` FK on the cluster row. No separate mapping needed.
4. **Soft dissociation.** Deleting a person sets `person_id = NULL` on associated clusters. Clusters revert to their backend-assigned label.
5. **Outbox sync (Epic D).** `wp_acx_persons.person_uuid` is carried to backend `identity_clusters.roster_id` through outbox/sync. No ad-hoc BIGINT->UUID mapping is allowed.
6. **Stability across reclustering.** Person survives cluster UUID churn (merges, splits, re-clustering). The person_id FK is re-pointed to the surviving/new cluster.
7. **Legacy option cutover policy.** On activation, if legacy options exist (`acx_roster_entries`, `acx_roster_assignments`), perform one-time import into `wp_acx_persons` + `wp_acx_clusters.person_id`, then retire both options.

### Table Name: `wp_acx_persons` (not `wp_acx_roster_entries`)

The entity represents a **person** -- an operator-curated identity. The table name should reflect what it stores, not the UI page it appears on. "Roster" is a UI/page-level concept; "Person" is the domain entity.

## Rationale

### 1. Eliminates Dual Source of Truth

With `wp_acx_roster_entries` as originally planned, the system would have two independent naming paths: cluster labels (synced from backend PG) and roster entry names (local WP table). The reconciliation question -- "which name wins?" -- has no clean answer.

With Person as the canonical entity:

- Person.name is the single source of truth for "who is this."
- Cluster.label is a fallback display value for unassigned clusters.
- No reconciliation needed; the derivation rule is deterministic.

### 2. Person Provides Identity Stability

Clusters are volatile -- they merge, split, and get re-formed when recognition parameters change. A person entity is stable:

- Person ID survives cluster merges (re-point FK to surviving cluster).
- Person ID survives re-clustering (new cluster gets the same person_id).
- Person carries metadata (tags, reference photo) that outlives any single cluster.

### 3. Future Entity Type Extensibility

The backend already has an `identity_type` discriminator on `identity_clusters` (values: `person`, with `brand`, `object` planned). Each entity type gets its own local table with type-specific metadata:

- `wp_acx_persons` -- name, tags, reference photo
- `wp_acx_brands` (future) -- brand name, logo, brand guidelines
- `wp_acx_objects` (future) -- object class, attributes

This avoids premature generalization (no polymorphic `wp_acx_entities` table) while remaining extensible. The `person_id` FK on clusters is specific to person-type clusters; future types get their own FK columns or a discriminated join pattern.

### 4. No Backend Changes Required

The backend's `identity_clusters.roster_id` column (UUID, nullable) already exists and has no FK constraint. The plugin writes `wp_acx_persons.person_uuid` directly to this column via outbox/sync. Backend-side lookup code that queries `roster_entries` must be removed or replaced as part of Epic D.

### 5. Aligns with ADR-001 Nomenclature Boundary

ADR-001 established that infrastructure uses `Face*` and domain uses `*Identity`. Person is a **curation concept** parallel to `IdentityCluster`:

- `IdentityCluster` = system-inferred grouping (backend domain)
- `Person` = operator-curated identity (plugin domain)

The boundary is clean: backend clusters identities, plugin curates persons.

## Alternatives Considered

### 1. `wp_acx_roster_entries` (Original Plan)

**Rejected**: "Roster entry" describes the UI location, not the domain concept. Creates naming ambiguity with the backend's nonexistent `roster_entries` table. Does not clarify the label vs entry-name dual-source problem.

### 2. `wp_acx_entities` (Generic)

**Rejected**: Premature generalization. Person-specific metadata (name, tags, reference photo) does not generalize to brands or objects. A polymorphic table would require discriminator columns and conditional validation that adds complexity without current benefit.

### 3. Keep `acx_roster_entries` as WP Option

**Rejected**: Options do not support indexing, pagination, relational integrity, or SQL joins. Not viable for a table that needs FK references from clusters.

## Consequences

### Positive

- Single source of truth for identity names (Person.name)
- Deterministic label derivation (no reconciliation logic)
- Identity stability across cluster lifecycle events
- Stable UUID sync contract from plugin person record to backend `roster_id`
- Clean extensibility path for future entity types
- No backend schema changes needed
- Eliminates `acx_roster_assignments` option entirely

### Negative

- "Person" is not immediately obvious as a face-recognition concept to new developers (mitigated by in-code documentation and this ADR)
- `person_id` FK column on clusters requires a schema addition to `wp_acx_clusters`
- `person_uuid` requires generation/backfill logic during create/import paths
- Label derivation rule must be consistently applied in all display paths (PHP and TypeScript)

## References

- [ADR-001: Face -> Identity Nomenclature Boundary](ADR-001-face-identity-nomenclature.md)
- [Roadmap v4](../../roadmaps/roadmap-v4.md)
- [Recognition UX Epic](../../epics/v0.2.0/recognition-ux-and-ergonomics-epic.md)
- [Phase 2 Task Plan](../../tasks/5.0/phase-2-recognition-ux-polish-task-plan.md)
- Backend schema: `apps/prototype-description-service/db/migrations/versions/001_identity_schema.py`
- Plugin clusters table: `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`
