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

After the operator reviews the Terraform plan and separately approves apply,
use this exact input-file order so the generated GPU OCID is the last variable
value source:

```sh
terraform -chdir=infra/oci plan -var-file=terraform.tfvars -var-file=gpu-api-key.tfvars
terraform -chdir=infra/oci apply -var-file=terraform.tfvars -var-file=gpu-api-key.tfvars
```

Do not apply as part of minting. If the generated tfvars file already contains
different content, the mint helper stops instead of replacing it; inspect and
resolve that file before retrying.
