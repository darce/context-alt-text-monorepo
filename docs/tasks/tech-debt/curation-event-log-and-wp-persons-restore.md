# Curation event log and WP persons restore (tech debt #29)

**Status:** deferred, scope in the wave after GPUFLOW-1 / plugin 0.0.22.
**Origin:** GPUFLOW-1 design review 2026-09-15 (handoff decision under `GPUFLOW-1`, session `gpuflow-1-orchestrator-20260915`), prompted by the finding that no cluster label exists in any service database while names live only in `wp_acx_persons.cluster_uuid`.
**Decision kept:** WordPress stays the sole system of record for person names (ADR-003, ADR-009 rejected "backend owns person labels after replay"); the service `identity_clusters.label` remains a derived copy fed by the curation outbox. No plaintext dual write (heuristics canon DATA-14; PII minimization MLDATA-13/15, PROV-12).

## Gaps this item closes

1. **Merge/split are not event-sourced.** `roster/application/curation_sync_service.py` `_CLUSTER_OPERATION_TYPES` (:57-68) carries `cluster_person_bound` / `cluster_label_updated` only. A manual merge or split is an irreproducible human decision (DDIA:604; architecture-hard-parts:28,449); losing the WP database loses it even though embeddings survive.
2. **No rehydration path.** `/retention/export` (export_service.py:246-254; class-retention-controller.php:80-109) is a privacy export (ADR-004), not a documented restore. There is no `wp_acx_persons` restore from `identity_clusters.label` + `curation_replay_records`. PG-10: an untested backup is not a backup; RLSE-10: drill restore within RTO.
3. **Reconnect conflict rule undefined.** After a WP restore from an older backup the two stores disagree; DATA-15 forbids last-writer-wins on human decisions.

## Scope (promote to a dated task plan before implementation)

- Outbox: add `cluster_merged` / `cluster_split` events (source, target, member ids, actor, occurred_at) so `curation_replay_records` is a real replay log (FLOW-06: derived stores heal from the log). Replay must be idempotent against the existing ledger keys.
- WP: `acx persons restore` (WP-CLI + admin Tools action) rebuilding `acx_persons(name, cluster_uuid)` from the service label column plus the replay ledger, dry-run first, per-row report.
- Reconciliation: order by outbox sequence, not wall clock; service ledger wins for events WP never emitted, WP wins for its own emitted events; true conflicts surface in the People screen (existing ux-map only, no new screens).
- Drill: runbook under `docs/runbooks/` with a rehearsed local restore (`make reset-local` fixture → export → drop persons → restore → diff), recorded as a `test_result`.
- Optional hardening, out of scope here: encrypted name escrow in the service.

## Acceptance

- Merge/split replay reproduces the same cluster topology on a fresh WP install.
- Restore drill completes with zero unmatched `cluster_uuid`s on the demo fixture.
- No new write path from WP to `identity_clusters.label` outside the outbox.
