# Recognition-service deploy — GitHub Actions pipeline

Repeatable deploy of the recognition service to the OCI VM. The workflow
(`.github/workflows/deploy-recognition.yml`) is a thin wrapper: it joins the
tailnet as an ephemeral node and runs the existing
`scripts/deploy/recognition-service.sh deploy <env>` in `REMOTE_BUILD=1` mode —
the script remains the single source of truth for build → OCIR push → systemd
restart → `/health` verify.

**Why this shape (free, reliable):** the VM builds and pushes to OCIR after its
instance principal fetches the credential from `acx-vault`, so CI carries **no
Docker and no OCIR secrets** — only tailnet reachability + an SSH deploy key.
GitHub Actions + Tailscale both run on free tiers.

## Trigger policy

| Event | Environment | Gate |
| --- | --- | --- |
| Push to `main` (touching service, deploy, deploy-test, Makefile, or workflow paths) | `dev` | Deploy-contract test gate |
| Manual **Run workflow** → `staging` | `staging` | Deploy-contract test gate + GitHub Environment (optional reviewer) |
| Manual **Run workflow** → `prod` | `prod` | Deploy-contract test gate + **`confirm=PROMOTE`** in the dispatch form + `main`-only deployment branch; script also enforces `CONFIRM=PROMOTE` |

## Test gate

Every automatic or manually dispatched deployment first runs
`make test-deploy-contract` in an isolated GitHub Actions job with Python 3.12.
The gate installs only `pytest` and `pyyaml`; it uses no deployment environment,
tailnet connection, Docker daemon, or secrets. The deploy job starts only after
that command succeeds. Changes to `scripts/test_ocirv1_vault_readiness.py`,
`scripts/deploy/tests/**`, or the root `Makefile` trigger the workflow so edits
to the gate's test inputs prove the documented command still passes.

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
  **Connectivity:** add the least-privilege grant as part of this setup step —
  it is not an optional later tightening:
  ```jsonc
  "grants": [
    { "src": ["tag:ci"], "dst": ["tag:oci-vm"], "ip": ["tcp:22"] }
  ]
  ```
  A default allow-all grant (`{"src":["*"],"dst":["*"],"ip":["*"]}`) does make
  the deploy work without this edit, and that is exactly the problem: the CI
  OAuth identity's blast radius then covers every port on every node in the
  tailnet, not TCP/22 on the deployment VM. Remove the wildcard, or record the
  accepted blast radius explicitly. Leaving it in place unexamined is not a
  default this runbook endorses.

  **Make the tailnet check it, not you.** Merge a `tests` block into the same
  top-level policy file (do not create a duplicate key):
  ```jsonc
  "tests": [
    {
      "src": "tag:ci",
      "proto": "tcp",
      "accept": ["tag:oci-vm:22"],
      "deny": ["tag:oci-vm:443", "tag:oci-vm:55432"]
    }
  ]
  ```
  Then click **Save policy**. That save *is* the enforcement check: Tailscale
  evaluates `tests` on every policy change and rejects the save unless `tag:ci`
  can still reach TCP/22 while TCP/443 and the database listener on TCP/55432
  stay denied. A surviving or re-added wildcard grant fails both `deny`
  assertions and cannot be saved, so the narrow grant above stops depending on
  an operator remembering it. Preserve any other narrowly scoped grants and
  policy tests; do not preserve or re-add a wildcard. The workflow's **Pin VM
  tailnet address + wait for SSH reachability** step then exercises the allowed
  TCP/22 path on every deploy.
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

In the same repository's *Settings → Secrets and variables → Actions →
Variables* tab, add these non-secret deployment values:

| Variable | Value |
| --- | --- |
| `ACX_GPU_READY_URL` | The current private HTTP(S) readiness URL for the burst-GPU service |
| `ACX_GPU_INSTANCE_ID` | The current `acx-gpu-burst` instance OCID |

The workflow has no fallback readiness endpoint. Selecting the GPU lifecycle
option with an empty `ACX_GPU_READY_URL` fails before any host mutation. Pinning
the OCID as a repository variable also avoids giving the Actions runner OCI API
credentials merely to resolve a display name.

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
- OCI CLI installed at `~/.oci-venv/bin/oci`.
- Instance `acx-backend-dg` covered by policy `acx-backend-secret-read`, with
  `SECRET_BUNDLE_READ` access to `acx-vault`.
- Active `OCIR_USERNAME` and `OCIR_AUTH_TOKEN` secret versions in `acx-vault`.
  Bootstrap or rotate them from an operator laptop with an OCI API-key profile:
  ```bash
  scripts/deploy/ocir-token-rotate.sh --set-username 'idu2kqqe2jxy/<email>'
  ```
  Later token-only rotations use `scripts/deploy/ocir-token-rotate.sh`. The
  helper stores the token in Vault and verifies both laptop and VM login paths;
  do not pre-seed a cached Docker login on either host.

## Operating the pipeline

- **Deploy dev**: merge/push to `main` — the workflow runs automatically.
- **Deploy staging/prod**: *Actions → Deploy recognition service → Run workflow*
  → pick the environment. On the private Free-plan repository, `prod` is gated
  by typing `PROMOTE`; there is no required-reviewer pause. The script's own
  `CONFIRM=PROMOTE` check, boot-smoke, and `/health` verification then run.
- **Install GPU lifecycle timers**: on a manual run, select
  **gpu_lifecycle**. After the recognition deploy succeeds, the separately
  flag-gated step runs `recognition-service.sh gpu-lifecycle`, converges the two
  timers idempotently, and fails the workflow unless both timers are enabled and
  active. Leaving the option off (the default) does not invoke the installer.
- **Verify**: the script fails closed — it GETs `/health` and compares
  `commit_sha` to the deployed ref (retries for warm-up). A green run means the
  running service is at that SHA.

The successful timer step ends with these verification lines:

```text
acx-gpu-start.timer enabled active
acx-gpu-reap.timer enabled active
gpu-lifecycle-install: done
```

For a local, transport-free review of exactly what the pipeline will install,
run the following from the repository root. These commands read the same
repository variables configured above; they do not open SSH or start a GPU:

```bash
ACX_GPU_READY_URL="$(gh variable get ACX_GPU_READY_URL)" || exit 1
export ACX_GPU_READY_URL
GPU_INSTANCE_ID="$(gh variable get ACX_GPU_INSTANCE_ID)" || exit 1
export GPU_INSTANCE_ID
ACX_DEPLOY_GPU_LIFECYCLE=1 ACX_GPU_LIFECYCLE_DRY_RUN=1 \
  scripts/deploy/recognition-service.sh gpu-lifecycle
```

The dry-run output identifies the OCID source as `pinned` (when
`GPU_INSTANCE_ID` is supplied) or `resolved-by-name`, and includes the rendered
reaper `--max-lease-seconds` argument
and the planned `systemctl is-enabled` / `systemctl is-active` checks. The
installer argv never contains an OCI `instance action START` or `launch`
operation: deployment installs and schedules the units; it does not directly
start or provision a GPU instance.

`START_INTERVAL` (default `30s`) and `REAP_INTERVAL` (default `2min`) accept
a positive integer followed by `s`, `min`, `h`, or `d`, within systemd's finite
microsecond range. Empty, zero, infinite, compound, and calendar values are
rejected before transport so a malformed interval cannot leave a boot-only
reaper timer.

## Rollback

Roll back by re-pointing the tag to a known-good image (no rebuild) or
redeploying a prior SHA:
```bash
# fastest: retag the last-good image on OCIR + restart + verify
CONFIRM=PROMOTE scripts/deploy/recognition-service.sh promote staging prod
# or redeploy a specific commit (export GOOD_SHA first — see below)
CONFIRM=PROMOTE GIT_REF="$GOOD_SHA" REMOTE_BUILD=1 scripts/deploy/recognition-service.sh deploy prod
```
Before the second command, set `GOOD_SHA` to the full 40-character known-good
commit — `export GOOD_SHA=$(git rev-parse origin/main~1)`, or paste the SHA from
the last green deploy run. Both commands then run exactly as written. Do not
re-introduce an angle-bracket placeholder here: the shell passes it through
verbatim, `git rev-parse` rejects it, and the rollback fails at the worst
possible moment. `scripts/test_deploy_workflow_gate.py` asserts this.

### Roll back the GPU lifecycle release

The installer stages rollback snapshots in a temporary directory and publishes
them with an atomic rename. Before updating `previous`, it requires the saved
environment, tmpfiles configuration, and all four unit files. An incomplete
snapshot from an older installer aborts deployment and leaves both release
links unchanged; restore its missing artifacts from that generation before
retrying.

The installer preserves the previous content-addressed lifecycle generation at
`/opt/acx-gpu/previous`. This rollback disables the start timer first, leaves
the reap timer in place while restoring, then restores the previous Python
release, environment, tmpfiles configuration, and exact units. It verifies the
effective fragments and rejects drop-ins before re-arming the start timer
([RLSE-08]). Run it from a machine with the same SSH access as the deploy:

<!-- gpu-lifecycle-rollback:start -->
```bash
ssh -l "${OCI_USER:-ubuntu}" -- "${OCI_HOST:?set OCI_HOST}" \
  'bash --noprofile --norc -s' <<'REMOTE'
set -euo pipefail
start_timer_armed=0
cleanup_unverified_start_timer() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$start_timer_armed" -eq 1 ]; then
    sudo systemctl disable --now acx-gpu-start.timer || \
      echo "ERROR: could not disable START timer" >&2
    sudo systemctl start acx-gpu-reap.service || \
      echo "ERROR: fail-safe STOP invocation failed" >&2
  fi
  exit "$status"
}
trap cleanup_unverified_start_timer EXIT

sudo systemctl disable --now acx-gpu-start.timer
previous_release=$(readlink -f /opt/acx-gpu/previous)
test -d "$previous_release/infra/oci/gpu_lifecycle"
test -d "$previous_release/systemd"

# Reject a generation whose cost cap is absent, disabled, or unreasonable.
max_lease=$(sed -n 's/^MAX_LEASE_SECONDS=//p' \
  "$previous_release/systemd/gpu-lifecycle.env")
[[ "$max_lease" =~ ^[0-9]+$ ]]
(( max_lease >= 1 && max_lease <= 86400 ))

sudo install -m 0644 "$previous_release/systemd/gpu-lifecycle.env" \
  /etc/acx/gpu-lifecycle.env
sudo install -m 0644 "$previous_release/systemd/acx-gpu.conf" \
  /etc/tmpfiles.d/acx-gpu.conf
for unit in acx-gpu-start.service acx-gpu-start.timer \
  acx-gpu-reap.service acx-gpu-reap.timer; do
  sudo install -m 0644 "$previous_release/systemd/$unit" \
    "/etc/systemd/system/$unit"
done
ln -sfn "$previous_release" /opt/acx-gpu/.rollback-current
sudo mv -Tf /opt/acx-gpu/.rollback-current /opt/acx-gpu/current
sudo systemctl daemon-reload
sudo cmp -s "$previous_release/systemd/gpu-lifecycle.env" \
  /etc/acx/gpu-lifecycle.env

# Restore and synchronously prove the STOP-only backstop before start is armed.
sudo systemctl enable --now acx-gpu-reap.timer
sudo systemctl start acx-gpu-reap.service
for unit in acx-gpu-start.service acx-gpu-start.timer \
  acx-gpu-reap.service acx-gpu-reap.timer; do
  fragment=$(systemctl show "$unit" --property=FragmentPath --value)
  test "$fragment" = "/etc/systemd/system/$unit"
  test -z "$(systemctl show "$unit" --property=DropInPaths --value)"
  sudo cmp -s "$previous_release/systemd/$unit" "$fragment"
done
expected_exec=$(sed -n 's/^ExecStart=//p' \
  "$previous_release/systemd/acx-gpu-reap.service")
effective_exec=$(systemctl show acx-gpu-reap.service \
  --property=ExecStart --value)
case "$effective_exec" in
  *"argv[]=$expected_exec ;"*) ;;
  *) echo "ERROR: effective reaper command differs from selected generation" >&2; exit 1 ;;
esac
case "$effective_exec" in
  *'--max-lease-seconds ${MAX_LEASE_SECONDS}'*) ;;
  *) echo "ERROR: effective reaper does not consume MAX_LEASE_SECONDS" >&2; exit 1 ;;
esac
systemctl is-enabled --quiet acx-gpu-reap.timer
systemctl is-active --quiet acx-gpu-reap.timer

start_timer_armed=1
sudo systemctl enable --now acx-gpu-start.timer
systemctl is-enabled --quiet acx-gpu-start.timer
systemctl is-active --quiet acx-gpu-start.timer
start_timer_armed=0
trap - EXIT
REMOTE
```
<!-- gpu-lifecycle-rollback:end -->

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
- **Dark face_pipeline envs (FIR-4):** the image still ships insightface via
  `.[bench]` (incumbent dark default) and does **not** bake face_pipeline ONNX
  weights. Today the only host-mounted volume is `/data/cache`. Before setting
  `RECOGNITION_FACE_PIPELINE_PROFILE=face_pipeline`:
  1. Fetch models into a host path that maps into that volume, e.g.
     `uv run python scripts/fetch_face_pipeline_models.py --dest /data/cache/face_pipeline_models`
     (from `apps/prototype-description-service` on the host, or any path that
     becomes the container mount).
  2. Set `RECOGNITION_FACE_PIPELINE_MODELS_DIR` to the **container** path for
     that directory (recommended: `/data/cache/face_pipeline_models`).
  3. Re-check offline with
     `uv run python scripts/fetch_face_pipeline_models.py --dest <same-path> --verify-only`
     before flipping the profile. Missing, model-hash, or license-hash mismatches
     fail closed at boot (no network on verify).
