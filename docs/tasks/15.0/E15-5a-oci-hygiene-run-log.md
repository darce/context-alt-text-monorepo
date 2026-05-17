# E15-5a OCI Operational Hygiene -- Run Log

> Captures evidence from the three exit criteria in [E15-5a-oci-operational-hygiene-task-plan.md](./E15-5a-oci-operational-hygiene-task-plan.md). Fill in each section as the slice executes; operator-only sections are marked. Code/docs work happens on `feature/e15-5a`; operator verification commands run against the live OCI VM and Tailscale tenant.

## Slice 1 -- OCI Budget Alerts

> Operator action. Configure in the OCI console (Governance & Administration -> Budgets).

### Budgets

| Name        | Monthly Cap | Threshold Rules                                              | Notification Topic | Budget OCID |
|-------------|-------------|--------------------------------------------------------------|--------------------|-------------|
| `budget-1`  | $1          | `100% actual spend` (canary, single rule)                    |                    |             |
| `budget-5`  | $5          | `50% forecast` + `75% forecast` + `100% actual spend`        |                    |             |
| `budget-10` | $10         | `50% forecast` + `75% forecast` + `100% actual spend`        |                    |             |

All three budgets share the compartment scope + `project=acx` cost-tracking tag filter.

### Tag Filter Sanity Check

- [ ] Compute (instance, attached block volumes) carries `project=acx`.
- [ ] OCIR repository `acx-backend` carries `project=acx` (or is in the same compartment scope and the budget targets the compartment).
- [ ] Networking (VCN, subnet, security list, load balancer if any) carries `project=acx`.
- [ ] Any DNS zone managed in OCI carries `project=acx`.

Record the tagging command/timestamp used to backfill missing tags here:

```
<paste oci CLI / console action>
```

### Test Alert

- Notification topic: ____________________
- Subscription (operator email): ____________________
- Test send timestamp (UTC): ____________________
- Delivery confirmed in inbox: yes / no / spam-folder
- If routed to spam, secondary inbox added: yes / no -- secondary address: ____________________

Exit: three alerts configured + one verified test delivery -> tick the Slice 1 checklist items in the task plan.

---

## Slice 2 -- Tailscale SSH Drift Fix

> Operator action against the live OCI VM. The canonical Tailscale install procedure already lives in [infra/oci/README.md](../../../infra/oci/README.md#tailscale-recommended-for-dynamic-ip-workstations); update that file only if the live procedure diverges.

### State Before This Slice

- [ ] Tailscale already installed on the OCI VM? yes / no
- [ ] Workstation already on the tailnet? yes / no
- [ ] Current OCI security list contains a CIDR allowlist for SSH from a residential IP? yes / no -- if yes, capture the rule here:

```
<paste current rule>
```

### Break-Glass Recovery Path (captured BEFORE tightening the security list)

> The point of this section is to prove the operator can get back in if Tailscale itself becomes unavailable. Capture exact commands and verify them before removing the public-IP allowlist.

#### (a) OCI Console Serial-Console Access

- Console URL traversed: Compute -> Instances -> `<instance>` -> Console connection.
- Created console connection? yes / no
- SSH command for serial console (printed by OCI console):

```
<paste ssh -i ... -o ProxyCommand=... command>
```

- Connection verified (got `ocid1.instanceconsoleconnection.oc1...` shell prompt): yes / no  -- timestamp: ____________________

#### (b) Host-Level Recovery: Re-allow IP-based SSH

If the tailnet is unreachable, the recovery path is:

1. Get current workstation public IP: `curl -s checkip.amazonaws.com`.
2. From OCI console, edit security list `<security-list-OCID>` and add ingress rule `<current-IP>/32` -> TCP 22. (Mirror the rule that was in place before this slice removed it -- captured above.)
3. Re-apply via terraform when convenient: update `ssh_allowed_cidrs` in `infra/oci/terraform.tfvars`, then `cd infra/oci && terraform apply -target=oci_core_security_list.acx_security_list`.

Verification dry-run (do not actually re-open; just confirm the path is understood and the security-list OCID is known):

- Security list OCID recorded: ____________________
- Terraform target string verified: `oci_core_security_list.acx_security_list` resolves cleanly via `terraform state list | grep security_list`. yes / no

### Tailscale Verification

- [ ] `tailscale status` on workstation lists the OCI VM under its expected MagicDNS name.
- [ ] `ssh ubuntu@acx-backend.<tailnet>.ts.net 'hostname && uname -m'` succeeds.
- [ ] `make deploy-status` succeeds end-to-end with `OCI_HOST` defaulted to the tailnet name (proves deploy automation rides the tailnet).

### SSH from Two Networks

| Network        | Source                | Timestamp (UTC) | `hostname` returned | Notes |
|----------------|-----------------------|-----------------|---------------------|-------|
| Home Wi-Fi     |                       |                 |                     |       |
| Tethered/Mobile|                       |                 |                     |       |

### Security List Cleanup

- Removed CIDR allowlist entries: ____________________
- `terraform apply -target=oci_core_security_list.acx_security_list` run timestamp: ____________________
- Post-apply diff verified by `terraform plan` returning "No changes": yes / no
- Public TCP/22 confirmed closed via `nmap -p22 <public-ip>` from a non-tailnet network: yes / no

### Doc Drift Decision

- Did the live procedure require changes to `infra/oci/README.md`? yes / no
- If yes, summarize the changes here and reference the commit:

```
<diff summary + commit SHA>
```

Exit: SSH works from both networks, security list scrubbed of stale CIDRs, break-glass recovery path verified.

---

## Slice 3 -- Hetzner Fallback Plan

> See sibling file [E15-5a-hetzner-fallback-plan.md](./E15-5a-hetzner-fallback-plan.md) for the plan itself.

### Postgres Backup Baseline Check

> Lookup sequence is owned by [the fallback plan § Backup Baseline](./E15-5a-hetzner-fallback-plan.md#backup-baseline). Run those commands verbatim and record per-step outcomes here.

| Lookup step | Output (recurring schedule found? path?) |
|-------------|------------------------------------------|
| `sudo crontab -l` on OCI VM (root + ubuntu) |                                          |
| `/etc/cron.d` / `/etc/cron.daily` / `/etc/cron.hourly` |                                          |
| `systemctl list-timers --all` (any pg/backup) |                                          |
| Docker backup sidecar (`docker ps -a` filtered) |                                          |
| `/var/backups/postgres` / `/opt/acx-backend/backups` |                                          |

- Final result: standing backup found / absent (one-off `pg_dump` required) -- circle one.
- If absent, follow-up task ref to automate backups: ____________________ (link in handoff state once filed).
- Sample command output saved to (run log attachment or paste path): ____________________

### Memory-Sampling Evidence Capture

> A 15-minute sample of the description-service + Postgres stack drives the CX22-vs-CX32 sizing decision (see [E15-5a-hetzner-fallback-plan.md § Sizing Analysis](./E15-5a-hetzner-fallback-plan.md#sizing-analysis-cx22-baseline)).

| Sample window (start -> end, UTC) | Sample command | Peak RSS (api+worker+postgres) | Peak CPU% | Output file/snippet |
|-----------------------------------|----------------|--------------------------------|-----------|---------------------|
|                                   |                |                                |           |                     |

Sampling commands (paste verbatim used commands here):

```
<docker stats --no-stream --format ...>
<ssh ubuntu@acx-backend.<tailnet>.ts.net "free -m && top -bn1 | head -20">
```

### amd64 Parity Check Outcome

| Step                                    | Outcome | Notes |
|-----------------------------------------|---------|-------|
| `docker buildx build --platform linux/amd64 ...` |       |       |
| `docker compose -f docker-compose.env.yml up -d` on x86 host |  |       |
| `/health` smoke against x86 stack       |         |       |
| `/recognition/health` smoke against x86 stack |   |       |

- Decision: CX22 baseline holds / escalate to CX32 / blocked on architecture-specific fix
- Rationale: ____________________

### Planning-Review Outcome

- [x] `/planning-review` run against `docs/tasks/15.0/E15-5a-hetzner-fallback-plan.md` returned `pass` on 2026-05-17.
- Review run id: `planning-review-E15-5a-slice3-20260517` (MCP id 586; verdict decision `planning_review_e15_5a_slice3_pass`).
- Findings opened (now all fixed): `E15-5a-PA-01..PA-10` (carried over from `plan-analyze-E15-5a-slice3-20260517`) plus net-new `E15-5a-PR-01`, `E15-5a-PR-02`. All closed at commit `1a66402e6a97f5c6bc13e743ccef077e10b4ead5`.

Exit: fallback plan merged with planning-review approval recorded.

---

## Task-Level Sign-Off

- [ ] All three slices passed their exit gates above.
- [ ] Budget OCIDs recorded in handoff state (`record_event(event_kind="decision", decision="e15-5a_oci_budget_ids", rationale="<list>")`).
- [ ] E15-5 notified that OCI hygiene is complete (cross-task decision recorded).
