# E15-5. Remote E2E Verification + Operational Hygiene (MVP-critical)

> **Task Short ID**: E15-5
> **Status**: scoped -- not started
> **Epic**: [E15. Public Demo Launch Readiness](../../epics/v0.4.0/public-demo-launch-readiness-epic.md) Phase 4
> **Predecessors**: [E15-3](./E15-3-wordpress-demo-provisioning-task-plan.md) (WP demo live)
> **Blocks**: MVP demo-URL-live signal. Once this closes, E15 MVP is shippable.
> **Sibling**: [E15-4](./E15-4-local-reset-bootstrap-hardening-task-plan.md) continues in parallel but does not gate E15-5.

---

## Objective

Prove that the full WP -> backend -> recognition round trip works against the live system, and close the operational hygiene items that would embarrass the demo (runaway OCI spend, SSH drift locking operators out, no documented fallback if OCI goes sideways).

## MVP Exit Criteria

1. A manual round-trip through the live WP demo returns recognition results, captured in a run log.
2. OCI budget alerts are active at `$1 / $5 / $10` thresholds and at least one test alert has been triggered and acknowledged.
3. SSH access to the OCI VM works reliably without requiring a `terraform apply` when the operator's public IP changes (Tailscale or equivalent persistent fix).
4. A Hetzner CX22 fallback plan is documented: what to migrate, which env vars/secrets move, which DNS records change, and an estimated time-to-cutover.

All four are required. Partial completion does not unlock MVP.

## Slice Plan

### Slice 1 -- Manual round-trip + run log

- From the public WP URL, trigger a recognition scan against the seeded media.
- Capture: timestamp, WP origin, backend correlation IDs (pulled from `/metrics` or log tail), observed latency percentiles, any errors.
- File the evidence as `docs/tasks/15.0/E15-5-mvp-round-trip-log.md`.
- Capture the ARM compatibility evidence that E14 delegated into this task: `uname -m`, container image architecture, a representative `pip freeze` or install transcript showing `aarch64` wheels where relevant, and a passing integration-test transcript against the live A1 instance. File it as `docs/tasks/15.0/E15-5-arm-compat-evidence.md`.
- If the round-trip fails, open a blocker against the active handoff and stop here; resolve before continuing.

Exit: run log filed; green round-trip confirmed.

### Slice 2 -- OCI budget alerts

- In the OCI console, configure budgets at `$1`, `$5`, and `$10` on the relevant compartment with email notifications to the operator address.
- Trigger a synthetic test alert (OCI supports a "send test notification" affordance on the notification topic) and confirm it lands in the operator inbox.
- Record the budget IDs and the test alert timestamp in the run log.

Exit: three alerts configured + one verified test delivery.

### Slice 3 -- Tailscale SSH drift fix

- Reference: [tech-debt/dynamic-ip-ssh-access.md](../tech-debt/dynamic-ip-ssh-access.md).
- Install Tailscale on the OCI VM (single-machine tailnet acceptable for a solo operator).
- Open SSH (22) on the Tailscale interface only; tighten the OCI security list to remove the prior home-IP CIDR allowlist.
- Verify SSH works from two networks (home + tethered/mobile) without any `terraform apply` cycle.
- Update `infra/oci/README.md` (or equivalent) to document the Tailscale flow as the canonical SSH path.

Exit: SSH works from two networks, security list scrubbed of stale CIDRs, docs updated.

### Slice 4 -- Hetzner CX22 fallback plan

- Produce `docs/tasks/15.0/E15-5-hetzner-fallback-plan.md` covering:
  - Hetzner CX22 sizing + estimated monthly cost.
  - Which env vars + secrets move (`.env.prod` surface).
  - Which DNS records change (`api.altcontext.com` A record -> Hetzner IP).
  - Postgres data migration path (`pg_dump` + transfer + restore).
  - Estimated time-to-cutover and the trigger condition for executing it (e.g., two consecutive OCI capacity failures on reboot, or a 24h outage).
- This is a plan, not an execution. The plan exits when the document reviews cleanly against the current `docker-compose.prod.yml` and `.env.prod.example`.

Exit: fallback plan merged.

## Deliverables

- `docs/tasks/15.0/E15-5-mvp-round-trip-log.md`
- `docs/tasks/15.0/E15-5-arm-compat-evidence.md`
- `docs/tasks/15.0/E15-5-hetzner-fallback-plan.md`
- OCI budget IDs logged in the handoff state
- Tailscale setup flow documented in `infra/oci/README.md`

## Dependencies Not Owned Here

- E15-3 WP demo live (hard predecessor).
- Operator must have OCI console admin access and a Tailscale account.

## Risks

- **Round-trip fails** -- indicates a gap between E15-1/E15-2 verification and real-world use. Mitigation: Slice 1 stops immediately and opens a blocker; root-cause before continuing.
- **OCI alert delivery unreliable** -- some email providers drop OCI notification mail as spam. Mitigation: test delivery in Slice 2 explicitly; route to a second email as secondary.
- **Tailscale bypass of corporate network** -- n/a for solo operator, but documented as a future constraint if a second operator joins.

## Handoff

When done, set `E15-5` status to `done`, archive, and record a slice-complete decision that E15 MVP signal is achieved. E15 epic can then be marked complete for v0.4.0.
