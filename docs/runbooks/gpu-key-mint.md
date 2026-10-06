# GPU endpoint key minting

The enabled GPU endpoint requires `ACX_GPU_ENDPOINT_API_KEY`. Mint the Vault
secret only after the tooling has landed and an operator has approved the
Vault write. The bounded readiness check reads every TOML fragment in
`config/env/manifest.d`; it must find the derived prod Vault map, the four
required prod secret refs, and one GPU key declaration before contacting the
writer. The key declaration stays in its owning fragment, currently
`21-service-vm.toml`.

Bootstrap creates the secret only when it does not exist. Rotation is a
separate action and must include `--rotate`; it reuses the existing OCID. If
the manifest still has host refs, run bootstrap first and let it record the
returned OCID. Rotation then refuses before SSH unless the complete manifest
contains matching dev OCI and prod Vault refs for that OCID.
Provide the approved VM's SSH target when running the command:

```sh
bash scripts/deploy/gpu-key-mint.sh --approve-mint --ssh-target user@approved-vm
```

The equivalent Make target is:

```sh
make gpu-key-mint GPU_KEY_MINT_ARGS="--approve-mint --ssh-target user@approved-vm"
```

For rotation, append `--rotate` to either command. The Make target requires
the explicit `--approve-mint` argument; bare `make gpu-key-mint` refuses.

The generated key is piped to the VM writer on stdin. It is not placed in an
argument, log, manifest, or Terraform input. On success, the command prints
only the secret OCID and byte length, updates the GPU declaration's dev/prod
references atomically, and writes the identifier-only file
`infra/oci/gpu-api-key.tfvars` durably. The staging reference is preserved.
If the manifest already contains a consistent dev OCI and prod Vault OCID, the
command binds the remote request to that identifier. The writer must refuse a
missing or recreated name-selected secret before create or update. Initial
bootstrap from the checked-in host refs has no prior identifier to bind;
rotation is unavailable until bootstrap records one.

Before contacting the writer, the command takes the canonical environment-root
cooperative write lock shared with harvest and checks that both output
destinations can be updated. Fragment paths resolve through symlinks to the
environment root, matching harvest's `--root` lock identity. The lock serializes
cooperating tools; it does not exclude arbitrary editors. The helper rechecks
captured destination bytes before replacement and refuses stale external edits.
An unknown or stale Terraform input fails closed before the Vault write; when
an existing input matches the manifest OCID, rerunning with that OCID is
idempotent. If the second local publication fails, the helper restores and
fsyncs the earlier file's preimage.

After the operator reviews the Terraform plan and separately approves apply,
use this exact input-file order so the generated GPU OCID is the last variable
value source:

```sh
terraform -chdir=infra/oci plan -var-file=terraform.tfvars -var-file=gpu-api-key.tfvars
terraform -chdir=infra/oci apply -var-file=terraform.tfvars -var-file=gpu-api-key.tfvars
```

Do not apply as part of minting. If the generated tfvars file has content that
does not match the current manifest OCID, the mint helper stops before invoking
the Vault writer; inspect and resolve the mismatch before retrying.

## After a mint

Complete these steps in order after the mint succeeds:

1. Regenerate the examples with `make env-examples`. Commit the updated
   `config/env/manifest.d/21-service-vm.toml` fragment and all regenerated
   example files. Without the regenerated examples, `make env-check` (and
   `check-all`) reports that an example differs.
2. The mint records the GPU key's own `dev` `oci:<ocid>` and `prod`
   `vault:<ocid>` refs on `ACX_GPU_ENDPOINT_API_KEY` (the staging ref is
   preserved). `RECOGNITION_VAULT_SECRET_MAP` derives the corresponding
   `ACX_GPU_ENDPOINT_API_KEY` entry automatically. Do not set a value on or
   hand-edit `RECOGNITION_VAULT_SECRET_MAP`.
3. Check, then apply, the materialized environment on the VM for production
   and development:

   ```sh
   make env-materialize ENV=prod TARGET=svc-vm
   APPLY=1 CONFIRM=prod make env-materialize ENV=prod TARGET=svc-vm
   make env-materialize ENV=dev TARGET=svc-vm
   APPLY=1 make env-materialize ENV=dev TARGET=svc-vm
   ```

4. Restart the API and worker containers for both environments so they read
   the refreshed values. On the backend VM, restart the corresponding
   `acx-prod.service` and `acx-dev.service` units:

   ```sh
   sudo systemctl restart acx-prod.service
   sudo systemctl restart acx-dev.service
   ```

5. Review the Terraform plan, then separately approve apply. Keep
   `terraform.tfvars` first and `gpu-api-key.tfvars` last so the minted OCID
   is the final variable value source:

   ```sh
   terraform -chdir=infra/oci plan -var-file=terraform.tfvars -var-file=gpu-api-key.tfvars
   terraform -chdir=infra/oci apply -var-file=terraform.tfvars -var-file=gpu-api-key.tfvars
   ```

## After a rotation

Rotation changes the secret value for the existing OCID. The GPU host fetches
the key only in the `ExecStartPre` command for `acx-gpu-vlm.service` in
`infra/oci/gpu-cloud-init.yaml`. Production's `OciVaultSecretProvider` caches
resolved values per process in
`apps/prototype-description-service/shared/secrets.py`, while development
uses its materialized `.env` copy. Until every consumer refreshes, the API and
GPU endpoint can hold different keys and requests can fail with HTTP 401.
Refresh them in this order:

1. Check and apply the updated development environment:

   ```sh
   make env-materialize ENV=dev TARGET=svc-vm
   APPLY=1 make env-materialize ENV=dev TARGET=svc-vm
   ```

2. Restart the production and development API/worker services so production
   drops its cached Vault value and development reads its updated `.env`:

   ```sh
   sudo systemctl restart acx-prod.service
   sudo systemctl restart acx-dev.service
   ```

3. Restart `acx-gpu-vlm.service` on the GPU host to rerun its key-fetch
   `ExecStartPre` (or restart the GPU instance).
4. Verify the GPU endpoint with an authenticated probe and confirm it
   succeeds before returning traffic to normal use.
