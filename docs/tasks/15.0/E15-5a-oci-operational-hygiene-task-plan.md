# E15-5a. OCI Operational Hygiene (runs with the LocalWP gate)

> **Task Short ID**: E15-5a
> **Status**: scoped -- not started
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 4 (pre-public-demo hygiene)
> **Predecessors**: None (pure OCI ops; the backend is already live).
> **Sibling (runs in parallel)**: [E15-3a](./E15-3a-localwp-oci-roundtrip-task-plan.md) (LocalWP -> OCI round-trip verification).
> **Relationship to E15-5**: E15-5's original Slices 2, 3, and 4 were split out to here so they can land before the public WP demo is provisioned. [E15-5](./E15-5-manual-remote-e2e-task-plan.md) now covers only the remote E2E round-trip against the public WP demo plus the ARM-compat evidence artifact.
> **Format Note**: This is a condensed operator gate plan rather than a full feature-implementation task plan. It intentionally does not mirror every heading in `docs/agentic/templates/TASK_PLAN.template.md`; reviewers should evaluate it against the exit criteria, slice gates, and checklist evidence below.

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
- `budget-1` is the canary and uses a single `100% actual spend` threshold rule with email notifications to the operator address.
- `budget-5` and `budget-10` also add `50%` and `75%` early-warning rules (forecast or actual spend, whichever OCI supports on the chosen rule type) so a slow-burn regression is visible before the hard ceiling is crossed.
- Verify all tracked resources carry the same `project=acx` tag filter before attaching the budgets so the alert scope covers ACX-only resources.
- Trigger a synthetic test alert (OCI notification topic "send test notification" affordance) and confirm delivery to the operator inbox.
- Record the budget IDs and the test alert timestamp in the run log.

Exit: three alerts configured + one verified test delivery.

### Slice 2 -- Tailscale SSH drift fix

- Reference: [tech-debt/dynamic-ip-ssh-access.md](../tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md).
- `infra/oci/README.md` already documents Tailscale as the canonical SSH path, including install, verification, and the post-verification removal of the public TCP/22 allowlist. This slice verifies that documented flow against the live OCI VM rather than introducing a second competing procedure.
- Install Tailscale on the OCI VM (single-machine tailnet acceptable for a solo operator) if it is not already present, or verify the existing install if it is already active.
- Before tightening the OCI security list, capture and verify a break-glass recovery path: (a) OCI console serial-console access for this VM, and (b) the cloud-init / host-level procedure that would restore an IP-based SSH allowlist if Tailscale becomes unavailable. Record the exact recovery commands and verification outcome in `docs/tasks/15.0/E15-5a-oci-hygiene-run-log.md`; update `infra/oci/README.md` only if the live procedure differs from the current documented flow.
- Open SSH (22) on the Tailscale interface only; tighten the OCI security list to remove the prior home-IP CIDR allowlist.
- Verify SSH works from two networks (home + tethered/mobile) without any `terraform apply` cycle.
- If any step, hostname, or break-glass detail diverges from the existing `infra/oci/README.md` guidance, update that README in the same slice so the run log and operator docs stay aligned.

Exit: SSH works from two networks, security list scrubbed of stale CIDRs, and both the canonical Tailscale path and the verified break-glass recovery path are documented.

### Slice 3 -- Hetzner fallback plan (CX22 baseline; sizing analysis required)

- Verify the current Postgres backup mechanism on the OCI host. Expected baseline: the E14 self-hosting epic's MVP recommendation of a daily `pg_dump` cron. If that backup flow is not currently running, document that the Hetzner migration starts with a one-off `pg_dump` before transfer/restore and open a separate follow-up to automate ongoing backups.
- Produce `docs/tasks/15.0/E15-5a-hetzner-fallback-plan.md` covering:
  - Hetzner sizing selection (CX22 as baseline candidate; escalate to CX32 if a representative 15-minute OCI sample using host/container stats shows the description-service + Postgres stack sustaining more than 3 GB combined memory usage, or if the image stack fails the A1.Flex-to-x86 workload parity check defined below); document the sampling commands, timestamps, measured memory/CPU baseline, and the chosen SKU + estimated monthly cost.
  - Which env vars + secrets move (`prod/.env` surface).
  - Which DNS records change (`api.altcontext.com` A record -> Hetzner IP).
  - Postgres data migration path (`pg_dump` + transfer + restore), including whether it uses the standing backup mechanism or a one-off backup prerequisite.
  - Estimated time-to-cutover and the trigger condition (e.g. two consecutive OCI capacity failures on reboot, or a 24h outage).
- Define the parity check inline in the fallback plan: a `linux/amd64` rebuild of the current prod image stack via `docker buildx` must complete cleanly, the stack must boot with the current `docker-compose.env.yml` / `prod/.env` surfaces on an x86 target, and the same health / connection smoke used by the OCI gate must succeed without architecture-specific fixes. Failure on any of those steps is a parity miss and forces CX32 review or an explicit follow-up.
- This is a plan, not an execution. The plan exits when it passes `/planning-review` against the current `prod/.env` and `docker-compose.env.yml` surfaces (same review bar as Slices 1 and 2).

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
- **Fallback-plan rot** -- the plan references `prod/.env` and `docker-compose.env.yml`; both change over time. Mitigation: Slice 3 exit criterion is "reviews cleanly against the current files"; revisit whenever either file changes materially.

## Consolidated Checklist

> **Checklist scope rule:** Describe work being delivered, not finding status. Do not add rows like `(BR-04 closed)` or "resolve handoff issue X"; finding status lives in MCP / `DASHBOARD.txt`.

## Context and Ownership

- [x] Loaded the OCI operational context, fallback-plan anchors, and handoff state before making changes.
- [x] Confirmed no extra external dependency context is required beyond OCI, Tailscale, and the current compose/env surfaces already cited in the plan.
- [x] Kept task ownership clean: E15-5a owns OCI hygiene only, while E15-3a and E15-5 retain their gate-specific responsibilities.

### Checklist for Slice 1: OCI budget alerts

- [ ] Configure the `$1`, `$5`, and `$10` monthly OCI budgets, with the `$1` canary at `100% actual spend` and the `$5` / `$10` budgets also carrying `50%` and `75%` early-warning rules.
- [ ] Verify ACX resources carry the shared `project=acx` tag filter before attaching the budgets.
- [ ] Trigger and acknowledge a synthetic test alert, then record the budget IDs and timestamp in the run log and handoff state.

### Checklist for Slice 2: Tailscale SSH drift fix

- [ ] Verify the existing canonical Tailscale flow against the live OCI VM (installing it first only if absent) and capture the break-glass serial-console / allowlist recovery path before tightening SSH access.
- [ ] Remove the stale home-IP CIDR allowlist once Tailscale-only SSH access is confirmed.
- [ ] Verify SSH from two networks and keep `infra/oci/README.md` aligned with the verified canonical path plus break-glass recovery details.

### Checklist for Slice 3: Hetzner fallback plan (CX22 baseline; sizing analysis required)

- [ ] Verify the current Postgres backup mechanism and document any one-off `pg_dump` prerequisite if the standing backup flow is absent.
- [x] Produce `E15-5a-hetzner-fallback-plan.md` with explicit memory-sampling evidence, the amd64 parity-check definition, secrets/env migration, DNS cutover, data migration path, cutover timing, and trigger conditions.
- [ ] Hold the fallback-plan slice open until it passes planning review against the current `prod/.env` and `docker-compose.env.yml` surfaces.

## Review Readiness

- [ ] The hygiene run log captures budget verification, Tailscale verification, and the fallback-plan handoff state needed by E15-5.
- [ ] No operational hardening change lands without the matching operator documentation update.
- [ ] E15-5 is unblocked only after the backend is cost-safe, SSH-reachable, and backed by a reviewed fallback plan.

## Success Criteria

- [ ] OCI budget alerts, Tailscale SSH hardening, and the Hetzner fallback plan all meet the three declared MVP exit criteria.
- [ ] E15-5 can execute its remote E2E slice against a backend that is operationally safe enough for the public demo.

## Handoff

When done, set `E15-5a` status to `done`, archive, and notify E15-5 that OCI hygiene is complete so its Slice 1 (remote E2E) can execute against a cost-safe, SSH-reachable backend.
