# OCI Infra Topology — redacted discovered map

> **Live OCI identifiers are operator-held and are not stored in this repo.**
> Repo-owned configuration contracts live in [`variables.tf`](variables.tf) and
> [`terraform.tfvars.example`](terraform.tfvars.example); lifecycle installation
> is implemented by [`scripts/deploy/gpu-lifecycle-install.sh`](../../scripts/deploy/gpu-lifecycle-install.sh).
> The tables below are a redacted human narrative and must be verified against OCI.

> **Purpose.** Snapshot of the *actual* provisioned OCI topology so agents don't
> re-discover it each session. Captured 2026-07-13 during VLM-3B Slice 7a GPU
> provisioning. Verify OCIDs with `oci ... get` before destructive ops — this is a
> map, not live state. Terraform state is **absent** (see §Terraform), so OCI is
> the only source of truth until adoption lands.

## Tenancy / region / compartment

| Field | Value |
| --- | --- |
| Tenancy OCID | `<tenancy-ocid>` |
| Region | `us-ashburn-1` (iad) |
| Compartment | **root tenancy** — all resources live here (no sub-compartments; the runbook's "acx-secrets" compartment is aspirational, not real) |
| Admin OCI user | `<user-ocid>` (fingerprint `ac:72:f7:...:d0`) |

## Vault + secrets (secrets topology)

**Vault `acx-vault`:** `<vault-ocid>`
- KMS master key: `<key-ocid>`
- mgmt endpoint: `https://ejvffpzlaafc4-management.kms.us-ashburn-1.oraclecloud.com`
- crypto endpoint: `https://ejvffpzlaafc4-crypto.kms.us-ashburn-1.oraclecloud.com`

| Secret name | OCID (suffix) | Purpose |
| --- | --- | --- |
| `POSTGRES_DSN` | `...n2xp5l2eu243wqqa` | app (description-service) |
| `POSTGRES_SYNC_DSN` | `...yb4kd4ke7zwn73jq` | app |
| `PGPASSWORD` | `...ijw32nzjly2uetzq` | app / postgres bootstrap |
| `RECOGNITION_ADMIN_TOKEN` | `...l72gxqhjkai7a2ea` | service root-of-trust |
| `OCI_ADMIN_API_KEY_PEM` | `<vaultsecret-ocid>` | **admin API signing key** (base64 PEM) — added 2026-07-13 |
| `OCI_ADMIN_CONFIG` | `<vaultsecret-ocid>` | **admin oci config** (base64; `key_file=/home/ubuntu/.oci/oci_api_key.pem`) — added 2026-07-13 |

### Admin-credential flow (how acx-backend gets compute rights)

acx-backend's instance-principal (`acx-backend-dg`) is **secret-read only** — it has
**no compute/image rights**. To run terraform/oci-CLI/bench, acx-backend fetches the
admin key from the vault and configures oci-CLI:

```bash
# on acx-backend (needs oci-cli + instance-principal):
mkdir -p ~/.oci
oci --auth instance_principal secrets secret-bundle get \
  --secret-id <vaultsecret-ocid> \
  --query 'data."secret-bundle-content".content' --raw-output | base64 -d > ~/.oci/oci_api_key.pem
oci --auth instance_principal secrets secret-bundle get \
  --secret-id <vaultsecret-ocid> \
  --query 'data."secret-bundle-content".content' --raw-output | base64 -d > ~/.oci/config
chmod 600 ~/.oci/oci_api_key.pem ~/.oci/config
oci os ns get   # verify
```

> **SECURITY [SEC-04].** `OCI_ADMIN_*` is a *tenancy-admin* key readable by
> `acx-backend-dg`. This grants acx-backend effective full-admin — accepted trade-off
> for greenfield provisioning (operator decision 2026-07-13). Follow-up: replace with a
> least-privilege user scoped to compute+network+KMS in the GPU compartment once the
> tier is stable. **VERIFY PENDING:** acx-backend has no oci-CLI installed yet; the
> instance-principal read round-trip is untested.

### Dynamic group + policy (least privilege, read-only)

```
Dynamic group acx-backend-dg: Any {instance.id = '<acx-backend OCID>'}
Policy: Allow dynamic-group acx-backend-dg to read secret-family in compartment <root>
        where request.permission = 'SECRET_BUNDLE_READ'
```

## Network (VCN `acx-vcn`)

| Resource | OCID | Notes |
| --- | --- | --- |
| VCN `acx-vcn` | `<vcn-ocid>` | `<vcn-cidr>` |
| Subnet `acx-public-subnet` | `<subnet-ocid>` | `<public-subnet-cidr>`, **regional** (AD=null), public IPs allowed |
| `acx_private_subnet` (GPU target) | **DOES NOT EXIST** | main.tf defines it; must be created (terraform apply or CLI) |

**Security lists (acx-vcn):**
- `acx-security-list`: ingress `:22` from **`<operator-ip>/32` only**; `:80`/`:443` from the public internet.
- `Default Security List`: ingress `:22` from the public internet, ICMP.
- SSH to VMs is effectively **tailscale-only** for the operator; ad-hoc laptop SSH from other IPs is blocked. Use the OCI instance-agent run-command plane or tailscale for VM access.

## Instances

| Instance | OCID | Shape / AD | Role |
| --- | --- | --- | --- |
| `acx-backend` | `<instance-ocid>` | A1.Flex (ARM) / AD-3 | prod/staging/demo backend; tailscale `acx-backend.tail1a44b8.ts.net` (user `ubuntu`) |
| `acx-gpu-bake` | `<instance-ocid>` | **VM.GPU.A10.1 / AD-1** | **EPHEMERAL bake host — ~$2/hr, capture→TERMINATE (RES-07)**; public address operator-held |

## GPU quota (us-ashburn-1)

`gpu-a10-count = 1` in **US-ASHBURN-AD-1** (0 in AD-2/AD-3). A100/L40S/BM-GPU all 0 →
A10 in AD-1 is the only GPU option without a new limit-increase.

## Images

| Image | OCID |
| --- | --- |
| Base Ubuntu 24.04 (A10-compatible) | `<image-ocid>` |
| Base Ubuntu 22.04 (x86) | `<image-ocid>` |
| Golden GPU image (`gpu_image_ocid`) | **AVAILABLE and used by the 2026-07-14 spike host** — identifier operator-held, not in repo; production tfvars wiring remains open |

## Model artifacts (pinned)

Repo `Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF` (official, ungated, Apache-2.0-family):
- LLM Q4: `Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf` (18.6 GB) → `/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-q4.gguf`
- mmproj: `mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf` → `/opt/acx-gpu/models/qwen3-vl-30b-a3b-instruct-mmproj.gguf`

Served by `ghcr.io/ggerganov/llama.cpp:server-cuda` on `:8000` (see `gpu-cloud-init.yaml`
for the golden-image serving unit, `gpu-bake-cloud-init.yaml` for the from-scratch bake).

## Terraform

- **No backend configured** (main.tf has no `backend` block) and **no state exists** —
  yet `acx-vcn`, `acx-public-subnet`, and `acx-backend` are live. A naive `terraform apply`
  would try to recreate them.
- **Decision (2026-07-13, greenfield/no-users):** most-correct = single terraform root with
  a **remote OCI Object Storage state backend**, adopting existing infra (import; clean
  destroy+reapply permitted if drift is irreconcilable), then apply adds the private subnet
  + NAT + GPU (`gpu_image_ocid`). Prefer correctness over blast-radius (no prod users).

## Provisioning sequence (VLM-3B Slice 7a)

1. ✅ Golden image bake/capture completed and the image was used by the 2026-07-14 spike host; operator must verify the ephemeral bake host was terminated.
2. Set up remote tf state backend; adopt existing infra into one root.
3. tfvars (`gpu_image_ocid`, `compartment_ocid`=root, `availability_domain`=AD-1, `gpu_shape`=VM.GPU.A10.1, ssh key) → `terraform apply` → private subnet + NAT + GPU.
4. Configure oci-CLI on acx-backend from the vaulted admin key; run `scripts/gpu_spike_bench.py` from acx-backend against the private `:8000`.
