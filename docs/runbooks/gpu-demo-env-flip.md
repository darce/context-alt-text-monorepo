# GPU demo environment flip

Use this procedure to switch the production description service and demo
WordPress stack to the A10-backed `gpu_qwen30b` profile as one change. The
preflight fails before deployment on an incomplete adapter, endpoint, snapshot,
or WordPress recognition contract and never prints secret values.

## 1. Edit the two live env files

From the repository root, review the complete worked blocks first:

```bash
sed -n '/# --- GPU burst profile (demo) ---/,+35p' apps/prototype-description-service/.env.prod.example
sed -n '/# --- GPU burst profile (demo) ---/,+35p' infra/oci/demo/.env.example
ssh -t ubuntu@acx-backend.tail1a44b8.ts.net 'sudoedit /opt/acx-backend/prod/secrets/.env /opt/acx-backend/demo/secrets/.env'
```

Set `ACX_DESCRIPTION_ADAPTER=gpu_qwen30b` in both files. Set the same private
`ACX_GPU_ENDPOINT_URL`, snapshot paths, freshness limit, recognition URL,
tenant API key, and tenant ID shown by the worked blocks. With
`RECOGNITION_SECRET_BACKEND=oci_vault`, leave the producer's direct
`ACX_GPU_ENDPOINT_API_KEY` blank and replace its
`RECOGNITION_VAULT_SECRET_MAP` entry with the real GPU-key Vault OCID. With the
`env` backend, set the producer's direct key instead. Replace the demo block's
GPU-key coordination assertion too; WordPress does not consume it. In the demo
file, the three recognition values must be the
`WORDPRESS_CONFIG_EXTRA` `define()` values because those PHP constants are the
operative plugin configuration. Do not paste live credentials into the
repository or terminal output.

## 2. Preflight both files

Stage the validator in a private temporary directory on the VM, then validate
both halves in one invocation. Success is exactly one `OK:` line; any duplicate,
placeholder, malformed value, or cross-file mismatch stops the change before
deployment.

```bash
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'install -d -m 700 /tmp/acx-gpu-preflight/lib'
scp scripts/deploy/preflight-gpu-env.sh ubuntu@acx-backend.tail1a44b8.ts.net:/tmp/acx-gpu-preflight/
scp scripts/deploy/lib/gpu-env-contract.sh ubuntu@acx-backend.tail1a44b8.ts.net:/tmp/acx-gpu-preflight/lib/
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'chmod 700 /tmp/acx-gpu-preflight/preflight-gpu-env.sh && sudo /tmp/acx-gpu-preflight/preflight-gpu-env.sh /opt/acx-backend/prod/secrets/.env /opt/acx-backend/demo/secrets/.env'
```

## 3. Deploy in producer-then-consumer order

Deploy the description producer first. Deploy WordPress only after the
recognition deploy's verification passes, so the demo never publishes against
an unverified adapter.

```bash
CONFIRM=PROMOTE scripts/deploy/recognition-service.sh deploy prod
PLUGIN_ZIP="$(find dist -maxdepth 1 -type f -name 'alt-context-*.zip' -print -quit)"
test -n "$PLUGIN_ZIP"
PLUGIN_ZIP="$PLUGIN_ZIP" make deploy-demo
```

`bootstrap-wp.sh` probes the running service's authenticated
`/health/detailed` response and refuses to publish when the live adapter is not
on the shared trusted-profile allowlist.

## 4. Verify and close the change

Verify the container received the requested non-secret profile and re-run the
demo bootstrap gate. The second command is idempotent and must finish with
`Bootstrap complete`.

```bash
ssh ubuntu@acx-backend.tail1a44b8.ts.net "cd /opt/acx-backend/prod && sudo docker compose -f docker-compose.env.yml -f docker-compose.admin.yml exec -T api sh -c 'test \"\$ACX_DESCRIPTION_ADAPTER\" = gpu_qwen30b'"
ssh ubuntu@acx-backend.tail1a44b8.ts.net "cd /opt/acx-backend/demo && PLUGIN_ZIP=/tmp/alt-context.zip ./bootstrap-wp.sh"
ssh ubuntu@acx-backend.tail1a44b8.ts.net 'rm -f /tmp/acx-gpu-preflight/preflight-gpu-env.sh /tmp/acx-gpu-preflight/lib/gpu-env-contract.sh && rmdir /tmp/acx-gpu-preflight/lib /tmp/acx-gpu-preflight'
```

If verification fails, do not run the describe pass manually. Restore the
previous adapter/env values and use the existing recognition rollback path.

Design grounding: Release It!, ch. 5.5 (fail before consuming deployment
capacity), plus the lane's `rg-008` load-time configuration validation and
`rg-006` copy-pasteable-command rules. Preflight output follows the OBS
redaction rule: secret key names and redacted lengths only.
