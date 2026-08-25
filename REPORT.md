# Lane A report — AUTH-01 + AUTH-03

Final HEAD: recorded by the integrator after transplant.

## Commits

- `fix(demo): AUTH-01 rotate wp-admin credential on bootstrap`
- `fix(demo): AUTH-03 split CI account from demo admin`

## AUTH-01

**RED** (test before impl):

```
FAIL bootstrap uses wp user update for rotation: expected .../infra/oci/demo/bootstrap-wp.sh to match /wp user update/
6 assertion(s) failed
```

**GREEN:** `bash infra/oci/demo/tests/test-credential-lifecycle.sh` → `all assertions passed`

Second bootstrap with a changed secret calls `wp user update` then re-checks; unchanged secret is a no-op (`UPDATE_CALLS=0`). Update or post-update verify failure exits 2.

**TEST-15 mutant:** `if wp_user_password_matches` → `if true` (always no-op). Suite:

```
FAIL changed secret calls wp user update once: expected 1, got 0
9 assertion(s) failed
```

Restore: production `git diff` clean vs pre-mutant tree; suite green.

Pins (sed after code commit):

- `infra/oci/demo/bootstrap-wp.sh:68` `wpcli wp user check-password`
- `infra/oci/demo/bootstrap-wp.sh:71` `converge_wp_user_password()`
- `infra/oci/demo/bootstrap-wp.sh:79` `wpcli wp user update ... --user_pass=`
- `infra/oci/demo/bootstrap-wp.sh:190` call on `$WP_ADMIN_USER` (outside first-install `if`)
- `docs/runbooks/key-management.md:151` rotation procedure (secret-store write, then apply)

## AUTH-03

**RED** (test before impl):

```
FAIL bootstrap reads WP_CI_USER: expected .../bootstrap-wp.sh to match /env_get WP_CI_USER/
19 assertion(s) failed
```

```
FAILED .../test_provision_demo.py::test_cli_help_documents_account_kinds - assert '--account' in "usage: provision_demo provision [-h] --label LABEL [--seed SEED]..."
FAILED ...::test_cli_provision_ci_requires_admin_user - SystemExit: 2
5 failed, 4 passed
```

**GREEN:** `bash infra/oci/demo/tests/test-ci-account-split.sh` → `all assertions passed`. `uv run --extra dev pytest recognition/tests/scripts/test_provision_demo.py` → `9 passed`. `make -n issue-demo-ci-account LABEL="ACX CI" ADMIN_USER=acx-demo-admin` expands to `python -m scripts.provision_demo --account ci --admin-user ...`.

**TEST-15 mutant:** collision guard `if [[ "$ci_user" == "$admin_user" ]]` → `if false && ...`. Suite:

```
FAIL CI user equal to admin exits 2: expected 2, got 0
FAIL collision does not create a user: expected 0, got 1
2 assertion(s) failed
```

Restore green.

Pins (sed after code commit):

- `infra/oci/demo/bootstrap-wp.sh:47` `env_get WP_CI_USER`
- `infra/oci/demo/bootstrap-wp.sh:52` required-vars include `WP_CI_*`
- `infra/oci/demo/bootstrap-wp.sh:94` role `acx_ci`
- `infra/oci/demo/bootstrap-wp.sh:100` `--clone=subscriber`
- `infra/oci/demo/bootstrap-wp.sh:104` `cap add ... manage_options`
- `infra/oci/demo/bootstrap-wp.sh:110` `converge_wp_ci_account()`
- `infra/oci/demo/bootstrap-wp.sh:193` CI converge after admin
- `.github/workflows/deploy-demo.yml:217` refuse demo-admin identity
- `.github/workflows/deploy-demo.yml:226` `acx-demo-admin|admin`
- `.github/workflows/deploy-demo.yml:246-247` Playwright env values from `secrets.ACX_E2E_WP_CI_*`
- `apps/prototype-description-service/scripts/provision_demo.py:36` `AccountKind`
- `apps/prototype-description-service/scripts/provision_demo.py:43` `CI_RECOGNITION_QUOTA = 20`
- `apps/prototype-description-service/scripts/provision_demo.py:104` `resolve_account_issuance`
- `Makefile.d/demo-auth.mk:10` `issue-demo-ci-account:`
- `docs/runbooks/key-management.md:179` issuance table + documented `make` commands
- `docs/workbay/contracts/security.md:76` demo identity contract

rg-006: documented `make issue-demo-ci-account LABEL="ACX CI" ADMIN_USER=acx-demo-admin` and `make provision-demo LABEL="Acme Gallery" SEED=default` both exist as written.

## Undone

- `infra/oci/demo/.env.example` not updated (outside ownership); operators must add `WP_CI_*` from the runbook before the next bootstrap or it exits 2.
- Playwright `auth.setup.ts` still reads `ACX_E2E_WP_ADMIN_*` names (outside ownership); split is secret-value + workflow map only.
- `docs/runbooks/deploy-demo-cicd.md` still lists `ACX_E2E_WP_ADMIN_USER/PASS` as the smoke secrets (outside ownership) — runbook drift vs workflow.
- `acx_ci` still holds `manage_options` (plugin admin pages require it). Not administrator, but not a tiny cap set; shrinking further needs PHP capability changes (outside ownership).
- `/Makefile.d` is gitignored; `demo-auth.mk` was force-added so the documented target survives transplant.
- Live demo VM is not rotated here; first apply after transplant must populate `WP_CI_*` and GitHub `ACX_E2E_WP_CI_*` (two-key: store write then bootstrap/deploy).
- WEB-17 login rate-limit not added; Caddy `rate_limit` remains the deferred-hardening comment (stock image has no module).
- Dual-control is procedural (secret-store write ≠ apply), not a two-person GitHub Environment reviewer gate (free plan).
- `scripts/test_e15_28_demo_bootstrap.py::test_caddy_demo_vhost_blocks_xmlrpc_without_nonstock_directives` IndexError is pre-existing Caddyfile parse, not this lane. Bootstrap artifact assertions in that file still pass.

## Canon cited

- **SEC-06** — passwords stay in the VM secret file / GitHub Environment; runbook forbids prompt/ticket paste.
- **WEB-16** — no demo passwords committed; tests use mock store values; stdout of provision still prints the API key once by design (hash-only in DB).
- **WEB-17** — checked; this slice does not add wp-login rate limits (existing Caddy xmlrpc 403 only).
- **least-privilege-blast-radius** — CI WP user is not the admin login; CI API quota 20 vs viewer 200; role is subscriber clone + `manage_options`, not `administrator`.
- **dual-control-two-keys** — rotation is two acts: secret-store write, then bootstrap/deploy apply. Either alone does not complete revoke.
- **fail-loudly-succeed-quietly** — rotation/collision/missing-CI-secret failures exit non-zero with ERROR; unchanged secret is a no-op.
- **TEST-15** — each item: production mutant turned the suite red; restore re-greened.
