# Tech Debt Plan: OCI Staging Environment Not Deployed

## Problem Statement

`make reset-remote ENV=staging CONFIRM_REMOTE_RESET=RESET` brings the
`acx-staging` compose project down, clears `/opt/acx-backend/data/staging-pgdata`,
restarts the unit, and then never reaches `/ready` — Caddy returns HTTP 502
(Bad Gateway) for the full 6-attempt / 30-second retry envelope.

Dev (`dev.api.altcontext.com`) and prod (`api.altcontext.com`) come up cleanly
on the same SSH session, with `/ready` returning `{"status":"ok",...}` after
the third or fourth retry. Only staging stays unreachable.

## Evidence (2026-05-02)

Captured from a real `make reset-remote` invocation against the OCI VM
`ubuntu@acx-backend.tail1a44b8.ts.net`:

```
==> Stopping unit acx-staging
==> Bringing compose project down to release the postgres volume
 Container acx-staging-worker-1   Stopped/Removed
 Container acx-staging-api-1      Stopped/Removed
 Container acx-staging-postgres-1 Stopped/Removed
 Network   acx-staging-net        Removing
==> Sourcing ACX_PGDATA_PATH from /opt/acx-backend/staging/.env
==> Clearing /opt/acx-backend/data/staging-pgdata
==> Starting unit acx-staging
==> Verifying readiness at https://staging.api.altcontext.com/ready
curl: (56) The requested URL returned error: 502
==> Readiness not yet reported (attempt 1/6); retrying in 5s
... (attempts 2-5 also 502) ...
xx Readiness check failed after 6 attempts
```

The same script run with `ENV=dev` and `ENV=prod` succeeded on the same day,
on the same VM, against the same Caddy front, in the same SSH session.

## Implications for MVP Launch

The v0.4.0 epic ([docs/epics/v0.4.0/public-demo-launch-readiness-epic.md](../../epics/v0.4.0/public-demo-launch-readiness-epic.md))
locks the demo to `api.altcontext.com` (prod) for the public URL gate, so
prod is the only critical path for the demo itself. **However, the documented
deploy promotion path is `dev → staging → prod`** ([infra/oci/README.md](../../../infra/oci/README.md)
lines 467-486). Without a working staging:

- Promotion gates that say "after e2e verification on staging" cannot be
  satisfied — the team has been promoting dev → prod directly.
- The first real public incident triggers a rollback target that has never
  been exercised.
- Any change that depends on the full prod-shape probe surface
  (`/health/detailed`, auth-gated metrics, model-cache warm path) cannot be
  rehearsed before it lands in front of users.

This is not a release blocker for the MVP demo URL itself, but it is a
launch-readiness gap that should close before public traffic.

## Suspected Root Causes (Investigation Order)

The compose project on the VM exists and the systemd unit is defined
(`acx-staging.service` per `infra/oci/README.md:331-348`). The 502 means
Caddy resolves `staging.api.altcontext.com` to the OCI VM and forwards, but
the upstream container is not accepting traffic.

1. **The `iad.ocir.io/idu2kqqe2jxy/acx-backend:staging` image tag has never
   been built/pushed.** Promotion from dev to staging requires
   `make deploy-promote-staging` (which retags an existing dev SHA as
   `:staging` on OCIR + restarts the unit). If that has never run, compose
   pulls a stale or non-existent tag and the api container exits.

   _Check_: on the VM, `sudo docker compose -f /opt/acx-backend/staging/docker-compose.env.yml ps`
   immediately after a restart, and `sudo docker logs acx-staging-api-1`. On
   OCIR (or via `make deploy status`), confirm that `acx-backend:staging`
   exists.

2. **Alembic migrations fail on first init against the staging DSN.** After
   the destructive reset clears `staging-pgdata`, the api container runs
   migrations from scratch on start. A schema or seed-data assumption that
   passes on dev/prod but breaks on staging would leave the api stuck in
   restart loop and Caddy would still see no upstream.

   _Check_: `sudo docker logs acx-staging-api-1` for Alembic stack traces.

3. **Caddy upstream block for `staging.api.altcontext.com` is missing or
   wrong.** The dev and prod blocks work; if staging's `reverse_proxy`
   target points at a hostname/port that is no longer valid (typo,
   stale network name), Caddy would 502 even with a healthy backend.

   _Check_: `/opt/acx-backend/Caddyfile` (or wherever the multi-subdomain
   config lives — see `infra/oci/README.md` § VM Layout).

4. **The api container is healthy on its own port but the
   `acx-staging-net` Docker network attachment to the Caddy container is
   broken.** Caddy joins each env's network; if staging's network was
   recreated under a different name during the destructive reset and
   Caddy never re-joined, the proxy would 502.

   _Check_: `sudo docker network inspect acx-staging-net` for the Caddy
   container's presence.

## Acceptance Criteria

- `make reset-remote ENV=staging CONFIRM_REMOTE_RESET=RESET` reaches /ready
  within the 30-second envelope (same as dev/prod).
- `make deploy-promote-staging` runs cleanly end-to-end at least once and
  the resulting `:staging` image tag serves `/health` with a `commit_sha`
  matching the promoted ref.
- Operator runbook ([infra/oci/README.md](../../../infra/oci/README.md))
  reflects whatever the actual staging bootstrap turns out to require — a
  dev → staging promotion that has never been exercised is not a documented
  workflow.

## Priority

**Pre-MVP-launch.** Not a blocker for the demo URL itself, but the documented
promotion path (`dev → staging → prod`) cannot be exercised until staging is
healthy. Resolve before the public demo URL goes live so the team has at
least one rehearsed rollback target.

## Related

- Epic: [v0.4.0 Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md)
- Reset workflow: [`scripts/deploy/recognition-service.sh`](../../../scripts/deploy/recognition-service.sh) `do_reset()`
  (currently on `feature/e15-12`; lands on `main` with E15-12)
- Runbook: [`docs/operations/reset-smoke-runbook.md`](../../operations/reset-smoke-runbook.md)
  (currently on `feature/e15-12`)
