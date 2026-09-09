# GPU demo environment flip

Use this procedure to switch the production description service and demo
WordPress stack to the A10-backed `gpu_qwen30b` profile as one change. The
producer redeploy and backend lifecycle convergence are part of the same
release: a green environment preflight alone does not prove that the live
producer is publishing snapshots or that the backend STOP path is installed.
The preflight fails before deployment on an incomplete adapter, endpoint,
snapshot, or WordPress recognition contract and never prints secret values.

## 1. Edit the two live env files

From the repository root, review the complete worked blocks first:

```bash
set -euo pipefail
sed -n '/# --- GPU burst profile (demo) ---/,+35p' apps/prototype-description-service/.env.prod.example
sed -n '/# --- GPU burst profile (demo) ---/,+35p' infra/oci/demo/.env.example
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'sudo cp -a /opt/acx-backend/prod/secrets/.env /opt/acx-backend/prod/secrets/.env.pre-gpu-flip && sudo cp -a /opt/acx-backend/demo/secrets/.env /opt/acx-backend/demo/secrets/.env.pre-gpu-flip'
ssh -t ubuntu@acx-backend.tail1a44b8.ts.net 'sudoedit /opt/acx-backend/prod/secrets/.env /opt/acx-backend/demo/secrets/.env'
```

Set `ACX_DESCRIPTION_ADAPTER=gpu_qwen30b` in both files. Set the same private
or producer-allowlisted `ACX_GPU_ENDPOINT_URL`, snapshot paths, and freshness
limit shown by the worked blocks. With
`RECOGNITION_SECRET_BACKEND=oci_vault`, leave the producer's direct
`ACX_GPU_ENDPOINT_API_KEY` blank and replace its
`RECOGNITION_VAULT_SECRET_MAP` entry with the real GPU-key Vault OCID. With the
`env` backend, set the producer's direct key instead. Replace the demo block's
GPU endpoint URL assertion, but do not put the GPU endpoint credential in the
demo file because WordPress does not consume it. Recognition URL, API key, and tenant ID belong only in the demo file and must be the
`WORDPRESS_CONFIG_EXTRA` `define()` values because those PHP constants are the
operative plugin configuration. Do not paste live credentials into the
repository or terminal output.

Recognition constants must use unconditional, literal single-quoted `define`
statements. The shared PHP reader accepts comments and literal boolean/integer
values for other constants, but rejects conditional or interpolated PHP.
Leave the whole `WORDPRESS_CONFIG_EXTRA` dotenv value unquoted, as in the
example, or wrap it in double quotes. An outer single quote conflicts with
the PHP string delimiters. Preflight rejects unterminated quotes, embedded
matching delimiters, escapes and multiline values instead of guessing how
Compose would decode them.
GPU addresses must be private and cannot be loopback, unspecified, multicast,
or link-local, including IPv4-mapped IPv6 and allowlisted DNS answers.

## 2. Stage and optionally prove the preflight contract

Stage the validator in a private temporary directory on the VM, then optionally
validate both halves in one invocation. This is a contract check only; it does
not replace the release gate that `deploy-demo` repeats after the prod API
redeploy. The reaper check loads the argument parser
from the effective service WorkingDirectory; that checkout and its
`scripts/deploy/gpu-snapshot-deployments.conf` registry must be readable and
valid. It verifies both the executable path and the effective arguments.
The effective OCI executable must return help identifying the Oracle Cloud
Infrastructure CLI within ten seconds. This local probe uses the service
user, its home directory, and the standard system-service PATH; switching
users requires noninteractive sudo. Missing, non-executable, and unrelated
binaries fail closed. The probe does not call an OCI API.
Reaper EnvironmentFiles must use exact `KEY=value` assignments for the
installer keys (`GPU_INSTANCE_ID`, `MAX_LEASE_SECONDS`, `IDLE_SECONDS`,
`ACX_DESCRIBE_LOAD_STALE_GRACE_SECONDS`, and `READY_URL`). Whole-value single
or double quotes and repeated assignments (last wins) are supported; leading
assignment whitespace, escapes, multiline values, and unknown keys fail closed.
`--check-reaper` is mandatory for this flip: it
fails unless `acx-gpu-reap.timer` is enabled and active and its effective
service targets an instance OCID with a finite positive maximum lease. It also
prints the exact `MANUAL STOP fallback:` command. The final success line is `OK:`; any
reaper, duplicate, placeholder, malformed value, or cross-file mismatch stops
the change before deployment.

```bash
set -euo pipefail
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'install -d -m 700 /tmp/acx-gpu-preflight/lib'
scp scripts/deploy/preflight-gpu-env.sh ubuntu@acx-backend.tail1a44b8.ts.net:/tmp/acx-gpu-preflight/
scp scripts/deploy/lib/gpu-env-contract.sh ubuntu@acx-backend.tail1a44b8.ts.net:/tmp/acx-gpu-preflight/lib/
scp infra/oci/demo/lib/describe-gate.sh ubuntu@acx-backend.tail1a44b8.ts.net:/tmp/acx-gpu-preflight/lib/
scp scripts/deploy/lib/verify-live-gpu.sh ubuntu@acx-backend.tail1a44b8.ts.net:/tmp/acx-gpu-preflight/lib/
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'chmod 700 /tmp/acx-gpu-preflight/preflight-gpu-env.sh /tmp/acx-gpu-preflight/lib/verify-live-gpu.sh && sudo /tmp/acx-gpu-preflight/preflight-gpu-env.sh --check-reaper /opt/acx-backend/prod/.env /opt/acx-backend/demo/secrets/.env'
```

If this optional check is run before the producer change, leave the staged
helpers in place and continue with the producer flip; do not treat this early
check as permission to publish the demo.

## 3. Deploy in producer-then-consumer order

Converge the backend lifecycle before the description producer redeploy. Deploy
WordPress only after the recognition deploy's verification passes, so the demo
never publishes against an unverified adapter.

### Green ordering

Use this producer-to-consumer order for the live flip:

1. Flip the description SERVICE producer profile by setting
   `ACX_DESCRIPTION_ADAPTER` on the running producer. The producer is the
   authority; do not make a demo-only env edit stand in for this change.
2. Converge the backend lifecycle release before the producer redeploy. The
   `gpu-lifecycle` command stages the module atomically, provisions the
   `/run/acx-write/<environment>` producer directories, installs the
   `--load-dir /run/acx-write` units with the durable lease path and shared
   lifecycle lock, and verifies both timers are enabled and active. Do not
   enable an old unit by hand or copy the module directly into a live path.
   On a fresh host the installer enables `acx-gpu-reap.timer` without a
   synchronous reaper start when `describe-load.json` snapshots have not been
   published yet (`OnActiveSec` delays the first tick). Runtime reaper cycles
   stay fail-closed on missing or stale snapshots; do not skip this
   convergence, and do not start the reaper unit by hand before deploy prod.
3. On a cold or partially converged host, stop for the producer-preparation
   gate before invoking the production deploy. The standard recognition
   deploy verifies every environment in
   `gpu-snapshot-deployments.conf` after restart; it is an aggregate release
   gate, not a first-producer bootstrap, and rolls back if any registered
   sibling has no fresh snapshot. The deployment helper must first provide a
   scoped producer-preparation operation that proves the selected image,
   effective `/run/acx-write/<environment>/describe-load.json` writer, valid
   schema, and freshness for each producer being brought up. If that scoped
   operation is unavailable, stop and request it from the deployment owner.
   Do not use `ACX_VERIFY_OPTIONAL` or fabricate zero-valued snapshots to get
   past the aggregate gate.
   Once that preparation has succeeded, run the full live snapshot checker
   before the production deploy as a fail-closed proof that the aggregate
   verifier will not reject a missing or stale registered sibling.
4. Redeploy the prod API and wait for its health/adapter verification to pass.
   That publish is what makes the load snapshots exist for the later live
   checker and for the first timer-driven reaper cycle.
5. Verify both env halves with `preflight-gpu-env.sh --check-reaper` after the
   lifecycle convergence and before publishing any demo descriptions.
6. Run the live GPU snapshot checker after lifecycle convergence:
   `GPU_SNAPSHOT_ENV=prod make check-gpu-snapshots-live`. This is mandatory;
   it validates every registered `describe-load.json` for schema, readability,
   and freshness on the host, rather than only checking that the files are
   non-empty. The checker must finish with its `OK:` line before continuing.
7. Run `deploy-demo` with `ACX_DEMO_GPU_PREFLIGHT=1`, so the deploy repeats the
   reaper/environment gate immediately before the demo stack is brought up.
   Repeat `GPU_SNAPSHOT_ENV=prod make check-gpu-snapshots-live` immediately
   before that deploy so a slow artifact copy cannot exceed the snapshot
   freshness budget after the earlier check. `--check-reaper` also rejects
   any already-published load snapshot that has gone stale.
8. Confirm the bounded first-burst result (`Describe burst bounded` and
   `PASS demo first describe burst`) and retain the preflight's `MANUAL STOP
   fallback` line as the operator's reaper-stop backstop.

```bash
set -euo pipefail
# Persist the same PHP reader for bootstrap; sync-demo preserves this helper.
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'sudo install -m 644 /tmp/acx-gpu-preflight/lib/gpu-env-contract.sh /opt/acx-backend/demo/lib/gpu-env-contract.sh'
GPU_INSTANCE_ID="${GPU_INSTANCE_ID:-$(terraform -chdir=infra/oci output -raw gpu_instance_id)}"
GPU_READY_URL="${GPU_READY_URL:?Set GPU_READY_URL to the private GPU service /health URL}"
ACX_DEPLOY_GPU_LIFECYCLE=1 \
  GPU_INSTANCE_ID="$GPU_INSTANCE_ID" \
  ACX_GPU_READY_URL="$GPU_READY_URL" \
  scripts/deploy/recognition-service.sh gpu-lifecycle
GPU_SNAPSHOT_ENV=prod make check-gpu-snapshots-live
CONFIRM=PROMOTE scripts/deploy/recognition-service.sh deploy prod
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'set -euo pipefail
for timer in acx-gpu-start.timer acx-gpu-reap.timer; do
  systemctl is-enabled --quiet "$timer"
  systemctl is-active --quiet "$timer"
done
exec_start="$(systemctl show acx-gpu-reap.service --property=ExecStart --value)"
grep -F -- "--load-dir /run/acx-write" <<<"$exec_start"
grep -F -- "--running-since-path /var/lib/acx-gpu/running-since.json" <<<"$exec_start"
deployments_file=/opt/acx-gpu/current/scripts/deploy/gpu-snapshot-deployments.conf
[ -r "$deployments_file" ] || {
  echo "Missing GPU snapshot deployments registry: $deployments_file" >&2
  exit 1
}
while IFS= read -r environment || [ -n "$environment" ]; do
  [ -n "$environment" ] || {
    echo "Empty GPU snapshot deployment in $deployments_file" >&2
    exit 1
  }
  test -s "/run/acx-write/$environment/describe-load.json" || {
    echo "Missing describe-load snapshot for $environment; redeploy that producer before continuing." >&2
    exit 1
  }
done < "$deployments_file"'
# GNU coreutils uses sha256sum; Homebrew installs that command as gsha256sum
# on macOS. Select the local payload digest tool before opening SSH.
if command -v sha256sum >/dev/null 2>&1; then
  GPU_SNAPSHOT_SHA256=sha256sum
elif command -v gsha256sum >/dev/null 2>&1; then
  GPU_SNAPSHOT_SHA256=gsha256sum
else
  echo 'Install GNU coreutils (macOS: brew install coreutils) to provide sha256sum or gsha256sum.' >&2
  exit 1
fi
export GPU_SNAPSHOT_SHA256
GPU_SNAPSHOT_ENV=prod make check-gpu-snapshots-live
PLUGIN_ZIP=dist/alt-context-reviewed.zip # Replace with the artifact named in the review record.
PLUGIN_ZIP_SHA256=replace-with-reviewed-sha256 # Replace with that record's SHA-256.
case "$PLUGIN_ZIP" in dist/alt-context-*.zip) ;; *) echo "Refusing unscoped plugin artifact path." >&2; exit 1 ;; esac
case "$PLUGIN_ZIP_SHA256" in replace-*|*[!0-9a-fA-F]*|'') echo "Set the reviewed artifact SHA-256." >&2; exit 1 ;; esac
test "${#PLUGIN_ZIP_SHA256}" -eq 64
test -f "$PLUGIN_ZIP"
ACTUAL_PLUGIN_ZIP_SHA256="$("$GPU_SNAPSHOT_SHA256" "$PLUGIN_ZIP" | awk '{print $1}')"
test "$ACTUAL_PLUGIN_ZIP_SHA256" = "$PLUGIN_ZIP_SHA256"
printf 'Deploying reviewed plugin artifact: %s\n' "$PLUGIN_ZIP"
# Re-validate snapshot freshness immediately before stack startup.
GPU_SNAPSHOT_ENV=prod make check-gpu-snapshots-live
ACX_DEMO_GPU_PREFLIGHT=1 PLUGIN_ZIP="$PLUGIN_ZIP" make deploy-demo
```

`bootstrap-wp.sh` probes the running service's authenticated
`/health/detailed` response and refuses to publish when the live adapter is not
on the shared trusted-profile allowlist.

## 4. Verify and close the change

Verify the container received the requested non-secret profile and re-run the
demo bootstrap gate. The bootstrap command is idempotent and must finish with
`Bootstrap complete`, but it is not proof of inference: it can legitimately
skip generation when the demo has no media or already has complete coverage.
The remote block therefore submits one fresh image to `/scene/describe/run`
with `recognition_enabled=false`, using the configured GPU adapter. This run
worker waits for readiness before invoking that adapter. Enqueueing publishes pending describe load so
`acx-gpu-start.timer` can wake a stopped burst instance; the verifier then polls
the durable run for up to 15 minutes, then verifies the completed item’s provenance. It fails unless the response proves an
uncached final GPU result with model identity and non-empty generated alt text.
Do not remove the staged contract helpers until this live request succeeds.

```bash
set -euo pipefail
ssh ubuntu@acx-backend.tail1a44b8.ts.net "cd /opt/acx-backend/prod && sudo docker compose -f docker-compose.env.yml -f docker-compose.admin.yml exec -T api sh -c 'test \"\$ACX_DESCRIPTION_ADAPTER\" = gpu_qwen30b'"
ssh ubuntu@acx-backend.tail1a44b8.ts.net "cd /opt/acx-backend/demo && PLUGIN_ZIP=/tmp/alt-context.zip ./bootstrap-wp.sh"
ssh ubuntu@acx-backend.tail1a44b8.ts.net '/tmp/acx-gpu-preflight/lib/verify-live-gpu.sh /opt/acx-backend/demo/secrets/.env'
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'rm -f /tmp/acx-gpu-preflight/preflight-gpu-env.sh /tmp/acx-gpu-preflight/lib/gpu-env-contract.sh /tmp/acx-gpu-preflight/lib/describe-gate.sh /tmp/acx-gpu-preflight/lib/verify-live-gpu.sh && rmdir /tmp/acx-gpu-preflight/lib /tmp/acx-gpu-preflight'
```

If verification fails, do not run the describe pass manually. Restore the
pre-flip env files and restart both consumers. If the A10 is unexpectedly
running after any failure, run the STOP block only after its executable guard
proves that no bake or evaluation is in flight. Bake/evaluation operators must
hold `/run/acx-gpu/bake.lease` or `/run/acx-gpu/evaluation.lease` for the full
activity. They must also acquire `/run/acx-gpu/activity.lock` with an atomic
`mkdir` before starting and remove it only after the activity ends. The STOP
block holds that same mutex across both its guard and the OCI action, closing
the guard/action race; a stale or occupied mutex fails closed. The guard also
checks the corresponding live processes and fails closed when `pgrep` is
unavailable. These commands are compensating actions, so run them as a
separate block rather than appending them to the happy path.

```bash
set -euo pipefail
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'sudo cp -a /opt/acx-backend/prod/secrets/.env.pre-gpu-flip /opt/acx-backend/prod/secrets/.env && sudo cp -a /opt/acx-backend/demo/secrets/.env.pre-gpu-flip /opt/acx-backend/demo/secrets/.env && sudo systemctl restart acx-prod.service acx-demo.service'
```

```bash
set -euo pipefail
GPU_HOST=ubuntu@acx-backend.tail1a44b8.ts.net
GPU_INSTANCE_ID="$(terraform -chdir=infra/oci output -raw gpu_instance_id)"
test -n "$GPU_INSTANCE_ID"
ACTIVITY_LOCK=/run/acx-gpu/activity.lock
activity_lock_held=0
release_activity_lock() {
    if [[ "$activity_lock_held" -eq 1 ]]; then
        ssh "$GPU_HOST" "sudo rmdir '$ACTIVITY_LOCK'"
        activity_lock_held=0
    fi
}
trap release_activity_lock EXIT
trap 'exit 130' HUP INT TERM
if ! ssh "$GPU_HOST" "sudo mkdir '$ACTIVITY_LOCK'"; then
    echo "Refusing STOP: the shared A10 activity mutex is occupied." >&2
    exit 1
fi
activity_lock_held=1
ssh "$GPU_HOST" 'set -euo pipefail
command -v pgrep >/dev/null
if pgrep -af "scripts[.]eval_harness[.](bakeoff|cli)|gpu[-_]bake" >/dev/null; then
    echo "Refusing STOP: an A10 bake/evaluation process is active." >&2
    exit 1
else
    process_status=$?
    if [[ "$process_status" -ne 1 ]]; then
        echo "Refusing STOP: process inspection failed." >&2
        exit 1
    fi
fi
for lease in /run/acx-gpu/bake.lease /run/acx-gpu/evaluation.lease; do
    # Require successful proof of absence. sudo failures can also return 1,
    # so a failed positive existence test cannot establish that no lease exists.
    if ! sudo test ! -e "$lease"; then
        echo "Refusing STOP: active activity lease or lease inspection failed at $lease." >&2
        exit 1
    fi
done'
oci compute instance action --action STOP --instance-id "$GPU_INSTANCE_ID"
release_activity_lock
trap - EXIT HUP INT TERM
```

Design grounding: Release It!, ch. 5.5 (fail before consuming deployment
capacity), plus the lane's `rg-008` load-time configuration validation and
`rg-006` copy-pasteable-command rules. Preflight output follows the OBS
redaction rule: secret key names and redacted lengths only.

The reaper preflight executes import and disposable lease-store probes with
the interpreter declared by the service's ExecStart. Its shared test harness
redirects that executable to the pytest interpreter and supplies a synthetic
boot identity to the disposable lease probe, so tests can run on macOS or
with masked procfs. Production does not supply this override: the lease store
must obtain the host's boot identity. The test override is an internal probe
argument, not a deployment environment setting.
