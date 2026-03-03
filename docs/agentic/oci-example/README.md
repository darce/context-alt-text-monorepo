# OCI Always Free Deployment

Infrastructure-as-code for deploying the marketing backend to Oracle Cloud Infrastructure Always Free tier.

## Architecture

- **Compute**: VM.Standard.E2.1.Micro (AMD, 1 GB RAM, 50 GB boot)
- **Database**: PostgreSQL 18 (containerized, same VM)
- **Networking**: VCN with public subnet + Internet Gateway
- **Security**: Security List (SSH + HTTP/HTTPS), fail2ban, automatic security updates
- **Runtime**: Docker + Docker Compose

## Prerequisites

1. **OCI Account**: Already configured with CLI at `~/.oci/config`
2. **SSH Key**: Generate if needed: `ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa`
3. **Terraform**: Install via Homebrew: `brew install terraform`

## Setup

### 1. Configure Terraform Variables

```bash
cd backend/infra/oci
cp terraform.tfvars.example terraform.tfvars
vim terraform.tfvars  # Update with your OCI credentials
```

Required values:

- `tenancy_ocid`: Your OCI tenancy OCID
- `user_ocid`: Your OCI user OCID
- `fingerprint`: Your OCI API key fingerprint (from `~/.oci/config`)
- `compartment_ocid`: Use tenancy OCID for root compartment
- `ssh_allowed_cidrs`: Restrict to your IP (get with `curl -s ifconfig.me`)

### 2. Create Infrastructure

```bash
make -C backend oci-init    # Initialize Terraform
make -C backend oci-plan    # Preview changes
make -C backend oci-apply   # Create infrastructure
```

This creates:

- VCN + public subnet + Internet Gateway
- Security List (SSH port 22, HTTP port 3000, HTTPS port 443)
- VM.Standard.E2.1.Micro instance with Ubuntu 22.04
- Installs Docker, Docker Compose, fail2ban via cloud-init

**Wait ~3 minutes** for cloud-init to complete provisioning.

### 3. Verify Cloud-Init Completion

```bash
make -C backend oci-ssh
# Then on the instance:
tail -f /var/log/cloud-init-output.log
# Wait for "Cloud-init provisioning complete!"
# Exit: Ctrl-C, then 'exit'
```

### 4. Create Secrets

SSH into the instance and create secret files:

```bash
ssh ubuntu@<instance-ip>
cd /opt/marketing-backend

# Generate secure random strings
mkdir -p secrets

# Database password (24+ chars)
openssl rand -hex 32 > secrets/db_password.txt

# IP hash pepper (32+ chars)
openssl rand -hex 32 > secrets/ip_hash_pepper.txt

# Admin API key (24+ chars)
openssl rand -hex 32 > secrets/admin_api_key.txt

# Restrict permissions
chmod 600 secrets/*.txt
```

### 5. Configure Environment

```bash
# Still on the instance
cp .env.oci.example .env.oci
vim .env.oci
```

Update:

- `CORS_ALLOWED_ORIGINS`: Add your frontend domain(s)
- `PRIVACY_CONTACT_EMAIL`: Your privacy compliance email

### 6. Deploy Code

From your local machine:

```bash
make -C backend oci-deploy
```

This:

1. Runs quality gates (typecheck, lint, format)
2. Syncs code to the instance (rsync)
3. Builds Docker image
4. Runs Prisma migrations
5. Starts backend + Postgres containers

### 7. Verify Deployment

```bash
make -C backend oci-health   # Check health endpoint
make -C backend oci-logs     # View logs
```

### 8. Enable Auto-Start on Boot

```bash
ssh ubuntu@<instance-ip>
sudo systemctl enable marketing-backend
sudo systemctl status marketing-backend
```

## Common Makefile Targets

```bash
make -C backend oci-init      # Initialize Terraform
make -C backend oci-plan      # Preview infrastructure changes
make -C backend oci-apply     # Create infrastructure
make -C backend oci-output    # Show Terraform outputs (instance IP, etc.)
make -C backend oci-ssh       # SSH into the instance
make -C backend oci-deploy    # Deploy code (rsync + build + migrate + restart)
make -C backend oci-logs      # Tail logs from containers
make -C backend oci-health    # Check backend health
make -C backend oci-destroy   # Destroy all infrastructure (WARNING!)
```

## Post-Deployment Operations

### View Logs

```bash
# From local machine
make -C backend oci-logs

# Or SSH and use Docker Compose
ssh ubuntu@<instance-ip>
cd /opt/marketing-backend
docker compose -f docker-compose.oci.yml logs -f backend
docker compose -f docker-compose.oci.yml logs -f postgres
```

### Restart Services

```bash
ssh ubuntu@<instance-ip>
cd /opt/marketing-backend
docker compose -f docker-compose.oci.yml restart
```

### Run Migrations

```bash
ssh ubuntu@<instance-ip>
cd /opt/marketing-backend
docker compose -f docker-compose.oci.yml exec backend npx prisma migrate deploy
```

### Database Backup

```bash
ssh ubuntu@<instance-ip>
cd /opt/marketing-backend
docker compose -f docker-compose.oci.yml exec postgres \
  pg_dump -U altcontext altcontext_prod > backup-$(date +%Y%m%d).sql
```

### Prisma Studio (via SSH Tunnel)

```bash
# Terminal 1: Start Prisma Studio on instance
ssh ubuntu@<instance-ip>
cd /opt/marketing-backend
docker compose -f docker-compose.oci.yml exec backend npx prisma studio

# Terminal 2: Create SSH tunnel
ssh -L 5555:localhost:5555 ubuntu@<instance-ip>

# Browser: http://localhost:5555
```

### Monitor System Resources

```bash
ssh ubuntu@<instance-ip>
htop              # Real-time process viewer
docker stats      # Real-time container stats
df -h             # Disk usage
free -m           # Memory usage
```

### Check Cloud-Init Logs

```bash
ssh ubuntu@<instance-ip>
sudo cat /var/log/cloud-init-output.log    # Full log
sudo cat /var/log/marketing-keepalive.log  # Anti-idle keepalive
```

## Security

### SSH Access Control

Restrict SSH to your IP in `terraform.tfvars`:

```hcl
ssh_allowed_cidrs = ["203.0.113.42/32"]  # Replace with your IP
```

Then apply changes:

```bash
make -C backend oci-plan
make -C backend oci-apply
```

### Fail2ban

Automatically bans IPs after 5 failed SSH attempts:

```bash
ssh ubuntu@<instance-ip>
sudo fail2ban-client status sshd  # Check banned IPs
sudo fail2ban-client set sshd unbanip <ip>  # Unban an IP
```

### Automatic Security Updates

Configured via `unattended-upgrades`:

```bash
ssh ubuntu@<instance-ip>
sudo cat /var/log/unattended-upgrades/unattended-upgrades.log
```

## Idle Reclamation Prevention

OCI reclaims Always Free instances with <20% CPU/network/memory for 7 consecutive days.

**Keepalive script** runs every 6 hours via cron:

- Calls backend health endpoint
- Generates minimal CPU activity (1-2%)
- Logs container stats

Check logs:

```bash
ssh ubuntu@<instance-ip>
sudo cat /var/log/marketing-keepalive.log
```

Monitor metrics in OCI Console:

- Compute > Instances > `marketing-backend` > Metrics
- Watch CPU, network, memory trends

## Troubleshooting

### Backend Container Won't Start (OOM)

**Symptom**: Container exits immediately, logs show "Killed".

**Check**:

```bash
ssh ubuntu@<instance-ip>
sudo dmesg | grep -i "out of memory"
docker compose -f docker-compose.oci.yml logs backend
```

**Solution**: Reduce memory limits in `docker-compose.oci.yml`:

- Backend: 450M → 400M
- Postgres: 300M → 250M

### Database Connection Refused

**Symptom**: Backend logs show "ECONNREFUSED postgres:5432".

**Check**:

```bash
docker compose -f docker-compose.oci.yml ps
docker compose -f docker-compose.oci.yml logs postgres
```

**Solution**: Wait for Postgres health check to pass (10-20 seconds after start).

### Port 3000 Not Accessible from Outside

**Check**:

1. Security List rules in OCI Console (Networking > VCN > Security Lists)
2. Docker container is listening: `docker compose ps` (should show "Up")
3. Firewall on Ubuntu (should be inactive): `sudo ufw status`

**Solution**: Verify Security List has ingress rule for TCP port 3000 from 0.0.0.0/0.

### Terraform Apply Fails (Quota Exceeded)

**Error**: "You have reached the limit for VM.Standard.E2.1.Micro instances".

**Solution**: Always Free tier allows max 2 instances. Delete one:

```bash
oci compute instance list --compartment-id <compartment-ocid>
oci compute instance terminate --instance-id <instance-ocid>
```

## Cost

**Total cost**: **$0/month** (OCI Always Free tier)

Included:

- VM.Standard.E2.1.Micro (1 GB RAM, 0.125 OCPU)
- 50 GB boot volume
- Public IP
- 10 TB/month outbound transfer
- VCN + Internet Gateway

**GPU ML Service** (external):

- See [service-rules.md](../../agentic/instructions/backend/service-rules.md) for GPU provider comparison
- Recommendation: Use Replicate.com API (~$0.50-5/month for <5K images/month)

## Next Steps

1. **Add HTTPS**: Use Caddy or nginx reverse proxy with Let's Encrypt
2. **Monitoring**: Set up Prometheus + Grafana or use OCI Monitoring/Alarms
3. **Backups**: Automate PostgreSQL backups to OCI Object Storage (20 GB free)
4. **Migrate to Managed DB**: Move to Always Free Autonomous Database (20 GB, 1 OCPU)
5. **Load Balancer**: Add OCI Flexible Load Balancer (1 free) if scaling to multiple instances
6. **ML Service**: Integrate Replicate.com API for image description (Phi-3 + InsightFace)

## References

- [OCI Always Free Documentation](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [Backend Service Rules](../../agentic/instructions/backend/service-rules.md)
- [OCI CLI Patterns](../../agentic/instructions/available-tools.md#oci-cli)
