# ADR-003: WordPress Local Authority and Durable Outbox Replay

**Date**: March 10, 2026
**Status**: Accepted
**Context**: Recognition state reconciliation, offline continuity, durable curation replay

---

## Context

The recognition product now operates across two stores with different responsibilities:

1. **WordPress plugin (MySQL)** renders the operator-visible recognition UI and stores local curation.
2. **Description service (Postgres)** performs machine compute such as detection, clustering, and proposal generation.

That split is necessary for offline usability, but it creates an architectural question: how should local curation and backend machine state stay aligned without silent overwrite, duplicate mutation processing, or a brittle dual-write model?

The earlier system shape was not explicit enough. It allowed local projection reads and some curation preservation, but it did not define a durable contract for:

- recording local operator intent while offline,
- replaying that intent safely when connectivity returns,
- rejecting stale replays cleanly,
- distinguishing machine proposals from curated local truth,
- preventing the backend from being treated as the live UI source of truth.

The key decision is whether the product should behave like:

- a dual-write or active-active system where both stores can overwrite each other directly, or
- a local-authority system where WordPress renders and curates state locally, while backend compute is imported as proposals and local intent is replayed durably.

## Decision

**WordPress is the operator-visible source of truth, and all local curation mutations must be recorded durably in an outbox and replayed to the backend with idempotency and expected-base-version semantics.**

### Architecture

```text
Backend compute
  analyze -> clustering -> machine proposal export
                                      |
                                      v
WordPress projection store
  machine state projection + local curation overlay
                                      |
                                      v
WordPress outbox
  durable local intent records
                                      |
                                      v
Backend curation replay endpoint
  idempotent apply / acknowledge / conflict
```

### Key Rules

1. **WordPress local projection is the rendering authority.** Admin reads and operator workflows must not depend on live backend reads.
2. **User curation is authoritative.** Backend machine clustering is advisory until it is projected locally and accepted under curation-preserving rules.
3. **Every replayable local mutation writes locally first and inserts an outbox record in the same transaction.**
4. **Outbox delivery is at-least-once, not at-most-once.** Safety comes from idempotency keys and conflict detection, not from assuming a request runs only once.
5. **The backend must deduplicate by idempotency key.** Retrying the same outbox operation must return the same acknowledgement or conflict result.
6. **Replay uses `expected_base_version`.** If local intent is built on stale backend state, the backend must reject it as a conflict rather than silently applying it.
7. **Conflicts are explicit records, not implicit behavior.** Divergence between local curation and backend state must be stored and surfaced for review.
8. **Projection acknowledgement is part of pipeline completion.** Backend compute is not operator-complete until WordPress has projected the resulting machine state.
9. **The system is not active-active.** Backend state is compute state plus acknowledged curation alignment; it is not the live authority for rendered UX state.

## Rationale

### 1. Offline usability requires a real local authority

If the plugin UI depends on live backend reads, operators lose access to clusters, identities, and curation during backend outages. The product requirement is the opposite: useful local reads and durable local edits even during connectivity loss.

Making WordPress the rendering authority gives the UI one place to read from consistently.

### 2. Dual-write semantics are brittle under network failure

A direct "write local and write backend" model cannot guarantee whether a failed request means:

- the backend never saw the mutation,
- the backend applied it but the response was lost,
- the backend rejected it because state moved on.

The outbox pattern resolves this ambiguity by preserving intent durably and replaying it with stable identifiers.

### 3. Idempotency is required for safe retry

Once delivery is allowed to retry after timeouts or worker restarts, the backend must treat repeated submissions of the same logical mutation as the same operation. Otherwise retries can duplicate bindings, merges, or version changes.

Idempotency keys make replay safe without requiring exactly-once transport.

### 4. Expected-base-version protects against silent lost updates

Local curation can be made while backend clustering continues to evolve. A replayed mutation must prove what backend state it was based on. If the backend has moved forward, the system must record a conflict rather than silently applying an outdated local intent on top of newer machine state.

### 5. Proposal import and curation replay are different flows

Backend snapshots or deltas are machine proposals imported into WordPress projection state. Outbox replay is local operator intent being pushed back to the backend. Treating both directions as the same kind of sync would blur authority boundaries and make conflict semantics harder to reason about.

### 6. Projection acknowledgement closes the pipeline contract

The backend may finish compute before the operator can actually see the result. Treating compute completion as final before WordPress projection would leave scan/clustering lifecycle reporting incomplete and make retention or disposal semantics premature.

## Alternatives Considered

### 1. Live backend authority for reads and writes

**Rejected**: breaks offline usability and makes the plugin UI dependent on backend availability.

### 2. Best-effort dual write without durable outbox

**Rejected**: cannot safely distinguish transient failure from partial success, and provides no durable recovery path after outages or worker interruption.

### 3. Active-active dual master between plugin and backend

**Rejected**: too complex for the MVP, conflicts with curation-first UX, and encourages silent overwrite or hidden reconciliation logic.

### 4. Event sourcing everything immediately

**Rejected**: potentially valuable later, but overbuilt for the current launch needs. Versioned projection plus durable replay is sufficient for the current product scope.

## Consequences

### Positive

- Operators can keep working against local state while the backend is unavailable.
- Local mutation intent survives crashes, timeouts, and drain restarts.
- Retry behavior is well defined through idempotency keys.
- Version conflicts become explicit reviewable records instead of silent corruption.
- Pipeline completion can reflect what the operator can actually see locally.
- The authority split between plugin UX state and backend compute state is easier to reason about.

### Negative

- The system now requires outbox, conflict, and sync-state storage plus background drain behavior.
- Mutation handlers must preserve transaction boundaries between local write and enqueue.
- Backend APIs must implement idempotency retention and version-aware conflict handling.
- Operators may need conflict resolution UX for cases that used to fail silently.
- Retention and audit semantics become part of the architecture once projected machine state is acknowledged and later disposed.

## Implementation Notes

- WordPress stores projected machine state, curation overlays, outbox rows, sync state, and conflict records.
- Replayable local mutations insert outbox rows with `idempotency_key`, `expected_base_version`, payload, and status metadata.
- The backend persists replay results so the same idempotency key can be answered deterministically on retry.
- Snapshot or delta imports must preserve curated local fields according to the curation-first merge contract.
- Compound topology operations require explicit conflict ownership and resolution rules; they must not be treated as naive single-row updates.
- Tenant retention policy and audit infrastructure sit on top of this architecture and depend on projection acknowledgement semantics.

## References

- [ADR-001: Face -> Identity Nomenclature Boundary](ADR-001-face-identity-nomenclature.md)
- [ADR-002: Person as First-Class Local Entity](ADR-002-person-as-first-class-local-entity.md)
- [Curation Sync API](contracts/curation-sync-api.md)
- [Recognition State Reconciliation + Offline Continuity Epic](../epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md)
- Plugin outbox implementation:
  - `apps/prototype-wp-alt-context/src/sovereign/sync`
- Plugin lifecycle/schema entrypoint:
  - `apps/prototype-wp-alt-context/src/support/class-life-cycle-manager.php`
