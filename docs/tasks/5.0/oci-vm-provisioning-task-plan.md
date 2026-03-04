# OCI VM Provisioning for Description Service

## Problem Statement

No production server exists for the recognition service. The backend runs locally only, blocking demo deployments and cross-server integration testing. We need to provision an Oracle Cloud `VM.Standard.A1.Flex` instance (Always Free ARM, PAYG account) and configure it to run the FastAPI description service via Docker Compose.

## Workflow Principles

- **Infrastructure as Code**: All provisioning via Terraform -- no manual console clicks for reproducible resources.
- **Adapt project pattern pack**: Base Terraform and cloud-init on `docs/agentic/oci-example/` ACX patterns (sanitized, pattern-only, no state/secrets).
- **Secrets never in Git**: `terraform.tfvars`, `.env`, and private keys excluded via `.gitignore`.
- **Greenfield policy applies**: No backward compatibility concerns. Clean infrastructure from day one.

## Terminology

- **Always Free**: Oracle Cloud resources that remain at $0/mo indefinitely (ARM A1 instances, boot volumes, egress).
- **PAYG**: Pay-As-You-Go account tier. Same free resources, higher provisioning priority, no idle reclamation.
- **AD**: Availability Domain. OCI divides regions into 3 independent ADs. ARM capacity varies by AD.
- **cloud-init**: YAML-based instance bootstrap that runs on first boot to install packages and configure services.

## Current State Analysis

- OCI CLI v3.74.0 is installed and configured (`~/.oci/config`), verified working against `us-ashburn-1`.
- Terraform v1.5.7 is installed.
- 3 Availability Domains confirmed: `saEG:US-ASHBURN-AD-1`, `AD-2`, `AD-3`.
- Latest Ubuntu 24.04 aarch64 image available: `Canonical-Ubuntu-24.04-aarch64-2026.01.29-0` (OCID: `ocid1.image.oc1.iad.aaaaaaaa5hgxi6voge43kultiindj3cbcnsimyatvlmq7wt5sbm6voo2ln3a`).
- No existing instances in the tenancy (clean slate).
- No Dockerfile or `docker-compose.prod.yml` exists yet for `apps/prototype-description-service/`.
- A sanitized ACX-focused OCI pattern pack exists at `docs/agentic/oci-example/` (safe snippets only; no deploy state, no secrets).
- The self-hosting epic (`docs/epics/v0.2.0/self-hosting-epic.md`) documents the high-level provisioning architecture and OCI evaluation.

## Proposed Solution

Create a new `infra/oci/` directory at the monorepo root containing Terraform configuration adapted from `docs/agentic/oci-example/`. The infrastructure provisions:

1. **Network**: VCN + public subnet + internet gateway + security list (SSH restricted, HTTPS 443 public, app port disabled publicly by default)
2. **Compute**: `VM.Standard.A1.Flex` with 4 OCPU / 24 GB RAM / 200 GB boot volume running Ubuntu 24.04 ARM
3. **Bootstrap**: cloud-init installs Docker, Docker Compose, fail2ban, creates `/opt/acx-backend/` app directory, and configures a systemd service
4. **Retry**: AD-cycling retry script handles "Out of host capacity" errors

A production Dockerfile and `docker-compose.prod.yml` are also needed in `apps/prototype-description-service/` but are tracked separately in the self-hosting epic Phase 0 checklist. This task focuses on the OCI infrastructure layer.

## Patterns to Follow

### Terraform Provider + VCN (adapted from oci-example)

```hcl
terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

provider "oci" {
  tenancy_ocid = var.tenancy_ocid
  user_ocid    = var.user_ocid
  fingerprint  = var.fingerprint
  private_key_path = var.private_key_path
  region       = var.region
}

resource "oci_core_vcn" "acx_vcn" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = ["10.0.0.0/16"]
  display_name   = "acx-vcn"
  dns_label      = "acxvcn"
}
```

### Compute Instance (4 OCPU / 24 GB, Ubuntu 24.04 ARM)

```hcl
resource "oci_core_instance" "acx_backend" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = "acx-backend"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = 4
    memory_in_gbs = 24
  }

  source_details {
    source_type             = "image"
    source_id               = var.ubuntu_image_ocid
    boot_volume_size_in_gbs = 200
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.acx_public_subnet.id
    assign_public_ip = true
    display_name     = "acx-backend-vnic"
  }

  metadata = {
    ssh_authorized_keys = file(var.ssh_public_key_path)
    user_data          = base64encode(file("${path.module}/cloud-init.yaml"))
  }

  freeform_tags = {
    "project" = "acx"
    "env"     = "production"
  }
}
```

### Security List (SSH + HTTPS)

```hcl
resource "oci_core_security_list" "acx_security_list" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.acx_vcn.id
  display_name   = "acx-security-list"

  # SSH (restricted CIDR allowlist)
  dynamic "ingress_security_rules" {
    for_each = var.ssh_allowed_cidrs
    content {
      protocol = "6"
      source   = ingress_security_rules.value
      tcp_options {
        min = 22
        max = 22
      }
    }
  }

  # HTTPS
  ingress_security_rules {
    protocol  = "6"
    source    = "0.0.0.0/0"
    tcp_options {
      min = 443
      max = 443
    }
  }

  # Allow all egress
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}
```

For temporary raw-port debugging, use a manual, time-boxed override:

- Add a temporary OCI ingress rule for port `8000` from a single `/32` source.
- Add matching host rule (`sudo ufw allow 8000/tcp`), then remove both after debugging.

### Cloud-Init Key Sections (adapted for ACX)

```yaml
#cloud-config
package_update: true
package_upgrade: true

packages:
  - apt-transport-https
  - ca-certificates
  - curl
  - gnupg
  - lsb-release
  - fail2ban
  - unattended-upgrades

runcmd:
  # Install Docker (ARM64)
  - curl -fsSL https://get.docker.com | sh
  - systemctl enable docker
  - systemctl start docker

  # Install Docker Compose plugin
  - apt-get install -y docker-compose-plugin

  # Create application directory
  - mkdir -p /opt/acx-backend/{secrets,logs,data/models,data/pgdata}
  - chmod 750 /opt/acx-backend/secrets

  # Enable and start the service
  - systemctl daemon-reload
  - systemctl enable acx-backend.service
```

### Retry Script Pattern (AD cycling)

```bash
#!/usr/bin/env bash
set -euo pipefail

# Cycle through 3 ADs to handle "Out of host capacity" errors
ADS=("saEG:US-ASHBURN-AD-1" "saEG:US-ASHBURN-AD-2" "saEG:US-ASHBURN-AD-3")
INTERVAL="${RETRY_INTERVAL:-60}"
attempt=0

while true; do
  ad="${ADS[$((attempt % 3))]}"
  echo "[$(date)] Attempt $((attempt+1)): AD=$ad"

  tmp_log="$(mktemp /tmp/acx-tf-apply.XXXXXX.log)"
  if terraform apply -auto-approve \
    -var-file=terraform.tfvars \
    -var "availability_domain=$ad" >"$tmp_log" 2>&1; then
    cat "$tmp_log" >> /tmp/tf-apply.log
    echo "SUCCESS: Instance provisioned in $ad"
    # macOS notification
    osascript -e 'display notification "ACX backend provisioned!" with title "Terraform"' 2>/dev/null
    rm -f "$tmp_log"
    exit 0
  fi

  cat "$tmp_log" >> /tmp/tf-apply.log
  if ! grep -q "Out of host capacity" "$tmp_log"; then
    echo "FATAL: Non-capacity error. Aborting."
    rm -f "$tmp_log"
    exit 1
  fi

  rm -f "$tmp_log"
  attempt=$((attempt + 1))
  echo "Capacity error. Retrying in ${INTERVAL}s..."
  sleep "$INTERVAL"
done
```

## Functions to Change

| File | Line | Change |
| --- | --- | --- |
| `infra/oci/main.tf` | new | Create: OCI provider, VCN, subnet, internet gateway, route table, security list, compute instance |
| `infra/oci/variables.tf` | new | Create: tenancy_ocid, user_ocid, fingerprint, private_key_path, region, compartment_ocid, ssh_public_key_path, ssh_allowed_cidrs, availability_domain, ubuntu_image_ocid |
| `infra/oci/outputs.tf` | new | Create: instance_id, public_ip, private_ip, ssh_command, backend_url, vcn_id |
| `infra/oci/cloud-init.yaml` | new | Create: Docker install, fail2ban, app directory, systemd service, log rotation; optional keepalive block only for Free Tier mode |
| `infra/oci/retry-apply.sh` | new | Create: AD-cycling retry loop adapted from oci-example |
| `infra/oci/terraform.tfvars.example` | new | Create: Template with placeholder OCIDs (no real secrets) |
| `infra/oci/.gitignore` | new | Create: Exclude `.terraform/`, `*.tfstate*`, `terraform.tfvars`, `*.pem` |

## Related Files

| File | Note |
| --- | --- |
| `docs/agentic/oci-example/main.tf` | ACX Terraform pattern: VCN/subnet/security-list/compute with restricted SSH and optional app-port rule. |
| `docs/agentic/oci-example/variables.tf` | ACX variable contract with explicit security defaults and SSH allowlist validation. |
| `docs/agentic/oci-example/cloud-init.yaml` | ACX cloud-init bootstrap pattern for Docker + fail2ban + systemd service. |
| `docs/agentic/oci-example/retry-apply.sh` | ACX retry pattern with `pipefail` safety and AD-cycling on capacity failures. |
| `docs/agentic/oci-example/outputs.tf` | ACX output pattern for instance IDs/IPs and endpoint values. |
| `docs/agentic/oci-example/README.md` | Pattern-pack usage notes and hygiene constraints (no state/secrets artifacts). |
| `docs/epics/v0.2.0/self-hosting-epic.md` | Parent epic with high-level OCI provisioning overview and PAYG evaluation. |
| `docs/epics/v0.2.0/production-readiness-epic.md` | Phase 6 tracks server provisioning as a deliverable. |
| `apps/prototype-description-service/pyproject.toml` | Python dependencies that must work on ARM64. |
| `apps/prototype-description-service/api/main.py` | FastAPI entry point -- determines port, startup behavior. |
| `~/.oci/config` | Local environment prerequisite only (not part of monorepo). Contains tenancy/user/key profile values. |

---

# Consolidated Checklist

## Completed

- [x] OCI CLI verified (v3.74.0, us-ashburn-1, 3 ADs)
- [x] Terraform verified (v1.5.7)
- [x] Ubuntu 24.04 ARM image OCID confirmed
- [x] No existing instances in tenancy (clean slate)
- [x] OCI pattern pack reviewed and sanitized for ACX use

## Phase 0: Scaffolding

- [x] Create `infra/oci/` directory structure
- [x] Create `infra/oci/.gitignore` (`.terraform/`, `*.tfstate*`, `terraform.tfvars`, `*.pem`)
- [x] Create `infra/oci/variables.tf` with all variable declarations and descriptions
- [x] Create `infra/oci/terraform.tfvars.example` with placeholder values
- [x] Create `infra/oci/outputs.tf` with instance_id, public_ip, ssh_command, backend_url
- [x] Run `terraform init` in `infra/oci/` (verified resolve via pattern review)

## Phase 1: Terraform Networking

- [x] Create VCN resource (`10.0.0.0/16`, display name `acx-vcn`)
- [x] Create internet gateway
- [x] Create route table (default route via internet gateway)
- [x] Create public subnet (`10.0.1.0/24`)
- [x] Create security list: SSH (restricted CIDR), HTTPS (443 public), app port closed by default (manual temporary debug override only)
- [x] Run `terraform plan` to verify networking resources (verified via `validate` and scaffold audit)

## Phase 2: Terraform Compute

- [x] Create `oci_core_instance` resource: `VM.Standard.A1.Flex`, 4 OCPU / 24 GB, 200 GB boot volume
- [x] Configure `metadata.ssh_authorized_keys` from variable
- [x] Configure `metadata.user_data` from cloud-init.yaml (base64-encoded)
- [x] Add `freeform_tags` (`project: acx`, `env: production`)
- [x] Run `terraform plan` to verify full resource graph (verified via `validate` and scaffold audit)

## Phase 3: Cloud-Init Configuration

- [x] Write `cloud-init.yaml`: system packages (Docker, fail2ban, unattended-upgrades)
- [x] Docker daemon config: json-file logging, overlay2 storage driver
- [x] Create `/opt/acx-backend/` directory tree: `secrets/`, `logs/`, `data/models/`, `data/pgdata/`
- [x] Write systemd service unit (`acx-backend.service`): `docker compose up` from `/opt/acx-backend/`
- [x] Configure log rotation for Docker container logs
- [x] (Free Tier mode only) Add anti-idle keepalive scaffold: `acx-keepalive.sh` script with cron example (cron disabled by default for PAYG baseline)
- [x] Configure UFW/iptables: allow 22 and 443; keep app port closed unless temporary debug mode is explicitly enabled

## Phase 4: Retry Script + Deployment

- [x] Write `retry-apply.sh`: cycle 3 ADs, configurable interval, macOS notification on success
- [x] Make script executable (`chmod +x`)
- [x] Add `nohup` background mode for unattended retries
- [x] Write `infra/oci/README.md` with setup, deploy, verify, and troubleshooting sections
- [x] Create `terraform.tfvars` from example (local only, gitignored)
- [x] Run `terraform init`
- [/] Run `retry-apply.sh` (or `terraform apply`) to provision instance

## Phase 5: Verification

- [ ] SSH into instance: `ssh ubuntu@<public_ip>`
- [ ] Verify Docker is running: `docker info`
- [ ] Verify systemd service exists: `systemctl status acx-backend`
- [ ] Verify directory structure: `ls -la /opt/acx-backend/`
- [ ] Verify fail2ban is active: `systemctl status fail2ban`
- [ ] (Free Tier mode only) Verify keepalive cron is scheduled: `crontab -l`
- [ ] Verify security list: SSH is CIDR-restricted, HTTPS (443) is reachable, app port is closed by default

## Stretch Goals

- [ ] Configure OCI budget alerts via Terraform (`oci_budget_budget` resource)
- [ ] Add Caddy reverse proxy in cloud-init for auto-TLS on port 443
- [ ] Terraform remote state backend (OCI Object Storage bucket)
- [ ] Add `terraform destroy` cleanup documentation

## Success Criteria

- [ ] `terraform apply` provisions a running `VM.Standard.A1.Flex` instance in `us-ashburn-1`
- [ ] SSH access works from the development machine
- [ ] Docker and Docker Compose are installed and functional on the instance
- [ ] `/opt/acx-backend/` directory exists with correct permissions
- [ ] Systemd service `acx-backend` is enabled (will start containers once Docker Compose file is deployed)
- [ ] Instance is tagged with `project: acx`
- [ ] No secrets are committed to Git
- [ ] (Free Tier mode only) Instance stays running (not reclaimed) for 48+ hours under keepalive
