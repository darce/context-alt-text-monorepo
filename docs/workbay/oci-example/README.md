# OCI Pattern Pack (ACX)

Project-scoped OCI patterns for provisioning the ACX description-service host.

## Purpose

This directory is a **pattern pack**, not a deployed environment snapshot.
Use these files as source material when creating `infra/oci/`.

## Included Patterns

- `main.tf`: VCN, subnet, security list, compute instance, and networking lookups
- `variables.tf`: variable contract with secure defaults and debug-port gating
- `outputs.tf`: instance/IP/endpoint outputs
- `cloud-init.yaml`: Docker + fail2ban + service bootstrap for `/opt/acx-backend`
- `retry-apply.sh`: AD-cycling apply loop for OCI capacity errors
- `terraform.tfvars.example`: placeholder-only variable template

## Guardrails

- No state snapshots in Git (`*.tfstate*`)
- No local variable files in Git (`terraform.tfvars`)
- No logs/backups in Git (`*.log`, `*.bak`, `.DS_Store`)
- No project-specific secrets, OCIDs, or API fingerprints

## Security Defaults

- Public ingress: `443` only
- SSH (`22`): restricted to explicit CIDR allowlist
- App port (`8000` by default): closed unless temporary debug mode is explicitly enabled

## Usage

1. Copy patterns into `infra/oci/` and rename/adapt as needed.
2. Populate a local `terraform.tfvars` from `terraform.tfvars.example`.
3. Keep `terraform.tfvars` untracked.
4. Use `retry-apply.sh` only after validating `terraform plan`.

## Free Tier vs PAYG

- PAYG baseline: no keepalive cron required.
- Free Tier mode: optional keepalive may be added if idle reclamation is observed.
