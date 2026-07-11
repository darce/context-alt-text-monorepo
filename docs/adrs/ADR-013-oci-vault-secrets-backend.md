# ADR-013: OCI Vault Secrets Backend Behind a Provider Seam

## Status

Accepted

## Date

2026-07-11

## Context

Secrets (DB credentials, the `/admin` root-of-trust token, provider/eval API
keys) were scattered across `.env` files with no single owner and shipped as
host plaintext on the prod/demo OCI VM. The service is shipping to production
soon on OCI. Task `MAINT-secrets-consolidation-20260708` (scope:
`docs/scopes/secrets-consolidation.md`; intake decision `#1717`; phase decisions
`#1882`) set out to give every secret one documented owner, one fetch
mechanism, and single-place prod rotation.

Phase 1 retired the plaintext dev-key allowlist (`RECOGNITION_ALLOWED_API_KEYS`)
so DB-backed keys via `/admin` are the sole tenant-key authority, and added
load-time required-secret validation. Phase 2 introduced a `SecretProvider` port
(`shared/secrets.py`, [REF-15]) routing all seven service secret reads through
one seam with zero behavior change, enforced by a seam-closure guard test. This
ADR records the Phase 3 decision that consumes that seam.

## Decision

Adopt **OCI Vault** as the production secret backend behind the Phase-2
`SecretProvider` seam:

- `OciVaultSecretProvider` implements the port, selected by
  `RECOGNITION_SECRET_BACKEND=oci_vault|env` (default `env` for local/CI).
- On the VM, secrets are fetched via the instance's **instance principal**
  ([SEC-04] least privilege) — compose/systemd carry no app-secret plaintext.
- **Single Vault compartment**, secrets **namespaced by trust domain**
  (`secret/<domain>/<name>`) mapped to OCIDs by the non-secret
  `RECOGNITION_VAULT_SECRET_MAP` (decision `#1882`).
- **Fail-fast** at boot when Vault is unreachable / auth fails / a required
  secret is missing — the process refuses to serve rather than start degraded
  ([RES-13]); the Vault call is bounded by timeout ([RES-02]) with 5xx/transport
  backoff ([RES-06]).
- Local and CI stay on `EnvSecretProvider`.
- The `postgres` container's own `POSTGRES_PASSWORD` (not a Python-app secret)
  is fetched into the runtime `.env` by a systemd `ExecStartPre` hook before
  compose up — the one accepted second fetch mechanism.

Runbook: `infra/oci/vault-instance-principal-runbook.md`. Operator precondition
A2 (OCI IAM can grant the dynamic group + instance-principal policy) gates prod
cutover.

## Why This Decision

- **OCI-native, no bootstrap secret.** Instance principals mean only the VM's
  *identity* unlocks secrets; nothing plaintext ships in compose/systemd. KMS-
  backed, IAM-scoped, rotation-capable, effectively free — and we are already on
  OCI and shipping soon.
- **Non-disruptive.** The Phase-2 seam ([REF-15]) means swapping backends never
  touches consumers; env stays the local/CI story.
- **Single-place rotation.** Rotating a DB cred / admin token / tenant secret
  becomes one Vault operation; app restart re-fetches the current version (the
  OCID is stable across versions).
- **Blast-radius preserved for later split.** Trust-domain namespacing means a
  future move to per-service compartments is an IAM-policy change, not a data
  migration ([DIAG-07]).

## Alternatives Considered

Every option trades something off ([ARCH-06]); this is the least-worst for an
OCI-hosted, ship-soon runtime.

### 1. SOPS (age/KMS) encrypted `.env` in git — rejected/deferred (`#1882`)

Great local story and encrypts the demo compose secrets in git, but it is static
(no dynamic rotation) and adds a second, throwaway mechanism (age keys) that
Vault then replaces — two migrations for a short window ([REF-12] YAGNI,
[REF-05] two-hats). Trigger to revisit: only if Phase 3 slips and demo compose
needs encrypted-at-rest git secrets before Vault lands.

### 2. Doppler / Infisical — rejected

Best DX and one system for local+prod+rotation, but a new external trust surface
(SaaS Doppler / self-hosted Infisical) that is not OCI-native — more moving
parts than instance principals for no gain here.

### 3. HashiCorp Vault — rejected

Most powerful (dynamic/leased secrets) but heavy ops cost; overkill for the
current secret set ([REF-12] YAGNI, [ARCH-08] choose boring).

### 4. Per-service Vault compartments now — deferred

Stronger isolation but N× IAM policy + management for one VM running all
services today. Trust-domain namespacing (chosen) keeps the later split a
policy change, not a migration, so building it now is speculative ([REF-12]).

### 5. Keep plaintext `.env` on the host — rejected

The status quo: app secrets readable by anyone on the box, no rotation story.
This is the problem the task exists to fix ([SEC-06]).
