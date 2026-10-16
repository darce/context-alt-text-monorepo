# ADR-017: Description authority — WordPress curates, the service generates

- **Status:** Proposed (needs operator acceptance before DESCAUTH-1 implementation slices S1+)
- **Date:** 2026-10-16
- **Context task:** DESCAUTH-1
- **Extends:** [ADR-003](ADR-003-wordpress-local-authority-and-durable-outbox-replay.md) (recognition only) to image descriptions.
- **Heuristics (canon v0.26.2):** AGT-13, HAI-12, DATA-14, DOM-06, RES-17, PROV-01, PROV-09, HAI-06, HAI-02, STOR-07, STOR-05, MLDATA-15, INT-11, INT-07.

## Status

Proposed. Implementation in [DESCAUTH-1](../tasks/v0.5.0/DESCAUTH-1-description-authority-history-and-reset-task-plan.md) starts only after the operator accepts it. AGT-13 ("No silent ADR override") applies: ADR-003 rule 1 is already broken for descriptions, so this ADR makes the decision explicit before the code changes.

## Date

2026-10-16

## Context

ADR-003 makes the WordPress local projection the rendering authority. It also says admin reads must not depend on live backend reads, but it was written for recognition. Descriptions have no matching decision, and the code has drifted:

- Every operator-visible draft list reads live from the service:
  - `GET /acx/v1/recognition/describe/runs/{id}/items`, which serves the Review Queue `?run=` filter, the activity strip, bulk apply and the guided demo.
  - Bulk apply, which reads the live run status and the live items before it writes alt text.
- Run membership lives in options (`acx_describe_run_media_ids_<run>`). The WordPress tables built for runs (`wp_acx_description_runs`, `wp_acx_description_run_items`) are written only by the unused `DescriptionBulkRunService`.
- **No usable history.**
  - Backend `audit_events` holds `description.generated`/`description.cache_hit` with `{media_id, image_hash, adapter}` only. It has no retention, and no purge can erase it.
  - Mutable run items are overwritten.
  - On the WordPress side, only the latest provenance meta is kept per attachment.
- **No reset.**
  - Retention purge scopes are `disposed` and `all`. Both cover recognition tables only, so "All machine data" leaves every description behind.
  - "Regenerate" returns the cached draft, because the cache key is unchanged.
- The "Description Runs" admin page is a redirect with no remaining function.

### Constraints from prior review

- Greenfield: edit `001_identity_schema.py` and the WordPress `CREATE TABLE` statements directly. Delete dead code; don't flag it off.
- The epic authority split (recognition-state-reconciliation epic): WordPress owns operator-visible state and curation; the service owns compute outputs and machine proposals.

## Current State Inventory

| Surface | Today | Owner after this ADR |
| --- | --- | --- |
| Generated draft (cache `image_descriptions`, run items) | service | service (sole writer) |
| Draft shown for review/apply | live proxy read | WordPress projection `wp_acx_description_run_items` |
| Run membership | WordPress options | `wp_acx_description_runs` + items |
| Applied alt text, provenance meta, human edits | WordPress meta | WordPress (sole writer) |
| Generation history | none (audit has 3 fields) | service `image_description_generations` |
| Curation history | latest meta only | WordPress `wp_acx_description_events` |
| Reset/wipe | none | WordPress-first + outbox `descriptions_purged` |

### Downstream surfaces that must migrate together

- The items route and the apply route in `class-describe-controller.php`.
- `wp_acx_description_run*` DDL in `class-life-cycle-manager.php`.
- The `VisualFactsResponse` contract (`docs/workbay/contracts/image-description-api.md`): add `generation_id`.
- Retention purge scopes, on both the WordPress and service sides.

## Decision

### Chosen design rules

1. **Generation authority.** The description service is the only writer of generated descriptions: the cache, run rows and run items, and the generation log. WordPress never writes them.
2. **Curation authority.** WordPress is the only writer of the following:
   - alt text and description provenance meta;
   - human edits, discards and resets;
   - the curation event log.

   The service never stores applied alt text or human corrections (HAI-12: output is a proposal).
3. **Local reads.**
   - Every draft that an operator can review or apply is read from the WordPress projection.
   - Two bounded exceptions are allowed:
     - (a) Run *progress* (`GET …/runs/{id}`) may proxy live, because it is a compute-status read. When the service is unreachable it must fall back to the local run row, never to an error.
     - (b) The single-image describe `POST` is a command, and its response carries the draft.
   - No other description read may proxy.
4. **Projection by derivation (DATA-14).**
   - WordPress *derives* the projection from the service by pulling; it never writes it as a second source.
   - Pulls happen on submit, from an Action Scheduler backstop, and as one bounded refresh when an operator reads a non-terminal run.
   - A run is complete for WordPress only when its terminal status has been projected (ADR-003 rule 9). After that, it never calls the service again.
5. **Two append-only histories, joined by `generation_id`.**
   - The service writes one `image_description_generations` row per describe outcome (`generated` or `cache_hit`).
     - Each row carries adapter, model, version, prompt/task version, tier, hashes and timing (PROV-01, PROV-09).
     - It also carries the adapter output *before* identity weaving.
     - It never carries the woven named draft, the applied names or cluster ids.
   - WordPress writes `wp_acx_description_events` (`applied`, `corrected`, `discarded`, `reset`) with the same `generation_id` (HAI-06, HAI-02).
   - `audit_events` stays a security trail. It is not history.
6. **Reset is a WordPress-first replayable mutation (DOM-06, RES-17).**
   - In one `run_transactional` call, WordPress clears its local description state and enqueues an outbox op, `descriptions_purged`.
   - The service purge is idempotent.
   - While that op is pending, WordPress refuses describe submissions and new resets, so a late replay cannot delete newer drafts.
   - Reset is refused while a run is active.
   - Alt text with a human edit is kept unless the operator opts in.
7. **Purge scopes.**
   - `descriptions` deletes the service cache, runs, items and terminal describe operations. It keeps the generation log, because that is the history.
   - `all` additionally deletes the generation log and all description tables, so "All machine data" becomes true.
   - The generation log has a fixed age limit of 365 days, applied by the startup retention purge (MLDATA-15).
8. **Benchmarks are derived (STOR-07, STOR-05).**
   - Accuracy and performance comparisons use a local SQLite export built from the two logs, keyed by image sha256 and `generation_id`.
   - The export is never a source of truth, and it never goes into Git, MCP or prompts. It is separate from the FIRBENCH private DB.
9. **Per-image recovery over tenant wipe (INT-11).**
   - "Regenerate" bypasses the cache and replaces the cache row.
   - "Reset this description" discards the draft and, when the alt text is still unedited AI output, clears that alt text and its provenance.
   - The tenant-wide reset is the last resort, with preview counts (INT-07).
10. The "Description Runs" admin page is removed. History is reached through the Review Queue and the event log.

### Target outcome

With the service stopped, the Review Queue still shows every draft from completed runs, and bulk apply still works. A reset of #116 clears its AI alt text locally at once and erases the service copy when the outbox drains. Every applied alt text can be traced back to the generation that produced it.

## Why This Decision

### One writer per fact

Drafts are generated in one place and curated in one place, so the two copies cannot diverge silently. The projection is a derived copy (DATA-14).

### Offline continuity matches recognition

The same ADR-003 guarantees now hold for descriptions: local reads, outbox replay and explicit acknowledgement.

## Alternatives Considered

### 1. Keep live reads, add a cache with a short TTL

Rejected. The read still depends on the service, the TTL invents freshness, and apply would still race the service (RES-08).

### 2. Use `audit_events` as the history

Rejected. Audit events have no retention or purge, and making them erasable weakens the security trail. Payloads would also have to grow to carry lineage.

### 3. Service-first synchronous purge (the current recognition pattern)

Rejected for descriptions. With the service down, the operator could not reset at all, and the WordPress state would stay stale until a later pull.

## Consequences

### Positive

- Review and apply keep working offline.
- Lineage is complete, and accept/edit rates become measurable (AIPX-02).
- Reset is honest and recoverable.

### Negative

- Schema changes on both sides force the greenfield wipe on the next deploy.
- There is a new pull job to keep alive.
- Projected drafts lag the service by up to one pull interval.

### Guardrails for the follow-on implementation task

- No proxy fallback in the items route or the apply route. If the projection is missing, return the local result with `projection.stale=true`.
- Status values are enums: PHP backed enums, Python `StrEnum` (sr-007).
- `generation_id` is passed through verbatim and never synthesized (rg-015).
- The pull job tracks no-progress cycles per run and stops after a bound (rg-007).

## References

- [ADR-003](ADR-003-wordpress-local-authority-and-durable-outbox-replay.md)
- [recognition-state-reconciliation epic](../epics/v0.2.0/recognition-state-reconciliation-and-offline-continuity-epic.md)
- `docs/workbay/contracts/image-description-api.md`
- Canon v0.26.2 rows (`lexicons/`):
  - `engineering.md`: `#agt-13`, `#data-14`, `#dom-06`, `#res-17`, `#stor-05`, `#stor-07`
  - `ml-systems.md`: `#prov-01`, `#prov-09`, `#mldata-15`
  - `interaction-ux.md`: `#hai-02`, `#hai-06`, `#hai-12`, `#int-07`, `#int-11`
  - `business-marketing.md`: `#aipx-02`
