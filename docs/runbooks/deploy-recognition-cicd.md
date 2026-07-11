# Recognition-service deploy — GitHub Actions pipeline

Repeatable deploy of the recognition service to the OCI VM. The workflow
(`.github/workflows/deploy-recognition.yml`) is a thin wrapper: it joins the
tailnet as an ephemeral node and runs the existing
`scripts/deploy/recognition-service.sh deploy <env>` in `REMOTE_BUILD=1` mode —
the script remains the single source of truth for build → OCIR push → systemd
restart → `/health` verify.

**Why this shape (free, reliable):** the VM builds and pushes to OCIR with its
own cached credential, so CI carries **no Docker and no OCIR secrets** — only
tailnet reachability + an SSH deploy key. GitHub Actions + Tailscale both run on
free tiers.

## Trigger policy

| Event | Environment | Gate |
| --- | --- | --- |
| Push to `main` (touching `apps/prototype-description-service/**`, `scripts/deploy/**`, or this workflow) | `dev` | none (continuous) |
| Manual **Run workflow** → `staging` | `staging` | GitHub Environment (optional reviewer) |
| Manual **Run workflow** → `prod` | `prod` | GitHub Environment **required reviewer** + `CONFIRM=PROMOTE` (auto-set by the workflow; enforced by the script) |

## One-time setup

### 1. Tailscale — ephemeral CI identity

- **OAuth client**: Tailscale admin → *Settings → OAuth clients* → generate a
  client with scope `devices:write` (or `auth_keys`) and tag `tag:ci`. Note the
  client id + secret.
- **ACL**: ensure `tag:ci` may reach the VM on SSH. In the tailnet policy:
  ```jsonc
  "tagOwners": { "tag:ci": ["autogroup:admin"] },
  "acls": [
    { "action": "accept", "src": ["tag:ci"], "dst": ["acx-backend.tail1a44b8.ts.net:22"] }
  ]
  ```
  (Adjust `dst` to the VM's tag/host as your ACL is structured.)

### 2. Deploy SSH key

Generate a dedicated CI key (do not reuse a personal key):
```bash
ssh-keygen -t ed25519 -f acx-ci-deploy -C "github-actions-deploy" -N ""
# public key -> the VM:
ssh ubuntu@acx-backend.tail1a44b8.ts.net \
  "cat >> ~/.ssh/authorized_keys" < acx-ci-deploy.pub
```

### 3. GitHub repository secrets

*Settings → Secrets and variables → Actions →* add:

| Secret | Value |
| --- | --- |
| `TS_OAUTH_CLIENT_ID` | Tailscale OAuth client id |
| `TS_OAUTH_SECRET` | Tailscale OAuth client secret |
| `ACX_DEPLOY_SSH_KEY` | Contents of the **private** `acx-ci-deploy` key |

### 4. GitHub Environments (the gates)

*Settings → Environments →* create `dev`, `staging`, `prod`.
- `prod`: enable **Required reviewers** (add yourself) and **Deployment branches → Selected → `main`**. This pauses every prod run for approval.
- `staging`: optional reviewer.

### 5. VM prerequisites (already true post-secrets-consolidation)

- Docker running; user in the `docker` group.
- Cached OCIR credential: `docker login iad.ocir.io -u 'idu2kqqe2jxy/<email>'`
  (paste an OCI auth token) — the script's remote-build push reuses it.

## Operating the pipeline

- **Deploy dev**: merge/push to `main` — the workflow runs automatically.
- **Deploy staging/prod**: *Actions → Deploy recognition service → Run workflow*
  → pick the environment. `prod` waits for the required-reviewer approval, then
  the script's `CONFIRM=PROMOTE` gate + boot-smoke + `/health` verify run.
- **Verify**: the script fails closed — it GETs `/health` and compares
  `commit_sha` to the deployed ref (retries for warm-up). A green run means the
  running service is at that SHA.

## Rollback

Roll back by re-pointing the tag to a known-good image (no rebuild) or
redeploying a prior SHA:
```bash
# fastest: retag the last-good image on OCIR + restart + verify
scripts/deploy/recognition-service.sh promote staging prod   # CONFIRM=PROMOTE for prod
# or redeploy a specific commit
GIT_REF=<good-sha> REMOTE_BUILD=1 scripts/deploy/recognition-service.sh deploy prod   # CONFIRM=PROMOTE
```
The same `promote`/`GIT_REF` levers are available by dispatching the workflow
from an older commit.

## Notes

- **Secrets backend is unaffected by deploy.** Prod stays on the `env` secret
  backend until `RECOGNITION_SECRET_BACKEND=oci_vault` + `RECOGNITION_VAULT_SECRET_MAP`
  are set on the VM **and** OCI IAM precondition A2 is confirmed — see
  [`../../infra/oci/vault-instance-principal-runbook.md`](../../infra/oci/vault-instance-principal-runbook.md).
  A deploy alone does not change secret sourcing.
- The workflow deliberately duplicates none of the deploy logic; fix deploy
  behavior in `scripts/deploy/recognition-service.sh`, not here.
- Local/manual deploy remains available and identical:
  `REMOTE_BUILD=1 scripts/deploy/recognition-service.sh deploy <env>`.
