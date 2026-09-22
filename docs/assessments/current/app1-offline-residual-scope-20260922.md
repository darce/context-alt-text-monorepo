# APP-1 offline residual scope — 2026-09-22

This is a bounded context/requirements census after the supplied landed
receipts. It does not re-review repaired scene, recognition, operator, worker,
or evaluator implementations, change MCP status, assign prices, or claim beta
or release readiness. The current checkout and the supplied receipts are the
authority; the older usage-fix document is used only for its frozen interface
contract, not as a current-failure report. `[GRPH-09][GRPH-31]` keep this
classification separate from implementation/review ownership.

## APP1-CONT-P02 — residual route census

The three scene compute POSTs are already offline-addressed by the scene receipt
(`fc1289f0b07fd31a731c689aba35799f4966ebee`, 152 tests), and the GPU,
clustering/recovery, and revert operator paths are already offline-addressed by
the operator receipt (`f8014e39dddc6c4b18e2f23975f9de63576fd2ef`, 28 tests).
Those lanes are not reopened here. The reconciliation report and route
inventory retain the residual census as open (`APP1-CONT-P02`; see
`app1-offline-evidence-reconciliation-20260922.md` and
`app-1-s0-route-metering-inventory.md`).

### Exact pending read route

| Route | Owning handler | Current classification | Seam mapping |
| --- | --- | --- | --- |
| `GET /recognition/jobs/{job_id}` | `recognition/interface_adapters/http/routers/analyze.py::get_job_status` | `FREE-POLL`: authenticated, tenant-scoped status/pipeline read; zero customer usage units; the existing per-key rate limit remains the only metering | It observes the job created by the compute POST. It must not call `admit_usage` or create a reservation. Compute admission remains `usage_admission.py::admit_usage`; terminal commit/release/recovery remains `UsageSettlementService::settle_job` / `recover_job`. |

The handler's pipeline resolution may select the linked follow-up job for the
response, but that is still a read and does not make polling billable. The
missing item is a receipt that enumerates this route, proves the authenticated
tenant predicate, and proves that the read leaves the usage ledger unchanged;
it is not a metering or settlement fix. This is consistent with the frozen
contract that status/result reads are tenant-scoped and free
(`[DDIA-TRANSACTIONS][DDIA-FENCING][RES-01][RES-02][DATA-03]`).

### Remaining OPEN-Q classifications

The current inventory's `OPEN-Q` rows are requirements decisions, not hidden
billable behavior. No price or unit count is inferred here.

| Exact route family in the current inventory | Owning surface | Residual decision |
| --- | --- | --- |
| Topology writes: `/recognition/clusters/{cluster_id}/dismiss` (POST/DELETE), `/{cluster_id}` (PATCH), `create-for-identity`, `/{cluster_id}/merge`, `/{cluster_id}/split`, `/topology-commands/split`, `/clusters/reassign`, `/{cluster_id}/assign`, and representative pin | topology router | Decide whether curation/topology work is free control-plane work or uses a separate bounded operational budget. If costly, name the admission/settlement owner; do not silently attach it to image units. |
| Suggestion reads/computation and accept/reject/bulk mutations: `/recognition/suggestions*`, `/recognition/clusters/{cluster_id}/roster-candidates`, and `/recognition/identities*/*suggestions` | suggestions router | Classify whether generation is costly and cap it; classify mutations as free control-plane work or the separate operational budget. |
| Retention mutations: `/recognition/retention/policy` (PATCH), `/policy/preset`, `/export`, `/purge`, and `/import` | retention router | Decide admission and byte/operational bounds. Export status/data and audit GETs remain `FREE-POLL` reads. |
| `PUT /recognition/tenant/naming-agreement` | tenant router | Decide the control-plane budget boundary; it is not an image-unit read. |
| `/admin/tenants*`, `/admin/keys*`, `/admin/`, and `/admin/ui/*` | admin router | Operator-only, outside customer entitlement and unmetered by customer usage; preserve the existing admin boundary and auditability. |

Adjacent unresolved census item: `POST /roster/curation/sync` is currently
unauthenticated and unmetered (`get_tenant_id` only). Before beta it needs an
explicit exclusion from the customer surface or an owned authentication and
operational-budget decision. It must not become an entitlement bypass. The
inventory also classifies demo `/x/*`, health/readiness, docs, and version
surfaces separately as public/operational traffic; they are not customer image
usage.

### Small offline follow-up DAG

There is one genuine offline gap: the route-census receipt, not a second fix or
review.

1. **P02-CENSUS (P / contract-inventory owner):** record the exact route list
   above, the `get_job_status` tenant/read-only assertion, and the
   `roster/curation/sync` auth/exclusion decision against the current inventory
   and already-landed receipts.
2. **Coordinator disposition:** record each OPEN-Q choice and assign any future
   costly-path implementation to its existing surface owner; only a decision
   that makes a path billable may depend on the landed G1 admission/worker
   settlement seam. `[GRPH-09][GRPH-31][RELEASE-IT-BOUNDS][PERF-13]`

No pricing choice is made by this assessment, and no new UX map or fixed-lane
review is proposed.

## APP1-CONT-P05 — evaluator and V-packet boundary

The evaluator enforcement change `b95948a6f0ec0e67435446ea9d1e0db19e8b28d2`
is offline-addressed by its 29-test receipt. The current runner now rejects
untyped/nonempty-only evidence, release-mode partial selection, zero/failed/
skipped evidence-only JUnit, missing or mismatched parametrized instances, and
missing required artifacts. That is enforcement proof, not a full V packet;
`APP1-CONT-P05` remains open as stated in
`app1-offline-evidence-reconciliation-20260922.md`.

The required declarations are in
`docs/scopes/app-altcontext-beta-clerk-polar-evals.json`:

- The beta gate requires `APP-SC-01` through `APP-SC-18`, fresh nonempty
  results, and sandbox/operational evidence. Expansion separately requires
  `APP-SC-19`; the paid gate requires `APP-SC-01` through `APP-SC-20` and
  explicit live-charge authorization.
- The manifest flags additional evidence for `APP-SC-04`, `09`, `10`, `12`,
  `14`, `15`, `16`, `17`, `18`, `19`, and `20`. Only `APP-SC-19` and
  `APP-SC-20` currently name literal artifacts:
  `docs/assessments/current/app1-beta-observation-report.md` and
  `docs/runbooks/evidence/app1-paid-release.json`. No artifact names are
  invented for the other flagged cases.

### Offline preparation versus external completion

| Cases | Can be prepared offline now | What still cannot be claimed offline |
| --- | --- | --- |
| `APP-SC-01`, `02`, `03`, `05`, `06`, `07`, `08`, `11` | Deterministic contract tests, fresh typed JUnit/provenance, and negative/fault-injection coverage can be prepared. | A fresh full-manifest result is still required; the evaluator's 29 unit tests are not these case receipts. |
| `APP-SC-13` | Local Clerk/Polar-outage fault injection and preservation of local API access can be prepared. | Any genuine provider outage rehearsal remains provider/account evidence, if required by the final V protocol. |
| `APP-SC-04`, `14` | A mocked/local browser harness, accessibility assertions, and typed artifact schema can be prepared. | The required two-tenant Clerk browser journey, deployed host/CSP loading, and browser-to-WordPress first-caption evidence await Clerk accounts and the live/staging host. |
| `APP-SC-09`, `15`, `16`, `17` | Test cases and artifact/provenance checks can be prepared; bounded local fault injection is useful. | V requires real PostgreSQL non-owner RLS/concurrency, reset-role denial, an authorized restore/replay drill, host-boundary probes, and actual alert/telemetry privacy evidence. Restore authorization and the native PG environment are not available here. |
| `APP-SC-10`, `12`, `18` | Fake-provider checkout, transition, signature, retry, and isolation fixtures can be prepared. | Genuine Polar sandbox checkout/webhook/cancel/refund/recovery and paid-transition evidence requires a provisioned Polar account/catalog/credentials; no fake fixture is live proof. |
| `APP-SC-19` | Only the report schema and evaluator declaration can be prepared. | The cohort study requires admitted users and observed attempts; its named report must not be fabricated. |
| `APP-SC-20` | Only the dossier schema/checklist can be prepared. | Merchant/catalog/notice/restore/rollback evidence and an explicitly authorized live transaction receipt necessarily await live-provider access and authorization. |

This follows Plan 0002 V: run the full declared testpaths with fresh JUnit and
provenance, then obtain real PostgreSQL/RLS, restore, host, alert/telemetry,
Clerk, Polar, and two-tenant browser evidence. The coordinator-supplied native
61-test receipt in `app1-offline-cross-slice-validation-20260922.md` is not a
substitute for that packet and is not rerun here. `[CARD-06][GRPH-14][RELEASE-IT-FAIL-CLOSED]`

### P05 disposition

No additional evaluator code task is justified in this lane. Offline work is
limited to preparing truthful typed case artifacts for the cases above and
preserving their exact case IDs; the remaining gate is external for the live
Clerk/Polar/browser/host/restore/cohort/paid portions. Accounts, credentials,
live services, protected environments, and live charges were not accessed.
P05 is not marked fixed, and no second evaluator fix/review is proposed.

## Evidence boundary

The supporting bounded documents are
`app-1-s0-route-metering-inventory.md`,
`app-1-s0-e16-7-disposition-matrix.md`,
`app1-offline-evidence-reconciliation-20260922.md`,
`app1-offline-cross-slice-validation-20260922.md`,
`app1-usage-schema-fix-groups-20260922.md`,
`docs/specs/app-portal-account-billing-spec.md`, and
`docs/plans/0002-app-altcontext-launch-continuation-task-plan.md`. Their
receipts distinguish source/feature evidence from live acceptance; they do not
close P02 or P05 or remove `HOST-RV01`.
