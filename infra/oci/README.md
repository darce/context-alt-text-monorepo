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
# Recommended: Tailscale (works regardless of residential-IP changes).
# See "Tailscale (recommended for dynamic-IP workstations)" below for one-time setup.
ssh ubuntu@acx-backend.tail1a44b8.ts.net

# Fallback: public IP (requires your workstation IP to be in the OCI security list).
ssh ubuntu@129.213.40.111
```

If the public-IP path times out, your workstation's IP has likely changed (residential ISP). Update the security list:

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

b. **Install + bring up on the VM** (over the existing public-IP SSH path):
   ```bash
   # Connected via the existing public-IP SSH path:
   ssh ubuntu@129.213.40.111

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

Caddy runs separately as `acx-caddy.service`, routing all three subdomains.

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
7. Runs the post-reset bootstrap to recreate one usable service-mode dev API
   key:
   `cd apps/prototype-description-service && PYENV_VERSION=description-service pyenv exec python scripts/manage_api_keys.py create --tenant-id acx-<env>-dev --name e15-12-reset-bootstrap`.
   The output is operator-captured and pasted into the plugin's settings page
   so the plugin can talk to the freshly-reset env in service mode.
8. Polls `https://<env>.api.altcontext.com/ready` (or `https://api.altcontext.com/ready`
   for prod) until it succeeds. The `/ready` probe is intentionally stricter
   than the `/health` liveness probe: it requires postgres to be up, the
   schema to be migrated, and models to be loaded before declaring the env
   operable. Up to 6 attempts at 5s intervals.

**Boundary:** the reset is environment-scoped. `make reset-remote ENV=dev`
touches only `/opt/acx-backend/dev/.env`'s `ACX_PGDATA_PATH` (`dev-pgdata`).
Staging and prod data roots are untouched. There is no shared multi-env reset
target by design — operators must opt into each env explicitly.

**Local counterpart:** the equivalent workflow for the local LocalWP/Postgres
pair is `make reset-local WP_PATH="<wordpress>/app/public" CONFIRM_LOCAL_RESET=RESET`.
Use `reset-local` for the local dev DB and `reset-remote ENV=<env>` for the
OCI envs. Don't cross the streams.


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
├── data/
│   ├── prod-pgdata/                 # prod Postgres (persists)
│   ├── prod-models/                 # prod InsightFace cache (persists)
│   ├── staging-pgdata/
│   ├── staging-models/
│   ├── dev-pgdata/
│   └── dev-models/
└── logs/
```

### Container Registry (OCIR)

- Registry: `iad.ocir.io`
- Namespace: `idu2kqqe2jxy`
- Repository: `acx-backend`
- Image tags: `:latest` (prod), `:staging`, `:dev`
- Auth: OCI auth token, username `idu2kqqe2jxy/<email>`

## Security Note

- The default security list restricts SSH to the CIDRs defined in `ssh_allowed_cidrs`.
- HTTPS (443) is open to the public.
- The raw app port (8000) is blocked by the host UFW firewall and OCI security lists. If temporary debug access is required, you must manually add an ingress rule in the OCI console **and** run `sudo ufw allow 8000/tcp` on the host.
