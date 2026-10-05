# GPU endpoint key minting

The enabled GPU endpoint requires `ACX_GPU_ENDPOINT_API_KEY`. Mint the Vault
secret only after the tooling has landed and an operator has approved the
Vault write. The bounded readiness check reads every TOML fragment in
`config/env/manifest.d`; it must find the derived prod Vault map, the four
required prod secret refs, and one GPU key declaration before contacting the
writer. The key declaration stays in its owning fragment, currently
`21-service-vm.toml`.

Bootstrap creates the secret only when it does not exist. Rotation is a
separate action and must include `--rotate`; it reuses the existing OCID.
Provide the approved VM's SSH target when running the command:

```sh
bash scripts/deploy/gpu-key-mint.sh --approve-mint --ssh-target user@approved-vm
```

The generated key is piped to the VM writer on stdin. It is not placed in an
argument, log, manifest, or Terraform input. On success, the command prints
only the secret OCID and byte length, updates the GPU declaration's dev/prod
references atomically, and writes the identifier-only file
`infra/oci/gpu-api-key.tfvars` durably. The staging reference is preserved.
Before contacting the writer, the command locks the local mint transaction and
checks that both output destinations can be updated. An unknown or stale
Terraform input fails closed before the Vault write; when an existing input
matches the manifest OCID, rerunning with that OCID is idempotent. If the
second local publication fails, the helper restores and fsyncs the earlier
file's preimage.

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
