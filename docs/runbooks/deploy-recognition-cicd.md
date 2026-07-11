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
| Manual **Run workflow** → `prod` | `prod` | Must type **`confirm=PROMOTE`** in the dispatch form (workflow gate) + `main`-only deployment branch; script also enforces `CONFIRM=PROMOTE` |

## One-time setup

### 1. Tailscale — ephemeral CI identity

The backend VM is tagged **`tag:oci-vm`** (tailnet `tail1a44b8.ts.net`). This
tailnet uses the **grants** policy model (not the legacy `acls` key).

- **ACL** (*Access controls* tab): the OAuth client can only own a tag that
  exists, so declare `tag:ci` in `tagOwners`:
  ```jsonc
  "tagOwners": {
    "tag:oci-vm": ["autogroup:admin"],
    "tag:ci":     ["autogroup:admin"]
  }
  ```
  **Connectivity:** if the policy still has the default allow-all grant
  (`{"src":["*"],"dst":["*"],"ip":["*"]}`), `tag:ci` can already reach the VM on
  `:22` — no grant edit needed. If/when you tighten that wildcard, add an
  explicit least-privilege grant instead:
  ```jsonc
  "grants": [
    { "src": ["tag:ci"], "dst": ["tag:oci-vm"], "ip": ["tcp:22"] }
  ]
  ```
- **OAuth client** (*Settings → OAuth clients → Generate OAuth client*): scope
  **Auth Keys / `auth_keys` = Write**, and assign tag **`tag:ci`**. Copy the
  client **ID** and **secret** (secret shown once). The GitHub Action uses this
  to mint a short-lived, tagged, ephemeral node per run.

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

### 4. GitHub Environments

*Settings → Environments →* create `dev`, `staging`, `prod` (for deploy history +
the `environment:` key to resolve). Add nothing to `dev`/`staging`.

For **`prod`**, under **Deployment branches and tags** switch the dropdown from
*No restriction* to **Selected branches and tags** → **Add rule** → `main` (so
prod can only deploy from `main`).

> **Note (private repo, Free plan):** GitHub *Required reviewers* / *Wait timer*
> protection rules are unavailable for private repos on the Free plan (they need
> Pro/Team, or a public repo). Instead, the prod gate is a **deliberate-action
> confirmation in the workflow**: a `prod` deploy is manual `workflow_dispatch`
> only AND requires typing `PROMOTE` in the run form's **confirm** field — the
> job fails fast otherwise. Upgrade to GitHub Pro later if you want native
> second-person approval.

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
