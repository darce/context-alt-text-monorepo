# OCI Infrastructure for ACX Backend

Infrastructure as Code for provisioning the ACX recognition service backend on Oracle Cloud.

## Prerequisites

1.  **OCI Account**: PAYG tier recommended for provisioning priority.
2.  **OCI CLI**: Installed and configured (`~/.oci/config`).
3.  **Terraform**: v1.5.7+ installed.
4.  **SSH Key**: Public key for instance access.

## Setup

1.  Clone this repository.
2.  Navigate to `infra/oci/`.
3.  Copy `terraform.tfvars.example` to `terraform.tfvars`.
4.  Fill in your OCI OCIDs and paths in `terraform.tfvars`.
5.  Initialize Terraform:
    ```bash
    terraform init
    ```

## Deployment

To provision the instance, especially if dealing with "Out of host capacity" errors for Always Free ARM shapes, use the retry script.

### Foreground Execution

```bash
./retry-apply.sh
```

### Background Mode (Recommended for long retries)

To run the provisioning in the background so it continues even if your SSH session disconnects:

```bash
RETRY_INTERVAL=300 APPLY_TIMEOUT_SEC=900 nohup ./retry-apply.sh > retry-apply.log 2>&1 &
tail -f retry-apply.log
```

This script cycles through the 3 Availability Domains in `us-ashburn-1` until an instance is successfully provisioned.

### Retry Script Tuning

`retry-apply.sh` supports environment overrides for overnight runs:

- `RETRY_INTERVAL` (default `300`): base retry interval in seconds.
- `THROTTLE_MIN_WAIT` (default `300`): minimum wait after 429/rate-limit style responses.
- `MAX_RETRY_INTERVAL` (default `1800`): cap for exponential backoff.
- `JITTER_MAX` (default `30`): random jitter seconds added to each sleep.
- `APPLY_TIMEOUT_SEC` (default `900`): timeout for a single `terraform apply` attempt (when `timeout`/`gtimeout` is available; install via `brew install coreutils`).
- `MAX_ATTEMPTS` (default `0`): max total attempts (`0` means no limit).
- `ADS_CSV` (default all 3 ADs): comma-separated AD override, e.g. `saEG:US-ASHBURN-AD-1,saEG:US-ASHBURN-AD-3`.
- `NOTIFY_WEBHOOK_URL` (optional): POST webhook for remote notifications (ntfy.sh, Slack, Discord). Message is sent as plain-text body.
- `NOTIFY_WEBHOOK_BODY_TPL` (optional): `printf` template with `%s` for the message, for services needing JSON (e.g. `'{"text":"%s"}'`).

### Cron Mode (Recommended for Overnight Runs)

The script prevents concurrent runs via `flock` when available, with a lock-directory fallback on environments without `flock`. This avoids the risk of a hung `terraform apply` being joined by a second invocation:

```bash
# Run every 5 minutes, with ntfy.sh notifications
*/5 * * * * NOTIFY_WEBHOOK_URL=https://ntfy.sh/my-acx-topic /path/to/infra/oci/retry-apply.sh >> /path/to/infra/oci/retry-apply.log 2>&1
```

`tail -f "$(ls -t "$TMPDIR"/acx-oci-apply.* | head -1)"`

The script will skip immediately if a previous apply is still in progress.

## GPU burst host (acx_gpu_burst)

- Provisioned **RUNNING** on first apply so cloud-init can enable `acx-gpu-vlm.service`
  before any STOP (creating with `state=STOPPED` races runcmd — VLMFIX-S2-05).
  **After first-boot cloud-init completes**, stop the instance to halt A10 billing:
  ```bash
  oci compute instance action \
    --instance-id "$(terraform -chdir=infra/oci output -raw gpu_instance_id)" \
    --action STOP --wait-for-state STOPPED
  ```
- Placed on the **private subnet** (`10.0.2.0/24`) with `assign_public_ip = false`,
  **NAT gateway** egress, and a **dedicated GPU security list** (no world 80/443;
  SSH from `ssh_allowed_cidrs` + backend subnet only; VLM :8000 from VCN).
- After apply, wire the description service:

```bash
terraform -chdir=infra/oci output -raw gpu_endpoint_url   # → ACX_GPU_ENDPOINT_URL
terraform -chdir=infra/oci output -raw gpu_instance_id    # → idle reaper
```

### Idle reaper (decision → fence → OCI STOP)

Each description-service environment dumps load to
`/run/acx-write/<env>/describe-load.json` (override with
`ACX_DESCRIBE_LOAD_PATH`) on async enqueue/terminal poll and at startup. The JSON
is produced by `scene/application/describe_load.py` (DB-derived, VLM-5). The
lifecycle units aggregate every environment's snapshot; stale dumps are treated
as busy so a dead writer cannot STOP a working GPU.

#### GPU lifecycle snapshots

The host lifecycle systemd units and description APIs exchange atomic JSON
snapshots through directories with separate ownership:

| Path | Ownership and access | Single writer | Reader | Freshness contract |
| --- | --- | --- | --- | --- |
| `/run/acx/gpu-state.json` | Host-owned; mounted read-only in each API container | Host start/reap units (`ubuntu`) | Description APIs | An API treats data older than `ACX_GPU_STATE_STALE_SECONDS` (180s by default) as `unknown`. |
| `/run/acx-write/<env>/describe-load.json` | API-owned; only the matching environment subdirectory is mounted read-write | That environment's description API (container uid 10001) | Host start/reap units aggregate `/run/acx-write/*/describe-load.json` | Refreshed every `ACX_DESCRIBE_LOAD_REFRESH_SECONDS` (45s by default); the lifecycle reader rejects stale data. |

Both writers atomically replace mode-0644 files. `/run/acx` remains host-owned
and read-only to containers. Each API receives only its own writable
`/run/acx-write/<env>` subdirectory, preventing dual writers while allowing the
units to aggregate load across dev, staging, and prod. `.env.prod.example` is the
production path seam for these two directories, and `docker-compose.env.yml`
enforces the corresponding read-only state and read-write load mounts. Pass
`ACX_DESCRIBE_LOAD_DIR` as the `/run/acx-write` parent the units aggregate,
not a per-environment subdirectory; the checker rejects the mismatch.

Run the fail-closed check as root so it can test readability as container uid
10001. Export the values from the deployed environment; do not source a secrets
file into an interactive shell:

```bash
sudo env \
  ACX_DESCRIBE_LOAD_DIR=/run/acx-write \
  ACX_DESCRIBE_LOAD_STALE_SECONDS=120 \
  ACX_GPU_COMPOSE_FILE=apps/prototype-description-service/docker-compose.env.yml \
  ACX_GPU_DEPLOYMENTS_FILE=scripts/deploy/gpu-snapshot-deployments.conf \
  ACX_GPU_INSTALL_SCRIPT=scripts/deploy/gpu-lifecycle-install.sh \
  ACX_GPU_READER_UID=10001 \
  ACX_GPU_SNAPSHOT_CONFIG_ONLY=0 \
  ACX_GPU_SNAPSHOT_DIR=/run/acx \
  ACX_GPU_STATE_PATH=/run/acx/gpu-state.json \
  ACX_GPU_STATE_STALE_SECONDS=180 \
  ACX_GPU_UNIT_LOAD_DIR=/run/acx-write \
  ACX_GPU_UNIT_STATE_PATH=/run/acx/gpu-state.json \
  ACX_NOW_EPOCH="$(date +%s)" \
  scripts/deploy/check-gpu-snapshots.sh
```

The deployment registry is shared with the lifecycle installer, so every listed
environment must have a writable, fresh snapshot directory. The command exits
non-zero for a missing/unreadable/malformed/stale file, a
non-read-only or drifted compose mount, or a configured path that differs from
the paths installed into the systemd units. A missing snapshot never passes.

```bash
# Production: real load file + OCI probe (not static --queue-depth 0 --in-flight 0)
python -m infra.oci.gpu_lifecycle \
  --instance-id "$(terraform -chdir=infra/oci output -raw gpu_instance_id)" \
  --idle-seconds 300 \
  --load-json '/run/acx-write/*/describe-load.json' \
  --probe-oci \
  --fence-delay-seconds 2
```

Auth: default OCI CLI API-key (`~/.oci/config`). On acx-backend with instance
principal, pass `--oci-auth instance_principal` (requires a dynamic group policy
granting `INSTANCE_POWER_ACTIONS` on the GPU compartment).

Scheduler: cloud-init installs `acx-gpu-idle-reaper.timer` (every 2 minutes).
Copy `/etc/acx/gpu-reaper.env.example` → `/etc/acx/gpu-reaper.env` with
`GPU_INSTANCE_ID=…` after apply. Manual cron equivalent:

```bash
*/2 * * * * GPU_INSTANCE_ID=ocid1... python3 -m infra.oci.gpu_lifecycle \
  --instance-id "$GPU_INSTANCE_ID" --load-json '/run/acx-write/*/describe-load.json' \
  --probe-oci --idle-seconds 300 >> /var/log/acx-gpu-reaper.log 2>&1
```

See `docs/tasks/vlm/VLM-3-gpu-detailed-tier-decision-memo.md` § Activation preconditions.

## Teardown

To destroy the infrastructure and stop incurring costs (or free up Always Free slots):

```bash
terraform destroy -var-file=terraform.tfvars
```

## Verification

Once provisioned:

1.  SSH into the instance:
    ```bash
    ssh ubuntu@<public_ip>
    ```
2.  Verify Docker status:
    ```bash
    docker info
    ```
3.  Check the ACX backend service:
    ```bash
    systemctl status acx-backend
    ```

## Troubleshooting

### Out of Host Capacity (Always Free ARM)

If provisioning fails with "Out of host capacity", this is normal for Always Free A1 instances. Use the background execution method of `retry-apply.sh` to continually poll for capacity. The script will cycle through Availability Domains until successful.

### 429 / Rate Limiting / Hung Apply

If OCI returns `429 TooManyRequests` or the provider stalls while creating networking resources, keep the script running in background mode. The script retries throttling errors and uses per-attempt apply timeouts (when `timeout`/`gtimeout` is installed) to avoid indefinite hangs.

### Checking Cloud-Init Progress

If the VM provisions but the service isn't working, check the cloud-init logs over SSH:

```bash
sudo cat /var/log/cloud-init-output.log
```

Look for errors installing Docker, creating directories, or setting up the `acx-backend` systemd unit.

### Checking Docker Logs

If `systemctl status acx-backend` shows the service is running but requests fail, check the Docker logs:

```bash
cd /opt/acx-backend
sudo docker compose logs -f
```

## Operations

### Accessing the VM

```bash
# Canonical path: Tailscale SSH (public port 22 is closed).
# See "Tailscale (recommended for dynamic-IP workstations)" below for one-time setup.
ssh ubuntu@acx-backend.tail1a44b8.ts.net
```

**Public port 22 is closed** (Tailscale-SSH hardening). `ssh ubuntu@129.213.40.111`
fails with `kex_exchange_identification: Connection reset by peer`. Use the
tailnet MagicDNS name above (same VM; public IP remains `129.213.40.111` for
non-SSH traffic). Deploy scripts default `OCI_HOST` to this tailnet host.

If you ever need to re-open temporary public SSH (emergency only), update the
security list for your workstation IP:

```bash
# Check your current IP
curl -s checkip.amazonaws.com

# Update terraform.tfvars with the new IP, then:
cd infra/oci
terraform apply -auto-approve -target=oci_core_security_list.acx_security_list
```

See `docs/tasks/tech-debt/archive-or-transfer-candidates/dynamic-ip-ssh-access.md` for the original drift note; Tailscale is now the canonical path.

#### Tailscale (recommended for dynamic-IP workstations)

Residential ISPs rotate the workstation's public IP, which silently breaks
the OCI security-list allowlist and every SSH-driven deploy step. Tailscale
puts the workstation and the VM on a private mesh network with stable
`100.x.x.x` addresses; you SSH via the tailnet IP and can close port 22 on
the public internet entirely.

Setup (one-time, ~10 minutes total).

##### 1. Install on the workstation

```bash
brew install tailscale
tailscale up                  # opens browser to sign in
tailscale status              # confirm your Mac shows up (e.g. tomato 100.76.x.x)
```

##### 2. Install on the OCI VM

The VM is headless, so use a pre-authenticated install via a one-shot
**auth key** generated from the Tailscale admin console. This avoids
the interactive browser-login dance over SSH.

a. **Generate an auth key** (browser, on your workstation):
   - Visit <https://login.tailscale.com/admin/settings/keys>.
   - Click **Generate auth key**.
   - Recommended toggles: **Reusable** off, **Ephemeral** off, **Pre-approved** on,
     **Tags** = `tag:oci-vm` (define the tag in *Access controls* first if you
     don't have one yet).
   - Copy the `tskey-auth-...` string. It is shown once; treat it as a secret.

b. **Install + bring up on the VM** (requires a temporary public SSH path
   during bootstrap only — port 22 is closed after Tailscale is live):
   ```bash
   # Historical bootstrap used the public IP; port 22 is now closed.
   # Prefer the tailnet host if already joined; otherwise open a temporary
   # security-list allow for setup, then close port 22 again.
   ssh ubuntu@acx-backend.tail1a44b8.ts.net

   # On the VM (interactive shell — heredoc is unreliable here because the
   # apt-daily timer often holds the lock; see "Troubleshooting" below):
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo apt-get install -y tailscale     # rerun if `apt-get update` was wedged

   # Generate-then-paste pattern keeps the key out of your shell history:
   read -rs TS_KEY                       # paste tskey-auth-..., press Enter (silent)
   sudo tailscale up \
     --authkey="$TS_KEY" \
     --hostname=acx-backend \
     --ssh \
     --advertise-tags=tag:oci-vm
   unset TS_KEY

   tailscale status
   tailscale ip -4
   ```
   Flag notes:
   - `--hostname=acx-backend` — gives a stable MagicDNS name
     (`acx-backend.<tailnet>.ts.net`) that survives VM reinstalls.
   - `--ssh` — lets Tailscale terminate SSH using your tailnet identity.
     Optional; the script still uses your existing `~/.ssh/id_*` keys
     either way.
   - `--advertise-tags` — makes the node owner the tag, not your user, so
     the auth key isn't tied to a single human identity.

   **Don't paste the `tskey-auth-...` value into a committed file.**
   For repeated use prefer `read -s TS_KEY` then `--authkey=$TS_KEY`,
   or store it in a password manager.

##### 3. Verify and wire up the deploy script

```bash
tailscale status              # workstation should now list the VM
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'hostname && uname -m'
```

(Replace `tail1a44b8.ts.net` with your own tailnet name from
`tailscale status` output.)

The deploy script's default `OCI_HOST` is already
`acx-backend.tail1a44b8.ts.net`, so no further wiring is needed for
the canonical tailnet — `make deploy-dev REMOTE_BUILD=1` will
route over the tailnet automatically. To override (different tailnet,
debugging via raw IP, etc.):

```bash
export OCI_HOST=<other-host-or-ip>
# Add to ~/.zshrc to persist.
```

The deploy automation (`scripts/deploy/recognition-service.sh`) is fully
SSH-routed in remote-build mode (rsync, ssh build, ssh push, ssh restart);
all of it inherits the address automatically.

##### Expose `/admin` over the tailnet (no SSH tunnel)

The operator `/admin` console (tenant + API-key lifecycle) is `404`'d on the
public `api.altcontext.com` vhost by design (`apps/prototype-description-service/Caddyfile`);
it is reachable only over the tailnet. To manage tenants/keys from your laptop
without an SSH tunnel, publish the loopback admin port with `tailscale serve`:

1. Layer the admin overlay on the VM (binds the api to `127.0.0.1:8000`):
   ```bash
   docker compose -f docker-compose.env.yml -f docker-compose.admin.yml up -d
   ```
2. Publish it over the tailnet (one-time; `--bg` survives reboots). Requires
   **MagicDNS + HTTPS** enabled in the tailnet admin console
   (*Settings → HTTPS Certificates*):
   ```bash
   sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
   sudo tailscale serve status   # confirm https://acx-backend.<tailnet>.ts.net → 127.0.0.1:8000
   ```
3. From any tailnet device, browse `https://acx-backend.<tailnet>.ts.net/admin/`
   and auth with the VM's `RECOGNITION_ADMIN_TOKEN` (HTTP Basic in the browser).

From the repo, `make -C apps/prototype-description-service admin-oci-serve` runs
step 2 over SSH and `make -C apps/prototype-description-service admin-oci` opens
the console; both honour `OCI_HOST` / `OCI_USER` (same env contract as
`scripts/deploy/*`).

This opens no public port — `tailscale serve` binds the tailnet interface only,
the public vhost still `404`s `/admin`, and the admin token still gates every
route. Note the serve command publishes the api **root** (`http://127.0.0.1:8000`),
so all routes — not just `/admin` — are reachable from tailnet devices; that is
harmless (tailnet-private, and every route is still auth-gated) but it is why the
name is "expose /admin" rather than a path-scoped mount. It is also why a key
minted in the *local* `make admin-dev` console never authenticates against the
OCI deployment: they are separate tenant databases.

##### 4. (Optional) Drop public port 22

Once tailnet SSH is proven, tighten `infra/oci/terraform.tfvars` to drop the
public-IP allowlist entry on TCP/22 and re-apply the security-list rule
(`terraform apply -target=oci_core_security_list.acx_security_list`).
Public HTTPS (443) on the load balancer stays open — only management SSH
moves onto the tailnet.

##### Troubleshooting

**On the workstation: `failed to connect to local Tailscale service`.**
On macOS the Homebrew formula installs only the CLI; the `tailscaled`
daemon is provided by the GUI app (App Store or
<https://tailscale.com/download/mac>). Launch Tailscale.app once and add
it to *System Settings → General → Login Items* so the daemon survives
reboots. Don't run `brew services start tailscale` alongside the app —
two daemons race for the same network extension.

**On the VM: `apt-get update` hangs forever (no timeout).**
Symptom: `E: Could not get lock /var/lib/apt/lists/lock. It is held by
process N (apt-get)` and the process has been alive for hours/days.
Root cause on stock Ubuntu cloud images: the `apt.systemd.daily` timer
hits an IPv6 mirror that stalls without timing out. The timer keeps
re-firing and queuing more wedges behind the original. Unwedge:

```bash
# 1. Identify the holder + kill its process tree.
sudo lsof /var/lib/apt/lists/lock        # note the PID
ps -ef | grep -E "apt|dpkg" | grep -v grep
sudo kill <PID>
sleep 2 && sudo kill -9 <PID> 2>/dev/null || true

# 2. Force IPv4 to fix the underlying stall.
echo 'Acquire::ForceIPv4 "true";' | sudo tee /etc/apt/apt.conf.d/99force-ipv4

# 3. Stop the timers so they don't re-wedge while you work.
sudo systemctl stop apt-daily.timer apt-daily-upgrade.timer
sudo systemctl disable apt-daily.timer apt-daily-upgrade.timer

# 4. Resume.
sudo apt-get update && sudo apt-get install -y tailscale
```

**On the VM: dpkg lock held by `unattended-upgrades`.**
*Different* service from the apt-daily timer. If the log
(`/var/log/unattended-upgrades/unattended-upgrades.log`) shows it
actively installing packages, **wait it out** — killing dpkg
mid-transaction corrupts package state. If it's wedged with no log
progress for >5 min, kill the process and disable the service
(`sudo systemctl disable --now unattended-upgrades.service`).

**`tailnet policy does not permit you to SSH to this node`.**
You enabled `--ssh` on the VM, which makes `tailscaled` intercept
inbound port 22 *before* OpenSSH sees it. The default ACL only allows
`autogroup:self`, which doesn't match a tag-owned device. Add an
`ssh` rule at <https://login.tailscale.com/admin/acls> granting admins
access to `tag:oci-vm` (and define the tag itself in `tagOwners`):

```jsonc
{
  "tagOwners": {
    "tag:oci-vm": ["autogroup:admin"],
  },

  "ssh": [
    // existing autogroup:self rule stays...
    {
      "action": "accept",
      "src":    ["autogroup:admin"],
      "dst":    ["tag:oci-vm"],
      "users":  ["ubuntu", "root"],
    },
  ],
}
```

Save; ACL changes propagate in seconds, no VM restart needed. To skip
Tailscale SSH entirely and rely on standard OpenSSH key auth instead,
re-run `sudo tailscale up --hostname=acx-backend --advertise-tags=tag:oci-vm --reset`
(the `--reset` is required to clear the previously-set `--ssh` preference).

### Environments

Three isolated environments share the VM:

| Environment | Subdomain | Image Tag | Systemd Unit |
|-------------|-----------|-----------|--------------|
| prod | `api.altcontext.com` | `:latest` | `acx-prod.service` |
| staging | `staging.api.altcontext.com` | `:staging` | `acx-staging.service` |
| dev | `dev.api.altcontext.com` | `:dev` | `acx-dev.service` |
| demo | `demo.altcontext.com` | WordPress `:6.8-php8.3-apache` + MariaDB `:11.4` | `acx-demo.service` |

Caddy runs separately as `acx-caddy.service`, routing all four subdomains.

### Service Management

```bash
# Per-environment control
sudo systemctl start acx-prod       # (or acx-staging, acx-dev)
sudo systemctl stop acx-staging
sudo systemctl restart acx-dev

# Caddy (reverse proxy for all envs)
sudo systemctl restart acx-caddy

# Check all services
sudo systemctl status acx-prod acx-staging acx-dev acx-caddy

# View logs for a specific environment
cd /opt/acx-backend/prod
docker compose -f docker-compose.env.yml logs -f
docker compose -f docker-compose.env.yml logs api --tail 50

# Caddy logs
cd /opt/acx-backend
docker compose -f docker-compose.caddy.yml logs -f
```

### Health Checks

```bash
# All three environments
curl https://api.altcontext.com/health
curl https://staging.api.altcontext.com/health
curl https://dev.api.altcontext.com/health

# Recognition endpoint
curl https://api.altcontext.com/recognition/health

# Postgres readiness per env
docker exec acx-prod-postgres-1 pg_isready -U acx_app
docker exec acx-staging-postgres-1 pg_isready -U acx_staging
docker exec acx-dev-postgres-1 pg_isready -U acx_dev
```

### Deploying the demo stack

```bash
# From repo root — ships compose, Caddy edge, plugin zip (when dist/ exists), bootstrap:
make deploy-demo

# Pin the plugin artifact explicitly:
PLUGIN_ZIP=dist/alt-context-<version>.zip make deploy-demo
```

Operator prerequisites before first deploy:

1. Copy `infra/oci/demo/.env.example` → `/opt/acx-backend/demo/secrets/.env` (chmod 600)
2. Populate DB creds, `WP_ADMIN_*`, `WORDPRESS_CONFIG_EXTRA`, and ACX constants
3. Mint tenant + key per `infra/oci/demo/tenant-mint-runbook.md` (explicit UUID)
4. Append `https://demo.altcontext.com` to `RECOGNITION_ALLOWED_ORIGINS` (staging first)

Bootstrap sequence is implemented by `infra/oci/demo/bootstrap-wp.sh` (wp core install +
plugin activate). Optional cohort reset: `infra/oci/demo/content-reset-runbook.md`.

### Deploying Updates

**Recommended:** use the wrapper at `scripts/deploy/recognition-service.sh`
(invoked via Makefile targets from the repo root). It runs the same
build/push/restart/verify procedure documented below plus pre-flight checks
(docker daemon, OCIR auth, SSH key, clean tree, branch sync) and a
post-deploy `/health` SHA comparison so version skew is caught immediately.
The wrapper double-tags every image with both `:ENV_TAG` and `:SHA` so
rollback by SHA stays available.

The wrapper supports two build modes:

| Mode | Trigger | When to use |
|---|---|---|
| **Local build** (default) | `make deploy-dev` | Fast iteration on a workstation with a healthy local docker daemon. Mac users need colima or Docker Desktop. |
| **Remote build** | `make deploy-dev REMOTE_BUILD=1` | Build runs on the OCI VM via SSH+rsync. Native arm64 (no cross-compile). No local docker required. Recommended path. |

```bash
# See every available deploy target:
make deploy-help

# Standard dev iteration (build + push :dev + :SHA + restart acx-dev + verify):
make deploy-dev

# Same, but build on the VM — no colima/Docker Desktop needed locally.
# This is the friction-free path; pair with Tailscale for stable SSH.
make deploy-dev REMOTE_BUILD=1

# Build only, no push (sanity before paying for an OCIR push):
make deploy-build                      # local
make deploy-build-remote               # on the VM

# Re-verify a deployed env without redeploying:
make deploy-verify-dev                 # or: make deploy-verify ENV=dev

# Snapshot all three envs at once:
make deploy-status

# Make remote-build the default (add to ~/.zshrc):
export ACX_REMOTE_BUILD=1

# Override defaults via env vars:
OCI_HOST=<other-tailnet-or-ip> make deploy-dev REMOTE_BUILD=1
ACX_ALLOW_DIRTY=1 make deploy-dev      # allow dirty tree (dev only)
ACX_REMOTE_BUILD_DIR=/var/tmp/acx-build make deploy-dev REMOTE_BUILD=1
```

**Remote-build prerequisites** (one-time):

- VM has docker installed and the `ubuntu` user is in the `docker` group
  (already true for the standard cloud-init).
- VM has cached OCIR auth: SSH in once and run
  `docker login iad.ocir.io -u 'idu2kqqe2jxy/<email>'`. The token is stored
  in `~ubuntu/.docker/config.json`.
- Workstation has `rsync` (default on macOS).

**Remote-build trade-offs:**

- Build consumes VM CPU (3-5 min on Always Free A1 4-core). If `acx-prod` is
  serving traffic on the same VM, expect a momentary CPU spike.
- First build on the VM is slow (no warm cache); subsequent builds reuse the
  BuildKit on-disk cache.
- VM disk fills with build cache over time; run
  `ssh ubuntu@<vm> 'docker buildx prune -f'` periodically.

#### acx_blobs ownership migration (non-root runtime)

Stacks that created the `acx_blobs` named volume while the recognition image
still ran as root keep that volume as `root:root` forever — Docker only
propagates image-path ownership when it **initialises an empty new volume**,
never on an existing one. After the image drops to `USER acx` (uid 10001),
multipart uploads fail with `EACCES` under `/var/lib/acx-blobs`.

`scripts/deploy/recognition-service.sh` runs an idempotent repair on every
`do_restart` (deploy / promote path):

```bash
docker compose -f docker-compose.env.yml --profile repair run --rm fix-blob-ownership
# prod compose file (manual / legacy stacks):
docker compose -f docker-compose.prod.yml --profile repair run --rm fix-blob-ownership
```

The `fix-blob-ownership` service is root (`user: "0:0"`), mounts `acx_blobs`,
and `chown -R acx:acx /var/lib/acx-blobs`. Safe to re-run. One-shot manual
repair on an already-deployed env (no full redeploy):

```bash
ssh ubuntu@acx-backend.tail1a44b8.ts.net \
  'cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml --profile repair run --rm fix-blob-ownership'
```

Alternatively, destroy the volume only when data loss is acceptable
(`docker volume rm <project>_acx_blobs`) so the next start re-initialises it
from the image seed. Prefer the chown repair. The entrypoint fails closed if
the blob root is unwritable and names this repair profile in the error.


**Manual procedure** (the wrapper runs exactly this; documented for
disaster-recovery scenarios where the script is unavailable):

```bash
# Build on local Mac (Apple Silicon).
# --build-arg GIT_COMMIT_SHA stamps the image so /health and /version
# surface the real deployed commit (E15-3a-BR-03). Without it the runtime
# falls back to APP_GIT_COMMIT_SHA=unknown and the plugin backend_too_old
# probe cannot detect deploy lag.
source ~/.zshrc
cd apps/prototype-description-service
docker build --platform linux/arm64 \
  --build-arg GIT_COMMIT_SHA=$(git rev-parse HEAD) \
  -t iad.ocir.io/idu2kqqe2jxy/acx-backend:dev .
docker push iad.ocir.io/idu2kqqe2jxy/acx-backend:dev

# Deploy to dev
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'cd /opt/acx-backend/dev && docker compose -f docker-compose.env.yml pull && sudo systemctl restart acx-dev'
```

### Promoting Images

**Recommended:** use the wrapper.

```bash
# Promote dev → staging (after dev testing).
# Requires HEAD == origin/main and a clean working tree.
make deploy-promote-staging

# Promote staging → prod (after e2e verification on staging).
# Requires CONFIRM=PROMOTE in addition to clean tree + synced HEAD.
make deploy-promote-prod CONFIRM=PROMOTE

# Rollback dev to whatever staging is currently running (skips rebuild):
make deploy-rollback-dev
```

**Manual procedure** (for disaster recovery):

```bash
# Promote dev → staging (after dev testing)
docker tag iad.ocir.io/idu2kqqe2jxy/acx-backend:dev iad.ocir.io/idu2kqqe2jxy/acx-backend:staging
docker push iad.ocir.io/idu2kqqe2jxy/acx-backend:staging
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'cd /opt/acx-backend/staging && docker compose -f docker-compose.env.yml pull && sudo systemctl restart acx-staging'

# Promote staging → prod (after e2e verification on staging)
docker tag iad.ocir.io/idu2kqqe2jxy/acx-backend:staging iad.ocir.io/idu2kqqe2jxy/acx-backend:latest
docker push iad.ocir.io/idu2kqqe2jxy/acx-backend:latest
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'cd /opt/acx-backend/prod && docker compose -f docker-compose.env.yml pull && sudo systemctl restart acx-prod'
```

### Greenfield schema drift (dev/staging)

**Symptom:** after a greenfield edit to
`db/migrations/versions/001_identity_schema.py`, the OCI `acx-<env>-api-1`
container crash-loops with `UndefinedColumn: <new_column>` (e.g.
`primary_contact_email`). Caddy returns 502 for `https://<env>.api.altcontext.com`.

**Cause:** long-lived Postgres volumes on the VM keep the previous schema.
Alembic has already stamped `001`, so an in-place `001` edit does not re-apply
and the API boots against columns that do not exist.

**Recovery (schema-only; no prod path):**

```bash
# Print remote commands only (no SSH):
make db-reset-remote ENV=dev CONFIRM=RESET DRY_RUN=1

# Drop public schema, recreate, restart api, poll /health:
make db-reset-remote ENV=dev CONFIRM=RESET
make db-reset-remote ENV=staging CONFIRM=RESET
```

This is lighter than `make reset-remote` (which wipes the whole `ACX_PGDATA_PATH`
volume and re-bootstraps API keys). Prefer `db-reset-remote` for migration
drift; use `reset-remote` when you also need a clean tenant/key bootstrap.

**Env-var changes are different:** `docker restart` does **not** re-read
`.env` — container env is fixed at create time. After editing
`/opt/acx-backend/<env>/.env`, recreate instead (this bit staging on
2026-07-12 when the retired `RECOGNITION_ALLOWED_API_KEYS` line was removed):

```bash
cd /opt/acx-backend/<env> && \
  COMPOSE_PROJECT_NAME=acx-<env> docker compose -f docker-compose.env.yml up -d --force-recreate api
```

### Destructive Remote Reset

The reset workflow rebuilds an OCI environment's database from empty. It is
**destructive by design**: the selected env's `ACX_PGDATA_PATH` is wiped and
recreated, all rows (tenants, jobs, persons, API keys, embeddings) are gone,
and the unit comes back up with a freshly migrated empty schema. There is no
preservation path. Use it when you intentionally want to rebuild dev state, or
to recover from corruption that cannot be untangled with a normal deploy.

**Always run with `ACX_RESET_DRY_RUN=1` first** to print the exact remote
command sequence and the verification plan. The dry-run opens no SSH session
and mutates no remote state — it is safe to run repeatedly.

```bash
# Plan the reset without touching anything (recommended first step):
make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET ACX_RESET_DRY_RUN=1

# Reset OCI dev for real after reviewing the dry-run plan:
make reset-remote ENV=dev CONFIRM_REMOTE_RESET=RESET

# Reset OCI staging:
make reset-remote ENV=staging CONFIRM_REMOTE_RESET=RESET

# Reset OCI prod (additional confirmation gate):
make reset-remote ENV=prod CONFIRM_REMOTE_RESET=RESET CONFIRM=PROMOTE
```

**Confirmation contract:**

| Lever | Required for | Purpose |
|---|---|---|
| `CONFIRM_REMOTE_RESET=RESET` | every env | Acknowledges the reset is destructive |
| `CONFIRM=PROMOTE` | prod only | Second gate so a stray `ENV=prod` cannot wipe production |
| `ACX_RESET_DRY_RUN=1` | optional | Print plan only; no SSH, no state mutation |

**What the reset does, in order:**

1. SSHes to `ubuntu@<OCI_HOST>` (override with `OCI_HOST=...` for non-default
   hosts).
2. `sudo systemctl stop acx-<env>`.
3. `sudo docker compose -f docker-compose.env.yml down --remove-orphans` from
   `/opt/acx-backend/<env>` to release the postgres volume mount.
4. Sources `/opt/acx-backend/<env>/.env` to read the env-scoped
   `ACX_PGDATA_PATH`. The script refuses to proceed if the path is empty,
   `/`, `/opt`, or `/opt/acx-backend`.
5. `sudo rm -rf -- "$ACX_PGDATA_PATH" && sudo mkdir -p -- "$ACX_PGDATA_PATH"`.
6. `sudo systemctl start acx-<env>` so the unit comes back up through the
   normal systemd contract; Alembic runs on container start.
7. Polls `https://<env>.api.altcontext.com/ready` (or `https://api.altcontext.com/ready`
   for prod) until it succeeds. The `/ready` probe is intentionally stricter
   than the `/health` liveness probe: it requires postgres to be up, the
   schema to be migrated, and models to be loaded before declaring the env
   operable. Up to 6 attempts at 5s intervals. The bootstrap in step 8 is
   gated on /ready because `docker compose exec` requires a running api
   container.
8. Runs the post-reset bootstrap inside the api container on the remote VM to
   recreate one usable service-mode API key:

   ```bash
   sudo docker compose -f docker-compose.env.yml exec -T api \
     python -m scripts.manage_api_keys --env prod \
     tenant create --tenant <uuid> --site-url <url>
   sudo docker compose -f docker-compose.env.yml exec -T api \
     python -m scripts.manage_api_keys --env prod \
     create --tenant <uuid>
   ```

   `ACX_RESET_SITE_URL` is **required** (no default). It must be the
  WordPress site URL the plugin will hit (e.g. `http://localhost:10010`
  for the repo's LocalWP install, or `https://staging.altcontext.com`). The bootstrap derives the per-site
   tenant UUID from this value via `scripts/deploy/_derive_tenant_id.py`,
   which mirrors the plugin's `TenantIdentity::derive_from_site_url()`. If
   the URL does not match the plugin's site URL, the plugin's recognition
   requests will fail with `403 tenant mismatch`. `ACX_RESET_TENANT_ID`
   remains an explicit override for non-derived tenants (rarely needed).
   `--env prod` is required regardless of the OCI deployment env
   (dev/staging/prod): the manage_api_keys CLI validates `--env` against
   the DSN host, and the in-container DSN host is `postgres` (compose
   service name), which only `--env prod` accepts. The tenant step runs
   first because `create` enforces the tenant-foreign-key. The `api_key=`
   line printed by `create` is operator-captured and pasted into the
   plugin's settings page so the plugin can talk to the freshly-reset env
   in service mode.

**Boundary:** the reset is environment-scoped. `make reset-remote ENV=dev`
touches only `/opt/acx-backend/dev/.env`'s `ACX_PGDATA_PATH` (`dev-pgdata`).
Staging and prod data roots are untouched. There is no shared multi-env reset
target by design — operators must opt into each env explicitly.

**Local counterpart:** the equivalent workflow for the local LocalWP/Postgres
pair is `make reset-local WP_PATH="<wordpress>/app/public" CONFIRM_LOCAL_RESET=RESET`.
Use `reset-local` for the local dev DB and `reset-remote ENV=<env>` for the
OCI envs. Don't cross the streams.

**Smoke proof:** after a reset, prove plugin connectivity end-to-end via
[`docs/operations/reset-smoke-runbook.md`](../../docs/operations/reset-smoke-runbook.md).
The runbook hosts the post-reset smoke procedure (key handoff → plugin
selector mode → workbench probe → captured proof) so this section stays
focused on the destructive contract.


### VM Layout

```
/opt/acx-backend/
├── Caddyfile                        # multi-subdomain reverse proxy config
├── docker-compose.caddy.yml         # standalone Caddy (joins all env networks)
├── prod/
│   ├── .env -> secrets/.env
│   ├── docker-compose.env.yml       # parameterized env template
│   ├── secrets/.env                 # prod credentials (chmod 600)
│   └── db/docker-prod-init/
├── staging/                         # same structure as prod
├── dev/                             # same structure as prod
├── demo/
│   ├── .env -> secrets/.env
│   ├── docker-compose.demo.yml      # WordPress + MariaDB demo stack
│   └── secrets/.env                 # demo credentials (chmod 600)
├── data/
│   ├── prod-pgdata/                 # prod Postgres (persists)
│   ├── prod-models/                 # prod InsightFace cache (persists)
│   ├── staging-pgdata/
│   ├── staging-models/
│   ├── dev-pgdata/
│   ├── dev-models/
│   ├── demo-wpdata/                 # demo WordPress content (persists)
│   └── demo-dbdata/                 # demo MariaDB (persists)
└── logs/
```

### Container Registry (OCIR)

- Registry: `iad.ocir.io`
- Namespace: `idu2kqqe2jxy`
- Repositories (distinct per image variant — not a tag on a shared repo):
  - `acx-backend` — recognition / default `runtime` stage
  - `acx-backend-vlm` — VLM / `runtime-vlm` stage (`ACX_BUILD_TARGET=runtime-vlm` in `scripts/deploy/recognition-service.sh`)
- Image tags: `:latest` (prod), `:staging`, `:dev` (and SHA / rollback tags from the deploy script)
- Auth: OCI auth token, username `idu2kqqe2jxy/<email>`

## GPU Burst Tier (detailed description)

The `oci_core_instance.acx_gpu_burst` resource (`VM.GPU.A10.1`, private subnet) serves
the scale-to-zero detailed-description tier. It is **not provisionable until an A10
service-limit increase is granted** (console request, not API) and a golden image OCID
is set. See **[GPU-BURST-PROVISIONING.md](GPU-BURST-PROVISIONING.md)** for the quota
procurement path, SSH/Tailscale admin-plane scope, provisioning sequence, and costs.
If OCI denies the A10 quota, **[GPU-TIER-FALLBACK-PLAN.md](GPU-TIER-FALLBACK-PLAN.md)**
covers the backend-agnostic fallbacks (self-host over Tailscale, serverless, hosted API).

## VLM weight cache (runtime-vlm / Florence LOCAL_CPU)

The `runtime-vlm` image is permanently offline for Hugging Face
(`HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` baked in). It cannot download
Florence weights at boot. Operators seed a host path **outside** that image,
write an integrity manifest, then mount the cache **read-only** at
`/data/cache` (compose: `${ACX_MODELS_PATH}:/data/cache:ro` on api and worker).
`trust_remote_code` still needs a writable module scratch path: compose mounts a
private `tmpfs` at `HF_MODULES_CACHE` (`/var/cache/acx/hf_modules`, `noexec`,
uid matching the image `acx` user) so weights stay `:ro` while import-time
module writes do not hit the host bind.

**Image variant is build-immutable.** Each runtime stage bakes
`recognition` or `vlm` into `/app/.image-variant` (chmod 0444). The entrypoint
and `/health`/`/version` read that artifact — not a free-form
`ACX_IMAGE_VARIANT` env switch. A non-empty env claim that disagrees with the
bake fails closed. Do not set `ACX_IMAGE_VARIANT` on a recognition container to
"select" VLM behaviour; pull the `acx-backend-vlm` image instead.

On the VLM image the shared entrypoint boot order is load-bearing:

1. fail-closed bake / blob-root checks
2. `alembic -c db/alembic.ini upgrade head`
3. `python -m scripts.sync_identity_schema`
4. `python -m scripts.verify_identity_schema`
5. `python -m scripts.verify_vlm_cache` (VLM bake only)
6. `exec uvicorn …`

The VLM cache gate fails closed when the pinned snapshot does not match the
integrity manifest exactly — including when an **extra unlisted file** appears
or when trust_remote_code `modeling_*.py` / `processing_*.py` files are absent
(model files are code; see SEC-13). If the active adapter is not LOCAL_CPU, the
gate still verifies the default `florence_small` pin so an empty mount cannot
boot green. Skipping is only for the recognition image (non-VLM bake) with a
non-LOCAL_CPU profile.

Identify which image is running (same commit SHA can be either variant). Port
8000 is **not** published on the host for staging/dev (`expose` only); prod
publishes it via `docker-compose.admin.yml` on `127.0.0.1:8000` only. Prefer
`docker exec` against the running api container (works in every env):

```bash
# Replace <api-container> with the env's api container name/id.
docker exec <api-container> wget -qO- http://127.0.0.1:8000/health \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print({k:d[k] for k in ("commit_sha","image_variant") if k in d})'
# or: docker exec <api-container> wget -qO- http://127.0.0.1:8000/version
# prod admin overlay only (127.0.0.1:8000 published):
# curl -sS http://127.0.0.1:8000/health | jq '{commit_sha, image_variant}'
```

### 1. Seed the pinned snapshot (outside the offline image)

From `apps/prototype-description-service`, with the `[vlm]` extra installed
(network required once):

```bash
cd apps/prototype-description-service
uv run --extra vlm python -m scripts.seed_vlm_cache \
  --hf-home /data/cache/huggingface_cache \
  --profile florence_small
```

This downloads the profile-pinned `model_id` at the pinned commit SHA (never a
branch name), including `trust_remote_code` modeling `*.py` files and weight
shards, then writes `acx-vlm-cache.manifest.json` inside the snapshot directory.

### 2. Manifest is a trust-establishing act

`--write-manifest` (also invoked by the seeder) **certifies whatever is on
disk at that moment**. Run it only on a freshly downloaded, out-of-band-verified
snapshot. **Never re-run it to silence a failing gate** — that would turn the
gate into a no-op (sr-001 / RLSE-02).

Standalone re-certify of an already-seeded tree (rare; prefer the seeder):

```bash
cd apps/prototype-description-service
export ACX_DESCRIPTION_ADAPTER=florence_small
export HF_HUB_CACHE=/data/cache/huggingface_cache
uv run python -m scripts.verify_vlm_cache --write-manifest
```

### 3. Mount read-only at runtime and fail closed on boot

Compose (and any ad-hoc run) must mount the pre-seeded cache at `/data/cache`
**read-only** (least privilege; a writable shared volume is a code-execution
vector under `trust_remote_code=True`). Reseeding is a one-shot RW job
**outside** the serving unit — never remount the serving stack RW to refresh
weights. Push/pull the VLM image under the `acx-backend-vlm` repository (not
`:vlm` on `acx-backend`).

**Do not** run the full image CMD without Postgres: the entrypoint's first
real work is Alembic (step 2 above), so a bare `docker run … acx-backend-vlm`
exits on a missing DSN and never reaches the VLM cache gate. To demonstrate
the gate in isolation (no network, no DSN):

```bash
docker run --rm \
  -e ACX_DESCRIPTION_ADAPTER=florence_small \
  -e HF_HUB_CACHE=/data/cache/huggingface_cache \
  -v /data/cache:/data/cache:ro \
  --entrypoint python \
  iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm:latest \
  -m scripts.verify_vlm_cache
```

Full-stack boot (migrations + gate + uvicorn) needs the env network and DSN:

```bash
docker run --rm \
  --env-file /opt/acx-backend/<env>/.env \
  --network acx-<env>-net \
  -v ${ACX_MODELS_PATH}:/data/cache:ro \
  iad.ocir.io/idu2kqqe2jxy/acx-backend-vlm:latest
```

Exit 0 from the isolated gate only when every manifest entry verifies, the
on-disk file set matches exactly, and remote-code `*.py` modules are present;
any problem exits non-zero. On full-stack boot the same gate is step 5 — an
earlier Alembic/schema failure is not a cache-gate failure.

Manual check against a host cache (no container):

```bash
cd apps/prototype-description-service
export ACX_DESCRIPTION_ADAPTER=florence_small
export HF_HUB_CACHE=/data/cache/huggingface_cache
uv run python -m scripts.verify_vlm_cache
```

## Security Note

- The default security list restricts SSH to the CIDRs defined in `ssh_allowed_cidrs`.
- HTTPS (443) is open to the public.
- The raw app port (8000) is blocked by the host UFW firewall and OCI security lists. If temporary debug access is required, you must manually add an ingress rule in the OCI console **and** run `sudo ufw allow 8000/tcp` on the host.
