# E15-5a. OCI Operational Hygiene (runs with the LocalWP gate)

> **Task Short ID**: E15-5a
> **Status**: scoped -- not started
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 4 (pre-public-demo hygiene)
> **Predecessors**: None (pure OCI ops; the backend is already live).
> **Sibling (runs in parallel)**: [E15-3a](./E15-3a-localwp-oci-roundtrip-task-plan.md) (LocalWP -> OCI round-trip verification).
> **Relationship to E15-5**: E15-5's original Slices 2, 3, and 4 were split out to here so they can land before the public WP demo is provisioned. [E15-5](./E15-5-manual-remote-e2e-task-plan.md) now covers only the remote E2E round-trip against the public WP demo plus the ARM-compat evidence artifact.

---

## Objective

Land the OCI operational hygiene that would embarrass the MVP demo if left undone (runaway spend, SSH drift locking operators out, no documented fallback if OCI proves unreliable) **before** any paid WP host is provisioned. None of these items depend on the WP demo existing; all of them should be in place when the demo goes public.

## MVP Exit Criteria

1. OCI budget alerts are active at `$1 / $5 / $10` thresholds, and at least one test alert has been triggered and acknowledged.
2. SSH access to the OCI VM works reliably from two networks (home + tethered/mobile) without any `terraform apply` cycle when the operator's public IP changes (Tailscale or equivalent persistent fix).
3. A Hetzner CX22 fallback plan is documented: what to migrate, which env vars / secrets move, which DNS records change, Postgres data migration path, estimated time-to-cutover, and the trigger condition for executing it.

All three are required.

## Non-Goals (explicit)

- Remote E2E round-trip against the public WP demo -- owned by [E15-5](./E15-5-manual-remote-e2e-task-plan.md) Slice 1.
- ARM compatibility verification artifact -- owned by [E15-5](./E15-5-manual-remote-e2e-task-plan.md) Deliverables.
- LocalWP round-trip verification -- owned by [E15-3a](./E15-3a-localwp-oci-roundtrip-task-plan.md).
- Executing the Hetzner migration -- this task only produces the plan document.

## Slice Plan

### Slice 1 -- OCI budget alerts

- Configure three **monthly** OCI budgets on the ACX compartment: `budget-1` = `$1`, `budget-5` = `$5`, `budget-10` = `$10`.
- Each budget uses a `100% actual spend` threshold rule with email notifications to the operator address.
- Verify all tracked resources carry the same `project=acx` tag filter before attaching the budgets so the alert scope covers ACX-only resources.
- Trigger a synthetic test alert (OCI notification topic "send test notification" affordance) and confirm delivery to the operator inbox.
- Record the budget IDs and the test alert timestamp in the run log.

Exit: three alerts configured + one verified test delivery.

### Slice 2 -- Tailscale SSH drift fix

- Reference: [tech-debt/dynamic-ip-ssh-access.md](../tech-debt/dynamic-ip-ssh-access.md).
- Install Tailscale on the OCI VM (single-machine tailnet acceptable for a solo operator).
- Before tightening the OCI security list, capture and verify a break-glass recovery path: (a) OCI console serial-console access for this VM, and (b) the cloud-init / host-level procedure that would restore an IP-based SSH allowlist if Tailscale becomes unavailable. Document both in `infra/oci/README.md` alongside the Tailscale flow.
- Open SSH (22) on the Tailscale interface only; tighten the OCI security list to remove the prior home-IP CIDR allowlist.
- Verify SSH works from two networks (home + tethered/mobile) without any `terraform apply` cycle.
- Update `infra/oci/README.md` (or equivalent) to document the Tailscale flow as the canonical SSH path.

Exit: SSH works from two networks, security list scrubbed of stale CIDRs, and both the canonical Tailscale path and the verified break-glass recovery path are documented.

### Slice 3 -- Hetzner CX22 fallback plan

- Verify the current Postgres backup mechanism on the OCI host. Expected baseline: the E14 self-hosting epic's MVP recommendation of a daily `pg_dump` cron. If that backup flow is not currently running, document that the Hetzner migration starts with a one-off `pg_dump` before transfer/restore and open a separate follow-up to automate ongoing backups.
- Produce `docs/tasks/15.0/E15-5a-hetzner-fallback-plan.md` covering:
  - Hetzner CX22 sizing + estimated monthly cost.
  - Which env vars + secrets move (`.env.prod` surface).
  - Which DNS records change (`api.altcontext.com` A record -> Hetzner IP).
  - Postgres data migration path (`pg_dump` + transfer + restore), including whether it uses the standing backup mechanism or a one-off backup prerequisite.
  - Estimated time-to-cutover and the trigger condition (e.g. two consecutive OCI capacity failures on reboot, or a 24h outage).
- This is a plan, not an execution. The plan exits when it reviews cleanly against the current `docker-compose.prod.yml` and `.env.prod.example`.

Exit: fallback plan merged.

## Deliverables

- `docs/tasks/15.0/E15-5a-oci-hygiene-run-log.md` (captures budget IDs, test alert timestamp, Tailscale verification transcript).
- `docs/tasks/15.0/E15-5a-hetzner-fallback-plan.md` (the fallback plan document).
- OCI budget IDs logged in the handoff state.
- Tailscale setup flow documented in `infra/oci/README.md`.

## Dependencies Not Owned Here

- OCI console admin access.
- Tailscale account (free personal tier acceptable).
- Operator email delivery not routing OCI mail to spam (verified in Slice 1).

## Risks

- **OCI alert delivery dropped as spam** -- silent failure mode for cost protection. Mitigation: Slice 1 test delivery is explicit; if the primary inbox drops it, route to a second address as secondary.
- **Tailscale bypass of corporate network** -- n/a for solo operator, but documented as a future constraint if a second operator joins.
- **Fallback-plan rot** -- the plan references `docker-compose.prod.yml` and `.env.prod.example`; both change over time. Mitigation: Slice 3 exit criterion is "reviews cleanly against the current files"; revisit whenever either file changes materially.

## Handoff

When done, set `E15-5a` status to `done`, archive, and notify E15-5 that OCI hygiene is complete so its Slice 1 (remote E2E) can execute against a cost-safe, SSH-reachable backend.
