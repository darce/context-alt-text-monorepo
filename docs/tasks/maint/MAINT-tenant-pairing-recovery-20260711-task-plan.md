# MAINT-tenant-pairing-recovery-20260711. Tenant Pairing Recovery + Prod Schema Convergence

> **Metadata**
>
> - **Date**: 2026-07-11 22:30 EST
> - **Author**: claude (Opus 4.8)
> - **Project**: prototype-description-service + prototype-wp-alt-context
> - **Task ID**: `MAINT-tenant-pairing-recovery-20260711`
> - **Target Branch**: `feature/maint-tenant-pairing-recovery-20260711`
> - **Review Coverage Target**: 1
>
> **Findings**: see `MAINT-TPR-01..03` in handoff — queried live, not duplicated here.
> **Heuristics**: canon `github.com/darce/heuristics-canon/lexicons/{engineering,security}.md`, IDs cited inline.

## Objective

A mismatched API key pasted into the plugin settings recovers to a working paired state in one click; prod can never again run an image whose ORM disagrees with its DB schema without failing fast and converging at deploy.

## Problem Statement

Three coupled defects (2026-07-11, LocalWP → `api.altcontext.com`; evidence in findings `MAINT-TPR-01..03`):

1. **Prod schema drift** — running image's ORM selects `tenants.naming_agreement_enabled`; column absent on prod Postgres. Every ORM path loading `Tenant` fails (`whoami` 500s, `manage_api_keys tenant list` crashes). Image and DB version independently with no convergence step or parity gate ([DATA-03]; rg-005).
2. **Pairing dead-end (plugin)** — `SettingsController::test_connection` attempts pairing only after a CONNECTED `/health/detailed` probe, but a mismatched key 403s that probe (plugin always sends `X-Tenant-ID`). First-time auto-adopt is unreachable exactly when needed; user gets a terminal "Tenant mismatch" banner ([RLSE-04], [RLSE-05]).
3. **`whoami` cannot discover (service)** — the route body (`routers/tenant.py:tenant_whoami`) already returns the key-canonical tenant, but `require_auth` (`deps/auth.py:198-208`) 403s on key↔`X-Tenant-ID` mismatch before the body runs. A client that doesn't know the key's tenant can never learn it ([API-10]).

Root cause across all three: **recovery paths designed only for the already-correct state** ([RES-13] crumple zones; [DIAG-07]).

## Constraints

- Tenant enforcement stays strict on every route except the designated discovery endpoint (`/recognition/tenant/whoami`).
- Greenfield policy: schema content lives in `db/migrations/versions/001_identity_schema.py`; no migration-file proliferation.
- Plugin boundary: only monorepo files; no WP core/LocalWP config changes.
- No new secrets surface (ownership matrix untouched).

## Terminology

- **tenant claim** — the tenant UUID bound to an API key row (`api_keys.tenant_id`), surfaced as `AuthContext.tenant_claim`.
- **pairing** — the plugin adopting the key's canonical tenant as its persisted identity (`TenantIdentity::adopt_paired_tenant`).
- **converge** — making the live DB match the ORM-declared schema.

## Current State Analysis

- `recognition/interface_adapters/http/deps/auth.py:198-208` — `require_auth` compares `tenant_claim` to `X-Tenant-ID`, raises 403 `tenant mismatch`.
- `recognition/interface_adapters/http/routers/tenant.py:17` — router-level `dependencies=[Depends(require_auth), Depends(enforce_rate_limit)]`; `tenant_whoami` also takes `auth: AuthContext = Depends(require_auth)`. Body is already key-canonical; existing tests: `recognition/tests/api/test_tenant_whoami.py`.
- `apps/prototype-wp-alt-context/src/api/class-settings-controller.php:216-296` — `test_connection`: probe → classify (`classify_http_status`, 403+`tenant mismatch` → `TENANT_MISMATCH`) → pairing only on CONNECTED (`:275-296`). `attempt_tenant_pairing` (`:303-389`) already handles auto-adopt vs `TENANT_PAIRING_CONFLICT`.
- `apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts:110` — mismatch banner is terminal text, no action.
- Prod DB: single alembic revision scheme; prod `alembic_version` presumed stamped at head from an earlier 001 — `alembic upgrade head` alone will no-op on the drifted DB.

## Target Outcome

- `whoami` returns the key's canonical tenant for any valid key regardless of `X-Tenant-ID`.
- Settings "Check health" with a mismatched key: never-paired auto-derived site → auto-adopt + one re-probe → green banner; paired site → conflict banner with explicit confirm action.
- API refuses to boot against a schema-drifted DB with an error naming the missing column; deploys converge schema before cutover; prod remediated.

## Context Loading

- `docs/workbay/contracts/security.md` (auth surface), ADR-013 (fail-fast precedent), findings `MAINT-TPR-01..03`.
- Code anchors listed in Current State Analysis — no broader load needed.

## Contract and Boundary Impact

- **Service HTTP contract change**: `whoami` no longer 403s on tenant mismatch (returns key-canonical identity). Sole consumer is the plugin's `attempt_tenant_pairing` (verified: no other caller in monorepo; [REF-08]). Document in `docs/workbay/contracts/security.md` auth-surface note.
- **Plugin REST response**: `acx/v1` test-connection payload gains no new fields; existing `tenant_paired`/`rekey_*`/`TENANT_PAIRING_CONFLICT` fields reused.
- **DB**: no schema content change; convergence applies existing 001 content.

## Proposed Solution

### D1. Key-only auth for the tenant discovery route (service)

Add `require_auth_key_only` to `deps/auth.py`: identical key resolution (`_lookup_api_key` — hash, expiry, revocation, disabled-auth handling) but **skips the `tenant_claim != X-Tenant-ID` comparison** (the `:198-208` branch). Wire it into `routers/tenant.py` only: router-level dependency AND the `tenant_whoami` parameter both switch from `require_auth`. Rate limiting (`enforce_rate_limit`) and auth-failure auditing unchanged ([SEC-08]). Disclosure is bounded to the caller's own key binding ([WEB-16], [PG-01]).

### D2. Pairing reachable from `TENANT_MISMATCH` (plugin)

In `test_connection`: when probe outcome is `TENANT_MISMATCH` (not only CONNECTED), call `attempt_tenant_pairing()`. On successful adoption, re-probe `/health/detailed` **exactly once** with the adopted tenant and return that payload; if the re-probe still fails, return its outcome as-is — one pairing attempt + one re-probe per request, no loops ([RLSE-05]; bounded per finding PA-04). Paired-elsewhere sites get the existing `TENANT_PAIRING_CONFLICT` flow, now reachable; `testConnectionBanner.ts` mismatch/conflict banners gain the confirm-pairing action ([RLSE-04]). Adoption is idempotent ([API-03]).

### D3. Schema parity: boot fail-fast + deploy converge (service/infra)

- **Boot fail-fast**: startup hook in `api/main.py` (beside the Vault fail-fast, ADR-013 precedent) runs a schema-parity probe: for `tenants` and `api_keys`, `SELECT <ORM-declared columns> LIMIT 0`; on `UndefinedColumnError` abort with the missing column name and the converge command ([RES-13]).
- **Deploy converge**: new `scripts/converge_schema.py` — compares SQLAlchemy `Base.metadata` for the two identity tables against `information_schema.columns` and emits/executes additive `ALTER TABLE ... ADD COLUMN` statements (server defaults from the model; additive-only — any non-additive drift aborts with instructions to reset per greenfield policy). Called by `scripts/deploy/recognition-service.sh` before container cutover. This bypasses the stamped-alembic no-op problem (PA-03) by diffing reality, not revision stamps. Rollback ([RLSE-08]): additive columns are backward-readable by the old build; non-additive changes require explicit reset.
- **Prod remediation**: run `converge_schema.py` once against prod (operator; documented in the runbook section this task adds to `docs/workbay/rules/development-workflow.md`).

### Non-goals

- No multi-tenant key re-binding UI; no admin-console changes; no tenant-enforcement change on any other route; no alembic multi-revision migration scheme.

## Files and Surfaces to Change

| File | Change |
| --- | --- |
| `apps/prototype-description-service/recognition/interface_adapters/http/deps/auth.py` | add `require_auth_key_only` (reuses `_lookup_api_key`, `_hash_api_key`) |
| `apps/prototype-description-service/recognition/interface_adapters/http/routers/tenant.py` | swap both `require_auth` usages to `require_auth_key_only` |
| `apps/prototype-description-service/recognition/tests/api/test_tenant_whoami.py` | extend: mismatched header → 200 key-canonical; revoked/expired → 401 |
| `apps/prototype-description-service/api/main.py` | schema-parity boot probe |
| `apps/prototype-description-service/scripts/converge_schema.py` | new: metadata vs information_schema additive converge |
| `scripts/deploy/recognition-service.sh` | invoke converge before cutover |
| `apps/prototype-wp-alt-context/src/api/class-settings-controller.php` | `test_connection` mismatch branch → pairing + single re-probe |
| `apps/prototype-wp-alt-context/tests/Unit/SettingsControllerTest.php` | mismatch-pairing flows |
| `apps/prototype-wp-alt-context/js/admin/pages/settings/testConnectionBanner.ts` | confirm action on mismatch/conflict banners |
| `apps/prototype-wp-alt-context/js/admin/pages/__tests__/SettingsPage.test.tsx` | banner flow tests |
| `docs/workbay/contracts/security.md` | whoami contract note |
| `docs/workbay/rules/development-workflow.md` | converge step + prod remediation runbook |

## Related Files

- `apps/prototype-wp-alt-context/src/api/class-tenant-identity.php` (adopt/paired logic — unchanged)
- `apps/prototype-wp-alt-context/src/api/services/class-tenant-local-rekey-service.php` (unchanged)
- `db/models/tenant.py`, `db/migrations/versions/001_identity_schema.py` (schema source of truth — unchanged)

## Verification Strategy

- Deterministic tests:
  - `cd apps/prototype-description-service && make test` (whoami key-only, boot-probe abort, converge additive/abort cases)
  - `cd apps/prototype-wp-alt-context && composer test && npm test`
- Runtime-parity / environment checks:
  - LocalWP settings "Check health" with the mismatched-tenant key → single-click green (manual, screenshot into handoff)
- Contract/fixture verification:
  - grep for `tenant/whoami` consumers — plugin remains sole caller
- Manual verification (operator):
  - prod: `converge_schema.py` run output; `curl whoami` 200; `manage_api_keys tenant list` succeeds — pasted into handoff `test_result`

## Slice Delivery

### Slice 1: Key-only whoami (D1)

**Goal**: whoami returns key-canonical tenant regardless of `X-Tenant-ID`.

Changes:

- `require_auth_key_only` in `deps/auth.py`; `routers/tenant.py` wired to it.
- `test_tenant_whoami.py` extended first, watched to fail ([TEST-06], [TEST-03]).

Proof:

- `make test` green; new test asserts 200 + canonical `tenant_id` under mismatched header; revoked/expired stay 401.

### Slice 2: Pairing from mismatch (D2)

**Goal**: mismatch probe recovers via pairing in one request, bounded to one re-probe.

Changes:

- `test_connection` mismatch branch; PHP unit tests for adopt/conflict/pairing-error paths.
- `testConnectionBanner.ts` + `SettingsPage.test.tsx` banner actions.

Proof:

- `composer test` + `npm test` green; LocalWP manual walkthrough screenshot.

### Slice 3: Schema parity gates (D3)

**Goal**: drifted DB fails fast at boot; deploys converge additively; prod remediated.

Changes:

- Boot probe in `api/main.py` (test: simulated missing column aborts naming it).
- `converge_schema.py` + deploy-script hook; docs/runbook section.

Proof:

- Unit tests green; operator evidence: prod whoami 200, `tenant list` lists rows.

## Consolidated Checklist

## Context and Ownership

- [ ] Loaded auth deps, tenant router, settings controller, and findings before editing.
- [ ] whoami contract change documented in `docs/workbay/contracts/security.md`.

### Checklist for Slice 1: Key-only whoami

- [ ] Extend `test_tenant_whoami.py` (mismatched header → 200 canonical; revoked/expired → 401); watch new tests fail.
- [ ] Add `require_auth_key_only` to `deps/auth.py`; wire `routers/tenant.py` (router deps + param).
- [ ] `make test` green in `apps/prototype-description-service`.

### Checklist for Slice 2: Pairing from mismatch

- [ ] `test_connection`: `TENANT_MISMATCH` → `attempt_tenant_pairing()` → on adopt, single re-probe; PHP tests for adopt/conflict/pairing-error.
- [ ] `testConnectionBanner.ts` confirm action + `SettingsPage.test.tsx` flows.
- [ ] `composer test` + `npm test` green; LocalWP walkthrough evidence captured.

### Checklist for Slice 3: Schema parity gates

- [ ] Boot-time parity probe in `api/main.py` with named-column abort + unit test.
- [ ] `scripts/converge_schema.py` (additive-only, abort on non-additive drift) + `recognition-service.sh` hook.
- [ ] Runbook section in `development-workflow.md`; operator runs prod converge; whoami 200 + `tenant list` evidence recorded.

## Review Readiness

- [ ] whoami contract change has matching doc + test evidence.
- [ ] Runtime-parity (LocalWP walkthrough, prod curl) included where unit tests can mask behavior.
- [ ] Handoff decisions record each slice with verification and contract implications.

## Success Criteria

- [ ] Mismatched key in LocalWP settings recovers to green in one "Check health" click (never-paired case) or one explicit confirm (paired case).
- [ ] Prod `whoami` and `manage_api_keys tenant list` succeed post-remediation.
- [ ] API refuses to boot against a drifted DB with an actionable error; `deploy-*` converges schema before cutover.

## Risks

- **D1 contract change**: whoami 403-on-mismatch consumers break — plugin verified sole consumer pre-merge ([REF-08]).
- **Converge on live DB**: additive `ALTER TABLE ADD COLUMN` with defaults is metadata-only in Postgres 11+; non-additive drift aborts rather than guesses.
- **Auto-adopt surprise**: wrong key pasted on a fresh site silently adopts a foreign tenant — bounded to never-paired auto-derived identities; banner names the adopted tenant explicitly ([RLSE-05]).
