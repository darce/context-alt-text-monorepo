# INV-NEXTVER-01 Unimplemented Inventory

Status-tagged inventory of planned-but-unshipped work (scoped sources only).

## v0.4.1

| id/title | path | status | evidence | value | size |
|---|---|---|---|---|---|
| source missing | docs/tasks/v0.4.1/ | — | directory absent | — | — |

## v0.5.0

| id/title | path | status | evidence | value | size |
|---|---|---|---|---|---|
| CRM-1: CRM-1. Customer & Tenant Management — CRM-Ready Admin | v0.5.0/CRM-1-customer-tenant-management-task-plan.md | not-started | checks 0/18 | Enrich `tenants` and `api_keys` with customer identity and credential provenance, | M |
| DS-2B: DS-2B. Shared demo compute budget across analyze + | v0.5.0/DS-2B-demo-shared-compute-budget-task-plan.md | not-started | checks 0/16 | A demo-tenant API key draws every GPU/compute call — recognition | M |
| RONLY-1: RONLY-1. Remote-Only Recognition & Key-Driven Tenanting | v0.5.0/RONLY-1-remote-only-recognition-task-plan.md | not-started | checks 0/18 | Collapse the plugin to a single remote recognition path against | M |
| E16-1: E16-1. Bounded iteration caps across REST + repos | v0.5.0/E16-1-bounded-iteration-caps-task-plan.md | shipped | checks 31/31 | Every REST controller and lifecycle-migration site listed under §3.1 (RX-3, | M |

## tech-debt

| id/title | path | status | evidence | value | size |
|---|---|---|---|---|---|
| REFA-1: REFA-1. Decompose `class-cluster-mutations-controller.php` | tech-debt/REFA-1-cluster-mutations-controller-task-plan.md | not-started | checks 0/19 | Reduce `src/api/class-cluster-mutations-controller.php` (1257 LOC, 21 declared methods, 11 `acx/v1` routes) | M |
| REFA-10: REFA-10. Close characterization-fixture drift recurrence (clusters-read symmetry + | tech-debt/REFA-10-characterization-fixture-drift-recurrence-task-plan.md | not-started | checks 0/15 | Stop characterization golden-fixture drift from recurring. REFA-8 repaired two of | M |
| REFA-2: REFA-2. Decompose `class-clusters-repository.php` | tech-debt/REFA-2-clusters-repository-task-plan.md | not-started | checks 0/22 | Reduce `src/sovereign/repositories/class-clusters-repository.php` (1164 LOC, 34 declared methods — 21 public | M |
| REFA-4: REFA-4. Decompose `class-analysis-jobs-controller.php` | tech-debt/REFA-4-analysis-jobs-controller-task-plan.md | not-started | checks 0/22 | Reduce `src/api/class-analysis-jobs-controller.php` (1144 LOC, 35 declared methods, 8 `acx/v1` routes) | M |
| REFA-5: REFA-5. Decompose `class-identity-members-repository.php` | tech-debt/REFA-5-identity-members-repository-task-plan.md | not-started | checks 0/22 | Reduce `src/sovereign/repositories/class-identity-members-repository.php` (1045 LOC, 28 declared methods incl. constructor — | M |
| REFA-7: REFA-7. Decompose `class-clusters-controller.php` | tech-debt/REFA-7-clusters-controller-task-plan.md | not-started | checks 0/22 | Reduce `src/api/class-clusters-controller.php` (770 LOC, 23 declared methods, 5 `acx/v1` GET | M |
| REFA-9: REFA-9. Extract `run_transactional(callable)` — sr-009 Transaction Wrapper Migration | tech-debt/REFA-9-run-transactional-task-plan.md | not-started | checks 0/21 | Introduce one shared `run_transactional( callable )` wrapper and migrate the | M |
| local-vs-oci-description-ser: Local vs OCI Description-Service: Drift Detection & Consolidation/Retirement | tech-debt/local-vs-oci-description-service-drift-and-retirement.md | not-started | Deferred (tech-debt registry entry) | Local vs OCI Description-Service: Drift Detection & Consolidation/Retirement Decision | S |
| migrate-pip-to-uv: Migrate pip to uv for dependency installation | tech-debt/archive-or-transfer-candidates/migrate-pip-to-uv.md | not-started | checks 0/4 | Migrate pip to uv for dependency installation | S |
| oci-staging-environment-not-: OCI Staging Environment Not Deployed | tech-debt/oci-staging-environment-not-deployed.md | not-started | no checklist | OCI Staging Environment Not Deployed | S |
| plugin-licensing-and-multi-t: Plugin Usage, Licensing, and Multi-Tenancy Models | tech-debt/plugin-licensing-and-multi-tenancy.md | not-started | no checklist | Plugin Usage, Licensing, and Multi-Tenancy Models | S |
| slice9-representative-select: Slice 9 increment 3 — RepresentativeSelector extraction (task | tech-debt/slice9-representative-selector-extraction-plan.md | not-started | planned | Extract the representative-selection concern out of the 1064-LOC `AssignmentWriter` god-class | S |
| trivial-test-harness-hangs: Trivial test harness hangs | tech-debt/trivial-test-harness-hangs.md | not-started | checks 0/5 | Trivial test harness hangs | S |
| vlm-description-unplanned-fe: VLM / Description-Service: Unplanned Feature Gaps | tech-debt/vlm-description-unplanned-feature-gaps.md | not-started | backlog no owner | VLM / Description-Service: Unplanned Feature Gaps | S |
| wp-alt-context-initial-refac: Initial Refactoring Plan — `apps/prototype-wp-alt-context` | tech-debt/wp-alt-context-initial-refactoring-plan.md | not-started | no checklist | Initial Refactoring Plan — `apps/prototype-wp-alt-context` | S |
| REFA-3: REFA-3. Tokenize `js/admin/styles/components/_workbench.scss` | tech-debt/REFA-3-workbench-scss-tokenization-task-plan.md | partial | checks 8/36 | Replace raw style literals in `_workbench.scss` with `--acx-*` design tokens | L |
| REFA-6: REFA-6. Simplify the sync drains (`split-topology-command-drain` + `outbox-drain`) | tech-debt/REFA-6-sync-drains-task-plan.md | partial | checks 1/20 | Simplify the two sync drains — `src/sovereign/sync/class-split-topology-command-drain.php` (799 LOC, 21 | M |
| REFA-8: REFA-8. Repair characterization-fixture pretty-vs-compact drift | tech-debt/REFA-8-characterization-fixture-drift-task-plan.md | partial | checks 2/13 | Restore the two failing characterization suites — `AnalysisJobsControllerCharacterizationTest` (10) and | M |
| correlation-dashboards: Cross-Tenant Correlation Dashboards | tech-debt/correlation-dashboards.md | partial | checks 2/6 | Cross-Tenant Correlation Dashboards | S |
| current-debt: Deferred (Document as Tech Debt) | tech-debt/current-debt.md | partial | checks 3/25 | Deferred (Document as Tech Debt) | M |
| lane-orchestration-followups: Lane Orchestration Follow-Ups | tech-debt/archive-or-transfer-candidates/lane-orchestration-followups.md | partial | Open checks 1/5 | Lane Orchestration Follow-Ups | S |
| maint-aomcp-quality-fixes-20: MAINT-AOMCP-QUALITY-FIXES-20260419 — Task Plan | tech-debt/archive-or-transfer-candidates/maint-aomcp-quality-fixes-20260419.md | partial | checks 2/5 | MAINT-AOMCP-QUALITY-FIXES-20260419 — Task Plan | S |
| pds-pipeline-stability-26: PDS Pipeline Stability (`pds-pipeline-stability-26`) | tech-debt/archive-or-transfer-candidates/pds-pipeline-stability-26-task-plan.md | partial | checks 38/48 | Land five literature-backed fixes from [docs/assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md](../../assessments/clustering-pipeline-postgres-refactor-literature-2026-04-26.md): per-call timeouts on external | L |
| refactoring-evaluation: Refactoring Evaluation: Code Smells and Opportunities | tech-debt/refactoring-evaluation.md | partial | checks 3/26 | Refactoring Evaluation: Code Smells and Opportunities | M |
| refactoring-typescript-evalu: Refactoring Evaluation: TypeScript Code Health | tech-debt/refactoring-typescript-evaluation.md | partial | checks 1/6 | Refactoring Evaluation: TypeScript Code Health | S |
| refactoring-ui-evaluation: Refactoring Evaluation: UI Design System | tech-debt/refactoring-ui-evaluation.md | partial | checks 1/7 | Refactoring Evaluation: UI Design System | S |
| rename-database-context-alt-: Rename Database: context_alt_text → alt_context | tech-debt/rename-database-context-alt-text-to-alt-context.md | partial | checks 3/6 | Rename Database: context_alt_text → alt_context | S |
| retry-attempt-observability: Retry/Attempt-Level Observability | tech-debt/retry-attempt-observability.md | partial | checks 2/7 | Retry/Attempt-Level Observability | S |
| rewrite-git-history-remove-c: Rewrite Git History to Remove Co-Authored-By Trailers | tech-debt/rewrite-git-history-remove-coauthored-by.md | partial | checks 2/5 | Rewrite Git History to Remove Co-Authored-By Trailers | S |
| scan-pipeline-trust-and-data: Scan Pipeline Trust & Data-Plane Canonicalization | tech-debt/scan-pipeline-trust-and-data-plane-canonicalization.md | partial | Scope stub for review checks 38/50 | Scan Pipeline Trust & Data-Plane Canonicalization | L |
| wp-alt-context-hardening-202: Hardening Plan — `apps/prototype-wp-alt-context` | tech-debt/wp-alt-context-hardening-plan-20260614.md | partial | checks 11/15 | Hardening Plan — `apps/prototype-wp-alt-context` | M |
| dynamic-ip-ssh-access: Dynamic IP SSH Access Drift | tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md | shipped | checks 5/5 | Dynamic IP SSH Access Drift | S |
| hardcoded-local-paths-in-tra: Hardcoded Local Paths in Tracked Configs | tech-debt/archive-or-transfer-candidates/hardcoded-local-paths-in-tracked-configs.md | shipped | checks 5/5 | Hardcoded Local Paths in Tracked Configs | S |
| review-parallel-merge-namesp: MAINT-REVPARALLEL-FIX-20260616. review-parallel scratch-namespace collision & drift fix | tech-debt/review-parallel-merge-namespace-fix-plan-20260616.md | shipped | SHIPPED checks 0/33 | Eliminate the cross-round finding-id collision and source/coordinator status drift produced | M |
| terminal-guard-test-performa: Investigation: terminal-guard test performance | tech-debt/archive-or-transfer-candidates/terminal-guard-test-performance.md | shipped | checks 4/4 | Investigation: terminal-guard test performance | S |

## GTM section-14 slices

| id/title | path | status | evidence | value | size |
|---|---|---|---|---|---|
| DS-1: `demo_instances` table + migration | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | `demo_instances` table + migration | S |
| DS-2: `/x/<slug>` router → tenant/key/seed; unknown → 404 | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | `/x/<slug>` router → tenant/key/seed; unknown → 404 | S |
| DS-3: `make provision-demo` wrapping `/admin` minter + slug insert | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | `make provision-demo` wrapping `/admin` minter + slug insert | S |
| DS-4: `make expire-demo` + daily expiry/quota-revoke job | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | `make expire-demo` + daily expiry/quota-revoke job | S |
| DS-5: Enumeration/rate-limit hardening on `/x/*` | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Enumeration/rate-limit hardening on `/x/*` | S |
| DS-6: Seed-bundle mechanism parameterized by `SEED=` | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Seed-bundle mechanism parameterized by `SEED=` | S |
| AP-1: `acx_business` schema (tenants/api_keys/usage/consent/leads/billing_events/ext-id cols) | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Epic no status | `acx_business` schema (tenants/api_keys/usage/consent/leads/billing_events/ext-id cols) | L |
| AP-2: Business API service (tenant CRUD, key lifecycle over | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Epic no status | Business API service (tenant CRUD, key lifecycle over `/admin`) | L |
| AP-3: Clerk integration + `user.*` webhooks (idempotent) → tenant | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Epic no status | Clerk integration + `user.*` webhooks (idempotent) → tenant lifecycle; cache | L |
| AP-4: `app.altcontext.com` dashboard: key, usage, install steps, upgrade link | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Epic no status | `app.altcontext.com` dashboard: key, usage, install steps, upgrade link | L |
| AP-5: Polar products + checkout + `subscription.*` webhooks → | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Epic no status | Polar products + checkout + `subscription.*` webhooks → plan/quota enforcement | L |
| AP-6: Resend welcome + receipt from `mail.altcontext.com` | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Resend welcome + receipt from `mail.altcontext.com` | S |
| AP-7: Concierge fast-path: `make` recipe + Polar payment link | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Concierge fast-path: `make` recipe + Polar payment link (ship week | S |
| AP-8: CRM projection sync (DB→Attio via API on lifecycle | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | CRM projection sync (DB→Attio via API on lifecycle events, one-way) | S |
| MK-1: Static landing implementing §8 skeleton + copy | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Epic no status | Static landing implementing §8 skeleton + copy | L |
| MK-2: Before/After hero component (real image, 3 caption tiers) | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Before/After hero component (real image, 3 caption tiers) | S |
| MK-3: Us-vs-Them + face-recognition proof blocks | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Us-vs-Them + face-recognition proof blocks | S |
| MK-4: PostHog events on all CTAs/sections | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | PostHog events on all CTAs/sections | S |
| MK-5: Retire Fly.io marketing backend; serve static | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Retire Fly.io marketing backend; serve static | S |
| OB-1: PostHog project + snippet; `page_view`+`cta_click` | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | PostHog project + snippet; `page_view`+`cta_click` | S |
| OB-2: Funnel events signup→key→first-caption | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Funnel events signup→key→first-caption | S |
| OB-3: `caption_accepted`/`caption_edited{...,skin_tone_cohort}` from plugin | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | `caption_accepted`/`caption_edited{...,skin_tone_cohort}` from plugin | S |
| OB-4: Sentry backend SDK + correlation-id binding | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Sentry backend SDK + correlation-id binding | S |
| OB-5: Sentry frontend SDK, release-tagged | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Sentry frontend SDK, release-tagged | S |
| OB-6: Retire Fly.io analytics; migrate rollups | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Retire Fly.io analytics; migrate rollups | S |
| OB-7: Privacy guard test: no media/embedding/PII in any event | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Privacy guard test: no media/embedding/PII in any event | S |
| OB-8: Infra/host observability + alerting (Notifications topic, symptom alarms, | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Epic no status | Infra/host observability + alerting (Notifications topic, symptom alarms, host agents, | L |
| LS-1: Concierge target list (10–30) + per-prospect demo links | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Concierge target list (10–30) + per-prospect demo links | S |
| LS-2: Public accuracy changelog + feedback form | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Public accuracy changelog + feedback form | S |
| LS-3: Plugin WP.org hardening (disclosure/consent, license, security, readme.txt) | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Epic no status | Plugin WP.org hardening (disclosure/consent, license, security, readme.txt) | L |
| LS-4: WP.org submission package + SVN repo | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | WP.org submission package + SVN repo | S |
| LS-5: Build-in-public kit: 5 Before/After posts + 2 essays | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Build-in-public kit: 5 Before/After posts + 2 essays (drafts) | S |
| LS-6: Case-study capture flow (consent + template) | gtm/altcontext-productization-launch-plan.md#14 | not-started | §14 Atomic no status | Case-study capture flow (consent + template) | S |

## Cross-cutting

- RONLY-1 blocks CRM/hosting tenant UX (remote-only + key tenanting).
- GTM DS-1..DS-6 demo stack clusters with DS-2B shared compute budget.
- GTM AP-1..AP-8 productization theme (billing, clerk, dashboard, CRM).
- REFA-1/2/4/5/7 PHP decompositions; REFA-9 transactional wrapper prerequisite.
- GTM OB-* observability + LS-3/4 WP.org gate public launch.
- E16-1 shipped; remaining v0.5.0 product/infra rows not-started.
