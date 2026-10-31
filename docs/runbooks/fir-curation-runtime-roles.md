# FIR curation runtime roles

This is a staged operator procedure for `FIR-RUNTIME-ROLE-01`, based on source
`44b476e6`. It requires the combined runtime-role delta gate, a deployed image
containing both source lanes, and a separate live acceptance receipt. Source
qualification does not authorize running these commands against FIR.

The recorded live request-session counterexample was own rows 4 / foreign rows
48 under `acx_dev_fir` with SUPERUSER/BYPASSRLS despite FORCE RLS. It establishes
a configuration defect, not an HTTP cross-tenant exploit. It blocks **new
curation live qualification**; accepted cf42 UI and helper f03 are not reopened.
Staged WP47a/API0967 remain inactive until their own acceptance.

## Scope and credentials

Run `python -m scripts.provision_fir_runtime_roles` from the description-service
application root, using the existing environment. Default execution is a
read-only dry run. Only `--apply` creates roles/grants and private profile files.
The tool never edits Compose, `.env`, policies, schema ownership, or app data.
There is no dependency installation, model loading, inference, or migration in
this tool. Supported server major is PostgreSQL 17.

The owner URL must arrive via a regular, operator-owned, single-link 0600 file,
or `--owner-dsn-file -` with redirected stdin. Never put it in argv, shell
history, a ticket, or a runtime profile. Owner and runtime principals must
differ. Supply the **existing** host, port and database independently; the tool
checks URL identity and actual connected database before any DDL. Only
`alt_context_dev_fir` and isolated `acx_role_*` / `acx_boot_*` test databases are
in scope. Every DSN must specify TCP host, port, database, username and password.
All URL queries/fragments are refused, including nested `dsn`, role/options,
service, and query credential overrides. This bounded path does not support
query-based TLS settings or an unresolved Vault provider; do not weaken it to
make an unrelated target pass.

Use a private resolved Compose JSON input: the existing configuration's
`services.api.environment`, `services.worker.environment`, and
`networks.backend.name`. Keep it outside the repository. Capture configuration
only into a private file with umask 077; `docker compose config` contains
secrets and must never be sent to stdout, logs, or an artifact publisher.
Resolve the two current DSNs explicitly using actual `db.settings` values:
`POSTGRES_DSN` and `POSTGRES_SYNC_DSN`. Include the existing `PGVECTOR_DIM` and
retain the exact per-service configuration. The input network must be
`acx-dev-fir-net`; `acx-dev-net` is a known bootstrap/alias collision. A flat
JSON environment mapping is supported only when it is deliberately common to
both services. A network-name field in a container environment alone is not a
Docker network assertion; the generated override also pins `networks.backend`.

The generated private `runtime.compose.json` overrides Compose **environment**,
which wins over `env_file`. API and worker receive separate random passwords.
It replaces `POSTGRES_DSN`, `POSTGRES_SYNC_DSN`, `PGUSER`, `PGPASSWORD`,
`POSTGRES_USER`, `POSTGRES_PASSWORD`, and the developer `APP_PGUSER` /
`APP_PGPASSWORD` aliases. Host/port/database aliases remain the existing target.
Unused `DATABASE_URL`, `SQLALCHEMY_DATABASE_URI`, `PGSERVICE`, `PGSERVICEFILE`,
`PGPASSFILE`, `PGOPTIONS`, and Vault-map aliases are emptied, preventing another
owner credential source from surviving. Unknown fields containing owner
credentials are refused. Existing tenant rows, DB-only application API keys,
authentication settings, recognition settings and embedding-space selection
remain unchanged. An environment API-key allowlist is retired and must not be
reintroduced.

Both roles are LOGIN, NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE,
NOREPLICATION and NOINHERIT, with no memberships or object ownership. Grants
name existing FIR data-plane tables and their owned sequences explicitly;
there are no ALL TABLES, future default privileges, TRUNCATE, ownership transfer,
or schema CREATE grants. The API has no MAINTAIN privilege. Payment/portal/
operator-recovery tables are outside this bounded grant set. This is not a new
billing integration or full application acceptance; ADR-014 remains provider
authority.

**PUBLIC prerequisites:** the target must already deny PUBLIC database
CREATE/TEMPORARY and schema CREATE. PostgreSQL privileges are additive: revoking
from the new role does not deny inherited PUBLIC rights. The provisioner
refuses rather than altering grants for unrelated principals. After inventorying
affected users, a separately authorized owner hardening job can use
`REVOKE TEMPORARY ON DATABASE alt_context_dev_fir FROM PUBLIC` and
`REVOKE CREATE ON SCHEMA public FROM PUBLIC` where applicable. Re-run preflight;
never silently broaden the runtime role or treat a denial as successful work.

Column privileges are audited the same way. PostgreSQL adds a column grant
such as `UPDATE (version_num) ON alembic_version` to table rights, and a
table-level check does not show it. Each role's effective SELECT, INSERT,
UPDATE and REFERENCES on any column, including PUBLIC grants and grant
options, must match its table manifest. Apply rolls back both new roles, and a
custody repeat refuses without changes. The dry run cannot audit roles that do
not exist yet, so an ambient PUBLIC column grant is first reported by `--apply`.
After inventorying affected users, a separately authorized owner job revokes
only that specific unintended grant. Then re-run the provisioner.

## Worker maintenance is an explicit scope

The exact worker sets transaction-local `app.bypass_rls` before global queue
claims. Existing policies intentionally support that context. It is distinct
from the PostgreSQL role's BYPASSRLS attribute. Real seeded queue claims and
claim/retry rollback must pass with NOSUPERUSER/NOBYPASSRLS. Neither a tenantless
empty scan nor `ALLOW_RLS_BYPASS_FOR_TESTS=1` qualifies the worker.

The default worker profile is **claim/retry only**. Actual source
`_refresh_mv_concurrent_with_bypass` fails SQLSTATE 42501 without centroid
maintenance permission; do not start the full worker on that basis. The
smallest optional mechanism is `--worker-centroid-maintain`: PostgreSQL 17
`MAINTAIN` on **only** the existing `mv_identity_cluster_centroids`, never
BYPASSRLS, ownership, or a policy edit. That scope is recorded in custody and
must match every repeat invocation. Its isolated qualification exercises the
actual refresh helper and reset of its session-level bypass GUC. It does not
qualify model execution, a live workload, or all worker handlers.

The API's exact request dependency resets bypass and sets tenant context; the
isolated request test must see foreign rows **0**. Existing policies also
permit a client that deliberately sets `app.bypass_rls` to request global
access. This repair does not redesign that existing GUC trust model, protect
against a compromised SQL client, or make materialized views RLS tables. Such
changes need their own reviewed policy scope.

## Ordered cutover after the combined gate

1. Record the exact source/image/Compose tuple, current role attributes,
   policies, actual request-session behavior, network identity and API-key /
   tenant identity. Drain **both API and worker writers**, including old
   containers and external writers. Keep them fenced throughout schema work.
2. Take a database backup and verify recovery in an isolated restore. Record
   the backup identifier, restore result, recovery point and custody. A file
   merely existing is not verified recovery. Preserve new receipts and the
   additive nullable replay-fingerprint column during any rollback.
3. In a separate privileged owner job, run the existing Alembic chain, then
   `python -m scripts.sync_identity_schema`, then the global
   `python -m scripts.verify_identity_schema`. Use the existing drain
   attestation only when writers are actually drained. No new migration is
   introduced. An old already-stamped 001 revision can make Alembic a no-op;
   the existing model001 heal/verify is required. Legacy NULL fingerprint
   receipts remain unknown; never adopt the first retry as their authority.
4. Harden PUBLIC privileges in that separately authorized job if preflight
   reports them. Prepare private owner and resolved-environment inputs and
   choose two unused dedicated names. For example, with operator-substituted
   existing endpoint values, first run this **without** `--apply`:

   ```sh
   python -m scripts.provision_fir_runtime_roles \
     --owner-dsn-file /secure/fir-owner.dsn \
     --runtime-environment-file /secure/fir-resolved-compose.json \
     --expected-host "$FIR_EXISTING_DB_HOST" \
     --expected-port "$FIR_EXISTING_DB_PORT" \
     --expected-database alt_context_dev_fir \
     --api-role acx_fir_api_runtime --worker-role acx_fir_worker_runtime \
     --worker-centroid-maintain \
     --profile-dir /secure/fir-runtime
   ```

   After reviewing the dry-run result and actual maintenance requirement,
   repeat the identical command with `--apply`. No endpoint is guessed here.
   For claim-only qualification omit `--worker-centroid-maintain` and keep the
   full worker stopped. Output is credential-free JSON; files are 0600 in a
   0700 directory. Do not display or publish `docker compose config` after
   applying the override.
5. Validate the assembled Compose configuration privately. It must select
   `acx-dev-fir-net`, preserve the existing host/port/database, application
   API key and tenant, and contain no owner URL in either runtime environment.
   Both runtime environments set `ACX_SCHEMA_BOOTSTRAP_MODE=verify` and
   `ALLOW_RLS_BYPASS_FOR_TESTS=0`. Retain owner input only in its separate
   operator custody; never mount or copy it into API/worker containers.
6. Start **API only**, including the private override as the final Compose
   file. Its verify-mode startup must run no migrations/healing/DDL, retain
   baked-image/blob/cache/signal guards and refuse privileged roles. Record
   actual settings resolution/current_user and exact request dependency
   own/foreign counts. Stop if the role is privileged, a safety gate fails,
   owner credentials survive, or foreign rows are nonzero.
7. Start the worker only after owner schema heal/verification and API role
   acceptance, with its dedicated profile and qualified maintenance scope.
   Compose's worker CMD (`python -m recognition.worker.scan_worker`) overrides
   the image's API entrypoint: it **does not run that migration chain**. Record
   claim/transaction/retry behavior with real seeded, non-inference controls,
   then follow the separately authorized live workload qualification. Never
   enable test RLS bypass or infer success from an empty queue.

## Custody, repeat operation and rollback

`custody.json` contains private generated credentials, target database OID,
role OIDs, and a random role-comment marker. Protect and back it up with the
same restrictions as the private profile. It contains no owner credential.
A repeat requires the same database/role identities, marker, exact profile,
scope, safe attributes, memberships, ownership and effective table, column and
sequence rights. It returns unchanged and does not rotate passwords. Missing custody,
an existing unowned role, privileges drifting, or a changed input/profile
causes refusal. The tool never repairs or adopts those roles silently.

DDL/grants are transactional; private files are staged before commit and
removed on failure only if created by that invocation. A crash or ambiguous
commit can leave orphan custody or orphan roles. Keep writers stopped, inspect
exact database/role OIDs and the marker in a separately authorized owner
recovery procedure, and recover private custody from backup. Do not rerun with
new names as a substitute for understanding the state or rotate/adopt an
unknown role. The tool has no automatic role deletion/recovery mode.

Rollback is fail closed: stop API and worker; keep old writers fenced. Prefer
a compatible transitional application with the additive column and new
receipts retained. Do not downgrade the schema, restore a pre-cutover backup
over newer receipts, or restart an old owner-credential profile merely because
an image is available. Recheck exact request-session RLS and worker scope
before reopening writes. If compatibility or custody is uncertain, leave
writers stopped and preserve evidence.

## Isolated verification

Use the existing venv through the coordinator's two-slot `common/run_check.py`:

```sh
/home/gate/src/context-alt-text-monorepo/.venv/bin/python ../../common/run_check.py \
  /home/gate/src/context-alt-text-monorepo/.venv/bin/python -m pytest \
  -q -s scripts/test_fir_runtime_roles.py
```

Run from the source checkout root; the relative wrapper path is specific to
this bounded workspace. Tests assert the supplied loopback15437 admin database
and PG17.11 before creating randomized `acx_role_*` databases/roles, construct
the existing current model001 schema, exercise real request and queue source,
and drop only their exact own artifacts in `finally`. No FIR connection,
Compose change, GPU, download or inference occurs. Retain `.task-state`
command/output evidence. Final acceptance still requires the one combined
independent delta gate and separately authorized rollout.
