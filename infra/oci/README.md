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

## Security Note

- The default security list restricts SSH to the CIDRs defined in `ssh_allowed_cidrs`.
- HTTPS (443) is open to the public.
- The raw app port (8000) is blocked by the host UFW firewall and OCI security lists. If temporary debug access is required, you must manually add an ingress rule in the OCI console **and** run `sudo ufw allow 8000/tcp` on the host.
