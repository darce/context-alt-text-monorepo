# Task Plan — Secrets Phase 3: OCI Vault Backend

> **Metadata**
>
> - **Date**: 2026-07-11
> - **Author**: claude-opus-4-8
> - **Project**: prototype-description-service (backend Python) + infra/oci (deployment)
> - **Task ID / Work ref**: `SECRETS-P3`
> - **Parent task**: `MAINT-secrets-consolidation-20260708`
> - **Target Branch**: `feature/maint-secrets-consolidation-20260708`
> - **Depends on**: `SECRETS-P2` (SecretProvider seam) — see Constraints
> - **Review Coverage Target**: 2

> Review coverage note: no mutable review counts, finding totals, or run histories in this file. Query live state via `get_review_coverage(task_ref=...)` / `list_review_runs(task_ref=...)`.

---

## SECRETS-P3. OCI Vault Backend for the Description Service

## Objective

Add an `OciVaultSecretProvider` behind the Phase-2 `SecretProvider` seam so the OCI-hosted recognition service fetches its infra + service-root secrets (DB password, `RECOGNITION_ADMIN_TOKEN`) from OCI Vault via **instance principals** at boot, and compose/systemd carry no plaintext secrets. Backend is selected by env `RECOGNITION_SECRET_BACKEND=oci_vault|env` (default `env` for local/CI). If Vault is unreachable at boot the process fails fast and refuses to serve.

## Intake

- **Scope one-pager**: `docs/scopes/secrets-consolidation.md` (Phase 3 section; Forward-looking §A per-tenant namespacing — **not built here**, YAGNI).
- **Key Q&A decisions**: scope intake `decision #1717` (`claude_scope_intake_secrets_consolidation`); operator topology decision `decision #1882` (resolves scope open Q1 + Q2 — read live via `search_handoff`).
- **Not-Doing** (confirmed): dynamic/leased Vault secrets; per-tenant secret namespaces (`secret/tenants/<id>/*`, scope §A — deferred behind its self-serve-signup trigger); per-compartment IAM split (deferred, a later policy change not a migration — decision #1882); SOPS(age) interim layer (skipped — decision #1882); any change to the WP plugin's `acx_recognition_api_key` WP-option key (scope Phase 2/3 explicitly exclude the plugin); local/CI secret manager (env stays).

## Problem Statement

Prod/demo secrets reach the VM today as **plaintext on host**. `docker-compose.prod.yml` and `docker-compose.env.yml` bind every service with `env_file: .env`, and that `.env` is a symlink to `/opt/acx-backend/<env>/secrets/.env` (`chmod 750` dir per `infra/oci/cloud-init.yaml:132-134`). It carries `POSTGRES_PASSWORD`, the password-embedded `POSTGRES_DSN`/`POSTGRES_SYNC_DSN`, and `RECOGNITION_ADMIN_TOKEN` (`apps/prototype-description-service/.env.prod.example:30-40`). Rotation means hand-editing that file on every host; a host compromise reads every secret in cleartext. Phase 2 introduced a `SecretProvider` seam so the app reads secrets through one port; Phase 3 must supply the Vault-backed adapter and remove the plaintext host surface, without touching local/CI (which stay on env) and without any big-bang.

## Constraints

- **Phase-2 dependency (precondition, must confirm before implementation).** Phase 2 (`SECRETS-P2`) introduces `SecretProvider` in the description-service. At authoring time the Phase-2 plan file (`docs/tasks/secrets/secrets-phase2-secretprovider-seam-task-plan.md`) and any `SecretProvider`/`EnvSecretProvider` symbol **do not yet exist in the tree** (grep of `apps/prototype-description-service/**/*.py` returns nothing). **Assumed port contract this plan adapts to** — confirm against the merged Phase-2 code before coding, and treat any divergence as a finding, not a silent re-shape:
  - `SecretProvider` is a `typing.Protocol` (or ABC) exposing `get_secret(name: str) -> str`, raising a typed `SecretNotFoundError` / `SecretProviderError` when a required secret is absent or the backend fails.
  - `EnvSecretProvider.get_secret(name)` reads `os.environ[name]` and raises on missing.
  - A single factory (assume `get_secret_provider()` in a module such as `recognition/config/secrets.py`) selects the concrete provider; Phase 3 extends **that** selector — it does not add a second selection site.
  - All service secret reads already route through the provider (Phase-2 success criterion), so Phase 3 changes zero consumers.
- **Least-privilege agency [SEC-04].** The instance-principal dynamic group + IAM policy grant the VM identity **read-only** on exactly the one Vault secret compartment and only `secret-family` read / `secret-bundle` read — nothing broader. Namespaced paths `secret/<domain>/<name>` keep the grant scopeable to a later per-domain split without a migration [decision #1882].
- **Fail-fast on boot [RES-13].** Vault unreachable / auth failure / missing required secret at startup ⇒ raise and exit non-zero **before** the app binds a port or serves a request. No partial serve, no env fallback when `RECOGNITION_SECRET_BACKEND=oci_vault`.
- **Bounded timeout [RES-02].** Every Vault call (auth signer construction + secret-bundle GET) uses an explicit connect/read timeout; no unbounded blocking call. No retry storm — at most a small bounded retry with backoff, 5xx/transport-only [RES-06], never on a 4xx auth/not-found.
- **Config validated at load [rg-008].** The backend selector validates `RECOGNITION_SECRET_BACKEND` against the known set at load; an unknown value fails fast with a clear message, not a silent default.
- **Ports & adapters [REF-15].** All `oci` SDK calls live inside `OciVaultSecretProvider`; no `oci` import leaks into consumers, config, or db/settings. No transport/OCID detail crosses back into domain code [REF-16].
- **Single seam [REF-12 / ARCH-08].** One provider, one compartment, namespaced paths. No per-tenant namespace, no per-service compartment, no abstraction with a single consumer.
- **Greenfield.** No migration/compat shim; `RECOGNITION_SECRET_BACKEND` defaults to `env` and the Vault path is additive.

## Workflow Principles

- Adapt to the Phase-2 port; do not redesign it [AGT-13 — the seam shape is a settled Phase-2 decision].
- No unresolved anchors — verify the Phase-2 symbols exist before citing them [AGT-02].
- Failure-injection over E2E for the fail-fast proof [TEST-09/TEST-10]; the real-Vault fetch is an operator runbook step, not a unit test.
- Instance principals only on the VM; **no bootstrap secret on the host** — the VM identity is the sole unlock [SEC-04].
- The `oci` SDK is a hallucination-risk dependency surface — pin it and verify it installs for real; no type shim [SEC-09 / rg-001].

## Terminology

- **SecretProvider**: Phase-2 port; `get_secret(name) -> str`. The seam Phase 3 plugs into.
- **Instance principal**: OCI auth mode where a compute instance's own identity (via a dynamic group + IAM policy) authorizes API calls — no API key / no secret stored on host. Precedent in this repo: the GPU reaper's `OCI_CLI_AUTH=instance_principal` mode (`infra/oci/cloud-init.yaml:39-40`, `infra/oci/gpu_lifecycle/reaper.py:20,146`).
- **Namespaced secret path**: `secret/<service|domain>/<name>`, e.g. `secret/recognition/pg-password`, `secret/recognition/admin-token` [decision #1882]. In OCI Vault this maps to a per-secret **Secret** resource named by that path convention within one compartment.
- **Secret bundle**: OCI Vault's `get_secret_bundle` response carrying the current secret content (base64) for a secret OCID.

## Current State Analysis

- **Works today:** app reads secrets from process env. `db/settings.py:25` `DatabaseSettings` builds the DSN from env (`_load_env_file` + `os.getenv`); `recognition/config/security.py:75` `admin_token` = `os.getenv("RECOGNITION_ADMIN_TOKEN", "")`, surfaced via `get_security_settings()` (`security.py:88`).
- **Plaintext host surface (the problem):** `docker-compose.prod.yml` (postgres/api/worker all `env_file: .env`) and `docker-compose.env.yml` (same) resolve secrets from `/opt/acx-backend/<env>/secrets/.env`; `.env.prod.example:30,38-39` shows `POSTGRES_PASSWORD`, `POSTGRES_DSN`, `POSTGRES_SYNC_DSN` (password embedded); `RECOGNITION_ADMIN_TOKEN` in the service env set (scope §Grounding). systemd `acx-env.service.template` just runs `docker compose … up` in `/opt/acx-backend/{{ENV}}`.
- **Instance-principal precedent exists** (CLI-based, in `gpu_lifecycle`) but the **`oci` Python SDK is NOT a dependency** — absent from `apps/prototype-description-service/pyproject.toml` `[project].dependencies` (verified: `grep oci pyproject.toml` empty). The reaper shells out to the OCI CLI; there is no in-process SDK usage. Phase 3 must add `oci` as a real dependency.
- **Misleading/absent:** no `SecretProvider` in code yet (Phase 2 unmerged at authoring time). No `docs/adr/` dir — ADRs live in `docs/adrs/`, convention `ADR-NNN-<slug>.md`, highest is `ADR-012-customer-tenant-management-crm-ready-admin.md` ⇒ **next number 013**.
- **Boundary nuance the plan must resolve:** the postgres **container** consumes `POSTGRES_PASSWORD` for its own bootstrap (`docker-compose.prod.yml` postgres `env_file`), which is *outside* the Python app process, so the Python `SecretProvider` cannot supply it. See Proposed Solution §Compose boundary.

## Target Outcome

On the VM, the api/worker containers start with `RECOGNITION_SECRET_BACKEND=oci_vault` and no secret values in their env. At app boot the process constructs an instance-principal signer, fetches `secret/recognition/pg-password` and `secret/recognition/admin-token` (and any other required infra secret) from the single Vault compartment with bounded timeouts, and injects them where the existing consumers read them. If Vault is unreachable or a required secret is missing, the process logs a clear error and exits non-zero without serving. Rotating a secret is a single Vault update + container restart — no host file edit. Local/CI are unchanged: `RECOGNITION_SECRET_BACKEND` unset ⇒ `env` ⇒ `EnvSecretProvider`.

## Context Loading

- Scope: `docs/scopes/secrets-consolidation.md` (Phase 3 + §A trigger).
- Phase-2 seam (confirm first): `docs/tasks/secrets/secrets-phase2-secretprovider-seam-task-plan.md` and the merged `SecretProvider`/factory module.
- Consumers to keep unchanged: `apps/prototype-description-service/recognition/config/security.py:75,88`; `apps/prototype-description-service/db/settings.py:25`.
- Deploy surfaces: `apps/prototype-description-service/docker-compose.prod.yml`, `docker-compose.env.yml`, `.env.prod.example`, `systemd/acx-env.service.template`, `infra/oci/cloud-init.yaml`.
- Instance-principal precedent: `infra/oci/gpu_lifecycle/reaper.py:20,146,386`.
- ADR convention: `docs/adrs/README.md`.
- Rules: `docs/workbay/rules/backend-python-guidelines.md`, `docs/workbay/rules/testing-python.md`.
- Heuristics (authoritative, current): `docs/reference/engineering-heuristics-canon.md` — cite rules by stable ID (`SEC-04`, `RES-13`, `ARCH-07`). This is the canonical lexicon; ignore any stale `docs/workbay/rules/engineering-heuristics.md`.
- Handoff: task `MAINT-secrets-consolidation-20260708`; decisions #1717, #1882.

## Contract and Boundary Impact

Internal service adapter + deployment/infra change. **No cross-service API contract change** — the plugin↔service HTTP contract, `/admin` surface, and REST namespace are untouched; the plugin is explicitly out of the Vault path (scope Phase 2/3). The only boundaries are (a) an internal Python port (already owned by Phase 2) and (b) the app↔OCI-Vault operational boundary (a new external integration point, not a published contract).

| Boundary | Owner | Current Contract | Expected Change | Compatibility Needed? | Verification |
| --- | --- | --- | --- | --- | --- |
| `SecretProvider` port | backend (Phase-2 owned) | `get_secret(name)->str` (assumed; confirm) | Add `OciVaultSecretProvider` impl + extend selector | no — additive impl, default unchanged | adapter unit tests (mocked `oci`) |
| app ↔ OCI Vault | backend / infra | none (new) | instance-principal fetch, bounded timeout, fail-fast | n/a (new integration point) | failure-injection test + operator runbook |
| compose/systemd ↔ host `.env` | infra | plaintext `env_file: .env` | remove infra secret values from prod host `.env`; VM identity supplies them | yes — env backend for local/CI must keep working | example-file diff + local `env` boot |
| plugin ↔ service HTTP | php-plugin / backend | `acx/v1/*` + API key | **none** | n/a | stated no-change |

## Proposed Solution

Add `OciVaultSecretProvider` implementing the Phase-2 port. Construct an OCI **instance-principals signer** (in-process, `oci` SDK) once; a `SecretsClient` reads each secret by its namespaced path with an explicit timeout, decodes the bundle, and returns the plaintext string. Extend the Phase-2 factory to return this provider when `RECOGNITION_SECRET_BACKEND=oci_vault`; validate the env value at load [rg-008]. Required secrets are fetched eagerly at boot so a missing/unreachable secret fails fast [RES-13] before serving.

**Path→resource resolution.** `secret/recognition/pg-password` and `secret/recognition/admin-token` are logical names [decision #1882]. Resolve them to OCI Secret OCIDs via a small **config map** injected by env/config at deploy time (e.g. `RECOGNITION_VAULT_SECRET_MAP` or per-name OCID env like `RECOGNITION_VAULT_PGPASSWORD_OCID`) — an OCID is not itself a secret, so it can ship in compose plaintext. The adapter validates the map covers every required logical name at load [rg-008]; the namespacing convention is preserved in the logical names so a later per-domain compartment split needs only a policy + map change, no code migration.

**Wiring into existing consumers (zero consumer edits beyond Phase-2 seam).** The consumers already read via the provider after Phase 2. Phase 3 only supplies values: `admin-token` → the value `security.py` reads for `RECOGNITION_ADMIN_TOKEN`; `pg-password` → the DSN password `db/settings.py` composes. Exact injection mechanics depend on the Phase-2 seam shape (confirm before coding).

**Compose boundary (the postgres-container secret) [ARCH-06 trade-off].** `POSTGRES_PASSWORD` is consumed by the postgres container's own bootstrap, outside the Python process, so the in-process provider cannot supply it. Chosen approach for this task: keep the postgres bootstrap credential out of the committed host `.env` and have the **VM provision step** materialize a **runtime-only, root-owned, restart-scoped** env fragment by fetching `secret/recognition/pg-password` via the OCI CLI instance-principal at container-start (an entrypoint/`ExecStartPre` fetch), never a committed file. Trade-off accepted: the postgres container still receives its password via a runtime env, but it is fetched from Vault per boot and never persisted in a committed file or a long-lived host secret — the app process itself takes the same value through the Python provider. Recorded as an alternative in the ADR (vs. app-owned DB user provisioning). Sacrifice: two fetch mechanisms (in-process SDK for the app, CLI for the container bootstrap) — justified because the postgres image's contract is env-only.

## Files and Surfaces to Change

| Surface | File | Change |
| --- | --- | --- |
| backend | `apps/prototype-description-service/recognition/config/secrets.py` (or the Phase-2 seam module) | Add `OciVaultSecretProvider`; extend the provider factory + `RECOGNITION_SECRET_BACKEND` validation [rg-008] |
| backend deps | `apps/prototype-description-service/pyproject.toml` | Add `oci` to `[project].dependencies` (pinned range) + refresh lock; real install, no shim [rg-001/SEC-09] |
| tests | `apps/prototype-description-service/recognition/tests/unit/test_oci_vault_secret_provider.py` | Adapter unit tests with `oci` mocked (spec'd): get + namespaced-path resolution + timeout arg asserted |
| tests | `apps/prototype-description-service/recognition/tests/unit/test_secret_backend_selection.py` | Backend selector: `oci_vault` returns the OCI provider; unknown value fails fast; default→env |
| tests | `apps/prototype-description-service/recognition/tests/unit/test_vault_boot_failfast.py` | Failure-injection: unreachable Vault at boot ⇒ non-zero exit + clear error + no serve [TEST-09/10] |
| infra | `apps/prototype-description-service/docker-compose.prod.yml`, `docker-compose.env.yml` | Set `RECOGNITION_SECRET_BACKEND=oci_vault` for api/worker; remove `RECOGNITION_ADMIN_TOKEN` + DB password from the app env; add OCID map vars |
| infra | `apps/prototype-description-service/.env.prod.example` | Delete plaintext infra-secret values; document the Vault backend + OCID-map vars + rotation-in-Vault flow |
| infra | `apps/prototype-description-service/systemd/acx-env.service.template` | Add `ExecStartPre` note / hook for the postgres-bootstrap Vault fetch (or document the compose entrypoint path) |
| infra docs | `infra/oci/vault-instance-principal-runbook.md` (new) | Dynamic-group + IAM policy (least-privilege, one compartment, read-only) + operator fetch/rotation runbook |
| ADR | `docs/adrs/ADR-013-oci-vault-secrets-backend.md` (new) | Context/decision/consequences + alternatives + single-compartment+namespacing choice [ARCH-07] |

## Related Files

| File | Note |
| --- | --- |
| `apps/prototype-description-service/recognition/config/security.py:75,88` | `admin_token` consumer — unchanged; value now sourced via provider |
| `apps/prototype-description-service/db/settings.py:25` | DSN/password consumer — unchanged; value now sourced via provider |
| `infra/oci/gpu_lifecycle/reaper.py:20,146` | Instance-principal precedent (CLI auth mode) — cite in runbook |
| `infra/oci/cloud-init.yaml:39-40,132-134` | VM secrets dir + existing instance_principal comment |
| `docs/adrs/README.md` | ADR numbering/format convention |
| `docs/scopes/secrets-consolidation.md` §A | Per-tenant namespacing — future, do not build |

## Verification Strategy

- Deterministic tests (from the service Makefile — `apps/prototype-description-service/Makefile:197` runs `uv run pytest -m "not integration and not pg and not timing"`):
  - `cd apps/prototype-description-service && make test`
  - Targeted: `cd apps/prototype-description-service && uv run pytest recognition/tests/unit/test_oci_vault_secret_provider.py recognition/tests/unit/test_secret_backend_selection.py recognition/tests/unit/test_vault_boot_failfast.py -q`
  - Watch each new test fail first with the predicted message [TEST-06].
- Contract/dependency verification:
  - `cd apps/prototype-description-service && uv run python -c "import oci; print(oci.__version__)"` (real install, not a shim [rg-001]).
- Runtime-parity check (local, env backend still works):
  - Boot the app locally with `RECOGNITION_SECRET_BACKEND` unset ⇒ `EnvSecretProvider` path, no OCI import required at runtime.
- Manual / operator verification (**cross-boundary infra — cannot unit-test real Vault**):
  - Runbook step: on the VM, confirm the dynamic group + policy resolve, then `oci secrets secret-bundle get …` succeeds via instance principal; restart the stack and confirm the app boots with no plaintext secret in container env (`docker inspect` shows no `RECOGNITION_ADMIN_TOKEN`/DB password).
  - Rotation check: update the secret in Vault, restart, confirm the new value is in effect with no host file edit.

## Slice Delivery

### Slice 1: `OciVaultSecretProvider` adapter + backend selection

**Goal**: A Vault-backed provider implementing the Phase-2 port, selected by `RECOGNITION_SECRET_BACKEND=oci_vault`, with `oci` added as a real dependency.

Changes:
- Confirm the Phase-2 port shape in-tree [AGT-02]; if it diverges from the assumed contract, record a finding and adapt.
- Add `oci` to `pyproject.toml` `[project].dependencies` + refresh lock; verify import [rg-001/SEC-09].
- Implement `OciVaultSecretProvider` (instance-principal signer, namespaced-path→OCID resolution via config map, bounded-timeout `get_secret_bundle`, bounded/backed-off retry on transport/5xx only) [REF-15, RES-02, RES-06].
- Extend the Phase-2 factory + validate `RECOGNITION_SECRET_BACKEND` at load [rg-008].

Proof:
- `uv run pytest recognition/tests/unit/test_oci_vault_secret_provider.py recognition/tests/unit/test_secret_backend_selection.py -q` — mocked (`spec`'d) `oci` client asserts: correct secret fetched by namespaced path, explicit timeout passed, `oci_vault`→OCI provider, unknown backend raises, default→env.
- `uv run python -c "import oci"` succeeds.

### Slice 2: Fail-fast failure-injection test

**Goal**: Prove the process refuses to serve when Vault is unreachable at boot.

Changes:
- Ensure required secrets are fetched eagerly at boot; on unreachable Vault / auth failure / missing required secret, raise a typed error and exit non-zero before binding a port (no env fallback under `oci_vault`) [RES-13].

Proof:
- `uv run pytest recognition/tests/unit/test_vault_boot_failfast.py -q` — inject an unreachable Vault (mock the signer/client to raise a transport error); assert the boot path raises the typed error, exits non-zero, logs a clear message, and never reaches the serve step (no partial serve) [TEST-09/TEST-10]. Test observed failing first with the predicted message [TEST-06].

### Slice 3: Infra — instance-principal identity + host de-plaintexting

**Goal**: The VM fetches secrets via its own identity; prod compose/systemd/env-example carry no infra-secret plaintext.

Changes:
- New `infra/oci/vault-instance-principal-runbook.md`: dynamic-group definition + least-privilege IAM policy (one compartment, read-only `secret-bundle`) [SEC-04]; operator fetch + rotation steps; cites the reaper precedent.
- `docker-compose.prod.yml` / `docker-compose.env.yml`: set `RECOGNITION_SECRET_BACKEND=oci_vault` for api/worker; remove `RECOGNITION_ADMIN_TOKEN` + DB password from app env; add OCID-map vars (non-secret).
- `.env.prod.example`: strip plaintext infra-secret values; document backend + OCID map + Vault-rotation flow.
- `acx-env.service.template`: document/hook the postgres-bootstrap Vault fetch (`ExecStartPre` or entrypoint) so the container password is fetched at boot, never committed.
- **Precondition A2** (from scope): confirm OCI IAM can grant the dynamic group + instance-principal policy — note as an operator-confirm gate before this slice ships.

Proof:
- Diff review: no secret values remain in the committed compose/env-example (`grep -nE 'ADMIN_TOKEN|PASSWORD|_DSN' docker-compose.prod.yml docker-compose.env.yml .env.prod.example` shows only non-secret refs / OCID vars).
- Operator runbook step (manual, cross-boundary): instance-principal `secret-bundle get` succeeds on the VM; `docker inspect` shows no plaintext secret in app container env.

### Slice 4: ADR-013 — OCI Vault secrets backend

**Goal**: Record the architecture decision so rationale outlives the author [ARCH-07].

Changes:
- New `docs/adrs/ADR-013-oci-vault-secrets-backend.md`: context (plaintext host surface, ship-to-prod), decision (OCI Vault behind the Phase-2 seam; instance principals; single compartment + trust-domain namespacing `secret/<domain>/<name>` per decision #1882; env for local/CI; fail-fast), consequences (OCI lock-in, weak local-dev story kept on env, two fetch mechanisms for the postgres-container secret), and **alternatives considered** — SOPS(age) (rejected/deferred per #1882), Doppler/Infisical (external trust surface), HashiCorp Vault (ops overkill, YAGNI), per-service compartments (deferred, no migration needed thanks to namespacing) [ARCH-06 trade-offs enumerated].

Proof:
- File exists, follows `docs/adrs/README.md` format, references decisions #1717/#1882 and this task plan; number 013 is the next free ADR.

## Consolidated Checklist

### Context and Ownership

- [ ] Loaded scope, Phase-2 seam module, and consumers before editing; confirmed the Phase-2 port shape in-tree [AGT-02].
- [ ] Recorded boundary ownership (internal port + app↔Vault op boundary; no cross-service contract change).

### Checklist for Slice 1: Adapter + selection

- [ ] Confirmed Phase-2 port contract; adapted (or filed a finding on divergence).
- [ ] `oci` added to `pyproject.toml` + lock refreshed; `import oci` verified.
- [ ] `OciVaultSecretProvider` implemented (instance-principal signer, namespaced path→OCID, bounded timeout, bounded 5xx-only retry).
- [ ] Factory extended + `RECOGNITION_SECRET_BACKEND` validated at load.
- [ ] Adapter + selection unit tests pass (mocked/spec'd `oci`).

### Checklist for Slice 2: Fail-fast

- [ ] Required secrets fetched eagerly at boot; unreachable/missing ⇒ typed error, non-zero exit, no partial serve, no env fallback under `oci_vault`.
- [ ] Failure-injection test observed failing first, then passing.

### Checklist for Slice 3: Infra

- [ ] Instance-principal dynamic-group + least-privilege policy runbook written.
- [ ] Prod compose/env set `RECOGNITION_SECRET_BACKEND=oci_vault`; app-env secret values removed; OCID-map vars added.
- [ ] `.env.prod.example` de-plaintexted + documents Vault backend + rotation.
- [ ] postgres-bootstrap Vault fetch documented/hooked in the systemd template.
- [ ] Precondition A2 (OCI IAM grant) confirmed with operator before ship.

### Checklist for Slice 4: ADR

- [ ] `docs/adrs/ADR-013-oci-vault-secrets-backend.md` written with alternatives + trade-offs + decision refs.

## Review Readiness

- [ ] No boundary-touching change without matching test/runbook/ADR evidence.
- [ ] Runtime-parity: local `env` backend still boots with no OCI import at runtime.
- [ ] Handoff decision records the change, the fail-fast test evidence, and the no-cross-service-contract-change conclusion.

## Success Criteria

- [ ] Prod api/worker boot with `RECOGNITION_SECRET_BACKEND=oci_vault` and fetch DB password + admin token from Vault via instance principal — no plaintext secret in container env (`docker inspect`).
- [ ] Vault unreachable at boot ⇒ process exits non-zero with a clear error and never serves (failure-injection test green).
- [ ] Local/CI unchanged: unset backend ⇒ `EnvSecretProvider`; full suite green.
- [ ] Rotating a secret is a single Vault update + restart — no host file edit.
- [ ] ADR-013 records the decision + alternatives; runbook lets an operator reproduce the instance-principal fetch.
