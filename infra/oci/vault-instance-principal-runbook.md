# OCI Vault — instance-principal secret fetch (prod)

> **Task:** `MAINT-secrets-consolidation-20260708` · Phase 3 · decision `#1882`
> **Backend:** `RECOGNITION_SECRET_BACKEND=oci_vault` (see
> `apps/prototype-description-service/shared/secrets.py:OciVaultSecretProvider`).
> **ADR:** `docs/adrs/ADR-013-oci-vault-secrets-backend.md`.

Under `oci_vault`, the `api`/`worker` containers fetch their secrets from OCI
Vault at boot using the VM's **instance principal** — no app secret ships as
host plaintext. This runbook defines the OCI identity + policy and the operator
fetch/rotation steps.

## Precondition A2 (operator-confirm gate — blocks prod cutover)

Confirm OCI IAM allows a **dynamic group** matching the backend VM plus an
**instance-principal policy** granting read-only access to the secret
compartment. **Do not flip `RECOGNITION_SECRET_BACKEND=oci_vault` in prod until
this is confirmed** — the fail-fast boot guard
(`shared/secrets.py`, [RES-13]) will refuse to serve otherwise.

## 1. Vault + secrets (single compartment, trust-domain namespacing)

Per decision `#1882`: **one** compartment, secrets namespaced by trust domain —
`secret/<domain>/<name>`. Create one Vault secret per app-consumed secret and
record its OCID in the non-secret map `RECOGNITION_VAULT_SECRET_MAP`
(`.env.prod.example`):

| Logical name (map key)    | Suggested Vault secret path          | Trust domain          |
| ------------------------- | ------------------------------------ | --------------------- |
| `POSTGRES_DSN`            | `secret/recognition/postgres-dsn`    | infra                 |
| `POSTGRES_SYNC_DSN`       | `secret/recognition/postgres-sync-dsn` | infra               |
| `PGPASSWORD`              | `secret/recognition/pg-password`     | infra                 |
| `RECOGNITION_ADMIN_TOKEN` | `secret/recognition/admin-token`     | service root-of-trust |

The map value is the secret **OCID** (an identifier, not a secret).

## 2. Dynamic group + least-privilege policy ([SEC-04])

Dynamic group — match the backend instance (scope to the exact instance OCID or
a tightly-scoped tag; do not match the whole tenancy):

```
Any {instance.id = 'ocid1.instance.oc1..<BACKEND_VM_OCID>'}
```

Policy — the **currently deployed** statement is read-only but tenancy-wide
(the VM identity may only *read* secret contents, not manage them):

```
Allow dynamic-group acx-backend-dg to read secret-family in tenancy where request.permission = 'SECRET_BUNDLE_READ'
```

> **Drift — named follow-up: scope `acx-backend-secret-read` to an
> `acx-secrets` compartment.** Verified
> 2026-09-02: no `acx-secrets` compartment exists, every secret lives in the
> **root** compartment, and the live policy `acx-backend-secret-read` reads
> `... to read secret-family **in tenancy** where request.permission =
> 'SECRET_BUNDLE_READ'`. So the VM identity can read *every* secret in the
> tenancy, not a scoped subset — the documented control was never implemented.
> This is what let a tenancy-admin API key sit in a VM-readable vault for seven
> weeks (OCIRV-1 blocker 175; key revoked and secrets scheduled for deletion
> 2026-09-02).
>
> This migration is a separate operator-gated change; do not apply it as part
> of credential rotation. Closing the drift means creating `acx-secrets`,
> moving the six secrets the VM actually consumes into it
> (`pg-password`, `POSTGRES_DSN`, `POSTGRES_SYNC_DSN`,
> `RECOGNITION_ADMIN_TOKEN`, `OCIR_USERNAME`, and `OCIR_AUTH_TOKEN`), then
> applying this **target-state** policy:
>
> ```
> Allow dynamic-group acx-backend-dg to read secret-family in compartment acx-secrets where request.permission = 'SECRET_BUNDLE_READ'
> ```
>
> Use `oci vault secret change-compartment` for those moves, then re-scope
> `acx-backend-secret-read` to the new compartment. OCIDs are stable across a
> compartment move, so `RECOGNITION_VAULT_SECRET_MAP` needs no change. A
> compartment boundary is preferable to enumerating secret OCIDs in the policy
> because a secret added to root later is then *not* readable by default
> ([SEC-04] fail-safe defaults).

Precedent: instance-principal signing is already used by
`infra/oci/gpu_lifecycle/reaper.py` — reuse that signer construction pattern.

## 3. App fetch (automatic, at boot)

`api`/`worker` build an instance-principal signer and call
`get_secret_bundle(secret_id=<OCID>)` per `RECOGNITION_VAULT_SECRET_MAP` entry,
with a bounded timeout ([RES-02]) and 5xx/transport-only backoff ([RES-06]). On
unreachable Vault / auth failure / missing required secret the process
**fail-fasts** before binding a port ([RES-13]) — no env fallback under
`oci_vault`.

## 4. Postgres container bootstrap (the one non-app secret)

The `postgres` container reads `POSTGRES_PASSWORD` directly (it is not a
Python-app secret and cannot use the provider). Under `oci_vault`, fetch it into
the runtime `.env` **before** `docker compose up` via the systemd
`ExecStartPre` hook (uncomment it in `acx-env.service.template`). Example fetch
script (operator-provided, `oci-cli` on the VM using the instance principal):

```bash
#!/usr/bin/env bash
set -euo pipefail
PW=$(oci --auth instance_principal secrets secret-bundle get-secret-bundle-by-name \
  --vault-id "$ACX_VAULT_OCID" --secret-name pg-password \
  --query 'data."secret-bundle-content".content' --raw-output | base64 -d)
# write only POSTGRES_PASSWORD into the runtime env, 0600, root-owned
grep -q '^POSTGRES_PASSWORD=' .env \
  && sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PW}|" .env \
  || printf 'POSTGRES_PASSWORD=%s\n' "$PW" >> .env
```

This is the accepted two-fetch-mechanism trade-off ([ARCH-06]; ADR-013).

## 4b. OCIR docker credential (OCIRV-1)

The registry credential used by `scripts/deploy/recognition-service.sh` is two
Vault secrets, fetched by the same mechanism as §4:

| Secret            | Contents                          | Secret? |
| ----------------- | --------------------------------- | ------- |
| `OCIR_USERNAME`   | `<namespace>/<oci-user-email>`    | no      |
| `OCIR_AUTH_TOKEN` | OCI auth token (docker password)  | yes     |

`scripts/deploy/lib/ocir-auth.sh` emits a fetch-and-login snippet that pipes the
token straight into `docker login --password-stdin`. The token is never written
to disk, never placed in argv (where `ps` would expose it), and no host keeps a
cached `~/.docker/config.json` entry. On the VM the fetch runs under
`--auth instance_principal`; on a laptop, under the operator's API key.

`oci-cli` must be present on the VM for the remote path:

```bash
python3 -m venv ~/.oci-venv && ~/.oci-venv/bin/pip install oci-cli
```

Failures are classified rather than collapsed into "auth missing", because the
three causes have different fixes and OCI returns the same
`NotAuthorizedOrNotFound` code for a missing secret and a missing grant. The
snippet emits a sentinel once it has read *any* secret from the vault, which
disambiguates the two: see `ocir_classify_login_failure`.

**Why this exists.** The credential used to be a `docker login` a human ran by
hand on each host from a token pasted out of the Console. Nothing recorded which
host held which token, and a revoked credential was indistinguishable from a
misconfigured one — one incident burned a session on a 20-pair
username/endpoint matrix before concluding the token itself was dead.
Release It! §5.4 (Steady State) rejects exactly this shape: if the system needs
regular crank-turning, admins stay logged in and fiddling follows.

**Residual manual step.** Oracle has no API that returns an auth token's secret
(`CreateAuthToken` returns it once; the Python SDK's `MyAuthToken` model omits
the field), so minting is irreducibly human. Everything after the mint is not:

```bash
make ocir-token-rotate          # prompts, does not echo, stores, verifies both hosts
pbpaste | make ocir-token-rotate OCIR_ROTATE_ARGS=--stdin    # from a password manager
```

Creating a secret is **asynchronous**: the OCID exists immediately, but
`get-secret-bundle-by-name` returns `NotAuthorizedOrNotFound` (404) until the
first version reaches ACTIVE. The rotate script therefore blocks on the
*consumer's* read path — the same call the deploy preflight makes — and only
reports success once the stored value reads back byte-identical. Expect a few
seconds under `waiting for OCIR_AUTH_TOKEN to become readable`. Without that
wait the laptop verify races the create and reports `secret_missing`, telling
the operator to store a token they just stored (observed live 2026-08-28).
Override the 120s ceiling with, for example,
`OCIR_ROTATE_ARGS='--readable-timeout 30' make ocir-token-rotate`, or invoke the
wrapper directly with
`scripts/deploy/ocir-token-rotate.sh --readable-timeout 30`. Zero explicitly
skips the consumer read-back wait; it
does not skip the mandatory direct OCIR proof.

## 5. Rotation (single-place operation)

1. Update the secret's value in OCI Vault (new secret version).
2. `POSTGRES_DSN`/`PGPASSWORD`/`RECOGNITION_ADMIN_TOKEN`: restart `api`/`worker`
   (`systemctl restart acx-<env>`) — they re-fetch the current version at boot.
3. Postgres container password: also re-run the `ExecStartPre` fetch (restart
   picks it up) and, if the DB role password changed, `ALTER ROLE` accordingly.
4. `OCIR_AUTH_TOKEN`: `make ocir-token-rotate`. The wrapper first contacts OCIR
   from the operator's laptop to prove the pasted token before any Vault write.
   After storing it, it verifies the Vault-backed credential with local Docker
   and opens an SSH session to the production VM for its Docker login check.
   `--skip-verify` skips only that production-VM SSH leg. Revoke the old token
   in the Console afterwards (the 2-token-per-user quota is easy to exhaust).

When `--set-username` is used, Vault cannot atomically update two secrets. The
wrapper proves the new username/token pair, writes `OCIR_AUTH_TOKEN` first, and
only after that helper reports success writes `OCIR_USERNAME`. A helper failure
can be indeterminate if Vault accepted a write before its read-back check
failed; inspect the named destination and retry. In particular, a later
username-write failure can leave the proven new token paired with the old
username and requires the operator to retry immediately.

No OCID map change is needed on rotation (the OCID is stable across versions).
