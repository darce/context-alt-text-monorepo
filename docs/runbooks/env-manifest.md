# Environment manifest runbook

## What it is

`config/env/manifest.d/*.toml` is the source of truth for the generated `.env.example` templates and local/runtime `.env` files in scope. `targets.toml` defines each output target; the other TOML fragments declare its variables. The generated header identifies these files. Do not hand-edit a generated file: change the manifest and render it again.

## Variable classes and sources

Each variable has a class, target list, section, documentation, and safe example. `public` and `config` variables take per-environment `values`; `secret` variables take per-environment secret references. A `derive` expression is an alternative source that interpolates other variables with `${NAME}`. A derived value that reaches a secret must itself be classed `secret`.

Public value:

```toml
[[var]]
name = "PUBLIC_API_ORIGIN"
class = "public"
targets = ["svc-local"]
section = "Runtime"
doc = "Public API origin."
example = "https://example.invalid"
values = { local = "https://api.example.invalid" }
```

Config value:

```toml
[[var]]
name = "PGHOST"
class = "config"
targets = ["svc-local"]
section = "Database"
doc = "Database host."
example = "db"
values = { local = "postgres" }
```

Secret reference:

```toml
[[var]]
name = "PGPASSWORD"
class = "secret"
targets = ["svc-local"]
section = "Database"
doc = "Database password."
example = "<from keychain>"
secret = { local = "keychain:acx-local/PGPASSWORD" }
```

Derived value:

```toml
[[var]]
name = "POSTGRES_DSN"
class = "secret"
targets = ["svc-local"]
section = "Database"
doc = "Database connection string."
example = "postgresql://<user>:<password>@<host>/<database>"
derive = "postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}/${DB_NAME}"
```

`required` defaults to `true`. A non-required variable with no runtime value is omitted from the runtime file and shown commented in example output.

## Secret references

- `keychain:<service>/<account>` reads a macOS Keychain item. Use this for local values.
- `env:<NAME>` reads a value from the process environment, for example in CI. Use this for local or CI values.
- `vault:<vault-secret-ocid>` is an app-time Vault map identifier. The rendered variable is blank (`NAME=`), and its OCID is added to `RECOGNITION_VAULT_SECRET_MAP` for the application to fetch. The VM materializer does not fetch `vault:` values.
- `oci:<vault-secret-ocid>` is fetched by the VM materializer with the OCI CLI and instance-principal authentication. It decodes the OCI secret-bundle's `BASE64` content and writes the bytes into the backend environment file. It is not added to `RECOGNITION_VAULT_SECRET_MAP`.
- `host:` has an empty remainder and preserves the existing backend environment-file value byte for byte during materialization. Use it for values maintained on the VM.

`vault:` and `oci:` must contain a vault-secret OCID. The manifest validates `vault:` against `^ocid1\.vaultsecret\.oc1\.[a-z0-9-]*\.[a-z0-9]{20,}$` and `oci:` against `^ocid1\.vaultsecret\.oc1\.[a-z0-9-]+\.[a-z0-9]{20,}$`. `host:` and `oci:` require a `remote_paths` entry for each selected environment. `vault:`, `oci:`, and `host:` are refused on `public_build` and `test` targets; derive expressions cannot reference any of them. `keychain:` and `env:` are refused for environments with a `remote_paths` entry.

Store a secret in the default Keychain service (`acx-local`):

```sh
make env-secret-set NAME=PGPASSWORD
```

For a non-default Keychain service, replace `<service>` with its name:

```sh
make env-secret-set NAME=PGPASSWORD ENV_SECRET_SERVICE='<service>'
```

The command prompts through `security`; the secret value is not an argument and does not enter shell history.

## Commands

```sh
make env-examples
make env-check
make env-render ENV=local TARGET=svc-local
make env-render ENV=local TARGET=svc-local ADOPT=1
```

`env-examples` renders all templates. `env-check` checks them for drift and is part of `check-all`. `env-render` writes the selected runtime target. Renderer CLI exit codes are `0` for success/no drift, `1` for drift, `2` for a manifest or usage error, and `3` when a secret is unavailable.

## Adopting an existing file

For a hand-edited file, run `make env-render ENV=local TARGET=svc-local ADOPT=1`. Adoption writes a `<path>.pre-envman` backup with mode `0600`. It refuses keys in the old file that the rendered manifest output does not manage. The direct CLI supports `--allow-unmanaged K,...` to allow specific keys through that check. Verify the generated file, then remove the backup as an operator step.

## Guards

A `public_build` target accepts only names beginning `VITE_`; it refuses secret variables and derives that reach a secret. It also refuses names matching `SECRET|TOKEN|PASSWORD|PRIVATE|(?<!PUBLISHABLE)_KEY$`, allowing the `PUBLISHABLE_KEY` suffix exception.

For every target, values and examples matching `sk_(test|live)_`, `\brk_(test|live)_`, `whsec_`, or `-----BEGIN` are refused. These checks keep secret-looking literals and PEM blocks out of the manifest.

## Adding a variable

Choose the appropriate fragment, class, target, and section. Add a safe example and the per-environment values, secret reference, or derive expression. Run `make env-examples`, commit the fragment and regenerated templates, then run `make env-check`.

## VM materialization

Run materialization on the VM for a target/environment with a configured `remote_paths` entry. This is the production path for backend `oci:` references; it keeps OCI retrieval on the VM and writes the resulting environment file with mode `0600`. `oci:` is for materialization-time secret bytes, while `vault:` remains an app-time map reference that renders blank. Removing prod `app-portal.env` in favour of build-time `VITE_*` arguments remains outside this runbook's scope.
