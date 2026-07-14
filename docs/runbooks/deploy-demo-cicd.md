# Demo deploy — GitHub Actions pipeline (DDEP-1)

Laptop-free deploy of the demo WordPress stack + ACX plugin to the OCI VM. The
workflow (`.github/workflows/deploy-demo.yml`) is a thin wrapper: it builds the
plugin zip on the runner, joins the tailnet as an ephemeral `tag:ci` node, and
runs the existing `scripts/deploy/sync-demo.sh` — the script remains the single
source of truth for rsync → demo stack up → `bootstrap-wp.sh` plugin install →
Caddy promote → vhost smoke.

**Why:** public port 22 is closed and the tailnet SSH ACL authorizes only the
ephemeral CI identity (`tag:ci`), so a laptop-bound `make deploy-demo` required a
specific operator on a specific machine. This pipeline moves the existing deploy
onto the already-trusted CI identity without widening VM access.

## Trigger policy

| Event | Gate |
| --- | --- |
| Manual **Run workflow** (`workflow_dispatch` only — no push trigger) | Must type **`confirm=PROMOTE`** in the dispatch form. This string input is the **primary** deliberate-action gate: free-plan private repos have no GitHub Environment required-reviewers, so the `demo` Environment exists for **secrets isolation only**. |

Deploys are serialized by the `deploy-demo` concurrency group
(`cancel-in-progress: false`) — one in-flight deploy, never cancelled mid-run.

## Dispatch

```bash
gh workflow run deploy-demo.yml -f confirm=PROMOTE
gh run watch
```

Note: `gh workflow run deploy-demo.yml --ref <branch>` requires the workflow
file to exist on that remote branch; some GitHub setups only surface a
`workflow_dispatch` workflow after it exists on the default branch. If a
feature-ref dispatch is refused, validate with `actionlint` pre-merge and run
the runtime proof post-merge from `main`.

## One-time setup

### 1. Shared with the recognition pipeline

Tailscale OAuth client (`tag:ci`) and the CI deploy SSH key are the same as the
recognition pipeline — see
[deploy-recognition-cicd.md](deploy-recognition-cicd.md) §"One-time setup" for
`tagOwners`/grants, OAuth client scope, and key generation. Reuse the existing
`TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, and `ACX_DEPLOY_SSH_KEY` secrets.

### 2. `demo` GitHub Environment + secrets

Create Environment **`demo`** (*Settings → Environments*) and add:

| Secret | Value |
| --- | --- |
| `TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET` | Tailscale OAuth client (may live at repo level, shared with recognition) |
| `ACX_DEPLOY_SSH_KEY` | Private half of the CI deploy key (may live at repo level) |
| `WP_BASE_URL` | `https://demo.altcontext.com` |
| `ACX_E2E_WP_ADMIN_USER` | Demo WP admin user (e.g. `acx-demo-admin`) |
| `ACX_E2E_WP_ADMIN_PASS` | Demo WP admin password |

The last three drive the post-deploy walkthrough smoke (Playwright login +
storage-state mint). The storage state is written runner-local
(`tests/e2e/.auth/storageState.json` on the ephemeral runner) and must never be
cached or uploaded as an artifact.

### 3. VM prerequisites (existing)

`sync-demo.sh` assumes the demo secrets file exists at
`/opt/acx-backend/demo/secrets/.env` on the VM (it fails loudly if missing) and
that licensed seed media has shipped for `seed/import.sh`.

## Smoke semantics — deploy vs recognition

Two independent signals; do not conflate them:

- **Deploy-landed (gates the job):**
  1. `sync-demo.sh`'s vhost smoke — `/health` for the `api.*` vhosts (they have
     no root route; `/` there is a benign 404), `/` for `demo.altcontext.com`.
     Any non-200 fails the deploy.
  2. The demo-walkthrough spec's **test exit code** — Settings/Workbench
     surfaces render and the RECOG-1 single-target contract is live (one
     hosted-service target card; no `local_url*` in `GET /acx/v1/settings`).
     Run file-scoped (`evidence/demo-walkthrough.spec.ts` only) so unrelated
     evidence specs — including recognition-exercising ones — cannot gate the
     deploy. Both browser steps run under `xvfb-run -a` because
     `playwright.config.ts` is deliberately headed for local evidence capture.
- **Recognition health (informational):** the spec's evidence-manifest
  `verdict` reflects the recognition round-trip and is published to the job
  summary only. A backend recognition failure does **not** fail a successful
  deploy; diagnosing it is the observability follow-up (`feature/ob-8`).

## Failure and recovery

Fail-loud, leave state: a failed step fails the run visibly and leaves the VM
as-is. Recovery is an idempotent re-dispatch — `sync-demo.sh` re-copies
everything, and `bootstrap-wp.sh`'s `--force` install + activation cycle
re-applies the plugin and its dbDelta schema on every run, so partial failures
(aborted scp, half-applied activation) converge on the next run.
