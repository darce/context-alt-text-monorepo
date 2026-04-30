# Dynamic IP SSH Access Drift

## Problem

The OCI VM security list restricts SSH to a single `/32` IP in `terraform.tfvars`. Residential ISPs reassign IPs without notice, breaking SSH access until `terraform apply` is re-run with the new IP. This has already caused deployment interruptions (E14-1 Slice 5).

## Impact

- Blocks all VM deployment and verification work until the IP is updated
- Requires manual detection of the new IP and a terraform apply cycle
- `terraform.tfvars` is ignored in this repo, so the SSH allowlist fix is workstation-local unless it is reapplied or documented elsewhere

## Solutions (ordered by recommendation)

### 1. Tailscale mesh VPN (recommended)

Install Tailscale on both the Mac and the OCI VM. SSH over the private `100.x.x.x` mesh. Lock the OCI security list to the Tailscale IP (stable, never changes).

**Effort**: ~15 minutes. Free for personal use.

```bash
# On Mac
brew install tailscale

# On VM (Ubuntu 24.04)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Then lock security list to the VM's Tailscale IP
ssh_allowed_cidrs = ["100.x.x.x/32"]
```

**Pros**: Zero-trust auth, stable IP, works from any network (coffee shop, travel).
**Cons**: Extra daemon on the VM.

### 2. Auto-detect IP alias (interim)

A shell alias that detects the current IP, applies terraform, and connects:

```bash
# Add to ~/.zshrc
alias ssh-oci='cd ~/Development/context-alt-text-monorepo/infra/oci && \
  terraform apply -auto-approve \
  -var "ssh_allowed_cidrs=[\"$(curl -s checkip.amazonaws.com)/32\"]" \
  -target=oci_core_security_list.acx_security_list && \
  ssh ubuntu@129.213.40.111'
```

**Pros**: No extra infrastructure. Works now.
**Cons**: Terraform apply on every connect (~30s), tfvars drift in git.

### 3. Broader CIDR block

Allow the ISP's subnet instead of a single IP:

```hcl
ssh_allowed_cidrs = ["99.237.0.0/16"]
```

**Pros**: Survives IP changes within the same ISP.
**Cons**: Less secure (exposes SSH to ~65k addresses), breaks if ISP changes subnet.

## Decision

Pending. Implement solution 2 (alias) immediately as a stopgap, then evaluate Tailscale for permanent fix.

## Consolidated Triage Checklist (2026-04-30)

**Disposition:** Archive candidate; Tailscale path is implemented/documented.
**Evaluation basis:** Current `main` infrastructure/deploy surfaces.

- [x] Canonical access path is documented in `infra/oci/README.md`: SSH via `ubuntu@acx-backend.tail1a44b8.ts.net`.
- [x] Tailscale setup, MagicDNS verification, troubleshooting, and deploy-script wiring are documented in `infra/oci/README.md`.
- [x] `scripts/deploy/recognition-service.sh` defaults `OCI_HOST` to `acx-backend.tail1a44b8.ts.net`.
- [x] Public-IP SSH remains documented as fallback only.
- [ ] Before final archive, update or remove stale cross-links that still describe this as pending E15/E14 work.
