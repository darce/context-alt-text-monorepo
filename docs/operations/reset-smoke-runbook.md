# Reset Smoke Runbook

Operator-facing procedure for proving the recognition service + plugin pair
still talks end-to-end after either of the two destructive reset paths fires.
Closes E15-12 Slice 3 checklist items "service-mode smoke after OCI dev reset"
and "local-mode smoke after local reset".

This runbook is procedure only. It does **not** restate the destructive reset
contracts or what the resets do — those live in the two reset docs and are
linked from the matching smoke section below.

## When to run

- Immediately after `make reset-remote ENV=<env>` (OCI smoke).
- Immediately after `make reset-local` (local smoke).
- Whenever a release-readiness gate calls for a fresh end-to-end proof on
  either side.

## OCI service-mode smoke

1. **Run the destructive reset and capture the bootstrap output.** See
   [`infra/oci/README.md` § Destructive Remote Reset](../../infra/oci/README.md#destructive-remote-reset)
   for the command, confirmation gates, and dry-run lever. The destructive run
   prints `api_key=<token>` from the in-container `manage_api_keys create`
   step — copy that line.
2. **Configure the plugin for service mode.** In WP admin → Settings → Alt
   Context, set:
   - Recognition source: `Service`
   - Service URL: the env's public API URL (e.g. `https://dev.api.altcontext.com`)
   - API key: the `api_key=` value from step 1
3. **Hit the plugin workbench probe.** WP admin → Alt Context → Workbench → run
   the connectivity probe. Expected: probe reports the service URL is reachable
   and the API key is accepted.
4. **Capture the proof** (see `## Proof template` below).

## Local-mode smoke

1. **Run the destructive reset.** See
   [`apps/prototype-description-service/README.md` § Database (Local PostgreSQL reset contract)](../../apps/prototype-description-service/README.md#database-local-postgresql-reset-contract)
   for the command and `.env` contract. Local reset rebuilds the dev DB; no
   API key is involved because local mode bypasses service-auth probing.
2. **Configure the plugin for local mode.** In WP admin → Settings → Alt
   Context, set:
   - Recognition source: `Local`
   - The Service URL / API key fields are intentionally inert in local mode
     and may be left as-is; the runtime targets `http://localhost:8000`
     directly.
3. **Hit the plugin workbench probe.** Expected: workbench/status copy
   describes the runtime as selected local mode, not as missing service
   configuration. The probe reaches `localhost:8000`.
4. **Capture the proof** (see `## Proof template` below).

## Proof template

File one proof per smoke under
`docs/tasks/15.0/E15-12-slice3-reset-smoke-proofs.md`, appending sections
rather than overwriting. Each section is short:

```markdown
### <oci-service-mode | local-mode> smoke — YYYY-MM-DD

- **Operator**: <name>
- **Reset command**: `<exact command, including ENV= and confirmation env vars>`
- **Service HEAD before reset**: `<commit_sha[:8]>` (from `/health` if remote, or `git rev-parse HEAD` if local)
- **/ready verification**: `<HTTP 200 from <url> at <timestamp>>` (remote only)
- **Plugin selector mode**: `service` | `local`
- **Workbench probe outcome**: `<one-line summary — pass/fail + observed message>`
- **Notes**: <one paragraph max — only if anything diverged from the runbook>
```

The proof is committed on whichever feature branch is active for the smoke
(for E15-12 itself, `feature/e15-12`). Once both smokes are filed, slice 3 is
closeable and this runbook stays as the standing procedure for future resets.

## Cross-references

- Destructive remote reset contract: [`infra/oci/README.md` § Destructive Remote Reset](../../infra/oci/README.md#destructive-remote-reset)
- Local reset contract: [`apps/prototype-description-service/README.md` § Database (Local PostgreSQL reset contract)](../../apps/prototype-description-service/README.md#database-local-postgresql-reset-contract)
- Recognition source selector contract: [E15-12 task plan § Slice 1](../tasks/15.0/E15-12-standard-deployment-reset-and-recognition-source-task-plan.md)
- Probe surfaces: [`docs/operations/observability-runbook.md`](./observability-runbook.md)
