# Hardening Plan — `apps/prototype-wp-alt-context`

**Task ref:** `MAINT-WPAC-HARDEN-20260614`
**Branch / worktree:** `feature/maint-wpac-harden-20260614` · `context-alt-text-monorepo-maint-wpac-harden-20260614`
**Baseline:** `main` @ `8fc7ff71` (post cleanup+hardening merge).
**Finding sources (live in MCP — query, do not duplicate here):**
- Defects: `MAINT-wpac-defect-review-20260614` (`review_findings(operation="list", task_ref=...)`)
- Deferred refactors: `MAINT-wpac-arch-deadcode-review-20260613`

> Scope: the 10 open defects + 5 deferred refactors that the two `/review-parallel` passes surfaced but the prior branch deliberately did not land (each needs an interface/SQL/schema change or a characterization-test safety net). Behavior changes here are bug fixes (feature hat), not refactors — keep them in separate commits from the ARCH refactors (Two Hats, Fowler Ch2).

---

## TL;DR — slice order (ROI × safety)

Safety net first, then the data-integrity quartet, then contract/resilience, then the deferred refactors. Char-tests-first is mandatory for every SQL/concurrency fix — the existing suite does not pin the racing/version behavior these fixes change.

| # | Slice | Findings addressed | Risk | Gate emphasis |
|---|---|---|---|---|
| 0 | Safety net | TST-1, TST-2 | low | new tests must fail first, then the prod guard makes them pass |
| 1 | Concurrency data-integrity | COR-1, CON-1, COR-2, CON-3, CON-4 | high | char-tests-first; per-fix gates |
| 2 | Contract + resilience | BND-1, COR-3, CON-5 | med | contract regen + boundary tests |
| 3 | Deferred refactors | ARCH-6, ARCH-1, ARCH-5, ARCH-7, DC-10 | mixed | behavior-preserving; tests prove unchanged |

---

## Slice 0 — Safety net (do first)

The defect review confirmed two false-confidence tests; fixing them hardens the net the next slices depend on.

- **0.1 — Enqueue-failure ROLLBACK coverage (TST-1).** Add per-service enqueue-fail tests (`ClusterMutationsOutboxWriterSpy` with `nextEnqueueResult=false`) for Lifecycle (dismiss/undismiss), Label, and Merge/revert-merge, mirroring the existing Membership/Representative tests; rename the misnamed `*RollbackWhenOutboxEnqueueFails` cases to reflect that they exercise COMMIT failure. Assert ROLLBACK + no COMMIT.
- **0.2 — Schema-parity guard derives columns from SQL (TST-2).** In `ClustersSchemaParityTest` / `IdentityMembersSchemaParityTest`, parse the referenced-column set out of the repository SQL and assert it is a subset of the parsed DDL columns (keep the allowlist as a secondary check); soften the over-stated docstring.

**Gate:** `composer test` (new tests RED before the change where they assert a real guard, GREEN after) · `phpstan` · `cs-check`.

---

## Slice 1 — Concurrency data-integrity (the corruption quartet + critical)

Each item: write a characterization/regression test that reproduces the wrong outcome FIRST, then apply the fix.

- **1.1 — Snapshot version-monotonicity guard (COR-1, critical).** Gate every overwritten data column in `ClusterSnapshotMerger::merge_snapshot_batch_for_tenant` and `IdentityMemberSnapshotMerger` on the incoming version (`IF(VALUES(snapshot_version) >= snapshot_version, VALUES(col), col)`); make member `projection_version` use `GREATEST`; add an early-return in `SnapshotProjector::project()/project_delta()` when `incoming_version <= get_snapshot_version(tenant)` for full snapshots; skip `delete_stale_non_curated_rows` for an older-than-current snapshot. Test: project v5 then v4, assert v5 data survives and version stays 5.
- **1.2 — Lost-update on `identity_count` (CON-1, high).** Replace the absolute `update_identity_count` write on the mutation paths with an atomic relative delta (new `adjust_identity_count($uuid, $delta)` → `SET identity_count = GREATEST(0, identity_count + %d)`), or recompute under `SELECT … FOR UPDATE` inside the transaction. Note the interface ripple: ~10 test doubles implement `ClustersRepositoryInterface` and must gain the new method. Test: two concurrent reassigns into one cluster end at +2, not +1.
- **1.3 — Applied split-command infinite retry (COR-2, high).** Add a reconcile-attempt counter (dedicated column, independent of dispatch attempts) in the `applied` reconcile path of `SplitTopologyCommandDrain`; transition to terminal `failed` past `resolve_max_attempts()`. Test: a permanently-unreconcilable applied command stops re-fetching after N drains.
- **1.4 — Outbox drain row-claim (CON-3, med).** Atomically claim before dispatch (`UPDATE outbox SET status='in_flight', claimed_at=NOW() WHERE status='pending' … LIMIT n`, then select claimed ids — or `FOR UPDATE SKIP LOCKED`); guard `apply_result` `WHERE` on the claim. Test: concurrent drains do not double-increment `attempts`.
- **1.5 — Split-topology command-claim (CON-4, med).** Claim commands before processing and add the expected-status guard to `update_status`/`mark_reconciled`/`record_failure` `WHERE` clauses so a stale worker's terminal write is a no-op. Test: an interleaved user reassign is not reverted by a second drain.

**Gate per item:** `composer test` · `phpstan` · `cs-check`; `composer dump-autoload` for any new class; verify SQL column names against the live DDL (rg-005). Concurrency acceptance asserts the fix **mechanism** — atomic relative-delta SQL is emitted; a claim `UPDATE` affects 0 rows under a simulated stale-status precondition; the `WHERE`-status guard is present — because PHPUnit cannot deterministically reproduce a true race (PA-2).

---

## Slice 2 — Contract + resilience

- **2.1 — `completed_with_errors` terminal status (BND-1, med).** Add the value to the source schema `recognition-job.schema.json`, regenerate (`npm run generate:contracts`), centralize terminal-status detection in an `as const`/enum (sr-007), and treat it as success-with-partial at `useJobStateMachineEffects.ts:115`; audit other `status === 'completed'` consumers. Cross-package: coordinate with the description-service `JobStatus`.
- **2.2 — Stop fabricating suggestions `total` (COR-3, low, rg-015).** In `SuggestionsController`, do not synthesize `total` from `count(page)`; either forward a real upstream envelope total or surface a server-side backlog count, else omit the authoritative total.
- **2.3 — Atomic circuit-breaker counter (CON-5, low).** Replace the transient read-modify-write in `record_proxy_failure` with an atomic counter (`wp_cache_incr` / DB row delta / short named lock) so concurrent failures trip the breaker deterministically at threshold.

**Gate:** TS `typecheck`/`lint`/`test` for 2.1; `composer test` for 2.2/2.3; `make check-all` before review-ready.

---

## Slice 3 — Deferred refactors (behavior-preserving)

- **3.1 — Co-locate single-consumer hooks (ARCH-6, quick win).** Merge the 7 conflict/outbox/dead-letter hooks into `useConflictHooks.ts` + `useOutboxHooks.ts`; update the 3 consumers + tests. No signature changes.
- **3.2 — Flatten the job state machine (ARCH-1, high value).** With Slice 1.x + COR-4/BND-1 characterization tests as the net: inline `useJobStateMachineDerivedState`'s memos into `useJobStateMachine`, merge `jobStateMachineRuntime.ts` + `jobStateMachineUtils.ts`; ~12 files → ~6. This is the "agents get lost" target — do it only with the status/progress-string char tests green.
- **3.3 — Inline `ClusterFacade` (ARCH-5).** Inline `list_top_unlabeled` into `ClusterReadService`, drop the `ClusterFacade` field + ctor param from `ClusterReadDependencies` + the 2 controllers; migrate `ClusterFacadeTest`/`ClusterReadServiceTest`/`SnapshotProjectorTest`.
- **3.4 — `SnapshotClientTransport` composition (ARCH-7).** Replace the false IS-A REST-controller inheritance with a shared `proxy_request`/`get_tenant_id` trait. NOT purely behavior-preserving — characterization tests first.
- **3.5 — `RecognitionController` forwarders (DC-10).** Decide whether `RecognitionController` stays a facade; if removing the 16 forwarders, re-seat the ~15 XMP-refresh integration tests onto sub-controller seams (add a test-only accessor or restructure).

**Gate:** full `make check-all`; tests prove behavior unchanged; cite the named technique per refactor.

---

## Context and Ownership

- **Owner:** branch `feature/maint-wpac-harden-20260614`, single-agent.
- **Upstream:** based on `main` @ `8fc7ff71` (cleanup + first defect-hardening merged). No cross-team blockers; Slice 2.1 touches the shared `recognition-job.schema.json` contract.
- **Two Hats:** bug-fix commits (Slices 0–2) stay separate from refactor commits (Slice 3).

## Consolidated Checklist

Slice 0 — Safety net
- [x] 0.1 per-service enqueue-fail ROLLBACK tests, Lifecycle/Label/Merge (TST-1)
- [x] 0.2 schema-parity guard derives referenced columns from SQL (TST-2)

Slice 1 — Concurrency data-integrity
- [x] 1.1 snapshot version-monotonicity guard on data columns + projector gate (COR-1, critical)
- [x] 1.2 atomic relative-delta identity_count (CON-1)
- [x] 1.3 reconcile-attempt cap + terminal failed state (COR-2)
- [ ] 1.4 outbox drain row-claim + apply_result status guard (CON-3)
- [ ] 1.5 split-topology command-claim + status-guarded terminal writes (CON-4)

Slice 2 — Contract + resilience
- [ ] 2.1 completed_with_errors terminal status across schema + effects (BND-1)
- [ ] 2.2 stop fabricating suggestions total (COR-3, rg-015)
- [ ] 2.3 atomic circuit-breaker failure counter (CON-5)

Slice 3 — Deferred refactors (behavior-preserving)
- [ ] 3.1 co-locate single-consumer conflict/outbox hooks (ARCH-6)
- [ ] 3.2 flatten job state machine, char-tests-first (ARCH-1)
- [ ] 3.3 inline ClusterFacade (ARCH-5)
- [ ] 3.4 SnapshotClientTransport composition over inheritance (ARCH-7)
- [ ] 3.5 RecognitionController forwarders decision + test re-seat (DC-10)

## Review Readiness

- [ ] every slice's tests green at branch HEAD (composer test · vitest · typecheck · lint · phpstan · cs-check)
- [ ] `make check-all` clean
- [ ] each addressed finding resolved/deferred in its source review task (MAINT-wpac-defect-review-20260614 · MAINT-wpac-arch-deadcode-review-20260613)
- [ ] zero open findings on MAINT-WPAC-HARDEN-20260614; fresh test_result tied to HEAD; slice-complete decisions recorded

## Success Criteria

- **COR-1:** an out-of-order snapshot cannot regress projection data (test proves v5 data survives a later v4 merge; version stays 5).
- **CON-1 / CON-3 / CON-4:** count + drain paths are race-safe by construction — atomic delta, claimed rows, status-guarded terminal writes (asserted via the mechanism per PA-2).
- **COR-2:** an unreconcilable applied split command reaches terminal `failed` within N drains instead of looping forever.
- **BND-1:** a `completed_with_errors` scan triggers the immediate identity/cluster/suggestion refresh.
- **Slice 3:** refactors land behavior-preserving (suite unchanged); ARCH-1 only after its status/progress char-tests are green.

## Close

Per-slice: review pass + findings in MCP (never inline — Review Findings Placement) → resolve/defer → `handoff_close_check(enforce=True)` → slice-complete decision. Merge via `make finalize-plan` → merge → `make task-finish`. Findings above are referenced by ID only; their live status is in the two review tasks' MCP rows.
