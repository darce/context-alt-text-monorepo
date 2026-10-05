# Plan 0004 - ENVMAN-2. VM env materializer

- **Task ID:** ENVMAN-2, slice B1. B1b (deploy integration) waits for DEFWAVE-2; B2 (app-portal targets) waits for APP-1.
- **Task Plan Status:** draft, for planning review.
- **Date:** 2026-09-28.
- **Target branch:** `feature/envman-2`. **Worktree:** `../context-alt-text-monorepo-envman-2`.
- **Baseline:** `45f6388e48925f97ee5f3fc07b5bd80fbea30b5c` (ENVMAN-1 merged).
- **Intake:** [scope § Phase B](../scopes/env-manifest-render-scope.md#phase-b-envman-2--after-app-1-merges-not-this-task); ENVMAN-1 decision 13993; this plan's split decision.
- **Routing:** implement and RED lanes codex-remote `gpt-6-astra` low standard; review lanes `gpt-6-luna` max fast. RED lanes write tests only.

## Objective

Make the five VM runtime files (`/opt/acx-backend/{dev,staging,prod,dev-fir}/.env`, `/opt/acx-backend/demo/secrets/.env`) generated artifacts of the manifest. No secret value leaves the VM or enters the laptop, git or a log.

## Why split B1 / B1b / B2

- `feature/app-1` (185 commits ahead, unmerged) owns every app-portal file. It does not touch `config/env`, `scripts/env` or `recognition-service.sh`, so B1 does not wait on it.
- `feature/defwave-2` carries a 770-line unmerged diff to `scripts/deploy/recognition-service.sh`. B1 does not edit that script. It ships a standalone `make env-materialize` that follows the deploy's lock protocol. Calling it from `recognition-service.sh` is B1b, after DEFWAVE-2 merges.

## Design (assumptions resolved from canon)

- **D-1 Render on the VM, not the laptop [SECD-05, PG-09].** The laptop ships `scripts/env/*.py` and `config/env/` to a `mktemp -d` on the VM over ssh stdin. It then runs `sudo python3 render_env.py materialize ...` there; the VM has Python 3.12 and needs only the stdlib. Host-only secrets are read and written on the VM only.
- **D-2 Four runtime sources for VM envs.**
  - `values`: literal config, as today.
  - `vault:<secret-ocid>`: the app fetches the value via `OciVaultSecretProvider`. The runtime file gets `NAME=` (blank), and the OCID is added to `RECOGNITION_VAULT_SECRET_MAP`. An OCID is not a secret (ADR-013), so it may be committed.
  - `oci:<vault-secret-ocid>`: at materialization time, the VM runs `oci secrets secret-bundle get --auth instance_principal --secret-id <ocid>` and writes the decoded secret bytes to that backend env var. This value is not added to `RECOGNITION_VAULT_SECRET_MAP`. The OCID must match `^ocid1\.vaultsecret\.oc1\.[a-z0-9-]+\.[a-z0-9]{20,}$`. A missing CLI, failed or timed-out command, invalid JSON/base64, unsupported encoding, or empty value refuses materialization; the diagnostic names only the variable and `oci` scheme and never includes CLI output or the secret value.
  - `host:`: a secret that exists only in the VM file, such as `POSTGRES_PASSWORD` for the postgres container or `MARIADB_*` for demo. The materializer keeps the existing line's bytes verbatim.

  `keychain:` and `env:` refs are refused for VM envs at load time.
- **D-3 Deploy-owned keys are preserved, not managed.** A target-level `preserve = [...]` names keys the deploy rewrites in place: `ACX_IMAGE_REPO`, plus the `# ACX_IMAGE_REPO_OWNER=` comment written by `image_repo_resource`. Rules:
  - These keys must not be manifest vars of that target.
  - Preserved lines are copied verbatim into a trailing `# Preserved (host/deploy-owned)` block, in `preserve` order, with owner comment lines first.
- **D-4 Same locks as the deploy [CON-11].** Before any write, `materialize` takes the deploy env lease using the same file protocol as `deploy_env_lease` (`${ACX_DEPLOY_BACKUP_ROOT}/locks/deploy-<env>.lease` plus `.lease.lock`).
  - If an unexpired lease is held by someone else, it refuses with exit 75.
  - It holds `<.env>.acx-image-repo.lock` (the `image_repo_resource` inode lock) across read, merge and write.
  - It releases both on exit.
  - The dev-fir lease key is `dev-fir`. Demo has no deploy lease, so it takes only its own `.env.acx-image-repo.lock`-style lock.
- **D-5 Check before write.** `--check` prints only key names and file metadata in four groups:
  - `missing` (required and absent);
  - `unmanaged` (present, neither managed nor preserved);
  - `differs` (managed value differs);
  - `mode` (existing file is not a regular 0600 file, or it lacks the materialized header).

  It exits 1 on drift, prints no values and writes nothing. Rollout is check-first on every env.

## Interface contract (pinned)

### Manifest

```toml
[targets.svc-vm]
remote_paths = { dev = "/opt/acx-backend/dev/.env", staging = "/opt/acx-backend/staging/.env", prod = "/opt/acx-backend/prod/.env" }
preserve = ["ACX_IMAGE_REPO"]            # plus the owner comment, implicitly
lease_env = { dev = "dev", staging = "staging", prod = "prod" }   # svc-fir: { fir = "dev-fir" }; demo: none

[[var]]
name = "PGPASSWORD"
class = "secret"
secret = { prod = "vault:ocid1.vaultsecret.oc1.iad.<id>", dev = "host:" }

[[var]]
name = "RECOGNITION_VAULT_SECRET_MAP"
class = "config"
derive_vault_map = true                  # compact JSON, keys sorted, from this target+env's vault refs
```

Loader refusals (`ManifestError`, fragment and var named, never the value):

- `remote_paths` entries must be absolute, normalized, under `/opt/acx-backend/`, and cover a subset of the target's `envs`.
- `preserve` must not overlap the target's var names.
- A `vault:` OCID must match `^ocid1\.vaultsecret\.oc1\.[a-z0-9-]*\.[a-z0-9]{20,}$`; an `oci:` OCID must match `^ocid1\.vaultsecret\.oc1\.[a-z0-9-]+\.[a-z0-9]{20,}$`.
- A (target, env) with any `vault:` ref must also have `derive_vault_map` and `RECOGNITION_SECRET_BACKEND = "oci_vault"` for that env. The reverse also holds: `oci_vault` with no `vault:` refs is refused. `oci_vault` also requires `vault:` refs for both boot-required keys, `PGPASSWORD` and `RECOGNITION_ADMIN_TOKEN` (`validate_oci_vault_boot` in `shared/secrets.py`).
- `vault:`/`oci:`/`host:` refs are refused on `public_build` and `test` audiences. `keychain:`/`env:` refs are refused on any env listed in `remote_paths`.
- `derive` expressions referencing a `vault:`, `oci:` or `host:` var are refused. For example, `POSTGRES_DSN` must itself be `vault:` or `host:` on those envs.

Loader API (`scripts/env/manifest.py`; the pinned names lanes code against):

- `Target` gains three fields, all with empty defaults:
  - `remote_paths: Mapping[str, str]`;
  - `preserve: tuple[str, ...]`;
  - `lease_env: Mapping[str, str]`.

  `lease_env` keys must be a subset of the `remote_paths` keys.
- `Var` gains `derive_vault_map: bool = False`. A var with `derive_vault_map = true` must be `class = "config"` and must have no `values`, `secret` or `derive`.
- `secret` refs accept the schemes `keychain`, `env`, `vault`, `oci` and `host`. `host:` must have an empty remainder; `vault:` and `oci:` must match their OCID regexes above. `vault:` refs render as blank values and populate the app-time map; `oci:` refs are fetched during materialization for backend envs.
- `vault_secret_map(manifest, target, env) -> dict[str, str]` returns a logical name → OCID map of the `vault:` refs for that target and env, with keys sorted. It returns `{}` when there are none. The rendered value is `json.dumps(map, separators=(",", ":"), sort_keys=True)`.
- Every refusal is a `ManifestError`. Its message names `targets.toml` plus the target for target-level rules, or the fragment file plus the var for var-level rules.

### `render_env.py materialize`

`materialize --root R --env E --target T --into PATH [--check] [--adopt] [--allow-unmanaged K,...]`

- `PATH` must equal the target's `remote_paths[E]`. Otherwise exit 2.
- Output = the generated header (with a `materialized` marker and the managed digest), then the managed sections, then the preserved block.
- Adoption and backup behave as in `write_env_file`: `<path>.pre-envman`, and an existing backup is never overwritten.
- Ownership: `_atomic_write` does not chown, and materialize runs under `sudo`. `materialize.py` therefore owns an owner-preserving atomic write:
  - `fchown` the 0600 temp file to the existing file's uid/gid, then `fsync` and `os.replace`.
  - The `.pre-envman` backup gets the same uid/gid.
  - With no existing file, it refuses (exit 2). The first materialize of an env is always an adoption.
- A `host:` var missing from the existing file: if required, exit 4, naming the var only. If optional, it is omitted.
- Exit codes: 0 ok, 1 drift (`--check`), 2 refusal, 4 secret unavailable, 75 lock/lease busy.

Materialize API (`scripts/env/materialize.py`; the pinned names lanes code against). The CLI subcommand is a thin wrapper; tests drive the function:

```python
def run(manifest_root: Path, *, env: str, target: str, into: str, check: bool = False, adopt: bool = False,
        allow_unmanaged: Sequence[str] = (), fs_root: Path = Path("/"),
        backup_root: Path = Path("/opt/acx-backend/.acx-deploy-backups"), lock_timeout: float = 30.0,
        now: Callable[[], float] = time.time, out: TextIO = sys.stdout, err: TextIO = sys.stderr) -> int
```

- `into` is compared to `remote_paths[env]` as a string. The file actually touched is `fs_root / into.lstrip("/")`. `fs_root` and `backup_root` are test seams, and the CLI does not expose them.
- Lease: when the target has `lease_env[env] = L`, the lease files are `backup_root/locks/deploy-L.lease` and `deploy-L.lease.lock`.
  - The protocol and record are byte-compatible with `deploy_env_lease` in `scripts/deploy/recognition-service.sh`:
    - `flock` the `.lease.lock`;
    - the record is `{"transaction","holder","expires_at"}` as compact JSON;
    - a record with `expires_at > now()` held by another transaction → exit 75;
    - otherwise write our own record with holder `envman-materialize` and expiry `now()+600`.
  - Release happens in `finally`. It unlinks the lease only if the transaction is still ours.
  - A malformed lease → exit 2.
- Image-repo lock: `flock(LOCK_EX|LOCK_NB)` on `<file>.acx-image-repo.lock`. If it is still busy after `lock_timeout`, exit 75. The lock is held across read, merge and write.
- Output bytes:
  - line 1: `HEADER_LINE`;
  - line 2: `# materialized target=<T> env=<E> digest=<sha256 hex of the managed body>`;
  - then the managed body exactly as `render_target` renders it. A `vault:` var renders `NAME=`, the map var renders the compact JSON, and a `host:` var copies the existing line's bytes verbatim;
  - then, if any preserved line exists, a blank line, `# Preserved (host/deploy-owned)`, the owner comment lines (`# ACX_IMAGE_REPO_OWNER=`), and each `preserve` key's line, in `preserve` order and byte-verbatim.
- `check=True` writes nothing and takes no lease. Its only output on `out` is one line per item: `<group>\t<NAME>`, with the group order `missing`, `unmanaged`, `differs`, `mode` and names sorted within each group. The `mode` group line is `mode\t<into>` (not regular 0600, or line 1 is not `HEADER_LINE`). The digest line is informational and is never compared. Exit 1 if there is any item, else 0.
- A present key that is neither managed, preserved nor in `allow_unmanaged`: apply refuses (exit 2), and `check` lists it as `unmanaged`.
- No value, secret or otherwise, ever reaches `out`, `err` or an exception message.

### Adoption hardening (em2-adopt; closes ENVMAN-1 deferrals EMREV-CLAUDE-09, EMREDS newline case)

- **Backup never overwritten.** When `_preflight_env_file` is adopting an unheaded file and `<path>.pre-envman` already exists (any file type), it raises `ValueError`. The message contains `.pre-envman` and `backup exists`. Nothing is written. Because the check runs in preflight, `--all-examples --adopt` refuses before any file changes.
- **Runtime renders refuse unmanaged keys.** `write_env_file` and `_preflight_env_file` gain the keyword `runtime: bool = False`.
  - With `runtime=True` and a headed existing file, a key present in the old file but absent from the new text and not in `allow_unmanaged` raises `ValueError(f"{path}: unmanaged key {first_sorted}")`. Nothing is written.
  - `allow_unmanaged` permits dropping the key.
  - `main` passes `runtime=True` when `--env` is given.
  - Example renders (no `--env`, or `--all-examples`) still regenerate silently, because examples are wholly generated.
- **CLI.** `--allow-unmanaged` is accepted with `--adopt` or with `--env`. Otherwise it is a parser error containing `--allow-unmanaged requires --adopt or --env`.
- **Keychain regression.** A stdout of only `"\n"` raises `SecretUnavailable`, as the empty stdout already does.
- No value from the old file appears in any message.

### Remote wrapper and make

- `scripts/env/materialize_remote.sh <env> <target> [--check|--apply] [--adopt]`. It forwards `--adopt` to `materialize`, and `--adopt` is refused without `--apply`.
- Uses `OCI_USER`/`OCI_HOST` with the same defaults as `recognition-service.sh`.
- Ships a tar of `scripts/env/*.py` + `config/env/` via ssh stdin, runs the command under `sudo`, and always removes the temp dir.
- Never passes a value in argv.
- `make env-materialize ENV=<env> TARGET=<target> [APPLY=1] [ADOPT=1] [CONFIRM=<env>]`:
  - check-only by default;
  - `APPLY=1` writes;
  - `ADOPT=1` (with `APPLY=1`) passes `--adopt`;
  - `prod` also requires `CONFIRM=prod`.

## Lanes and DAG

| Lane | Kind | Owns | Depends |
|---|---|---|---|
| em2-lows | GREEN (docs + small fixes) | `docs/runbooks/env-manifest.md`, `config/env/manifest.d/targets.toml` (svc-fir preamble only), `apps/prototype-description-service/.env.fir.example` (regenerated), `infra/oci/demo/bootstrap-wp.sh` | — |
| em2-red-adopt | RED | `scripts/env/tests/test_harden_render.py` (append), `scripts/env/tests/test_secret_resolvers.py` (append) | — |
| em2-adopt | GREEN | `scripts/env/render_env.py`, `scripts/env/secret_refs.py` | em2-red-adopt |
| em2-red-vault | RED | `scripts/env/tests/test_vm_manifest.py` (new) | — |
| em2-vault | GREEN | `scripts/env/manifest.py` | em2-red-vault |
| em2-red-mat | RED | `scripts/env/tests/test_materialize.py` (new) | — |
| em2-mat | GREEN | `scripts/env/render_env.py`, `scripts/env/materialize.py` (new: lease, lock, merge) | em2-red-mat, em2-adopt, em2-vault |
| em2-remote | GREEN | `scripts/env/materialize_remote.sh`, `mk/env.mk`, `scripts/env/tests/test_materialize_remote.py` | em2-mat |
| em2-frag | GREEN (migration) | `config/env/manifest.d/21-service-vm.toml`, `22-service-fir.toml`, `40-demo.toml`, `targets.toml` (remote_paths/preserve/lease_env) + regenerated examples | em2-vault, em2-lows (shared `targets.toml`) |

- Wave 1: em2-lows, em2-red-adopt, em2-red-vault, em2-red-mat.
- Wave 2: em2-adopt, em2-vault.
- Wave 3: em2-mat, em2-frag.
- Wave 4: em2-remote.
- Then one harmonizing review-pipeline gate and the merge.
- At most 4 open lane worktrees.

The em2-frag refs start as `host:` for every VM secret, which is behaviour-neutral: values stay where they are. Moving a secret to `vault:` is a per-env rollout step (below), not a code change.

## Rollout (after merge; operator-visible, VM writes)

1. `make env-materialize ENV=<e> TARGET=<t>` (check) for dev, staging, prod, fir and demo. Reconcile the manifest until every env reports only expected `differs`.
2. dev: `APPLY=1 ADOPT=1` on the first run (then `APPLY=1`), then restart and verify health. Then staging.
3. prod: `APPLY=1 CONFIRM=prod` only after dev and staging are healthy for one deploy cycle.
4. fir and demo last. For demo, EMW8-DEMO-01's quote fix must be live first.
5. Before the first apply on an env, check whether `acx-<env>.service` enables `ExecStartPre=.../fetch-vault-bootstrap.sh` (it is commented out in `systemd/acx-env.service.template`). If it is enabled, that hook is a second writer of `POSTGRES_PASSWORD` into the same `.env`. `POSTGRES_PASSWORD` stays `host:`, and making the hook take the image-repo lock is B1b.
6. Per env, opt secrets into `vault:` with `_vault_put_secret.py` (value via stdin), then flip `RECOGNITION_SECRET_BACKEND`. Each flip is its own check, apply and verify.

## Verification

- `python3 -m pytest scripts/env/tests -q` green; `make env-check` rc 0.
- The materialize tests run against a temp root with a fake lease dir. They cover, for each case, no write, 0600, byte-verbatim preserved lines, and no value in stdout/stderr:
  - lease held → 75;
  - lock contention;
  - a preserved owner comment round-trips;
  - `host:` missing → 4;
  - `--check` names only;
  - `--check` reports `mode` for a 0644 file;
  - uid/gid kept on the file and on the backup (tests use `os.chown` monkeypatched to record calls).
- Remote wrapper test: an ssh shim records argv and stdin. Assert no value in argv, temp-dir cleanup on failure, and that prod refuses without `CONFIRM=prod`.

## Out of scope

- B1b: calling materialize from `recognition-service.sh` (after DEFWAVE-2).
- B2: app-portal targets, `VITE_*` build args, removing `/opt/acx-backend/prod/app-portal.env` (after APP-1).
- Resolving `vault:` values anywhere except inside the app. The materializer fetches only explicit `oci:` refs and never fetches `vault:` refs.
