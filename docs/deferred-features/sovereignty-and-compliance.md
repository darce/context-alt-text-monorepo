# Deferred: Tenant Sovereignty, Encryption, and Compliance

## Source

Deferred from [recognition-state-reconciliation-and-offline-continuity-epic.md](../epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md) (v0.2.0), Deferred (Post-v0.2.0) section. Also surfaced in [remaining-sync-workbench-and-retention-epic.md](../epics/v0.2.0/remaining-sync-workbench-and-retention-epic.md) (v0.2.0), "Deferred Beyond This Epic" section.

## Why Deferred

These items represent architectural shifts beyond the current plugin-service boundary model. The v0.2.0 privacy posture is "minimized retention" and "auditable handling" -- not full tenant sovereignty. Implementing sovereignty tiers, key management, or region-pinning before the core sync and retention foundations are stable would over-engineer the MVP and create premature architectural lock-in.

**Prerequisite state that must exist before revisiting:**

- Stable delta ingest and drift reconciliation (v0.3.0 Phases 1-2).
- Proven retention export/import pipeline (v0.3.0 Phases 3-4).
- Operator trust established through the minimized-retention MVP.

## Deferred Items

### Sovereignty Tiers

> **Item**: Explore tenant-level sovereignty tiers where WordPress becomes the authoritative long-term store for embeddings and machine proposals.

WordPress currently acts as the operator-facing render authority (local projection), but the description service remains the authoritative compute and storage backend for embeddings and machine-derived clustering state. A sovereignty-tier model would let tenants opt into a configuration where WordPress holds the canonical embedding store and the backend becomes ephemeral compute-only.

This requires:

- A defined sovereignty-tier contract specifying which data classes move to WordPress custody at each tier level.
- A migration path for existing tenants from the current hybrid model to a higher sovereignty tier.
- Backend APIs that treat WordPress as a peer authority rather than a downstream consumer.
- A clear product narrative explaining to operators what each tier means for their data.

**Likely home when activated**: a new `tenant-sovereignty-tiers-epic.md` or a major phase of a v0.4.0 product architecture epic.

---

### Customer-Controlled Embedding Authority

> **Item**: Add customer-controlled embedding authority, ephemeral compute APIs, and sovereignty-tier deployment modes.

In the current architecture, embedding vectors are generated and stored by the description service. Tenants cannot control where embeddings are stored, how long they are retained, or whether the backend ever persists them at all. This item covers:

- An "ephemeral compute" mode where the backend generates embeddings on request but does not persist them beyond the clustering job lifecycle.
- A "bring your own storage" mode where embedding vectors are pushed to tenant-controlled infrastructure after generation.
- Sovereignty-tier deployment modes (e.g., on-premises, single-tenant cloud) that change the data residency model.

**Dependency**: sovereignty-tier contract above must be defined first.

**Likely home when activated**: same sovereignty tiers epic, or a dedicated deployment-modes epic.

---

### Tenant-Level Encryption and Compliance Controls

> **Item**: Add tenant-level encryption, key-management hooks, and region-pinning compliance features.

Current retention, export, and purge features operate at the application layer without per-tenant encryption or geographic data controls. This item covers:

- Per-tenant encryption keys for stored embeddings and biometric state (with a key-management hook so tenants can bring their own KMS).
- Region-pinning so that compute, storage, and export landing zones respect tenant geographic constraints.
- Compliance export formats aligned with GDPR Article 20 (data portability) and Article 17 (right to erasure) beyond the current "purge all" implementation.

**Dependency**: ephemeral compute and sovereignty-tier design must be resolved first, because encryption and region-pinning decisions interact with where data is stored.

**Likely home when activated**: compliance or enterprise-readiness epic, likely v0.4.0 or later.

---

## Relationship to v0.3.0

The v0.3.1 [sync-completion-and-retention-hardening-epic.md](../epics/v0.3.1/sync-completion-and-retention-hardening-epic.md) intentionally stops at export format versioning and embedding-level disposal tracking. It does not attempt sovereignty-tier deployment or per-tenant key management. These items remain deferred beyond v0.3.0.
