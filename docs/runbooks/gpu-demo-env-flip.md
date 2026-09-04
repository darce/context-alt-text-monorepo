# GPU demo environment flip

Use this procedure to switch the production description service and demo
WordPress stack to the A10-backed `gpu_qwen30b` profile as one change. The
preflight fails before deployment on an incomplete adapter, endpoint, snapshot,
or WordPress recognition contract and never prints secret values.

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

## 2. Prove the reaper and preflight both files

Stage the validator in a private temporary directory on the VM, then validate
both halves in one invocation. `--check-reaper` is mandatory for this flip: it
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
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'chmod 700 /tmp/acx-gpu-preflight/preflight-gpu-env.sh /tmp/acx-gpu-preflight/lib/verify-live-gpu.sh && sudo /tmp/acx-gpu-preflight/preflight-gpu-env.sh --check-reaper /opt/acx-backend/prod/secrets/.env /opt/acx-backend/demo/secrets/.env'
```

## 3. Deploy in producer-then-consumer order

Deploy the description producer first. Deploy WordPress only after the
recognition deploy's verification passes, so the demo never publishes against
an unverified adapter.

```bash
set -euo pipefail
CONFIRM=PROMOTE scripts/deploy/recognition-service.sh deploy prod
PLUGIN_ZIP="$(ls -t dist/alt-context-*.zip 2>/dev/null | head -1 || true)"
test -n "$PLUGIN_ZIP"
printf 'Deploying reviewed plugin artifact: %s\n' "$PLUGIN_ZIP"
PLUGIN_ZIP="$PLUGIN_ZIP" make deploy-demo
```

`bootstrap-wp.sh` probes the running service's authenticated
`/health/detailed` response and refuses to publish when the live adapter is not
on the shared trusted-profile allowlist.

## 4. Verify and close the change

Verify the container received the requested non-secret profile and re-run the
demo bootstrap gate. The bootstrap command is idempotent and must finish with
`Bootstrap complete`, but it is not proof of inference: it can legitimately
skip generation when the demo has no media or already has complete coverage.
The remote block therefore submits a fresh, authenticated multipart request
with explicit `tier=gpu` and fails unless the response proves an uncached final
GPU result with model identity and non-empty generated alt text. Do not remove
the staged contract helpers until this live request succeeds.

```bash
set -euo pipefail
ssh ubuntu@acx-backend.tail1a44b8.ts.net "cd /opt/acx-backend/prod && sudo docker compose -f docker-compose.env.yml -f docker-compose.admin.yml exec -T api sh -c 'test \"\$ACX_DESCRIPTION_ADAPTER\" = gpu_qwen30b'"
ssh ubuntu@acx-backend.tail1a44b8.ts.net "cd /opt/acx-backend/demo && PLUGIN_ZIP=/tmp/alt-context.zip ./bootstrap-wp.sh"
ssh ubuntu@acx-backend.tail1a44b8.ts.net '/tmp/acx-gpu-preflight/lib/verify-live-gpu.sh /opt/acx-backend/demo/secrets/.env'
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'rm -f /tmp/acx-gpu-preflight/preflight-gpu-env.sh /tmp/acx-gpu-preflight/lib/gpu-env-contract.sh /tmp/acx-gpu-preflight/lib/describe-gate.sh /tmp/acx-gpu-preflight/lib/verify-live-gpu.sh && rmdir /tmp/acx-gpu-preflight/lib /tmp/acx-gpu-preflight'
```

If verification fails, do not run the describe pass manually. Restore the
pre-flip env files and restart both consumers. If the A10 is unexpectedly
running after any failure, run the STOP block after checking that no bake or
evaluation is in flight. These commands are compensating actions, so run them
as a separate block rather than appending them to the happy path.

```bash
set -euo pipefail
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'sudo cp -a /opt/acx-backend/prod/secrets/.env.pre-gpu-flip /opt/acx-backend/prod/secrets/.env && sudo cp -a /opt/acx-backend/demo/secrets/.env.pre-gpu-flip /opt/acx-backend/demo/secrets/.env && sudo systemctl restart acx-prod.service acx-demo.service'
```

```bash
set -euo pipefail
GPU_INSTANCE_ID="$(terraform -chdir=infra/oci output -raw gpu_instance_id)"
test -n "$GPU_INSTANCE_ID"
oci compute instance action --action STOP --instance-id "$GPU_INSTANCE_ID"
```

Design grounding: Release It!, ch. 5.5 (fail before consuming deployment
capacity), plus the lane's `rg-008` load-time configuration validation and
`rg-006` copy-pasteable-command rules. Preflight output follows the OBS
redaction rule: secret key names and redacted lengths only.
