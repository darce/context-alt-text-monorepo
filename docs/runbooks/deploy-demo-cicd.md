# Demo deploy — GitHub Actions pipeline (DDEP-1)

Laptop-free deploy of the demo WordPress stack + ACX plugin to the OCI VM. The
workflow (`.github/workflows/deploy-demo.yml`) is a thin wrapper: it builds the
plugin zip on the runner, joins the tailnet as an ephemeral `tag:ci` node, and
runs the existing `scripts/deploy/sync-demo.sh` — the script remains the single
source of truth for rsync → demo stack up → `bootstrap-wp.sh` plugin install →
Caddy promote → vhost smoke.

For the required producer-flip → prod API redeploy → preflight → deploy-demo
ordering, see [gpu-demo-env-flip.md](gpu-demo-env-flip.md#green-ordering). The
demo is the consumer: never run `deploy-demo` before the producer redeploy and
its verification pass.

**Why:** public port 22 is closed and the tailnet SSH ACL authorizes only the
ephemeral CI identity (`tag:ci`), so a laptop-bound `make deploy-demo` required a
specific operator on a specific machine. This pipeline moves the existing deploy
onto the already-trusted CI identity without widening VM access.

## Trigger policy

| Event | Gate |
| --- | --- |
| Manual **Run workflow** (`workflow_dispatch` only — no push trigger) | Must type **`PROMOTE`** in the run form's `confirm` field. This string input is the **primary** deliberate-action gate: free-plan private repos have no GitHub Environment required-reviewers, so the `demo` Environment exists for **secrets isolation only**. |

Deploys are serialized by the `deploy-demo` concurrency group
(`cancel-in-progress: false`) — one in-flight deploy, never cancelled mid-run.
The job carries `timeout-minutes: 30` so a hung network step cannot hold the
serialized lane and block later deploys.

## GPU producer-to-demo ordering

When changing the description adapter, the green sequence is strict:

1. Flip the description-service producer profile.
2. Redeploy the prod API and wait for its adapter/health verification to pass.
3. Run the GPU/reaper preflight against the prod and demo env files.
4. Run `ACX_DEMO_GPU_PREFLIGHT=1 make deploy-demo` to publish the demo consumer.

The producer owns `ACX_DESCRIPTION_ADAPTER`; a demo-only env edit is not a
producer flip. The full command blocks and recovery procedure are in
[gpu-demo-env-flip.md](gpu-demo-env-flip.md#green-ordering).

**Ref guard:** the workflow **fails** on non-`main` refs unless the
`allow_non_main` dispatch input is set (reserved for rollback to a known-good
ref, or the one-time feature-ref runtime proof). Additionally add an Environment
**deployment-branch-and-tag rule** for `demo` (*Settings → Environments → demo →
Deployment branches and tags*) allowing branch `main` **plus tag pattern
`demo-rollback-*`** — feature branches then cannot even access the `demo`
secrets, while the tag pattern keeps the rollback path (below) alive. A rule of
`main` only would dead-end rollback: environment protection rejects the ref
before any workflow step runs.

## Dispatch

```bash
gh workflow run deploy-demo.yml -f confirm=PROMOTE
gh run watch
```

Note: `gh workflow run deploy-demo.yml --ref <branch>` requires the workflow
file to exist on that remote branch **and** `-f allow_non_main=true`; some
GitHub setups only surface a `workflow_dispatch` workflow after it exists on the
default branch. If a feature-ref dispatch is refused, validate with `actionlint`
pre-merge and run the runtime proof post-merge from `main`.

## One-time setup

### 1. Shared with the recognition pipeline

Tailscale OAuth client (`tag:ci`) and the CI deploy SSH key are the same as the
recognition pipeline — see
[deploy-recognition-cicd.md](deploy-recognition-cicd.md) §"One-time setup" for
`tagOwners`/grants, OAuth client scope, and key generation. Reuse the existing
`TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, and `ACX_DEPLOY_SSH_KEY` secrets.

### 2. `demo` GitHub Environment — secrets vs variables

Create Environment **`demo`** (*Settings → Environments*). **Secrets** (masked
in logs — only genuinely sensitive values belong here):

| Secret | Value |
| --- | --- |
| `TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET` | Tailscale OAuth client (may live at repo level, shared with recognition) |
| `ACX_DEPLOY_SSH_KEY` | Private half of the CI deploy key (may live at repo level) |
| `ACX_E2E_WP_CI_USER` | Dedicated least-privilege CI WP user; its value must equal the VM template's `WP_CI_USER` (for example, `acx-demo-ci`) |
| `ACX_E2E_WP_CI_PASS` | Password for the VM template's `WP_CI_PASSWORD` value; do not use the demo admin password |
| `ACX_VM_SSH_HOST_KEY` | VM SSH host public key: run `ssh-keyscan -t ed25519 acx-backend.tail1a44b8.ts.net` from an authorized machine and paste the output line. With it set, the workflow pins the key (`StrictHostKeyChecking yes`); without it, it falls back to `accept-new` (per-run TOFU on an ephemeral runner) with a loud warning. |

**Variables** (*Settings → Environments → demo → Variables*, or repo-level) —
public values that must stay readable in logs; secret-masking a URL would
redact every navigation URL in Playwright failure output:

| Variable | Value | Notes |
| --- | --- | --- |
| `WP_BASE_URL` | `https://demo.altcontext.com` | Public demo origin (workflow falls back to this literal if unset) |
| `OCI_VM_TS_IP` | `100.115.186.109` | Repo-level; shared with `deploy-recognition.yml` so a VM rebuild is a one-place edit |
| `ACX_E2E_RECOGNITION_URL` | `https://api.altcontext.com` | Stamped into the evidence manifest as recognition provenance; without it the spec defaults to **staging**, fabricating the manifest's lineage |

The CI creds drive the post-deploy walkthrough smoke (Playwright login via the
`auth-setup` project dependency — there is no separate mint step). The VM
bootstrap deliberately reads `WP_CI_USER`, `WP_CI_PASSWORD`, and `WP_CI_EMAIL`,
not the GitHub secret names. `deploy-demo.yml` maps the GitHub secrets
`ACX_E2E_WP_CI_USER` and `ACX_E2E_WP_CI_PASS` to those VM values, then exposes
them to the existing Playwright auth interface as `ACX_E2E_WP_ADMIN_USER` and
`ACX_E2E_WP_ADMIN_PASS`; the latter are compatibility names in the test
harness, not permission to use the demo administrator. The storage state is
written runner-local (`tests/e2e/.auth/storageState.json` on the ephemeral
runner) and must never be cached or uploaded as an artifact. The workflow also pins `ACX_E2E_REQUIRE_CONSTANT_PROVENANCE=1` and
`ACX_E2E_REQUIRE_SERVICE_TARGET=1` — the provenance-badge gate and the RECOG-1
single-target contract gate are independent flags; opting out of one must not
disable the other.

### 3. VM prerequisites (existing)

`sync-demo.sh` assumes the demo secrets file exists at
`/opt/acx-backend/demo/secrets/.env` on the VM (it fails loudly if missing) and
that licensed seed media has shipped for `seed/import.sh`.

## Smoke semantics — deploy vs recognition

Two independent signals; do not conflate them:

- **Deploy-landed (gates the job):**
  1. `sync-demo.sh`'s vhost smoke — `/health` for the `api.*` vhosts (they have
     no root route; `/` there is a benign 404), `/` for `demo.altcontext.com`.
     Classification logic lives in `scripts/deploy/lib/smoke-gate.sh` and its
     matrix is pinned by `scripts/deploy/tests/test-smoke-gate.sh`. The gate
     covers what the deploy owns: unreachable-after-retries (000) fails (retries
     absorb the Caddy-recreate/ACME window); an `api.*` HTTP error fails **only
     when that vhost was healthy in the pre-promote baseline** (deploy-caused
     edge regression — `caddy validate` is syntax-only and cannot catch a
     misrouted `reverse_proxy`), otherwise WARNs (pre-existing backend outage,
     out of scope). The demo probe follows redirects and requires a **final
     2xx that is not the WP installer** — a wiped DB 302→`install.php` answers
     200 and is a broken demo. (DNS cutover to `demo.altcontext.com` is done;
     the earlier blanket-3xx allowance for the interim sslip.io canonical host
     is retired.)
  2. A **runner-vantage public probe** — the VM-local smoke proves nothing
     about public DNS/443 ingress/security lists, so the workflow re-probes
     `WP_BASE_URL` from the runner (gating, same installer guard) and prints
     `api.*` public health as informational.
  3. The demo-walkthrough spec's **test exit code** — Settings/Workbench
     surfaces render and the RECOG-1 single-target contract is live (one
     hosted-service target card; no `local_url*` in `GET /acx/v1/settings`).
     Run file-scoped (`evidence/demo-walkthrough.spec.ts` only) so unrelated
     evidence specs — including recognition-exercising ones — cannot gate the
     deploy. The browser step runs under `xvfb-run -a` because
     `playwright.config.ts` is deliberately headed for local evidence capture.
- **Recognition health (informational):** the spec's evidence-manifest
  `verdict` reflects the recognition round-trip and is published to the job
  summary only. A backend recognition failure does **not** fail a successful
  deploy; diagnosing it is the observability follow-up (`feature/ob-8`).

## Failure, recovery, and rollback

Fail-loud, leave state: a failed step fails the run visibly and leaves the VM
as-is. Recovery is an idempotent re-dispatch — `sync-demo.sh` re-copies
everything, and `bootstrap-wp.sh`'s `--force` install + activation cycle
re-applies the plugin and its dbDelta schema on every run, so partial failures
(aborted scp, half-applied activation) converge on the next run.

**Rollback (successful-but-bad promote):** redeploy a known-good commit by
tagging it — `gh workflow run --ref` accepts only a branch or tag, never a bare
SHA, and the tag must (a) contain the workflow file and (b) match the
Environment rule's `demo-rollback-*` tag pattern:

```bash
git tag demo-rollback-$(date +%Y%m%d) <good-sha> && git push origin demo-rollback-$(date +%Y%m%d)
gh workflow run deploy-demo.yml --ref demo-rollback-$(date +%Y%m%d) \
  -f confirm=PROMOTE -f allow_non_main=true
```

The runner rebuilds that ref's plugin zip and the
deploy converges the VM onto it. Limits to know before relying on it:
`dbDelta` is additive-only (there are no reverse migrations — an old plugin
running against a newer schema is the expected greenfield-acceptable state, per
the repo's Greenfield Policy), and demo content/media created after the bad
deploy is untouched by rollback. The Caddy edge config keeps timestamped
`.bak.*` copies on the VM (`sync-demo.sh` stages them pre-promote) if the edge
itself must be restored by hand.
